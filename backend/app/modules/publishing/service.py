"""Publishing: issues, galleys, scheduling and publishing articles, versions, the read model and DOIs.

An article is published into an issue. If the issue is already out, the article appears at once
(continuous publication); otherwise it is scheduled and appears when the issue is published. A published
version is never changed: corrections are a new version, and readers keep access to the old one.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import ensure_version
from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.jobs import enqueue
from app.core.site import request_revalidation
from app.core.storage import PresignedUpload, Storage
from app.modules.files.models import FileStage, FileStatus
from app.modules.files.types import Genre
from app.modules.identity.models import User
from app.modules.journals.models import Journal, Section
from app.modules.journals.publishing_settings import PublishingSettings, publishing_settings
from app.modules.journals.submission_settings import submission_settings
from app.modules.publishing import crossref, emails, snapshot
from app.modules.publishing.doi import doi_url, make_doi
from app.modules.publishing.models import (
    DepositStatus,
    DoiDeposit,
    Galley,
    Issue,
    IssueStatus,
    PublishedArticle,
)
from app.modules.publishing.schemas import (
    Check,
    DepositOut,
    GalleyOut,
    GalleyUploadIn,
    IssueArticle,
    IssueIn,
    IssueOut,
    PublicationInfo,
    PublishingOut,
    PublishingUpdate,
    VersionOut,
)
from app.modules.submissions.models import (
    EDITABLE_PUBLICATION,
    Contributor,
    ParticipantRole,
    Publication,
    PublicationStatus,
    Stage,
    Submission,
    SubmissionStatus,
)
from app.modules.submissions.policies import Access
from app.modules.submissions.service import section_ref
from app.modules.workflow.models import EditorialDecision
from app.modules.workflow.service import WorkflowService
from app.modules.workflow.transitions import Decision

logger = logging.getLogger(__name__)

DEPOSIT_DOI = "publishing.deposit_doi"
CHECK_DEPOSIT = "publishing.check_deposit"
MAX_DEPOSIT_CHECKS = 30
GALLEY_MAX_MB = 100

# Articles that are still on their way to readers, or already with them.
LIVE = (SubmissionStatus.QUEUED, SubmissionStatus.SCHEDULED, SubmissionStatus.PUBLISHED)


def may_handle_galleys(access: Access) -> bool:
    return access.can_manage or ParticipantRole.LAYOUT_EDITOR in access.production_roles


def batch_timestamp(now: datetime) -> int:
    """Crossref keeps the deposit with the highest timestamp: YYYYMMDDHHMMSS plus milliseconds."""
    return int(now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}")


class PublishingService:
    def __init__(self, db: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.workflow = WorkflowService(db, settings, storage)
        self.files = self.workflow.files
        self.payments = self.workflow.payments
        self.mailer = self.workflow.mailer
        self.audit = self.workflow.audit

    # ------------------------------------------------------------------ issues

    async def list_issues(self, journal: Journal, *, status: str | None = None) -> list[IssueOut]:
        query = select(Issue).where(Issue.journal_id == journal.id)
        if status:
            query = query.where(Issue.status == status)
        query = query.order_by(Issue.status, Issue.published_at.desc().nulls_last(), Issue.id.desc())
        issues = (await self.db.scalars(query)).all()
        counts = await self._article_counts([issue.id for issue in issues])
        return [IssueOut.of(issue, article_count=counts.get(issue.id, 0)) for issue in issues]

    async def _article_counts(self, issue_ids: Sequence[int]) -> dict[int, int]:
        if not issue_ids:
            return {}
        rows = await self.db.execute(
            select(Publication.issue_id, func.count(func.distinct(Publication.submission_id)))
            .join(Submission, Submission.id == Publication.submission_id)
            .where(Publication.issue_id.in_(issue_ids), Submission.status.in_(LIVE))
            .group_by(Publication.issue_id)
        )
        return {issue_id: count for issue_id, count in rows if issue_id is not None}

    async def get_issue(self, journal: Journal, issue_id: int) -> Issue:
        issue = await self.db.scalar(
            select(Issue).where(Issue.id == issue_id, Issue.journal_id == journal.id)
        )
        if issue is None:
            raise NotFound("Issue not found.")
        return issue

    async def _ensure_unique(self, journal: Journal, data: IssueIn, issue_id: int | None = None) -> None:
        if data.volume is None or data.number is None:
            return
        query = select(Issue.id).where(
            Issue.journal_id == journal.id, Issue.volume == data.volume, Issue.number == data.number
        )
        if issue_id is not None:
            query = query.where(Issue.id != issue_id)
        if await self.db.scalar(query) is not None:
            raise Conflict(f"Vol. {data.volume} No. {data.number} already exists.", code="issue_exists")

    async def create_issue(self, journal: Journal, data: IssueIn, actor: User) -> Issue:
        await self._ensure_unique(journal, data)
        issue = Issue(journal_id=journal.id, **data.model_dump())
        self.db.add(issue)
        await self.db.flush()
        await self.audit.record(
            "issue.created",
            "issue",
            issue.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"label": issue.label},
        )
        return issue

    async def update_issue(
        self, journal: Journal, issue: Issue, data: IssueIn, *, expected_version: int, actor: User
    ) -> Issue:
        ensure_version(issue.row_version, expected_version)
        await self._ensure_unique(journal, data, issue.id)
        for field, value in data.model_dump().items():
            setattr(issue, field, value)
        await self.db.flush()
        if issue.status == IssueStatus.PUBLISHED:
            # Readers see the issue in every article's citation: rebuild them.
            slugs = []
            for submission in await self.issue_submissions(issue):
                article = await self.refresh_snapshot(journal, submission)
                if article is not None:
                    slugs.append(article.slug)
            await self.revalidate(["/", "/issues", f"/issues/{issue.id}", *(f"/articles/{s}" for s in slugs)])
        await self.audit.record(
            "issue.updated",
            "issue",
            issue.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"label": issue.label},
        )
        return issue

    async def delete_issue(self, journal: Journal, issue: Issue, actor: User) -> None:
        if issue.status == IssueStatus.PUBLISHED:
            raise Conflict("A published issue cannot be deleted.", code="issue_published")
        if await self.issue_submissions(issue):
            raise Conflict("Move the issue's articles to another issue first.", code="issue_not_empty")
        await self.db.delete(issue)
        await self.db.flush()
        await self.audit.record("issue.deleted", "issue", issue.id, actor_id=actor.id, journal_id=journal.id)

    async def issue_submissions(self, issue: Issue) -> list[Submission]:
        """The articles in the issue (by their current version), in the order readers see them."""
        candidates = (
            await self.db.scalars(
                select(Submission)
                .join(Section, Section.id == Submission.section_id)
                .where(
                    Submission.status.in_(LIVE),
                    exists(
                        select(Publication.id).where(
                            Publication.submission_id == Submission.id, Publication.issue_id == issue.id
                        )
                    ),
                )
                .order_by(Section.sort_order, Section.id, Submission.id)
            )
        ).all()
        chosen = [s for s in candidates if s.publication.issue_id == issue.id]
        # Sections keep their order; within a section, the editor's order.
        section_rank = {s.section_id: index for index, s in enumerate(chosen)}
        return sorted(chosen, key=lambda s: (section_rank[s.section_id], s.publication.issue_position, s.id))

    async def issue_articles(self, journal: Journal, issue: Issue) -> list[IssueArticle]:
        result = []
        for submission in await self.issue_submissions(issue):
            publication = submission.publication
            result.append(
                IssueArticle(
                    submission_id=submission.id,
                    number=submission.number,
                    title=publication.title,
                    authors=", ".join(c.full_name for c in publication.contributors if c.in_byline),
                    section=section_ref(submission),
                    status=submission.status,
                    pages=publication.pages,
                    doi=publication.doi,
                    fee_settled=await self.payments.fee_settled(journal, submission),
                )
            )
        return result

    async def order_articles(
        self, journal: Journal, issue: Issue, submission_ids: list[int], actor: User
    ) -> None:
        submissions = {s.id: s for s in await self.issue_submissions(issue)}
        if set(submission_ids) != set(submissions):
            raise Conflict("Send every article of the issue, each once.", code="order_mismatch")
        slugs = []
        for position, submission_id in enumerate(submission_ids):
            submission = submissions[submission_id]
            for publication in submission.publications:
                if publication.issue_id == issue.id and publication.issue_position != position:
                    # Positions are not metadata of the version: they are set on every version, published or not.
                    publication.issue_position = position
        await self.db.flush()
        if issue.status == IssueStatus.PUBLISHED:
            for submission in submissions.values():
                article = await self.refresh_snapshot(journal, submission)
                if article is not None:
                    slugs.append(article.slug)
            await self.revalidate([f"/issues/{issue.id}", "/", *(f"/articles/{s}" for s in slugs)])
        await self.audit.record(
            "issue.reordered", "issue", issue.id, actor_id=actor.id, journal_id=journal.id
        )

    async def set_current(self, journal: Journal, issue: Issue, actor: User) -> None:
        if issue.status != IssueStatus.PUBLISHED:
            raise Conflict("Only a published issue can be the current one.", code="issue_not_published")
        if issue.is_current:
            return
        previous = (
            await self.db.scalars(select(Issue).where(Issue.journal_id == journal.id, Issue.is_current))
        ).all()
        for other in previous:
            other.is_current = False
        await self.db.flush()  # the unique index allows one current issue at a time
        issue.is_current = True
        await self.db.flush()
        await self.revalidate(["/", "/issues"])
        await self.audit.record(
            "issue.made_current", "issue", issue.id, actor_id=actor.id, journal_id=journal.id
        )

    async def publish_issue(self, journal: Journal, issue: Issue, actor: User, *, make_current: bool) -> None:
        """Publish the issue and every article scheduled in it, all at once or not at all."""
        if issue.status == IssueStatus.PUBLISHED:
            raise Conflict("The issue is already published.", code="issue_published")
        scheduled = [s for s in await self.issue_submissions(issue) if s.status == SubmissionStatus.SCHEDULED]
        blocked = []
        for submission in scheduled:
            failing = [c.label for c in await self.checks(journal, submission, issue=issue) if not c.ok]
            if failing:
                blocked.append(f"{submission.number}: {', '.join(failing).lower()}")
        if blocked:
            raise Conflict(
                "These articles are not ready: "
                + "; ".join(blocked)
                + ". Fix them or unschedule them first.",
                code="articles_not_ready",
            )
        now = utcnow()
        issue.status = IssueStatus.PUBLISHED
        issue.published_at = now
        await self.db.flush()
        for submission in scheduled:
            await self.workflow.record_transition(journal, submission, Decision.PUBLISH, actor)
            await self._publish(journal, submission, submission.publication, actor, issue=issue, when=now)
        if make_current:
            await self.set_current(journal, issue, actor)
        await self.revalidate(["/", "/issues", f"/issues/{issue.id}"])
        await self.audit.record(
            "issue.published",
            "issue",
            issue.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"articles": [s.id for s in scheduled]},
        )

    # ------------------------------------------------------------------ the publication screen

    def _settings(self, journal: Journal) -> PublishingSettings:
        return publishing_settings(journal)

    async def galleys(self, publication_ids: Sequence[int]) -> dict[int, list[Galley]]:
        result: dict[int, list[Galley]] = defaultdict(list)
        if not publication_ids:
            return result
        rows = await self.db.scalars(
            select(Galley)
            .where(Galley.publication_id.in_(publication_ids))
            .order_by(Galley.position, Galley.id)
        )
        for galley in rows:
            result[galley.publication_id].append(galley)
        return result

    async def _slug_taken(self, journal: Journal, submission: Submission, slug: str) -> bool:
        taken = await self.db.scalar(
            select(PublishedArticle.id).where(
                PublishedArticle.journal_id == journal.id,
                PublishedArticle.slug == slug,
                PublishedArticle.submission_id != submission.id,
            )
        )
        if taken is not None:
            return True
        other = await self.db.scalar(
            select(Publication.id)
            .join(Submission, Submission.id == Publication.submission_id)
            .where(
                Submission.journal_id == journal.id,
                Publication.url_path == slug,
                Publication.submission_id != submission.id,
                Submission.status.in_(LIVE),
            )
        )
        return other is not None

    async def checks(
        self, journal: Journal, submission: Submission, *, issue: Issue | None = None
    ) -> list[Check]:
        """What must be true before the current version can be scheduled or published."""
        publication = submission.publication
        byline = [c for c in publication.contributors if c.in_byline]
        missing = [
            name
            for name, present in (
                ("a title", publication.title),
                ("an abstract", publication.abstract),
                ("authors", byline),
            )
            if not present
        ]
        result = [
            Check(
                key="metadata",
                label="Title, abstract and authors",
                ok=not missing,
                detail=f"Add {', '.join(missing)}." if missing else "",
            )
        ]
        if issue is None and publication.issue_id is not None:
            issue = await self.db.get(Issue, publication.issue_id)
        result.append(
            Check(
                key="issue",
                label="Issue",
                ok=issue is not None,
                detail=issue.label if issue else "Choose the issue the article appears in.",
            )
        )
        galleys = (await self.galleys([publication.id]))[publication.id]
        not_ready = [g.label for g in galleys if g.file.current.status != FileStatus.READY]
        result.append(
            Check(
                key="galleys",
                label="Galleys",
                ok=bool(galleys) and not not_ready,
                detail=(
                    "Add the PDF (or another file) readers download."
                    if not galleys
                    else f"Still being checked or rejected: {', '.join(not_ready)}."
                    if not_ready
                    else ", ".join(g.label for g in galleys)
                ),
            )
        )
        if submission.status != SubmissionStatus.PUBLISHED:
            settled = await self.payments.fee_settled(journal, submission)
            result.append(
                Check(
                    key="fee",
                    label="Publication fee",
                    ok=settled is not False,
                    detail="Paid, waived or not charged."
                    if settled is not False
                    else "The invoice is not paid yet.",
                )
            )
        settings = self._settings(journal)
        if settings.doi.enabled:
            result.append(
                Check(
                    key="doi",
                    label="DOI",
                    ok=settings.doi.ready,
                    detail=(
                        publication.doi or "Assigned on publication."
                        if settings.doi.ready
                        else "DOIs are enabled but the prefix is missing (Publishing settings)."
                    ),
                )
            )
        slug = snapshot.slug_of(submission, publication)
        taken = await self._slug_taken(journal, submission, slug)
        result.append(
            Check(
                key="address",
                label="Address on the site",
                ok=not taken,
                detail=f"“{slug}” is used by another article." if taken else slug,
            )
        )
        return result

    async def view(self, journal: Journal, submission: Submission, access: Access) -> PublishingOut:
        if not (access.is_editor or access.production_roles):
            raise NotFound("Submission not found.")
        publication = submission.publication
        settings = self._settings(journal)
        issue = await self.db.get(Issue, publication.issue_id) if publication.issue_id else None
        checks = await self.checks(journal, submission, issue=issue)
        ready = all(c.ok for c in checks)
        draft = publication.status in EDITABLE_PUBLICATION
        in_production = submission.stage == Stage.PRODUCTION
        if submission.status == SubmissionStatus.PUBLISHED:
            action = "publish_version" if draft and publication.version > 1 else None
        elif submission.status == SubmissionStatus.QUEUED and in_production:
            action = "publish" if issue is not None and issue.status == IssueStatus.PUBLISHED else "schedule"
        else:
            action = None
        all_galleys = await self.galleys([p.id for p in submission.publications])
        deposits = (
            await self.db.scalars(
                select(DoiDeposit)
                .where(DoiDeposit.publication_id.in_([p.id for p in submission.publications]))
                .order_by(DoiDeposit.id.desc())
                .limit(20)
            )
        ).all()
        slug = snapshot.slug_of(submission, publication)
        editable = draft and in_production and submission.status in LIVE
        return PublishingOut(
            submission_id=submission.id,
            stage=submission.stage,
            status=submission.status,
            publication=PublicationInfo(
                id=publication.id,
                version=publication.version,
                status=publication.status,
                row_version=publication.row_version,
                doi=publication.doi,
                doi_url=doi_url(publication.doi),
                url_path=publication.url_path,
                slug=slug,
                article_url=settings.article_url(slug),
                pages=publication.pages,
                license_url=publication.license_url,
                copyright_holder=publication.copyright_holder,
                copyright_year=publication.copyright_year,
                issue_id=publication.issue_id,
                version_note=publication.version_note,
                published_at=publication.published_at,
            ),
            issue=IssueOut.of(issue) if issue else None,
            galleys=[GalleyOut.of(g, submission.id) for g in all_galleys[publication.id]],
            checks=checks,
            action=action,
            ready=ready,
            fee_settled=await self.payments.fee_settled(journal, submission),
            can_edit=editable and access.can_manage,
            can_edit_galleys=editable and may_handle_galleys(access),
            can_publish=access.can_decide and action is not None,
            can_unschedule=access.can_decide and submission.status == SubmissionStatus.SCHEDULED,
            can_create_version=access.can_decide
            and submission.status == SubmissionStatus.PUBLISHED
            and publication.status == PublicationStatus.PUBLISHED,
            can_discard_version=access.can_decide
            and submission.status == SubmissionStatus.PUBLISHED
            and draft
            and publication.version > 1,
            versions=[
                VersionOut(
                    id=p.id,
                    version=p.version,
                    status=p.status,
                    published_at=p.published_at,
                    version_note=p.version_note,
                )
                for p in submission.publications
            ],
            doi_enabled=settings.doi.enabled,
            can_assign_doi=access.can_manage and settings.doi.ready and publication.doi is None and draft,
            can_deposit=access.can_decide
            and publication.doi is not None
            and self.settings.crossref_mode != "disabled"
            and any(p.status == PublicationStatus.PUBLISHED for p in submission.publications),
            deposits=[DepositOut.of(d) for d in deposits],
        )

    async def update(
        self,
        journal: Journal,
        submission: Submission,
        access: Access,
        data: PublishingUpdate,
        *,
        expected_version: int,
        actor: User,
    ) -> None:
        if not access.can_manage:
            raise Forbidden("Only the article's editors can change how it is published.")
        publication = self._editable(submission)
        ensure_version(publication.row_version, expected_version)
        changes = data.model_dump(exclude_unset=True)
        if "issue_id" in changes and changes["issue_id"] is not None:
            issue = await self.get_issue(journal, changes["issue_id"])
            if issue.id != publication.issue_id:
                publication.issue_position = await self._next_position(issue)
        if changes.get("url_path") and await self._slug_taken(journal, submission, changes["url_path"]):
            raise Conflict("Another article already uses this address.", code="url_path_taken")
        for field, value in changes.items():
            if field in ("pages", "license_url", "copyright_holder", "version_note") and value is None:
                value = ""
            setattr(publication, field, value)
        await self.db.flush()
        await self.audit.record(
            "publication.updated",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"fields": sorted(changes)},
        )

    async def _next_position(self, issue: Issue) -> int:
        positions = [s.publication.issue_position for s in await self.issue_submissions(issue)]
        return max(positions, default=-1) + 1

    def _editable(self, submission: Submission) -> Publication:
        publication = submission.publication
        if submission.stage != Stage.PRODUCTION or submission.status not in LIVE:
            raise Conflict("The article is not in production.", code="not_in_production")
        if publication.status not in EDITABLE_PUBLICATION:
            raise Conflict(
                "This version is scheduled or published. Unschedule it, or create a new version.",
                code="publication_locked",
            )
        return publication

    # ------------------------------------------------------------------ galleys

    async def _galley(self, submission: Submission, galley_id: int) -> Galley:
        galley = await self.db.get(Galley, galley_id)
        if galley is None or galley.publication_id not in {p.id for p in submission.publications}:
            raise NotFound("Galley not found.")
        return galley

    async def request_galley_upload(
        self, journal: Journal, submission: Submission, access: Access, data: GalleyUploadIn, user: User
    ) -> tuple[Galley, PresignedUpload]:
        if not may_handle_galleys(access):
            raise Forbidden("Only the layout editor and the article's editors add galleys.")
        publication = self._editable(submission)
        record, ticket = await self.files.request_upload(
            journal_id=journal.id,
            submission_id=submission.id,
            genre=Genre.GALLEY,
            file_name=data.file_name,
            size=data.size,
            max_size_mb=max(submission_settings(journal).max_file_size_mb, GALLEY_MAX_MB),
            uploaded_by_id=user.id,
            file_stage=FileStage.GALLEY,
        )
        existing = (await self.galleys([publication.id]))[publication.id]
        galley = Galley(
            publication_id=publication.id,
            label=data.label,
            file_id=record.id,
            position=max((g.position for g in existing), default=-1) + 1,
        )
        galley.file = record
        galley.revision = None
        self.db.add(galley)
        await self.db.flush()
        return galley, ticket

    async def complete_galley(self, submission: Submission, access: Access, galley_id: int) -> Galley:
        if not may_handle_galleys(access):
            raise Forbidden()
        galley = await self._galley(submission, galley_id)
        galley.file = await self.files.complete_upload(submission.id, galley.file_id)
        return galley

    async def rename_galley(
        self, submission: Submission, access: Access, galley_id: int, label: str
    ) -> Galley:
        if not may_handle_galleys(access):
            raise Forbidden()
        galley = await self._galley(submission, galley_id)
        if galley.publication_id != self._editable(submission).id:
            raise Conflict("This galley belongs to a published version.", code="publication_locked")
        galley.label = label
        await self.db.flush()
        return galley

    async def delete_galley(self, submission: Submission, access: Access, galley_id: int) -> None:
        if not may_handle_galleys(access):
            raise Forbidden()
        galley = await self._galley(submission, galley_id)
        if galley.publication_id != self._editable(submission).id:
            raise Conflict("This galley belongs to a published version.", code="publication_locked")
        record = galley.file
        await self.db.delete(galley)
        await self.db.flush()
        shared = await self.db.scalar(select(Galley.id).where(Galley.file_id == record.id).limit(1))
        if shared is None:  # earlier versions keep their files
            await self.files.delete(record)

    async def galley_download(self, submission: Submission, access: Access, galley_id: int) -> str:
        if not (access.is_editor or access.production_roles):
            raise NotFound("Galley not found.")
        galley = await self._galley(submission, galley_id)
        return self.files.download_url(galley.file)

    # ------------------------------------------------------------------ scheduling and publishing

    async def publish(self, journal: Journal, submission: Submission, access: Access, actor: User) -> str:
        """Schedule the article into its issue, or publish it if the issue is out. Returns the new status."""
        if not access.can_decide:
            raise Forbidden("Only an editor who makes decisions on the article can publish it.")
        publication = submission.publication
        if submission.status == SubmissionStatus.PUBLISHED:
            if publication.status not in EDITABLE_PUBLICATION or publication.version == 1:
                raise Conflict("There is no new version to publish.", code="nothing_to_publish")
            await self._require_ready(journal, submission)
            await self._publish(journal, submission, publication, actor, issue=None, when=utcnow())
            return submission.status
        if submission.stage != Stage.PRODUCTION or submission.status != SubmissionStatus.QUEUED:
            raise Conflict(
                "Only articles in production can be scheduled or published.", code="not_in_production"
            )
        issue = await self._require_ready(journal, submission)
        if issue.status == IssueStatus.PUBLISHED:
            await self.workflow.record_transition(journal, submission, Decision.PUBLISH, actor)
            await self._publish(journal, submission, publication, actor, issue=issue, when=utcnow())
            await self.revalidate([f"/issues/{issue.id}"])
        else:
            await self.workflow.record_transition(journal, submission, Decision.SCHEDULE, actor)
            publication.status = PublicationStatus.SCHEDULED
            await self.db.flush()
        return submission.status

    async def _require_ready(self, journal: Journal, submission: Submission) -> Issue:
        checks = await self.checks(journal, submission)
        failing = [c for c in checks if not c.ok]
        if failing:
            raise Conflict(
                "Not ready to publish: " + "; ".join(f"{c.label}: {c.detail}" for c in failing),
                code="not_ready",
            )
        issue_id = submission.publication.issue_id
        if issue_id is None:  # the checks above require an issue
            raise Conflict("Choose the issue first.", code="not_ready")
        return await self.get_issue(journal, issue_id)

    async def unschedule(self, journal: Journal, submission: Submission, access: Access, actor: User) -> None:
        if not access.can_decide:
            raise Forbidden()
        if submission.status != SubmissionStatus.SCHEDULED:
            raise Conflict("The article is not scheduled.", code="not_scheduled")
        await self.workflow.record_transition(journal, submission, Decision.UNSCHEDULE, actor)
        submission.publication.status = PublicationStatus.QUEUED
        await self.db.flush()

    async def _publish(
        self,
        journal: Journal,
        submission: Submission,
        publication: Publication,
        actor: User | None,
        *,
        issue: Issue | None,
        when: datetime,
    ) -> PublishedArticle:
        settings = self._settings(journal)
        publication.status = PublicationStatus.PUBLISHED
        publication.published_at = when
        if not publication.license_url:
            publication.license_url = settings.license_url
        if not publication.copyright_holder:
            publication.copyright_holder = (
                ", ".join(c.full_name for c in publication.contributors if c.in_byline)
                if settings.copyright_holder == "authors"
                else journal.publisher or journal.name
            )[:300]
        if publication.copyright_year is None:
            publication.copyright_year = when.year
        if publication.doi is None and settings.doi.ready:
            publication.doi = await self._new_doi(journal, submission)
        # Readers get exactly the files checked now, even if someone uploads a new revision later.
        for galley in (await self.galleys([publication.id]))[publication.id]:
            galley.revision = galley.file.current
        await self.db.flush()
        article = await self.refresh_snapshot(journal, submission)
        if article is None:
            raise RuntimeError("A published version always has a snapshot")
        if publication.doi and self.settings.crossref_mode != "disabled":
            await self.request_deposit(journal, publication, actor)
        await self.revalidate(["/", "/articles", f"/articles/{article.slug}"])
        if publication.version == 1:
            await self._tell_authors(journal, submission, article, issue)
        await self.audit.record(
            "publication.published",
            "submission",
            submission.id,
            actor_id=actor.id if actor else None,
            journal_id=journal.id,
            data={"version": publication.version, "doi": publication.doi},
        )
        return article

    async def _tell_authors(
        self, journal: Journal, submission: Submission, article: PublishedArticle, issue: Issue | None
    ) -> None:
        recipients: dict[str, str] = {submission.submitter.email: submission.submitter.full_name}
        for contributor in submission.publication.contributors:
            recipients.setdefault(contributor.email, contributor.full_name)
        link = article.data.get("doi_url") or article.data.get("url") or ""
        for email, name in recipients.items():
            await self.mailer.send(
                journal,
                emails.ARTICLE_PUBLISHED.key,
                submission,
                to_name=name,
                to_email=email,
                values={"issueNote": f", {issue.label}" if issue else "", "articleLink": link},
            )

    # ------------------------------------------------------------------ versions

    async def new_version(
        self, journal: Journal, submission: Submission, access: Access, note: str, actor: User
    ) -> Publication:
        """Start a correction: a copy of the published version, its galleys included, to change and publish."""
        if not access.can_decide:
            raise Forbidden()
        current = submission.publication
        if submission.status != SubmissionStatus.PUBLISHED or current.status != PublicationStatus.PUBLISHED:
            raise Conflict("A new version starts from a published one.", code="not_published")
        copied = Publication(
            submission_id=submission.id,
            version=current.version + 1,
            status=PublicationStatus.DRAFT,
            title=current.title,
            subtitle=current.subtitle,
            abstract=current.abstract,
            keywords=list(current.keywords),
            references=current.references,
            funding_statement=current.funding_statement,
            competing_interests=current.competing_interests,
            doi=current.doi,
            url_path=current.url_path,
            pages=current.pages,
            license_url=current.license_url,
            copyright_holder=current.copyright_holder,
            copyright_year=current.copyright_year,
            issue_id=current.issue_id,
            issue_position=current.issue_position,
            version_note=note,
        )
        copied.contributors = [
            Contributor(
                user_id=c.user_id,
                position=c.position,
                given_name=c.given_name,
                family_name=c.family_name,
                email=c.email,
                affiliation=c.affiliation,
                country=c.country,
                orcid=c.orcid,
                is_corresponding=c.is_corresponding,
                in_byline=c.in_byline,
            )
            for c in current.contributors
        ]
        submission.publications.append(copied)
        await self.db.flush()
        for galley in (await self.galleys([current.id]))[current.id]:
            self.db.add(
                Galley(
                    publication_id=copied.id,
                    label=galley.label,
                    file_id=galley.file_id,
                    position=galley.position,
                )
            )
        await self.db.flush()
        await self.audit.record(
            "publication.version_created",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"version": copied.version},
        )
        return copied

    async def discard_version(
        self, journal: Journal, submission: Submission, access: Access, actor: User
    ) -> None:
        if not access.can_decide:
            raise Forbidden()
        draft = submission.publication
        if draft.status not in EDITABLE_PUBLICATION or draft.version == 1:
            raise Conflict("There is no unpublished version to discard.", code="nothing_to_discard")
        for galley in (await self.galleys([draft.id]))[draft.id]:
            record = galley.file
            await self.db.delete(galley)
            await self.db.flush()
            if await self.db.scalar(select(Galley.id).where(Galley.file_id == record.id).limit(1)) is None:
                await self.files.delete(record)
        submission.publications.remove(draft)
        await self.db.flush()
        await self.audit.record(
            "publication.version_discarded",
            "submission",
            submission.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"version": draft.version},
        )

    # ------------------------------------------------------------------ the read model

    async def refresh_snapshot(self, journal: Journal, submission: Submission) -> PublishedArticle | None:
        """Rebuild what readers see of the article from its published versions."""
        versions = [p for p in submission.publications if p.status == PublicationStatus.PUBLISHED]
        row = await self.db.scalar(
            select(PublishedArticle).where(PublishedArticle.submission_id == submission.id)
        )
        if not versions:
            if row is not None:
                await self.db.delete(row)
                await self.db.flush()
            return None
        current = versions[-1]
        issue = await self.db.get(Issue, current.issue_id) if current.issue_id else None
        accepted_at = await self.db.scalar(
            select(func.max(EditorialDecision.created_at)).where(
                EditorialDecision.submission_id == submission.id,
                EditorialDecision.decision == Decision.ACCEPT.value,
                EditorialDecision.is_recommendation.is_(False),
            )
        )
        data = snapshot.build(
            settings=self._settings(journal),
            submission=submission,
            versions=versions,
            galleys=await self.galleys([v.id for v in versions]),
            issue=issue,
            accepted_at=accepted_at,
        )
        first_published = versions[0].published_at
        if first_published is None:
            raise RuntimeError("Published versions have a publication date")
        if row is None:
            row = PublishedArticle(
                journal_id=journal.id, submission_id=submission.id, published_at=first_published
            )
            self.db.add(row)
        row.publication_id = current.id
        row.issue_id = issue.id if issue else None
        row.section_id = submission.section_id
        row.slug = data["slug"]
        row.doi = current.doi
        row.title = current.title
        row.position = submission.section.sort_order * 10000 + current.issue_position
        row.published_at = first_published
        row.updated_at = utcnow()
        row.data = data
        row.search_vector = snapshot.search_vector(data)  # PostgreSQL computes it from the expression
        await self.db.flush()
        return row

    async def revalidate(self, paths: list[str]) -> None:
        await request_revalidation(self.db, self.settings, paths)

    # ------------------------------------------------------------------ DOIs

    async def _new_doi(self, journal: Journal, submission: Submission) -> str:
        doi = make_doi(self._settings(journal).doi, journal, submission)
        clash = await self.db.scalar(
            select(Publication.id).where(Publication.doi == doi, Publication.submission_id != submission.id)
        )
        return f"{doi}-{submission.id}" if clash is not None else doi

    async def reserve_doi(self, submission_id: int) -> None:
        """When an article enters production: its DOI is printed on the galleys, so it is needed now."""
        submission = await self.db.get(Submission, submission_id)
        if submission is None:
            return
        journal = await self.db.get(Journal, submission.journal_id)
        if journal is None:
            return
        publication = submission.publication
        if publication.doi is None and self._settings(journal).doi.ready:
            publication.doi = await self._new_doi(journal, submission)
            await self.db.flush()

    async def assign_doi(self, journal: Journal, submission: Submission, access: Access, actor: User) -> None:
        if not access.can_manage:
            raise Forbidden()
        if not self._settings(journal).doi.ready:
            raise Conflict(
                "Enable DOIs and set the prefix in the publishing settings first.", code="doi_disabled"
            )
        publication = self._editable(submission)
        if publication.doi is None:
            publication.doi = await self._new_doi(journal, submission)
            await self.db.flush()
            await self.audit.record(
                "publication.doi_assigned",
                "submission",
                submission.id,
                actor_id=actor.id,
                journal_id=journal.id,
                data={"doi": publication.doi},
            )

    async def request_deposit(
        self, journal: Journal, publication: Publication, actor: User | None
    ) -> DoiDeposit:
        if self.settings.crossref_mode == "disabled":
            raise Conflict("DOI registration is not set up on this server.", code="crossref_disabled")
        if publication.doi is None:
            raise Conflict("The article has no DOI.", code="no_doi")
        deposit = DoiDeposit(
            journal_id=journal.id,
            publication_id=publication.id,
            doi=publication.doi,
            batch_id=uuid.uuid4().hex,
            mode=self.settings.crossref_mode,
            status=DepositStatus.QUEUED,
            requested_by_id=actor.id if actor else None,
        )
        self.db.add(deposit)
        await self.db.flush()
        await enqueue(self.db, DEPOSIT_DOI, {"deposit_id": deposit.id})
        return deposit

    async def deposit_again(
        self, journal: Journal, submission: Submission, access: Access, actor: User
    ) -> DoiDeposit:
        if not access.can_decide:
            raise Forbidden()
        published = [p for p in submission.publications if p.status == PublicationStatus.PUBLISHED]
        if not published:
            raise Conflict("DOIs are registered when the article is published.", code="not_published")
        return await self.request_deposit(journal, published[-1], actor)

    async def run_deposit(self, deposit_id: int) -> None:
        deposit = await self.db.get(DoiDeposit, deposit_id, with_for_update=True)
        if deposit is None or deposit.status != DepositStatus.QUEUED:
            return
        journal = await self.db.get(Journal, deposit.journal_id)
        publication = await self.db.get(Publication, deposit.publication_id)
        if journal is None or publication is None:
            return
        article = await self.db.scalar(
            select(PublishedArticle).where(PublishedArticle.submission_id == publication.submission_id)
        )
        if article is None:
            self._finish(deposit, DepositStatus.FAILED, "The article is not published.")
            return
        now = utcnow()
        try:
            xml = crossref.build_deposit(
                journal=journal,
                settings=self._settings(journal),
                article=article.data,
                batch_id=deposit.batch_id,
                timestamp=batch_timestamp(now),
            )
        except crossref.NotReady as error:
            self._finish(deposit, DepositStatus.FAILED, str(error))
            return
        deposit.xml = xml.decode()
        deposit.doi = article.data["doi"]
        if deposit.mode == "fake":
            deposit.submitted_at = now
            deposit.response = "fake"
            self._finish(
                deposit, DepositStatus.REGISTERED, "Registered in fake mode: nothing was sent to Crossref."
            )
            return
        try:
            response = await crossref.CrossrefClient(self.settings).deposit(
                xml, file_name=f"{deposit.batch_id}.xml"
            )
        except crossref.CrossrefError as error:
            if not error.permanent:
                raise  # the job is retried
            self._finish(deposit, DepositStatus.FAILED, str(error))
            return
        deposit.status = DepositStatus.SUBMITTED
        deposit.submitted_at = now
        deposit.response = response[:5000]
        deposit.message = "Crossref received the deposit and is processing it."
        await enqueue(
            self.db,
            CHECK_DEPOSIT,
            {"deposit_id": deposit.id},
            delay=timedelta(seconds=self.settings.crossref_check_delay_seconds),
        )

    async def check_deposit(self, deposit_id: int) -> None:
        deposit = await self.db.get(DoiDeposit, deposit_id, with_for_update=True)
        if deposit is None or deposit.status != DepositStatus.SUBMITTED:
            return
        try:
            result = await crossref.CrossrefClient(self.settings).result(deposit.batch_id)
        except crossref.CrossrefError as error:
            if not error.permanent:
                raise
            self._finish(deposit, DepositStatus.FAILED, str(error))
            return
        deposit.checks += 1
        if result.state == "pending":
            if deposit.checks >= MAX_DEPOSIT_CHECKS:
                self._finish(
                    deposit,
                    DepositStatus.FAILED,
                    "Crossref has not reported a result. Check the deposit in Crossref's admin tool, "
                    "then deposit again if needed.",
                )
                return
            deposit.message = result.message
            delay = min(self.settings.crossref_check_delay_seconds * deposit.checks, 3600)
            await enqueue(self.db, CHECK_DEPOSIT, {"deposit_id": deposit.id}, delay=timedelta(seconds=delay))
            return
        deposit.response = result.raw[:20000]
        status = DepositStatus.REGISTERED if result.state == "registered" else DepositStatus.FAILED
        self._finish(
            deposit,
            status,
            result.message or ("Registered." if status == DepositStatus.REGISTERED else "Failed."),
        )

    async def give_up_deposit(self, deposit_id: int, error: str) -> None:
        deposit = await self.db.get(DoiDeposit, deposit_id)
        if deposit is not None and deposit.status in (DepositStatus.QUEUED, DepositStatus.SUBMITTED):
            self._finish(deposit, DepositStatus.FAILED, f"Gave up after repeated errors: {error}"[:2000])

    @staticmethod
    def _finish(deposit: DoiDeposit, status: str, message: str) -> None:
        deposit.status = status
        deposit.message = message
        deposit.completed_at = utcnow()
        if status == DepositStatus.FAILED:
            logger.warning("DOI deposit %s failed: %s", deposit.id, message)

    async def list_deposits(
        self, journal: Journal, *, status: str | None, limit: int
    ) -> list[tuple[DoiDeposit, Submission]]:
        query = (
            select(DoiDeposit, Submission)
            .join(Publication, Publication.id == DoiDeposit.publication_id)
            .join(Submission, Submission.id == Publication.submission_id)
            .where(DoiDeposit.journal_id == journal.id)
            .order_by(DoiDeposit.id.desc())
            .limit(limit)
        )
        if status:
            query = query.where(DoiDeposit.status == status)
        return [(deposit, submission) for deposit, submission in (await self.db.execute(query))]
