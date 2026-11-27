"""Peer review: rounds, review requests, reviews, and the author's revisions.

The router checks who is asking (``submissions.policies.access_for`` for editors and authors,
``reviewer_id`` for reviewers) before calling this service. The service enforces the rules of the
review process itself: what may happen in which state.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.storage import PresignedUpload, Storage
from app.modules.audit.service import AuditService
from app.modules.files.models import FileStage, FileStatus, SubmissionFile
from app.modules.files.service import FileService
from app.modules.files.types import Genre
from app.modules.identity.models import User
from app.modules.journals.email_templates import Rendered, fill
from app.modules.journals.models import Journal
from app.modules.journals.permissions import Role
from app.modules.journals.review_settings import ReviewSettings, review_settings
from app.modules.journals.schemas import InviteIn as MemberInviteIn
from app.modules.journals.service import JournalService
from app.modules.journals.submission_settings import submission_settings
from app.modules.review import emails
from app.modules.review.forms import (
    DEFAULT_FORM,
    ReviewFormIn,
    clean_answers,
    missing_answers,
    questions_of,
)
from app.modules.review.models import (
    AWAITING_REVISIONS,
    OPEN_STATUSES,
    RECOMMENDATION_LABELS,
    AssignmentStatus,
    DeclineReason,
    ReviewAssignment,
    ReviewForm,
    ReviewReminder,
    ReviewRound,
    RoundStatus,
)
from app.modules.review.schemas import NewReviewer, ReviewerInviteIn, ReviewIn
from app.modules.submissions.mailer import Mailer
from app.modules.submissions.models import ParticipantRole, Submission
from app.modules.submissions.schemas import UploadRequest
from app.modules.submissions.service import editors_to_notify

DECLINE_LABELS = {
    DeclineReason.CONFLICT_OF_INTEREST: "Conflict of interest",
    DeclineReason.NO_TIME: "No time at the moment",
    DeclineReason.OUTSIDE_EXPERTISE: "Outside my expertise",
    DeclineReason.OTHER: "Other reason",
}
MAX_ATTACHMENTS = 10
MAX_REVISION_FILES = 30


def today() -> date:
    return utcnow().date()


def is_overdue(assignment: ReviewAssignment) -> bool:
    if assignment.status == AssignmentStatus.INVITED:
        return today() > assignment.response_due
    if assignment.status == AssignmentStatus.ACCEPTED:
        return today() > assignment.review_due
    return False


def format_date(value: date) -> str:
    return f"{value.day} {value.strftime('%B %Y')}"


class ReviewService:
    def __init__(self, db: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.db = db
        self.settings = settings
        self.files = FileService(db, storage)
        self.journals = JournalService(db, settings)
        self.mailer = Mailer(db, settings)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ rounds

    async def rounds(self, submission_id: int) -> Sequence[ReviewRound]:
        return (
            await self.db.scalars(
                select(ReviewRound)
                .where(ReviewRound.submission_id == submission_id)
                .order_by(ReviewRound.number)
            )
        ).all()

    async def current_round(self, submission_id: int) -> ReviewRound | None:
        rounds = await self.rounds(submission_id)
        return rounds[-1] if rounds else None

    async def get_round(self, submission: Submission, round_id: int) -> ReviewRound:
        found = await self.db.scalar(
            select(ReviewRound).where(ReviewRound.id == round_id, ReviewRound.submission_id == submission.id)
        )
        if found is None:
            raise NotFound("Review round not found.")
        return found

    async def require_current(self, submission: Submission, round_id: int) -> ReviewRound:
        found = await self.get_round(submission, round_id)
        current = await self.current_round(submission.id)
        if current is None or current.id != found.id or found.status == RoundStatus.CLOSED:
            raise Conflict("This review round is closed.", code="round_closed")
        return found

    async def start_round(
        self, journal: Journal, submission: Submission, file_ids: Sequence[int], actor: User
    ) -> ReviewRound:
        """Open the next round with copies of the chosen files for its reviewers."""
        if not file_ids:
            raise ValidationFailed(
                "Choose the files the reviewers will receive.",
                code="no_review_files",
                errors=[FieldError(field="review_file_ids", message="Choose at least one file")],
            )
        previous = await self.current_round(submission.id)
        if previous is not None and previous.status != RoundStatus.CLOSED:
            await self.close_round(journal, submission, previous, actor)
        review_round = ReviewRound(
            submission_id=submission.id,
            number=(previous.number + 1) if previous else 1,
            status=RoundStatus.REVIEW,
        )
        self.db.add(review_round)
        await self.db.flush()
        await self.add_review_files(journal, submission, review_round, file_ids, actor)
        return review_round

    async def close_round(
        self, journal: Journal, submission: Submission, review_round: ReviewRound, actor: User
    ) -> None:
        """End a round. Requests still open are cancelled and their reviewers told."""
        review_round.status = RoundStatus.CLOSED
        review_round.closed_at = utcnow()
        for assignment in await self.assignments(submission.id, round_id=review_round.id):
            if assignment.status in OPEN_STATUSES:
                await self._cancel(journal, submission, assignment, actor, notify=True)
        await self.db.flush()

    async def add_review_files(
        self,
        journal: Journal,
        submission: Submission,
        review_round: ReviewRound,
        file_ids: Sequence[int],
        actor: User,
    ) -> list[SubmissionFile]:
        sources = (
            await self.db.scalars(
                select(SubmissionFile).where(
                    SubmissionFile.id.in_(list(file_ids)),
                    SubmissionFile.submission_id == submission.id,
                    SubmissionFile.file_stage.in_(
                        [FileStage.SUBMISSION, FileStage.REVISION, FileStage.REVIEW]
                    ),
                )
            )
        ).all()
        if len(sources) != len(set(file_ids)):
            raise ValidationFailed(
                "Some of the chosen files do not belong to this manuscript.", code="file_not_found"
            )
        copies = [
            await self.files.create_review_copy(
                source, journal_id=journal.id, review_round_id=review_round.id, created_by_id=actor.id
            )
            for source in sources
        ]
        await self.audit.record(
            "review.files_added",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"round": review_round.number, "files": [s.id for s in sources]},
        )
        return copies

    async def remove_review_file(
        self, submission: Submission, review_round: ReviewRound, file_id: int
    ) -> None:
        record = await self.files.get(submission.id, file_id)
        if record.file_stage != FileStage.REVIEW or record.review_round_id != review_round.id:
            raise NotFound("File not found.")
        await self.files.delete(record)

    # ------------------------------------------------------------------ requests (editors)

    async def assignments(
        self, submission_id: int, *, round_id: int | None = None
    ) -> Sequence[ReviewAssignment]:
        query = select(ReviewAssignment).where(ReviewAssignment.submission_id == submission_id)
        if round_id is not None:
            query = query.where(ReviewAssignment.round_id == round_id)
        return (await self.db.scalars(query.order_by(ReviewAssignment.id))).all()

    async def get_assignment(self, submission: Submission, assignment_id: int) -> ReviewAssignment:
        found = await self.db.scalar(
            select(ReviewAssignment).where(
                ReviewAssignment.id == assignment_id, ReviewAssignment.submission_id == submission.id
            )
        )
        if found is None:
            raise NotFound("Review request not found.")
        return found

    def _dates(
        self, settings: ReviewSettings, response_due: date | None, review_due: date | None
    ) -> tuple[date, date]:
        response = response_due or today() + timedelta(days=settings.response_days)
        review = review_due or response + timedelta(days=settings.review_days)
        errors = []
        if response < today():
            errors.append(FieldError(field="response_due", message="The date has passed"))
        if review < response:
            errors.append(FieldError(field="review_due", message="Must not be before the response date"))
        if errors:
            raise ValidationFailed("Check the dates.", code="invalid_dates", errors=errors)
        return response, review

    def _check_reviewer(self, submission: Submission, user: User) -> None:
        emails_of_authors = {c.email for c in submission.publication.contributors} | {
            submission.submitter.email
        }
        if user.email in emails_of_authors or any(
            c.user_id == user.id for c in submission.publication.contributors
        ):
            raise Conflict("An author of the manuscript cannot review it.", code="reviewer_is_author")
        if submission.participant(user.id, ParticipantRole.EDITOR) is not None:
            raise Conflict("The manuscript's editors cannot review it.", code="reviewer_is_editor")
        if not user.is_active:
            raise Conflict("This account is blocked.", code="reviewer_inactive")

    async def _known_reviewer(self, journal: Journal, reviewer_id: int) -> User:
        user = await self.db.get(User, reviewer_id)
        if user is None or Role.REVIEWER not in await self.journals.roles_of(journal.id, user.id):
            raise ValidationFailed(
                "This person is not one of the journal's reviewers.", code="not_a_reviewer"
            )
        return user

    async def _new_reviewer(self, journal: Journal, data: NewReviewer, actor: User) -> tuple[User, bool]:
        """Someone not yet a reviewer: an existing account gets the role, a new person an invitation."""
        existing = await self.journals.identity.get_by_email(str(data.email))
        if existing is not None:
            roles = await self.journals.roles_of(journal.id, existing.id)
            if Role.REVIEWER not in roles:
                await self.journals.set_roles(journal, existing, roles | {Role.REVIEWER}, actor=actor)
            return existing, False
        invited = await self.journals.invite_member(
            journal,
            MemberInviteIn(
                email=data.email,
                given_name=data.given_name,
                family_name=data.family_name,
                affiliation=data.affiliation,
                roles=[Role.REVIEWER],
            ),
            actor=actor,
        )
        return invited, True

    async def _reviewer_number(self, submission_id: int, reviewer_id: int) -> int:
        rows = (
            await self.db.execute(
                select(ReviewAssignment.reviewer_id, ReviewAssignment.reviewer_number).where(
                    ReviewAssignment.submission_id == submission_id
                )
            )
        ).all()
        for row_reviewer, number in rows:
            if row_reviewer == reviewer_id:
                return int(number)
        return max((int(number) for _, number in rows), default=0) + 1

    async def invitation_email(
        self,
        journal: Journal,
        submission: Submission,
        *,
        reviewer_name: str,
        response_due: date,
        review_due: date,
        assignment_id: int | None,
        new_account: bool,
        editor: User,
    ) -> Rendered:
        note = (
            "We have also sent you a separate e-mail to set up your account with the journal. "
            "Please set your password first, then open the link above.\n\n"
            if new_account
            else ""
        )
        return await self.mailer.render(
            journal,
            emails.REQUEST.key,
            submission,
            recipient_name=reviewer_name,
            values={
                "submissionAbstract": submission.publication.abstract,
                # Before the request exists the link is unknown: {reviewUrl} stays in the preview
                # and is filled in when the e-mail is sent.
                **({"reviewUrl": self.review_url(assignment_id)} if assignment_id is not None else {}),
                "responseDueDate": format_date(response_due),
                "reviewDueDate": format_date(review_due),
                "editorName": editor.full_name,
                "accountNote": note,
            },
        )

    async def preview_invitation(
        self,
        journal: Journal,
        submission: Submission,
        *,
        reviewer_id: int | None,
        new_reviewer: NewReviewer | None,
        response_due: date | None,
        review_due: date | None,
        editor: User,
    ) -> tuple[Rendered, str]:
        settings = review_settings(journal)
        response, review = self._dates(settings, response_due, review_due)
        if reviewer_id is not None:
            user = await self._known_reviewer(journal, reviewer_id)
            name, email, new_account = user.full_name, user.email, user.password_hash is None
        elif new_reviewer is not None:
            existing = await self.journals.identity.get_by_email(str(new_reviewer.email))
            name = f"{new_reviewer.given_name} {new_reviewer.family_name}".strip()
            email = str(new_reviewer.email)
            new_account = existing is None or existing.password_hash is None
        else:
            raise ValidationFailed("Choose a reviewer.", code="no_reviewer")
        rendered = await self.invitation_email(
            journal,
            submission,
            reviewer_name=name,
            response_due=response,
            review_due=review,
            assignment_id=None,
            new_account=new_account,
            editor=editor,
        )
        return rendered, email

    async def invite(
        self,
        journal: Journal,
        submission: Submission,
        review_round: ReviewRound,
        data: ReviewerInviteIn,
        actor: User,
    ) -> ReviewAssignment:
        if review_round.status != RoundStatus.REVIEW:
            raise Conflict(
                "Reviewers can be invited only while the round is under review.", code="round_not_in_review"
            )
        if data.reviewer_id is not None and data.new_reviewer is not None:
            raise ValidationFailed("Choose one reviewer.", code="no_reviewer")
        settings = review_settings(journal)
        response_due, review_due = self._dates(settings, data.response_due, data.review_due)
        if data.reviewer_id is not None:
            reviewer, new_account = await self._known_reviewer(journal, data.reviewer_id), False
        elif data.new_reviewer is not None:
            reviewer, new_account = await self._new_reviewer(journal, data.new_reviewer, actor)
        else:
            raise ValidationFailed("Choose one reviewer.", code="no_reviewer")
        self._check_reviewer(submission, reviewer)
        new_account = new_account or reviewer.password_hash is None
        form = await self._form(journal, data.form_id)

        assignment = await self.db.scalar(
            select(ReviewAssignment).where(
                ReviewAssignment.round_id == review_round.id, ReviewAssignment.reviewer_id == reviewer.id
            )
        )
        if assignment is not None and assignment.status not in (
            AssignmentStatus.DECLINED,
            AssignmentStatus.CANCELLED,
        ):
            raise Conflict("This reviewer is already invited to this round.", code="already_invited")
        if assignment is None:
            assignment = ReviewAssignment(
                round_id=review_round.id,
                submission_id=submission.id,
                reviewer_id=reviewer.id,
                reviewer_number=await self._reviewer_number(submission.id, reviewer.id),
            )
            assignment.reviewer = reviewer
            self.db.add(assignment)
        # A new request, or a fresh one for someone who declined or was cancelled.
        assignment.method = (data.method or settings.method).value
        assignment.status = AssignmentStatus.INVITED
        assignment.form_id = form.id
        assignment.questions = list(form.questions)
        assignment.invited_by_id = actor.id
        assignment.invited_at = utcnow()
        assignment.response_due = response_due
        assignment.review_due = review_due
        assignment.responded_at = None
        assignment.cancelled_at = None
        assignment.decline_reason = None
        assignment.decline_comment = ""
        await self.db.flush()

        if data.email is not None:
            rendered = Rendered(subject=data.email.subject, body=data.email.body)
        else:
            rendered = await self.invitation_email(
                journal,
                submission,
                reviewer_name=reviewer.full_name,
                response_due=response_due,
                review_due=review_due,
                assignment_id=assignment.id,
                new_account=new_account,
                editor=actor,
            )
        link = {"reviewUrl": self.review_url(assignment.id)}
        await self.mailer.send_rendered(
            Rendered(subject=fill(rendered.subject, link), body=fill(rendered.body, link)),
            submission,
            to_email=reviewer.email,
            key=emails.REQUEST.key,
            sent_by_id=actor.id,
        )
        await self.audit.record(
            "review.invited",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"round": review_round.number, "reviewer_id": reviewer.id, "method": assignment.method},
        )
        return assignment

    async def set_dates(self, assignment: ReviewAssignment, response_due: date, review_due: date) -> None:
        if assignment.status not in OPEN_STATUSES:
            raise Conflict("Dates can be changed only while the review is open.", code="review_not_open")
        if review_due < response_due:
            raise ValidationFailed(
                "Check the dates.",
                code="invalid_dates",
                errors=[FieldError(field="review_due", message="Must not be before the response date")],
            )
        assignment.response_due = response_due
        assignment.review_due = review_due
        await self.db.flush()

    async def cancel(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        actor: User,
        *,
        notify: bool,
    ) -> None:
        if assignment.status not in OPEN_STATUSES:
            raise Conflict("Only open review requests can be cancelled.", code="review_not_open")
        await self._cancel(journal, submission, assignment, actor, notify=notify)

    async def _cancel(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        actor: User,
        *,
        notify: bool,
    ) -> None:
        assignment.status = AssignmentStatus.CANCELLED
        assignment.cancelled_at = utcnow()
        if notify:
            await self.mailer.send(
                journal,
                emails.CANCELLED.key,
                submission,
                to_name=assignment.reviewer.full_name,
                to_email=assignment.reviewer.email,
                values=self._reviewer_values(assignment, editor=actor),
                sent_by_id=actor.id,
            )
        await self.audit.record(
            "review.cancelled",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"reviewer_id": assignment.reviewer_id},
        )

    def review_url(self, assignment_id: int) -> str:
        return f"{self.settings.workspace_url}/reviews/{assignment_id}"

    def _reviewer_values(self, assignment: ReviewAssignment, *, editor: User | None = None) -> dict[str, str]:
        return {
            "reviewUrl": self.review_url(assignment.id),
            "responseDueDate": format_date(assignment.response_due),
            "reviewDueDate": format_date(assignment.review_due),
            "editorName": editor.full_name if editor else "",
        }

    def reminder_key(self, assignment: ReviewAssignment) -> str:
        if assignment.status == AssignmentStatus.INVITED:
            return emails.RESPONSE_REMINDER.key
        if assignment.status == AssignmentStatus.ACCEPTED:
            return emails.REVIEW_REMINDER.key
        raise Conflict("Only open review requests can be followed up.", code="review_not_open")

    async def reminder_email(
        self, journal: Journal, submission: Submission, assignment: ReviewAssignment, editor: User | None
    ) -> Rendered:
        return await self.mailer.render(
            journal,
            self.reminder_key(assignment),
            submission,
            recipient_name=assignment.reviewer.full_name,
            values=self._reviewer_values(assignment, editor=editor),
        )

    async def remind(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        email: Rendered,
        actor: User,
    ) -> None:
        key = self.reminder_key(assignment)
        sent_before = await self.db.scalar(
            select(func.count()).where(
                ReviewReminder.assignment_id == assignment.id, ReviewReminder.kind == "manual"
            )
        )
        self.db.add(
            ReviewReminder(
                assignment_id=assignment.id, kind="manual", offset_days=int(sent_before or 0), due=today()
            )
        )
        await self.mailer.send_rendered(
            email, submission, to_email=assignment.reviewer.email, key=key, sent_by_id=actor.id
        )
        await self.db.flush()

    async def thanks_email(
        self, journal: Journal, submission: Submission, assignment: ReviewAssignment, editor: User
    ) -> Rendered:
        return await self.mailer.render(
            journal,
            emails.THANKS.key,
            submission,
            recipient_name=assignment.reviewer.full_name,
            values=self._reviewer_values(assignment, editor=editor),
        )

    async def acknowledge(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        *,
        rating: int | None,
        email: Rendered | None,
        actor: User,
    ) -> None:
        if assignment.status != AssignmentStatus.COMPLETED:
            raise Conflict("Only finished reviews can be acknowledged.", code="review_not_completed")
        assignment.rating = rating
        if assignment.acknowledged_at is None:
            assignment.acknowledged_at = utcnow()
            if email is not None:
                await self.mailer.send_rendered(
                    email,
                    submission,
                    to_email=assignment.reviewer.email,
                    key=emails.THANKS.key,
                    sent_by_id=actor.id,
                )
        await self.db.flush()

    async def last_reminders(self, assignment_ids: Sequence[int]) -> dict[int, datetime]:
        if not assignment_ids:
            return {}
        rows = await self.db.execute(
            select(ReviewReminder.assignment_id, func.max(ReviewReminder.sent_at))
            .where(ReviewReminder.assignment_id.in_(list(assignment_ids)))
            .group_by(ReviewReminder.assignment_id)
        )
        return {assignment_id: sent for assignment_id, sent in rows}

    # ------------------------------------------------------------------ reviewers

    async def for_reviewer(self, user: User, assignment_id: int) -> ReviewAssignment:
        found = await self.db.scalar(
            select(ReviewAssignment).where(
                ReviewAssignment.id == assignment_id, ReviewAssignment.reviewer_id == user.id
            )
        )
        if found is None or found.status == AssignmentStatus.CANCELLED:
            raise NotFound("Review not found.")
        return found

    async def reviewer_tasks(self, user: User, journal: Journal) -> Sequence[ReviewAssignment]:
        return (
            await self.db.scalars(
                select(ReviewAssignment)
                .join(Submission, Submission.id == ReviewAssignment.submission_id)
                .where(
                    ReviewAssignment.reviewer_id == user.id,
                    ReviewAssignment.status != AssignmentStatus.CANCELLED,
                    Submission.journal_id == journal.id,
                )
                .order_by(ReviewAssignment.invited_at.desc(), ReviewAssignment.id.desc())
            )
        ).all()

    async def _require_open_round(self, assignment: ReviewAssignment) -> None:
        if assignment.round.status == RoundStatus.CLOSED:
            raise Conflict("This review is no longer needed.", code="round_closed")

    async def accept(
        self, journal: Journal, submission: Submission, assignment: ReviewAssignment, competing: str
    ) -> None:
        if assignment.status != AssignmentStatus.INVITED:
            raise Conflict("You have already answered this request.", code="already_answered")
        await self._require_open_round(assignment)
        assignment.status = AssignmentStatus.ACCEPTED
        assignment.responded_at = utcnow()
        assignment.competing_interests = competing
        await self.db.flush()
        await self.audit.record(
            "review.accepted",
            "submission",
            submission.id,
            actor_id=assignment.reviewer_id,
            journal_id=journal.id,
        )

    async def decline(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        reason: str,
        comment: str,
    ) -> None:
        if assignment.status != AssignmentStatus.INVITED:
            raise Conflict("You have already answered this request.", code="already_answered")
        assignment.status = AssignmentStatus.DECLINED
        assignment.responded_at = utcnow()
        assignment.decline_reason = reason
        assignment.decline_comment = comment
        await self.db.flush()
        explanation = DECLINE_LABELS.get(reason, reason) + (f" — {comment}" if comment else "")
        await self._tell_editors(
            journal,
            submission,
            emails.DECLINED_TO_EDITOR.key,
            {"reviewerName": assignment.reviewer.full_name, "declineReason": explanation},
        )
        await self.audit.record(
            "review.declined",
            "submission",
            submission.id,
            actor_id=assignment.reviewer_id,
            journal_id=journal.id,
            data={"reason": reason},
        )

    async def save_draft(self, assignment: ReviewAssignment, data: ReviewIn) -> None:
        self.require_editable(assignment)
        assignment.answers = clean_answers(questions_of(assignment.questions), data.answers)
        assignment.recommendation = data.recommendation
        assignment.comments_for_author = data.comments_for_author.strip()
        assignment.comments_for_editor = data.comments_for_editor.strip()
        await self.db.flush()

    async def submit_review(
        self, journal: Journal, submission: Submission, assignment: ReviewAssignment, data: ReviewIn
    ) -> None:
        self.require_editable(assignment)
        await self._require_open_round(assignment)
        questions = questions_of(assignment.questions)
        answers = clean_answers(questions, data.answers)
        errors = missing_answers(questions, answers)
        if data.recommendation is None:
            errors.append(FieldError(field="recommendation", message="Choose a recommendation"))
        visible = [q for q in questions if q.visible_to_author and q.id in answers]
        if not data.comments_for_author.strip() and not visible:
            errors.append(
                FieldError(field="comments_for_author", message="Write your comments for the authors")
            )
        pending = [
            f
            for f in await self.files.list(
                submission.id, file_stage=FileStage.REVIEW_ATTACHMENT, review_assignment_id=assignment.id
            )
            if f.current.status in (FileStatus.PENDING_UPLOAD, FileStatus.PROCESSING)
        ]
        if pending:
            errors.append(
                FieldError(field="attachments", message="Wait until your files are uploaded and checked")
            )
        if errors:
            raise ValidationFailed("The review is not complete yet.", code="review_incomplete", errors=errors)
        assignment.answers = answers
        assignment.recommendation = data.recommendation
        assignment.comments_for_author = data.comments_for_author.strip()
        assignment.comments_for_editor = data.comments_for_editor.strip()
        assignment.status = AssignmentStatus.COMPLETED
        assignment.completed_at = utcnow()
        await self.db.flush()
        await self._tell_editors(
            journal,
            submission,
            emails.COMPLETED_TO_EDITOR.key,
            {
                "reviewerName": assignment.reviewer.full_name,
                "recommendation": RECOMMENDATION_LABELS.get(data.recommendation or "", ""),
            },
        )
        await self.audit.record(
            "review.completed",
            "submission",
            submission.id,
            actor_id=assignment.reviewer_id,
            journal_id=journal.id,
            data={"recommendation": data.recommendation},
        )

    @staticmethod
    def require_editable(assignment: ReviewAssignment) -> None:
        if assignment.status == AssignmentStatus.INVITED:
            raise Conflict("Accept the request before writing the review.", code="not_accepted")
        if assignment.status != AssignmentStatus.ACCEPTED:
            raise Conflict("This review can no longer be changed.", code="review_closed")

    async def request_attachment(
        self,
        journal: Journal,
        submission: Submission,
        assignment: ReviewAssignment,
        data: UploadRequest,
        user: User,
    ) -> tuple[SubmissionFile, PresignedUpload]:
        self.require_editable(assignment)
        existing = await self.files.list(
            submission.id, file_stage=FileStage.REVIEW_ATTACHMENT, review_assignment_id=assignment.id
        )
        if len(existing) >= MAX_ATTACHMENTS:
            raise Conflict(f"A review can have at most {MAX_ATTACHMENTS} files.", code="too_many_files")
        return await self.files.request_upload(
            journal_id=journal.id,
            submission_id=submission.id,
            genre=Genre.SUPPLEMENTARY,
            file_name=data.file_name,
            size=data.size,
            max_size_mb=submission_settings(journal).max_file_size_mb,
            uploaded_by_id=user.id,
            file_stage=FileStage.REVIEW_ATTACHMENT,
            review_round_id=assignment.round_id,
            review_assignment_id=assignment.id,
        )

    async def attachment(
        self, submission: Submission, assignment: ReviewAssignment, file_id: int
    ) -> SubmissionFile:
        record = await self.files.get(submission.id, file_id)
        if record.review_assignment_id != assignment.id or record.file_stage != FileStage.REVIEW_ATTACHMENT:
            raise NotFound("File not found.")
        return record

    # ------------------------------------------------------------------ authors' revisions

    async def request_revision_upload(
        self,
        journal: Journal,
        submission: Submission,
        review_round: ReviewRound,
        data: UploadRequest,
        user: User,
    ) -> tuple[SubmissionFile, PresignedUpload]:
        self.require_awaiting_revisions(review_round)
        existing = await self.files.list(
            submission.id, file_stage=FileStage.REVISION, review_round_id=review_round.id
        )
        if len(existing) >= MAX_REVISION_FILES:
            raise Conflict(f"A revision can have at most {MAX_REVISION_FILES} files.", code="too_many_files")
        return await self.files.request_upload(
            journal_id=journal.id,
            submission_id=submission.id,
            genre=data.genre,
            file_name=data.file_name,
            size=data.size,
            max_size_mb=submission_settings(journal).max_file_size_mb,
            uploaded_by_id=user.id,
            file_stage=FileStage.REVISION,
            review_round_id=review_round.id,
        )

    async def revision_file(
        self, submission: Submission, review_round: ReviewRound, file_id: int
    ) -> SubmissionFile:
        record = await self.files.get(submission.id, file_id)
        if record.file_stage != FileStage.REVISION or record.review_round_id != review_round.id:
            raise NotFound("File not found.")
        return record

    @staticmethod
    def require_awaiting_revisions(review_round: ReviewRound) -> None:
        if review_round.status not in AWAITING_REVISIONS:
            raise Conflict("The editor has not asked for revisions.", code="revisions_not_requested")

    async def submit_revisions(
        self, journal: Journal, submission: Submission, review_round: ReviewRound, response: str, user: User
    ) -> None:
        self.require_awaiting_revisions(review_round)
        files = await self.files.list(
            submission.id, file_stage=FileStage.REVISION, review_round_id=review_round.id
        )
        if not any(f.current.status == FileStatus.READY for f in files):
            raise ValidationFailed(
                "Upload the revised manuscript first.",
                code="no_revision_files",
                errors=[FieldError(field="files", message="Upload at least one revised file")],
            )
        if any(f.current.status in (FileStatus.PENDING_UPLOAD, FileStatus.PROCESSING) for f in files):
            raise Conflict("Wait until all files are uploaded and checked.", code="files_not_ready")
        review_round.status = RoundStatus.REVISIONS_SUBMITTED
        review_round.author_response = response
        review_round.revisions_submitted_at = utcnow()
        await self.db.flush()
        await self._tell_editors(
            journal, submission, emails.REVISIONS_TO_EDITOR.key, {"roundNumber": str(review_round.number)}
        )
        await self.audit.record(
            "review.revisions_submitted",
            "submission",
            submission.id,
            actor_id=user.id,
            journal_id=journal.id,
            data={"round": review_round.number},
        )

    # ------------------------------------------------------------------ forms

    async def forms(self, journal: Journal, *, active_only: bool = False) -> Sequence[ReviewForm]:
        await self._ensure_default(journal)
        query = select(ReviewForm).where(ReviewForm.journal_id == journal.id)
        if active_only:
            query = query.where(ReviewForm.is_active.is_(True))
        return (await self.db.scalars(query.order_by(ReviewForm.is_default.desc(), ReviewForm.title))).all()

    async def _ensure_default(self, journal: Journal) -> None:
        exists = await self.db.scalar(select(func.count()).where(ReviewForm.journal_id == journal.id))
        if not exists:
            self.db.add(self._form_from(journal, DEFAULT_FORM))
            await self.db.flush()

    @staticmethod
    def _form_from(journal: Journal, data: ReviewFormIn) -> ReviewForm:
        return ReviewForm(
            journal_id=journal.id,
            title=data.title,
            description=data.description,
            questions=[q.model_dump(mode="json") for q in data.questions],
            is_active=data.is_active,
            is_default=data.is_default,
        )

    async def _form(self, journal: Journal, form_id: int | None) -> ReviewForm:
        forms = await self.forms(journal, active_only=True)
        if form_id is not None:
            for form in forms:
                if form.id == form_id:
                    return form
            raise ValidationFailed("Choose an active review form.", code="form_not_found")
        default = next((f for f in forms if f.is_default), None) or (forms[0] if forms else None)
        if default is None:
            raise Conflict("The journal has no active review form.", code="no_review_form")
        return default

    async def get_form(self, journal: Journal, form_id: int) -> ReviewForm:
        form = await self.db.scalar(
            select(ReviewForm).where(ReviewForm.id == form_id, ReviewForm.journal_id == journal.id)
        )
        if form is None:
            raise NotFound("Review form not found.")
        return form

    async def create_form(self, journal: Journal, data: ReviewFormIn, actor: User) -> ReviewForm:
        await self._ensure_default(journal)
        form = self._form_from(journal, data)
        self.db.add(form)
        await self.db.flush()
        await self._single_default(journal, form)
        return form

    async def update_form(self, journal: Journal, form: ReviewForm, data: ReviewFormIn) -> ReviewForm:
        form.title = data.title
        form.description = data.description
        form.questions = [q.model_dump(mode="json") for q in data.questions]
        form.is_active = data.is_active
        form.is_default = data.is_default and data.is_active
        await self.db.flush()
        await self._single_default(journal, form)
        return form

    async def delete_form(self, journal: Journal, form: ReviewForm) -> None:
        # Invitations keep their own copy of the questions, so deleting a form loses nothing.
        await self.db.delete(form)
        await self.db.flush()

    async def _single_default(self, journal: Journal, form: ReviewForm) -> None:
        if not form.is_default:
            return
        for other in await self.forms(journal):
            if other.id != form.id and other.is_default:
                other.is_default = False
        await self.db.flush()

    # ------------------------------------------------------------------ notifications

    async def _tell_editors(
        self, journal: Journal, submission: Submission, key: str, values: dict[str, str]
    ) -> None:
        for editor in await editors_to_notify(self.journals, submission):
            await self.mailer.send(
                journal, key, submission, to_name=editor.full_name, to_email=editor.email, values=values
            )
