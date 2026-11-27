"""Publishing over HTTP, for the editorial office: issues, the publication screen, galleys, DOIs, settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import etag_for, parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import Forbidden, NotFound
from app.core.storage import Storage
from app.modules.journals.deps import Principal, get_journal_service, get_principal, require
from app.modules.journals.permissions import Capability, Role
from app.modules.journals.publishing_settings import (
    SUFFIX_PLACEHOLDERS,
    PublishingSettings,
    publishing_settings,
)
from app.modules.journals.service import JournalService
from app.modules.publishing import crossref
from app.modules.publishing.doi import make_doi
from app.modules.publishing.models import Issue
from app.modules.publishing.schemas import (
    ArticleOrderIn,
    DepositListItem,
    DepositOut,
    GalleyOut,
    GalleyUpdate,
    GalleyUploadIn,
    GalleyUploadOut,
    IssueDetail,
    IssueIn,
    IssueOut,
    IssuePublishIn,
    PublishingOut,
    PublishingSettingsOut,
    PublishingUpdate,
    VersionIn,
)
from app.modules.publishing.service import PublishingService
from app.modules.submissions.models import Submission, SubmissionStatus
from app.modules.submissions.policies import Access, access_for
from app.modules.submissions.schemas import UploadTarget
from app.modules.submissions.service import SubmissionService

router = APIRouter(tags=["publishing"])
MANAGE = require(Capability.PUBLISHING_MANAGE)


def get_publishing_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> PublishingService:
    return PublishingService(db, settings, storage)


def get_submission_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SubmissionService:
    return SubmissionService(db, settings, storage)


async def _load(
    submissions: SubmissionService, principal: Principal, submission_id: int
) -> tuple[Submission, Access]:
    submission = await submissions.get(principal.journal, submission_id)
    access = access_for(principal, submission)
    if submission.status == SubmissionStatus.DRAFT or not (access.is_editor or access.production_roles):
        raise NotFound("Submission not found.")
    return submission, access


def _editorial(principal: Principal = Depends(get_principal)) -> Principal:
    """Issues are listed to everyone who may put an article into one."""
    if not (
        principal.can(Capability.PUBLISHING_MANAGE)
        or principal.can(Capability.SUBMISSIONS_VIEW_ALL)
        or Role.SECTION_EDITOR in principal.roles
    ):
        raise Forbidden()
    return principal


async def _view(
    service: PublishingService, principal: Principal, submission: Submission, access: Access
) -> PublishingOut:
    await service.db.commit()
    return await service.view(principal.journal, submission, access)


# ---------------------------------------------------------------------- issues


@router.get("/issues")
async def list_issues(
    status: str | None = Query(default=None, pattern="^(future|published)$"),
    principal: Principal = Depends(_editorial),
    service: PublishingService = Depends(get_publishing_service),
) -> list[IssueOut]:
    """Future issues first, then the published ones, newest first."""
    return await service.list_issues(principal.journal, status=status)


async def _issue_detail(service: PublishingService, principal: Principal, issue: Issue) -> IssueDetail:
    articles = await service.issue_articles(principal.journal, issue)
    return IssueDetail(**IssueOut.of(issue, article_count=len(articles)).model_dump(), articles=articles)


@router.post("/issues", status_code=201)
async def create_issue(
    data: IssueIn,
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    issue = await service.create_issue(principal.journal, data, principal.user)
    await service.db.commit()
    return await _issue_detail(service, principal, issue)


@router.get("/issues/{issue_id}")
async def get_issue(
    issue_id: int,
    response: Response,
    principal: Principal = Depends(_editorial),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    """The issue with its articles in reading order. ETag: the issue's row_version."""
    issue = await service.get_issue(principal.journal, issue_id)
    response.headers["ETag"] = etag_for(issue.row_version)
    return await _issue_detail(service, principal, issue)


