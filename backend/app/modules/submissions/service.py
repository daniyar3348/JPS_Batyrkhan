"""Preparing and submitting manuscripts; the author's and the editorial office's lists.

Permission checks that depend on the viewer live in ``policies.py``; the router calls them before
using this service. The service enforces the rules that do not depend on who is asking.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, exists, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.concurrency import ensure_version
from app.core.config import Settings
from app.core.db import escape_like, utcnow
from app.core.errors import Conflict, FieldError, Forbidden, NotFound, ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor
from app.core.storage import PresignedUpload, Storage
from app.modules.audit.service import AuditService
from app.modules.files.models import FileStatus, SubmissionFile
from app.modules.files.service import FileService
from app.modules.files.types import Genre
from app.modules.identity.models import User
from app.modules.identity.schemas import UserSummary
from app.modules.journals.deps import Principal
from app.modules.journals.models import Journal, SectionEditor
from app.modules.journals.permissions import Capability, Role
from app.modules.journals.service import JournalService
from app.modules.journals.submission_settings import SubmissionSettings, submission_settings
from app.modules.similarity.models import CheckStatus, SimilarityCheck
from app.modules.similarity.service import SimilarityService
from app.modules.submissions import emails
from app.modules.submissions.mailer import Mailer
from app.modules.submissions.models import (
    EDITABLE_PUBLICATION,
    PRODUCTION_ROLES,
    Contributor,
    Participant,
    ParticipantRole,
    Publication,
    PublicationStatus,
    Stage,
    Submission,
    SubmissionCounter,
    SubmissionStatus,
)
from app.modules.submissions.policies import Access
from app.modules.submissions.schemas import (
    ContributorIn,
    ContributorUpdate,
    FileOut,
    PublicationOut,
    PublicationUpdate,
    SectionRef,
    SimilarityCheckOut,
    SubmissionOut,
    SubmissionSummary,
    SubmissionUpdate,
    UploadRequest,
    Viewer,
)

MAX_FILES = 50
MAX_CONTRIBUTORS = 100


class SubmissionService:
    def __init__(self, db: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.db = db
        self.settings = settings
        self.files = FileService(db, storage)
        self.similarity = SimilarityService(db, settings, storage)
        self.journals = JournalService(db, settings)
        self.audit = AuditService(db)
        self.mailer = Mailer(db, settings)

    # ------------------------------------------------------------------ loading

    async def get(self, journal: Journal, submission_id: int) -> Submission:
        submission = await self.db.scalar(
            select(Submission).where(Submission.id == submission_id, Submission.journal_id == journal.id)
        )
        if submission is None:
            raise NotFound("Submission not found.")
        return submission

    @staticmethod
    def require_editable(submission: Submission, access: Access) -> None:
        if access.can_edit:
            return
        if access.is_author and submission.status != SubmissionStatus.DRAFT:
            raise Conflict(
                "The manuscript has been submitted and can no longer be changed here.", code="not_editable"
            )
        raise Forbidden("Only the person who started this submission can change it.")

    @staticmethod
    def require_metadata_editable(submission: Submission, access: Access) -> None:
        """Title, abstract, authors... The author changes the draft; after acceptance the editors correct
        the metadata until the version is scheduled or published (a published version gets a new version)."""
        if access.can_edit:
            return
        if access.can_manage:
            if submission.stage not in (Stage.COPYEDITING, Stage.PRODUCTION):
                raise Conflict(
                    "Editors correct the metadata after acceptance, during copyediting and production.",
                    code="not_editable",
                )
            if submission.publication.status not in EDITABLE_PUBLICATION:
                raise Conflict(
                    "This version is scheduled or published. Unschedule it, or create a new version.",
                    code="not_editable",
                )
            return
        SubmissionService.require_editable(submission, access)

    # ------------------------------------------------------------------ drafts

    async def create_draft(self, principal: Principal, section_id: int) -> Submission:
        if not principal.can(Capability.SUBMISSIONS_CREATE):
            raise Forbidden(
                "Only authors can submit manuscripts. Ask the journal to give you the Author role."
            )
        section = await self.journals.get_section(principal.journal, section_id)
        if not section.is_active:
            raise ValidationFailed(
                "This section does not accept submissions.",
                code="section_closed",
                errors=[FieldError(field="section_id", message="Choose a section that accepts submissions")],
            )
        user = principal.user
        # The person submitting is listed as the first, corresponding author; they can change that.
        author = Contributor(
            position=0,
            user_id=user.id,
            given_name=user.given_name,
            family_name=user.family_name,
            email=user.email,
            affiliation=user.affiliation,
            country=user.country,
            orcid=user.orcid,
            is_corresponding=True,
            in_byline=True,
        )
        submission = Submission(
            journal_id=principal.journal.id,
            section_id=section.id,
            submitter_id=user.id,
            status=SubmissionStatus.DRAFT,
            stage=Stage.SUBMISSION,
            checklist_confirmed=[],
            comments_for_editor="",
        )
        submission.section = section
        submission.submitter = user
        submission.publications = [Publication(version=1, keywords=[], contributors=[author])]
        self.db.add(submission)
        await self.db.flush()
        await self.audit.record(
            "submission.created",
            "submission",
            submission.id,
            actor_id=user.id,
            journal_id=principal.journal.id,
        )
        return submission

    async def update_draft(
        self, principal: Principal, submission: Submission, data: SubmissionUpdate, *, expected_version: int
    ) -> Submission:
        ensure_version(submission.row_version, expected_version)
        values = data.model_dump(exclude_unset=True)
        if values.get("section_id") not in (None, submission.section_id):
            section = await self.journals.get_section(principal.journal, values["section_id"])
            if not section.is_active:
                raise ValidationFailed(
                    "This section does not accept submissions.",
                    code="section_closed",
                    errors=[
                        FieldError(field="section_id", message="Choose a section that accepts submissions")
                    ],
                )
            submission.section = section
        if "comments_for_editor" in values:
            submission.comments_for_editor = values["comments_for_editor"]
        if "checklist_confirmed" in values:
            submission.checklist_confirmed = list(dict.fromkeys(values["checklist_confirmed"]))
        await self.db.flush()
        return submission

    async def update_publication(
        self, submission: Submission, data: PublicationUpdate, *, expected_version: int
    ) -> Publication:
        publication = submission.publication
        ensure_version(publication.row_version, expected_version)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(publication, field, value)
        await self.db.flush()
        return publication

    async def delete_draft(self, principal: Principal, submission: Submission) -> None:
        if submission.status != SubmissionStatus.DRAFT:
            raise Conflict("Only drafts can be deleted.", code="not_a_draft")
        await self.files.delete_all(submission.id)
        await self.db.delete(submission)
        await self.db.flush()
        await self.audit.record(
            "submission.draft_deleted",
            "submission",
            submission.id,
            actor_id=principal.user.id,
            journal_id=principal.journal.id,
        )

    # ------------------------------------------------------------------ contributors

    def _contributor(self, submission: Submission, contributor_id: int) -> Contributor:
        for contributor in submission.publication.contributors:
            if contributor.id == contributor_id:
                return contributor
        raise NotFound("Author not found.")

    @staticmethod
    def _ensure_unique_email(publication: Publication, email: str, *, exclude_id: int | None) -> None:
        if any(c.email == email and c.id != exclude_id for c in publication.contributors):
            raise ValidationFailed(
                "This person is already in the list of authors.",
                code="duplicate_contributor",
                errors=[FieldError(field="email", message="Already in the list of authors")],
            )

    async def add_contributor(self, submission: Submission, data: ContributorIn) -> Contributor:
        publication = submission.publication
        if len(publication.contributors) >= MAX_CONTRIBUTORS:
            raise ValidationFailed(f"A submission can list at most {MAX_CONTRIBUTORS} authors.")
        values = data.model_dump()
        values["email"] = values["email"].lower()
        self._ensure_unique_email(publication, values["email"], exclude_id=None)
        if values["is_corresponding"]:
            for other in publication.contributors:
                other.is_corresponding = False
        contributor = Contributor(position=len(publication.contributors), **values)
        publication.contributors.append(contributor)
        await self.db.flush()
        return contributor

    async def update_contributor(
        self, submission: Submission, contributor_id: int, data: ContributorUpdate
    ) -> Contributor:
        publication = submission.publication
        contributor = self._contributor(submission, contributor_id)
        values = data.model_dump(exclude_unset=True)
        if "email" in values:
            values["email"] = values["email"].lower()
            self._ensure_unique_email(publication, values["email"], exclude_id=contributor.id)
            if values["email"] != contributor.email:
                contributor.user_id = None  # re-linked by e-mail on submission
        if values.get("is_corresponding"):
            for other in publication.contributors:
                other.is_corresponding = False
        for field, value in values.items():
            setattr(contributor, field, value)
        await self.db.flush()
        return contributor

    async def delete_contributor(self, submission: Submission, contributor_id: int) -> None:
        publication = submission.publication
        publication.contributors.remove(self._contributor(submission, contributor_id))
        for position, contributor in enumerate(publication.contributors):
            contributor.position = position
        await self.db.flush()

    async def reorder_contributors(self, submission: Submission, contributor_ids: list[int]) -> None:
        publication = submission.publication
        by_id = {c.id: c for c in publication.contributors}
        if sorted(contributor_ids) != sorted(by_id):
            raise ValidationFailed("Send every author exactly once.", code="invalid_order")
        for position, contributor_id in enumerate(contributor_ids):
            by_id[contributor_id].position = position
        publication.contributors.sort(key=lambda c: c.position)
        await self.db.flush()

    # ------------------------------------------------------------------ files

    async def request_upload(
        self, principal: Principal, submission: Submission, data: UploadRequest
    ) -> tuple[SubmissionFile, PresignedUpload]:
        if len(await self.files.list(submission.id)) >= MAX_FILES:
            raise ValidationFailed(f"A submission can have at most {MAX_FILES} files.", code="too_many_files")
        return await self.files.request_upload(
            journal_id=principal.journal.id,
            submission_id=submission.id,
            genre=data.genre,
            file_name=data.file_name,
            size=data.size,
            max_size_mb=submission_settings(principal.journal).max_file_size_mb,
            uploaded_by_id=principal.user.id,
        )

    @staticmethod
    def latest_manuscript(files: Sequence[SubmissionFile]) -> SubmissionFile | None:
        ready = [f for f in files if f.genre == Genre.MANUSCRIPT and f.current.status == FileStatus.READY]
        return max(ready, key=lambda f: f.current.id, default=None)

    # ------------------------------------------------------------------ submitting

    @staticmethod
    def problems(
        submission: Submission, settings: SubmissionSettings, files: Sequence[SubmissionFile], submitter: User
    ) -> list[FieldError]:
        """Everything that must be fixed before the manuscript can be submitted, in wizard order."""
        problems: list[FieldError] = []

        def add(field: str, message: str) -> None:
            problems.append(FieldError(field=field, message=message))

        if not submission.section.is_active:
            add("section_id", "This section no longer accepts submissions. Choose another one.")
        confirmed = set(submission.checklist_confirmed)
        if any(item not in confirmed for item in settings.checklist):
            add("checklist", "Confirm every item of the submission checklist.")

        statuses = [f.current.status for f in files]
        if SubmissionService.latest_manuscript(files) is None:
            add("files", "Upload the manuscript file.")
        if any(s in (FileStatus.PENDING_UPLOAD, FileStatus.PROCESSING) for s in statuses):
            add("files", "Wait until every file has been uploaded and checked.")
        if FileStatus.REJECTED in statuses:
            add("files", "Remove the files that were not accepted.")

        publication = submission.publication
        if not publication.title.strip():
            add("title", "Enter the title.")
        words = len(publication.abstract.split())
        if words == 0:
            add("abstract", "Enter the abstract.")
        elif words > settings.abstract_max_words:
            add("abstract", f"Shorten the abstract to {settings.abstract_max_words} words (it has {words}).")
        if len(publication.keywords) < settings.keywords_min:
            add("keywords", f"Add at least {settings.keywords_min} keywords.")
        elif len(publication.keywords) > settings.keywords_max:
            add("keywords", f"Use at most {settings.keywords_max} keywords.")

        contributors = publication.contributors
        if not any(c.in_byline for c in contributors):
            add("contributors", "List at least one author.")
        if sum(c.is_corresponding for c in contributors) != 1:
            add("contributors", "Choose one corresponding author.")
        for contributor in contributors:
            if not contributor.affiliation.strip():
                add("contributors", f"Add the affiliation of {contributor.full_name}.")

        if submitter.email_verified_at is None:
            add("account", "Confirm your e-mail address first: open the link we sent you.")
        return problems

    async def submit(self, principal: Principal, submission: Submission) -> Submission:
        journal = principal.journal
        settings = submission_settings(journal)
        files = await self.files.list(submission.id)
        problems = self.problems(submission, settings, files, principal.user)
        if problems:
            raise ValidationFailed(
                "The submission is not complete yet.", code="submission_incomplete", errors=problems
            )
        now = utcnow()
        submission.number = await self._next_number(journal.id, settings.number_prefix, now.year)
        submission.status = SubmissionStatus.QUEUED
        submission.stage = Stage.SUBMISSION
        submission.submitted_at = now
        submission.checklist_confirmed = list(settings.checklist)
        submission.publication.status = PublicationStatus.QUEUED
        await self._link_accounts(submission.publication)
        self._assign_section_editors(submission)
        await self.db.flush()

        await self._notify_submitted(journal, submission)
        manuscript = self.latest_manuscript(files)
        if settings.similarity.enabled and self.similarity.available and manuscript is not None:
            await self.similarity.start(
                submission_id=submission.id, revision_id=manuscript.current.id, requested_by_id=None
            )
        await self.audit.record(
            "submission.submitted",
            "submission",
            submission.id,
            actor_id=principal.user.id,
            journal_id=journal.id,
            data={"number": submission.number},
        )
        return submission

    async def _next_number(self, journal_id: int, prefix: str, year: int) -> str:
        statement = (
            insert(SubmissionCounter)
            .values(journal_id=journal_id, year=year, last_value=1)
            .on_conflict_do_update(
                index_elements=[SubmissionCounter.journal_id, SubmissionCounter.year],
                set_={"last_value": SubmissionCounter.last_value + 1},
            )
            .returning(SubmissionCounter.last_value)
        )
        value = (await self.db.execute(statement)).scalar_one()
        return f"{prefix}-{year}-{value:04d}"

    @staticmethod
    def _assign_section_editors(submission: Submission) -> None:
        """The section's editors handle a new manuscript, unless they wrote it."""
        author_emails = {c.email for c in submission.publication.contributors} | {submission.submitter.email}
        for editor in submission.section.editors:
            if (
                editor.is_active
                and editor.email not in author_emails
                and submission.participant(editor.id) is None
            ):
                participant = Participant(
                    user_id=editor.id, role=ParticipantRole.EDITOR, recommend_only=False
                )
                participant.user = editor
                submission.participants.append(participant)

    async def _link_accounts(self, publication: Publication) -> None:
        unlinked = {c.email: c for c in publication.contributors if c.user_id is None}
        if not unlinked:
            return
        for user in (await self.db.scalars(select(User).where(User.email.in_(list(unlinked))))).all():
            unlinked[user.email].user_id = user.id

    async def _notify_submitted(self, journal: Journal, submission: Submission) -> None:
        submitter = submission.submitter
        values = {"submitterName": submitter.full_name}
        await self.mailer.send(
            journal,
            emails.RECEIVED.key,
            submission,
            to_name=submitter.full_name,
            to_email=submitter.email,
            values=values,
        )

        author_emails = {submitter.email} | {c.email for c in submission.publication.contributors}
        editors = {u.id: u for u in await self.journals.users_with_role(journal.id, Role.EDITOR_IN_CHIEF)}
        editors |= {u.id: u for u in submission.section.editors if u.is_active}
        for editor in editors.values():
            if editor.email in author_emails:
                continue
            await self.mailer.send(
                journal,
                emails.NEW_FOR_EDITOR.key,
                submission,
                to_name=editor.full_name,
                to_email=editor.email,
                values=values,
            )

        notified = {submitter.email}
        for contributor in submission.publication.contributors:
            if contributor.email in notified:
                continue
            notified.add(contributor.email)
            await self.mailer.send(
                journal,
                emails.COAUTHOR_NOTICE.key,
                submission,
                to_name=contributor.full_name,
                to_email=contributor.email,
                values=values,
            )

    # ------------------------------------------------------------------ similarity (editors)

    async def rerun_similarity(self, principal: Principal, submission: Submission) -> SimilarityCheck:
        if not self.similarity.available:
            raise Conflict(
                "Similarity checking is not set up for this journal.", code="similarity_unavailable"
            )
        manuscript = self.latest_manuscript(await self.files.list(submission.id))
        if manuscript is None:
            raise Conflict("There is no manuscript file to check.", code="no_manuscript")
        check = await self.similarity.start(
            submission_id=submission.id, revision_id=manuscript.current.id, requested_by_id=principal.user.id
        )
        await self.audit.record(
            "submission.similarity_check_requested",
            "submission",
            submission.id,
            actor_id=principal.user.id,
            journal_id=principal.journal.id,
        )
        return check

    async def latest_scores(self, submission_ids: Sequence[int]) -> dict[int, int]:
        if not submission_ids:
            return {}
        rows = await self.db.execute(
            select(SimilarityCheck.submission_id, SimilarityCheck.score_percent)
            .where(
                SimilarityCheck.submission_id.in_(submission_ids),
                SimilarityCheck.status == CheckStatus.COMPLETED,
            )
            .order_by(SimilarityCheck.submission_id, SimilarityCheck.id.desc())
            .ext(distinct_on(SimilarityCheck.submission_id))
        )
        return {submission_id: score for submission_id, score in rows if score is not None}

    # ------------------------------------------------------------------ lists

    async def list_mine(
        self, principal: Principal, *, cursor: str | None, limit: int
    ) -> tuple[Sequence[Submission], str | None]:
        """Submissions the user started, plus submitted ones that list them as an author."""
        user = principal.user
        coauthored = (
            select(Publication.submission_id)
            .join(Contributor, Contributor.publication_id == Publication.id)
            .where(Contributor.user_id == user.id)
        )
        query = select(Submission).where(
            Submission.journal_id == principal.journal.id,
            or_(
                Submission.submitter_id == user.id,
                and_(Submission.id.in_(coauthored), Submission.status != SubmissionStatus.DRAFT),
            ),
        )
        return await self._page(query, Submission.created_at, cursor, limit)

    async def list_editorial(
        self,
        principal: Principal,
        *,
        status: str | None,
        section_id: int | None,
        q: str | None,
        cursor: str | None,
        limit: int,
        stage: str | None = None,
        assigned_to_me: bool = False,
    ) -> tuple[Sequence[Submission], str | None]:
        user = principal.user
        assigned = select(Participant.submission_id).where(
            Participant.user_id == user.id, Participant.role == ParticipantRole.EDITOR
        )
        query = select(Submission).where(
            Submission.journal_id == principal.journal.id,
            Submission.status != SubmissionStatus.DRAFT,
            Submission.submitted_at.is_not(None),
            Submission.submitter_id != user.id,
            ~exists(
                select(Contributor.id)
                .join(Publication, Publication.id == Contributor.publication_id)
                .where(
                    Publication.submission_id == Submission.id,
                    or_(Contributor.user_id == user.id, Contributor.email == user.email),
                )
            ),
        )
        if not principal.can(Capability.SUBMISSIONS_VIEW_ALL):
            if Role.SECTION_EDITOR not in principal.roles:
                raise Forbidden()
            own_sections = select(SectionEditor.section_id).where(SectionEditor.user_id == user.id)
            query = query.where(or_(Submission.section_id.in_(own_sections), Submission.id.in_(assigned)))
        if assigned_to_me:
            query = query.where(Submission.id.in_(assigned))
        if status:
            query = query.where(Submission.status == status)
        if stage:
            query = query.where(Submission.stage == stage)
        if section_id is not None:
            query = query.where(Submission.section_id == section_id)
        if q and q.strip():
            pattern = f"%{escape_like(q.strip().lower())}%"
            query = query.where(
                or_(
                    func.lower(Submission.number).like(pattern, escape="\\"),
                    exists(
                        select(Publication.id).where(
                            Publication.submission_id == Submission.id,
                            func.lower(Publication.title).like(pattern, escape="\\"),
                        )
                    ),
                )
            )
        return await self._page(query, Submission.submitted_at, cursor, limit)

    async def list_production_work(
        self, principal: Principal, *, include_done: bool, cursor: str | None, limit: int
    ) -> tuple[Sequence[Submission], str | None]:
        """Accepted articles the user copyedits, typesets or proofreads."""
        mine = select(Participant.submission_id).where(
            Participant.user_id == principal.user.id, Participant.role.in_(PRODUCTION_ROLES)
        )
        query = select(Submission).where(
            Submission.journal_id == principal.journal.id, Submission.id.in_(mine)
        )
        if not include_done:
            query = query.where(Submission.status.in_((SubmissionStatus.QUEUED, SubmissionStatus.SCHEDULED)))
        return await self._page(query, Submission.submitted_at, cursor, limit)

    async def _page(
        self,
        query: Select[Submission],
        column: InstrumentedAttribute[Any],
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[Submission], str | None]:
        """Keyset pagination, newest first, on (column, id)."""
        if cursor:
            last_time, last_id = decode_cursor(cursor, size=2)
            query = query.where(
                tuple_(column, Submission.id)
                < tuple_(literal(datetime.fromisoformat(str(last_time))), literal(int(last_id)))
            )
        rows = (
            await self.db.scalars(query.order_by(column.desc(), Submission.id.desc()).limit(limit + 1))
        ).all()
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor([getattr(last, column.key).isoformat(), last.id])
        return rows[:limit], next_cursor

    # ------------------------------------------------------------------ views

    async def to_out(self, principal: Principal, submission: Submission, access: Access) -> SubmissionOut:
        settings = submission_settings(principal.journal)
        files = await self.files.list(submission.id)
        problems = (
            self.problems(submission, settings, files, principal.user)
            if submission.status == SubmissionStatus.DRAFT and access.can_edit
            else []
        )
        checks = None
        if access.is_editor:
            threshold = settings.similarity.threshold_percent
            checks = [SimilarityCheckOut.of(c, threshold) for c in await self.similarity.list(submission.id)]
        return SubmissionOut(
            id=submission.id,
            number=submission.number,
            status=submission.status,
            stage=submission.stage,
            section=section_ref(submission),
            submitter=UserSummary.of(submission.submitter),
            created_at=submission.created_at,
            updated_at=submission.updated_at,
            submitted_at=submission.submitted_at,
            row_version=submission.row_version,
            comments_for_editor=submission.comments_for_editor,
            checklist_confirmed=list(submission.checklist_confirmed),
            publication=PublicationOut.of(submission.publication),
            files=[FileOut.of(f) for f in files],
            problems=problems,
            viewer=Viewer.of(access),
            similarity_checks=checks,
        )


