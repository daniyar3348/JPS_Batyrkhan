"""The editorial workflow: decisions, the editors handling a manuscript, discussions, history.

Decisions follow ``transitions.RULES``. Recording one is a single transaction: the decision, the
change of stage or status, what happens to the review round, the letters to the authors, the audit
entry. Two editors deciding at the same moment cannot both succeed: the submission row is versioned.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import Conflict, FieldError, Forbidden, NotFound, ValidationFailed
from app.core.jobs import enqueue
from app.core.storage import Storage
from app.modules.audit.service import AuditService
from app.modules.files.models import FileStage, FileStatus, SubmissionFile
from app.modules.identity.models import User
from app.modules.journals.email_templates import Rendered
from app.modules.journals.models import Journal
from app.modules.journals.permissions import SECTION_EDITOR_ROLES, Role
from app.modules.payments.service import PaymentService
from app.modules.review.forms import questions_of
from app.modules.review.models import AssignmentStatus, RoundStatus
from app.modules.review.policies import answer_text, author_label
from app.modules.review.service import ReviewService
from app.modules.submissions.models import Participant, ParticipantRole, Submission
from app.modules.submissions.policies import Access
from app.modules.submissions.service import editors_to_notify
from app.modules.workflow import emails
from app.modules.workflow.models import Discussion, DiscussionMessage, EditorialDecision
from app.modules.workflow.schemas import DecisionIn, DecisionOption, DiscussionCreate, EditorIn
from app.modules.workflow.stage_files import StageFiles
from app.modules.workflow.transitions import RULES, Decision, RoundEffect, Rule, allowed_here

SEPARATOR = "\n\n" + "-" * 40 + "\n\n"

# Who can be assigned to each kind of work on a manuscript, by their role in the journal.
PARTICIPANT_ROLES: dict[str, frozenset[Role]] = {
    ParticipantRole.EDITOR: SECTION_EDITOR_ROLES,
    ParticipantRole.COPYEDITOR: frozenset({Role.COPYEDITOR}),
    ParticipantRole.LAYOUT_EDITOR: frozenset({Role.LAYOUT_EDITOR}),
    ParticipantRole.PROOFREADER: frozenset({Role.PROOFREADER}),
}
TASKS = {
    ParticipantRole.COPYEDITOR: "copyedit",
    ParticipantRole.LAYOUT_EDITOR: "typeset",
    ParticipantRole.PROOFREADER: "proofread",
}
RESERVE_DOI = "publishing.reserve_doi"  # handled by the publishing module, which sits above this one


def option_of(rule: Rule, stage: str) -> DecisionOption:
    return DecisionOption(
        decision=rule.decision,
        label=rule.label,
        description=rule.description,
        is_recommendation=rule.recommendation,
        needs_files=rule.needs_files,
        needs_reason=rule.needs_reason,
        has_letter=stage in rule.letters,
    )


class WorkflowService:
    def __init__(self, db: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.db = db
        self.settings = settings
        self.review = ReviewService(db, settings, storage)
        self.files = self.review.files
        self.journals = self.review.journals
        self.mailer = self.review.mailer
        self.audit = AuditService(db)
        self.payments = PaymentService(db, settings)
        self.stage_files = StageFiles(self.files)

    # ------------------------------------------------------------------ decisions

    async def _round_status(self, submission: Submission) -> str | None:
        current = await self.review.current_round(submission.id)
        return current.status if current else None

    async def options(self, submission: Submission, access: Access) -> list[DecisionOption]:
        """Decisions the viewer can make now. Editors who may only recommend get recommendations."""
        if not access.can_manage:
            return []
        round_status = await self._round_status(submission)
        return [
            option_of(rule, submission.stage)
            for rule in RULES.values()
            if rule.decision != Decision.WITHDRAW
            and not rule.publishing
            and rule.recommendation == access.recommend_only
            and allowed_here(
                rule, stage=submission.stage, status=submission.status, round_status=round_status
            )
        ]

    async def candidate_files(self, submission: Submission) -> list[SubmissionFile]:
        """What can go to reviewers: the submitted files, and the revisions of the latest round."""
        files = list(await self.files.list(submission.id, file_stage=FileStage.SUBMISSION))
        current = await self.review.current_round(submission.id)
        if current is not None:
            files += await self.files.list(
                submission.id, file_stage=FileStage.REVISION, review_round_id=current.id
            )
        return [f for f in files if f.current.status == FileStatus.READY]

    async def reviewer_comments(self, submission: Submission) -> str:
        current = await self.review.current_round(submission.id)
        if current is None:
            return ""
        parts = []
        for assignment in sorted(
            await self.review.assignments(submission.id, round_id=current.id), key=lambda a: a.reviewer_number
        ):
            if assignment.status != AssignmentStatus.COMPLETED:
                continue
            lines = [f"{author_label(assignment)}:"]
            for question in questions_of(assignment.questions):
                if question.visible_to_author and question.id in assignment.answers:
                    lines.append(f"\n{question.label}\n{answer_text(assignment.answers[question.id])}")
            if assignment.comments_for_author:
                lines.append(f"\n{assignment.comments_for_author}")
            parts.append("\n".join(lines))
        return SEPARATOR.join(parts)

    @staticmethod
    def letter_recipients(submission: Submission) -> list[tuple[str, str]]:
        """The submitting author, then any other corresponding author."""
        recipients = [(submission.submitter.full_name, submission.submitter.email)]
        for contributor in submission.publication.contributors:
            if contributor.is_corresponding and contributor.email not in {e for _, e in recipients}:
                recipients.append((contributor.full_name, contributor.email))
        return recipients

    async def letter(
        self, journal: Journal, submission: Submission, rule: Rule, editor: User
    ) -> Rendered | None:
        key = rule.letters.get(submission.stage)
        if key is None:
            return None
        name, _ = self.letter_recipients(submission)[0]
        return await self.mailer.render(
            journal,
            key,
            submission,
            recipient_name=name,
            values={
                "editorName": editor.full_name,
                "reviewerComments": await self.reviewer_comments(submission),
            },
        )

    async def _check(self, submission: Submission, access: Access, decision: Decision) -> Rule:
        rule = RULES[decision]
        if decision == Decision.WITHDRAW:
            raise Forbidden("Only the authors can withdraw a manuscript.")
        if rule.publishing:
            raise Conflict(
                "Schedule and publish articles from the publication screen.", code="use_publishing"
            )
        if rule.recommendation:
            if not access.recommend_only:
                raise Forbidden("Recommendations are for editors who do not decide themselves.")
        elif not access.can_decide:
            raise Forbidden("Only the deciding editors can record this decision.")
        round_status = await self._round_status(submission)
        if not allowed_here(
            rule, stage=submission.stage, status=submission.status, round_status=round_status
        ):
            raise Conflict(f"“{rule.label}” is not possible at this point.", code="decision_not_allowed")
        return rule

    async def preview(
        self, journal: Journal, submission: Submission, access: Access, decision: Decision, editor: User
    ) -> tuple[Rule, Rendered | None, list[str], list[SubmissionFile]]:
        rule = await self._check(submission, access, decision)
        letter = await self.letter(journal, submission, rule, editor)
        to = [email for _, email in self.letter_recipients(submission)] if letter else []
        candidates = await self.candidate_files(submission) if rule.needs_files else []
        return rule, letter, to, candidates

    async def decide(
        self, journal: Journal, submission: Submission, access: Access, data: DecisionIn, actor: User
    ) -> EditorialDecision:
        rule = await self._check(submission, access, data.decision)
        if rule.needs_reason and not data.reason:
            raise ValidationFailed(
                "Give a reason.",
                code="reason_required",
                errors=[FieldError(field="reason", message="Required")],
            )
        stage_before = submission.stage
        letter_key = rule.letters.get(stage_before)
        letter: Rendered | None = None
        if letter_key is not None and (data.letter is None or data.letter.send):
            letter = (
                Rendered(subject=data.letter.subject, body=data.letter.body)
                if data.letter is not None
                else await self.letter(journal, submission, rule, actor)
            )

        current = await self.review.current_round(submission.id)
        round_id = current.id if current else None
        if rule.round == RoundEffect.START:
            new_round = await self.review.start_round(journal, submission, data.review_file_ids, actor)
            round_id = new_round.id
        elif rule.round == RoundEffect.CLOSE and current is not None and current.status != RoundStatus.CLOSED:
            await self.review.close_round(journal, submission, current, actor)
        elif rule.round in (RoundEffect.REVISIONS, RoundEffect.RESUBMIT) and current is not None:
            current.status = (
                RoundStatus.REVISIONS_REQUESTED
                if rule.round == RoundEffect.REVISIONS
                else RoundStatus.RESUBMIT_REQUESTED
            )
            current.revisions_submitted_at = None

        if rule.to_stage is not None:
            submission.stage = rule.to_stage
        if rule.to_status is not None:
            submission.status = rule.to_status
        recipients = self.letter_recipients(submission) if letter else []
        record = EditorialDecision(
            submission_id=submission.id,
            round_id=round_id,
            decision=rule.decision.value,
            is_recommendation=rule.recommendation,
            stage_before=stage_before,
            stage_after=submission.stage,
            status_after=submission.status,
            made_by_id=actor.id,
            reason=data.reason,
            letter_to=[email for _, email in recipients],
            letter_subject=letter.subject if letter else None,
            letter_body=letter.body if letter else None,
        )
        record.made_by = actor
        self.db.add(record)
        await self.db.flush()

        if letter is not None:
            for _, email in recipients:
                await self.mailer.send_rendered(
                    letter, submission, to_email=email, key=letter_key, sent_by_id=actor.id
                )
        if rule.recommendation:
            await self._tell_deciders(journal, submission, rule, data.reason, actor)
        if rule.decision == Decision.SEND_TO_PRODUCTION:
            # The DOI must exist before the galleys are typeset (it is printed on them).
            await enqueue(self.db, RESERVE_DOI, {"submission_id": submission.id})
        if rule.decision == Decision.ACCEPT:
            # The publication fee is invoiced only now, never before acceptance (§8.5).
            await self.payments.issue_for_accepted(journal, submission, actor)
        await self.audit.record(
            "submission.recommendation" if rule.recommendation else "submission.decision",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"decision": rule.decision.value, "stage": submission.stage, "status": submission.status},
        )
        return record

    async def record_transition(
        self, journal: Journal, submission: Submission, decision: Decision, actor: User, *, reason: str = ""
    ) -> EditorialDecision:
        """A publishing step (schedule, unschedule, publish), checked against the same table of transitions.
        The publishing module calls this after its own checks (issue, galleys, fee)."""
        rule = RULES[decision]
        if not rule.publishing:
            raise ValueError(f"{decision} is not a publishing step")
        if not allowed_here(rule, stage=submission.stage, status=submission.status, round_status=None):
            raise Conflict(f"“{rule.label}” is not possible at this point.", code="decision_not_allowed")
        stage_before = submission.stage
        if rule.to_stage is not None:
            submission.stage = rule.to_stage
        if rule.to_status is not None:
            submission.status = rule.to_status
        record = EditorialDecision(
            submission_id=submission.id,
            round_id=None,
            decision=rule.decision.value,
            is_recommendation=False,
            stage_before=stage_before,
            stage_after=submission.stage,
            status_after=submission.status,
            made_by_id=actor.id,
            reason=reason,
            letter_to=[],
        )
        record.made_by = actor
        self.db.add(record)
        await self.db.flush()
        await self.audit.record(
            "submission.decision",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"decision": rule.decision.value, "status": submission.status},
        )
        return record

    async def _deciders(self, journal: Journal, submission: Submission) -> list[User]:
        deciders = [
            p.user
            for p in submission.participants
            if p.role == ParticipantRole.EDITOR and not p.recommend_only
        ]
        if not deciders:
            deciders = list(await self.journals.users_with_role(journal.id, Role.EDITOR_IN_CHIEF))
        return [u for u in deciders if u.is_active]

    async def _tell_deciders(
        self, journal: Journal, submission: Submission, rule: Rule, comment: str, actor: User
    ) -> None:
        for editor in await self._deciders(journal, submission):
            if editor.id == actor.id:
                continue
            await self.mailer.send(
                journal,
                emails.RECOMMENDATION.key,
                submission,
                to_name=editor.full_name,
                to_email=editor.email,
                values={
                    "editorName": actor.full_name,
                    "recommendation": rule.label.removeprefix("Recommend ").capitalize(),
                    "comment": comment,
                },
                sent_by_id=actor.id,
            )

    async def withdraw(
        self, journal: Journal, submission: Submission, access: Access, reason: str, actor: User
    ) -> EditorialDecision:
        if not access.is_author:
            raise Forbidden("Only the manuscript's authors can withdraw it.")
        rule = RULES[Decision.WITHDRAW]
        if not allowed_here(rule, stage=submission.stage, status=submission.status, round_status=None):
            raise Conflict(
                "The manuscript can no longer be withdrawn here. Write to the editors.",
                code="decision_not_allowed",
            )
        current = await self.review.current_round(submission.id)
        if current is not None and current.status != RoundStatus.CLOSED:
            await self.review.close_round(journal, submission, current, actor)
        stage_before = submission.stage
        submission.status = rule.to_status or submission.status
        record = EditorialDecision(
            submission_id=submission.id,
            round_id=current.id if current else None,
            decision=rule.decision.value,
            is_recommendation=False,
            stage_before=stage_before,
            stage_after=submission.stage,
            status_after=submission.status,
            made_by_id=actor.id,
            reason=reason,
            letter_to=[],
        )
        record.made_by = actor
        self.db.add(record)
        await self.db.flush()
        for editor in await editors_to_notify(self.journals, submission):
            await self.mailer.send(
                journal,
                emails.WITHDRAWN.key,
                submission,
                to_name=editor.full_name,
                to_email=editor.email,
                values={"reason": reason},
                sent_by_id=actor.id,
            )
        await self.audit.record(
            "submission.withdrawn", "submission", submission.id, actor_id=actor.id, journal_id=journal.id
        )
        return record

    async def decisions(self, submission: Submission) -> Sequence[EditorialDecision]:
        return (
            await self.db.scalars(
                select(EditorialDecision)
                .where(EditorialDecision.submission_id == submission.id)
                .order_by(EditorialDecision.created_at, EditorialDecision.id)
            )
        ).all()

    # ------------------------------------------------------------------ editors

    async def candidates(self, journal: Journal, submission: Submission, role: str) -> list[User]:
        """People with the journal role for this part of the work, not yet assigned, not authors."""
        assigned = {p.user_id for p in submission.participants if p.role == role}
        authors = {c.email for c in submission.publication.contributors} | {submission.submitter.email}
        people: dict[int, User] = {}
        for journal_role in PARTICIPANT_ROLES[role]:
            for user in await self.journals.users_with_role(journal.id, journal_role):
                if user.id not in assigned and user.email not in authors:
                    people[user.id] = user
        return sorted(people.values(), key=lambda u: (u.family_name.lower(), u.given_name.lower()))

    @staticmethod
    def _may_assign(access: Access, role: str) -> None:
        # Deciding editors choose the editors; any of the manuscript's editors brings in production help.
        allowed = access.can_decide if role == ParticipantRole.EDITOR else access.can_manage
        if not allowed:
            raise Forbidden("Only the manuscript's editors can change who works on it.")

    async def assign(
        self, journal: Journal, submission: Submission, access: Access, data: EditorIn, actor: User
    ) -> None:
        self._may_assign(access, data.role)
        if submission.participant(data.user_id, data.role) is not None:
            raise Conflict("This person is already assigned.", code="already_assigned")
        candidate = next(
            (u for u in await self.candidates(journal, submission, data.role) if u.id == data.user_id), None
        )
        if candidate is None:
            raise ValidationFailed(
                "Choose someone with this role in the journal who is not an author of this manuscript.",
                code="not_eligible",
            )
        participant = Participant(
            user_id=candidate.id,
            role=data.role,
            recommend_only=data.recommend_only and data.role == ParticipantRole.EDITOR,
            assigned_by_id=actor.id,
        )
        participant.user = candidate  # loaded now, so responses never trigger lazy loading
        submission.participants.append(participant)
        await self.db.flush()
        if data.notify and candidate.id != actor.id:
            if data.role == ParticipantRole.EDITOR:
                key, values = (
                    emails.EDITOR_ASSIGNED.key,
                    {
                        "assignedBy": actor.full_name,
                        "roleNote": " and recommend a decision" if data.recommend_only else "",
                    },
                )
            else:
                key, values = (
                    emails.PRODUCTION_ASSIGNED.key,
                    {"assignedBy": actor.full_name, "task": TASKS[data.role]},
                )
            await self.mailer.send(
                journal,
                key,
                submission,
                to_name=candidate.full_name,
                to_email=candidate.email,
                values=values,
                sent_by_id=actor.id,
            )
        await self.audit.record(
            "submission.participant_assigned",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"user_id": candidate.id, "role": data.role, "recommend_only": participant.recommend_only},
        )

    async def unassign(
        self, journal: Journal, submission: Submission, access: Access, user_id: int, role: str, actor: User
    ) -> None:
        self._may_assign(access, role)
        participant = submission.participant(user_id, role)
        if participant is None:
            raise NotFound("This person is not assigned.")
        submission.participants.remove(participant)
        await self.db.flush()
        await self.audit.record(
            "submission.participant_unassigned",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"user_id": user_id, "role": role},
        )

    # ------------------------------------------------------------------ discussions

    async def people(self, journal: Journal, submission: Submission) -> list[tuple[User, str]]:
        """Who can take part in discussions: the manuscript's editors and its authors with accounts."""
        result: dict[int, tuple[User, str]] = {}
        for participant in submission.participants:
            role = "editor" if participant.role == ParticipantRole.EDITOR else "production"
            result[participant.user.id] = (participant.user, role)
        for chief in await self.journals.users_with_role(journal.id, Role.EDITOR_IN_CHIEF):
            result.setdefault(chief.id, (chief, "editor"))
        authors = [submission.submitter]
        contributor_ids = [c.user_id for c in submission.publication.contributors if c.user_id is not None]
        if contributor_ids:
            authors += list((await self.db.scalars(select(User).where(User.id.in_(contributor_ids)))).all())
        for author in authors:
            result[author.id] = (author, "author")
        return [(user, role) for user, role in result.values() if user.is_active]

    async def discussions(self, submission: Submission, access: Access, user: User) -> list[Discussion]:
        rows = (
            await self.db.scalars(
                select(Discussion)
                .where(Discussion.submission_id == submission.id)
                .order_by(Discussion.id.desc())
            )
        ).all()
        # The manuscript's editors oversee every discussion; others see the ones they are in.
        return [d for d in rows if access.can_manage or any(p.id == user.id for p in d.participants)]

    async def get_discussion(
        self, submission: Submission, access: Access, user: User, discussion_id: int
    ) -> Discussion:
        for discussion in await self.discussions(submission, access, user):
            if discussion.id == discussion_id:
                return discussion
        raise NotFound("Discussion not found.")

    async def create_discussion(
        self, journal: Journal, submission: Submission, access: Access, data: DiscussionCreate, actor: User
    ) -> Discussion:
        if not (access.is_author or access.can_manage or access.production_roles):
            raise Forbidden("Only the manuscript's authors and editors can start discussions.")
        people = {user.id: user for user, _ in await self.people(journal, submission)}
        chosen = []
        for user_id in dict.fromkeys(data.participant_ids):
            if user_id not in people:
                raise ValidationFailed(
                    "Some participants cannot take part in this discussion.", code="invalid_participant"
                )
            chosen.append(people[user_id])
        if actor.id not in {u.id for u in chosen}:
            chosen.append(actor)
        discussion = Discussion(
            submission_id=submission.id, stage=submission.stage, subject=data.subject, created_by_id=actor.id
        )
        discussion.participants = chosen
        discussion.messages = []
        self.db.add(discussion)
        await self.db.flush()
        await self._post(journal, submission, discussion, data.message, actor)
        return discussion

    async def add_message(
        self, journal: Journal, submission: Submission, discussion: Discussion, body: str, actor: User
    ) -> None:
        if discussion.is_closed:
            raise Conflict("This discussion is closed.", code="discussion_closed")
        if actor.id not in {p.id for p in discussion.participants}:
            discussion.participants.append(actor)  # an overseeing editor joins by writing
        await self._post(journal, submission, discussion, body, actor)

    async def _post(
        self, journal: Journal, submission: Submission, discussion: Discussion, body: str, actor: User
    ) -> None:
        message = DiscussionMessage(discussion_id=discussion.id, author_id=actor.id, body=body)
        message.author = actor
        discussion.messages.append(message)
        await self.db.flush()
        for person in discussion.participants:
            if person.id == actor.id or not person.is_active:
                continue
            await self.mailer.send(
                journal,
                emails.DISCUSSION_MESSAGE.key,
                submission,
                to_name=person.full_name,
                to_email=person.email,
                values={
                    "discussionSubject": discussion.subject,
                    "messageAuthor": actor.full_name,
                    "messageText": body,
                },
                sent_by_id=actor.id,
            )

    async def set_closed(self, discussion: Discussion, access: Access, actor: User, closed: bool) -> None:
        if not (access.can_manage or discussion.created_by_id == actor.id):
            raise Forbidden("Only the editors or the person who started the discussion can close it.")
        discussion.is_closed = closed
        await self.db.flush()