@router.put("/issues/{issue_id}")
async def update_issue(
    issue_id: int,
    data: IssueIn,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    issue = await service.get_issue(principal.journal, issue_id)
    await service.update_issue(
        principal.journal, issue, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await service.db.commit()
    response.headers["ETag"] = etag_for(issue.row_version)
    return await _issue_detail(service, principal, issue)


@router.delete("/issues/{issue_id}", status_code=204)
async def delete_issue(
    issue_id: int,
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> Response:
    issue = await service.get_issue(principal.journal, issue_id)
    await service.delete_issue(principal.journal, issue, principal.user)
    await service.db.commit()
    return Response(status_code=204)


@router.put("/issues/{issue_id}/order")
async def order_issue(
    issue_id: int,
    data: ArticleOrderIn,
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    """The articles' order within their sections (sections keep the journal's order)."""
    issue = await service.get_issue(principal.journal, issue_id)
    await service.order_articles(principal.journal, issue, data.submission_ids, principal.user)
    await service.db.commit()
    return await _issue_detail(service, principal, issue)


@router.post("/issues/{issue_id}/publish")
async def publish_issue(
    issue_id: int,
    data: IssuePublishIn,
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    """Publish the issue with every article scheduled in it. Refused if any of them is not ready."""
    issue = await service.get_issue(principal.journal, issue_id)
    await service.publish_issue(principal.journal, issue, principal.user, make_current=data.make_current)
    await service.db.commit()
    return await _issue_detail(service, principal, issue)


@router.post("/issues/{issue_id}/current")
async def make_issue_current(
    issue_id: int,
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> IssueDetail:
    issue = await service.get_issue(principal.journal, issue_id)
    await service.set_current(principal.journal, issue, principal.user)
    await service.db.commit()
    return await _issue_detail(service, principal, issue)


# ---------------------------------------------------------------------- the publication screen


@router.get("/submissions/{submission_id}/publishing")
async def get_publishing(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    """Issue, galleys, readiness, versions and DOI of the article: editors and production staff."""
    submission, access = await _load(submissions, principal, submission_id)
    return await service.view(principal.journal, submission, access)


@router.patch("/submissions/{submission_id}/publishing")
async def update_publishing(
    submission_id: int,
    data: PublishingUpdate,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    """Issue, pages, address, licence, copyright. If-Match: the publication's row_version."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.update(
        principal.journal,
        submission,
        access,
        data,
        expected_version=parse_if_match(if_match),
        actor=principal.user,
    )
    return await _view(service, principal, submission, access)


@router.post("/submissions/{submission_id}/publish")
async def publish_article(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    """Schedule into the article's issue, or publish at once if the issue is out (or publish a new version)."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.publish(principal.journal, submission, access, principal.user)
    return await _view(service, principal, submission, access)


@router.post("/submissions/{submission_id}/unschedule")
async def unschedule_article(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    submission, access = await _load(submissions, principal, submission_id)
    await service.unschedule(principal.journal, submission, access, principal.user)
    return await _view(service, principal, submission, access)


@router.post("/submissions/{submission_id}/versions", status_code=201)
async def create_version(
    submission_id: int,
    data: VersionIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    """Start a correction of the published article. Readers see it once it is published."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.new_version(principal.journal, submission, access, data.note, principal.user)
    return await _view(service, principal, submission, access)


@router.delete("/submissions/{submission_id}/versions/draft")
async def discard_version(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    submission, access = await _load(submissions, principal, submission_id)
    await service.discard_version(principal.journal, submission, access, principal.user)
    return await _view(service, principal, submission, access)


@router.post("/submissions/{submission_id}/doi")
async def assign_doi(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> PublishingOut:
    """Assign the DOI now (normally done when the article enters production)."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.assign_doi(principal.journal, submission, access, principal.user)
    return await _view(service, principal, submission, access)


@router.post("/submissions/{submission_id}/doi/deposits", status_code=202)
async def deposit_doi(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> DepositOut:
    """Send the published metadata to Crossref again (after a failure, or after changing the issue)."""
    submission, access = await _load(submissions, principal, submission_id)
    deposit = await service.deposit_again(principal.journal, submission, access, principal.user)
    await service.db.commit()
    return DepositOut.of(deposit)


# ---------------------------------------------------------------------- galleys


@router.post("/submissions/{submission_id}/galleys/uploads", status_code=201)
async def request_galley_upload(
    submission_id: int,
    data: GalleyUploadIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> GalleyUploadOut:
    """A galley and a signed upload link for its file (PDF, HTML, XML or EPUB)."""
    submission, access = await _load(submissions, principal, submission_id)
    galley, ticket = await service.request_galley_upload(
        principal.journal, submission, access, data, principal.user
    )
    await service.db.commit()
    return GalleyUploadOut(
        galley=GalleyOut.of(galley, submission.id),
        upload=UploadTarget(
            url=ticket.url, method=ticket.method, headers=ticket.headers, expires_at=ticket.expires_at
        ),
    )


@router.post("/submissions/{submission_id}/galleys/{galley_id}/complete")
async def complete_galley_upload(
    submission_id: int,
    galley_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> GalleyOut:
    submission, access = await _load(submissions, principal, submission_id)
    galley = await service.complete_galley(submission, access, galley_id)
    await service.db.commit()
    return GalleyOut.of(galley, submission.id)


@router.patch("/submissions/{submission_id}/galleys/{galley_id}")
async def rename_galley(
    submission_id: int,
    galley_id: int,
    data: GalleyUpdate,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> GalleyOut:
    submission, access = await _load(submissions, principal, submission_id)
    galley = await service.rename_galley(submission, access, galley_id, data.label)
    await service.db.commit()
    return GalleyOut.of(galley, submission.id)


@router.delete("/submissions/{submission_id}/galleys/{galley_id}", status_code=204)
async def delete_galley(
    submission_id: int,
    galley_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> Response:
    submission, access = await _load(submissions, principal, submission_id)
    await service.delete_galley(submission, access, galley_id)
    await service.db.commit()
    return Response(status_code=204)


@router.get(
    "/submissions/{submission_id}/galleys/{galley_id}/file/{file_id}/download",
    status_code=302,
    response_class=RedirectResponse,
)
async def download_galley(
    submission_id: int,
    galley_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: PublishingService = Depends(get_publishing_service),
) -> RedirectResponse:
    submission, access = await _load(submissions, principal, submission_id)
    return RedirectResponse(await service.galley_download(submission, access, galley_id), status_code=302)


# ---------------------------------------------------------------------- DOI deposits and settings


@router.get("/publishing/doi-deposits")
async def list_deposits(
    status: str | None = Query(default=None, pattern="^(queued|submitted|registered|failed)$"),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(MANAGE),
    service: PublishingService = Depends(get_publishing_service),
) -> list[DepositListItem]:
    """The latest deposits with Crossref and what Crossref answered."""
    rows = await service.list_deposits(principal.journal, status=status, limit=limit)
    return [
        DepositListItem(
            **DepositOut.of(deposit).model_dump(),
            submission_id=submission.id,
            submission_number=submission.number,
            title=submission.publication.title,
        )
        for deposit, submission in rows
    ]


def _settings_out(
    principal: Principal, saved: PublishingSettings, settings: Settings
) -> PublishingSettingsOut:
    # What the pattern gives for a manuscript numbered ...-2026-0042.
    example = (
        make_doi(saved.doi, principal.journal, Submission(id=42, number="X-2026-0042"))
        if saved.doi.prefix
        else None
    )
    return PublishingSettingsOut(
        settings=saved,
        crossref_mode=settings.crossref_mode,
        crossref_account_configured=bool(settings.crossref_username and settings.crossref_password),
        site_revalidation_configured=bool(settings.site_revalidate_url and settings.site_revalidate_secret),
        problems=crossref.deposit_problems(principal.journal, saved) if saved.doi.enabled else [],
        suffix_placeholders=SUFFIX_PLACEHOLDERS,
        example_doi=example,
    )


@router.get("/journal/publishing-settings", tags=["journal"])
async def get_publishing_settings(
    response: Response,
    principal: Principal = Depends(MANAGE),
    settings: Settings = Depends(get_settings),
) -> PublishingSettingsOut:
    response.headers["ETag"] = etag_for(principal.journal.version)
    return _settings_out(principal, publishing_settings(principal.journal), settings)


@router.put("/journal/publishing-settings", tags=["journal"])
async def update_publishing_settings(
    data: PublishingSettings,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(MANAGE),
    journals: JournalService = Depends(get_journal_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> PublishingSettingsOut:
    saved = await journals.update_publishing_settings(
        principal.journal, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await db.commit()
    response.headers["ETag"] = etag_for(principal.journal.version)
    return _settings_out(principal, saved, settings)