def section_ref(submission: Submission) -> SectionRef:
    section = submission.section
    return SectionRef(id=section.id, title=section.title, abbreviation=section.abbreviation)


def summary_of(
    submission: Submission, *, score: int | None = None, threshold: int = 101
) -> SubmissionSummary:
    publication = submission.publication
    return SubmissionSummary(
        id=submission.id,
        number=submission.number,
        status=submission.status,
        stage=submission.stage,
        title=publication.title,
        authors=", ".join(c.full_name for c in publication.contributors if c.in_byline),
        section=section_ref(submission),
        created_at=submission.created_at,
        submitted_at=submission.submitted_at,
        updated_at=submission.updated_at,
        similarity_score=score,
        similarity_flagged=score is not None and score >= threshold,
    )


async def editors_to_notify(journals: JournalService, submission: Submission) -> list[User]:
    """The manuscript's editors; while nobody is assigned, the editors-in-chief. Never its authors."""
    author_emails = {c.email for c in submission.publication.contributors} | {submission.submitter.email}
    editors = [p.user for p in submission.participants if p.role == ParticipantRole.EDITOR]
    if not editors:
        editors = list(await journals.users_with_role(submission.journal_id, Role.EDITOR_IN_CHIEF))
    seen: set[int] = set()
    result = []
    for user in editors:
        if user.is_active and user.email not in author_emails and user.id not in seen:
            seen.add(user.id)
            result.append(user)
    return result
