"""Submission wizard, the author's and the editorial lists, files and similarity checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import Forbidden, NotFound
from app.core.pagination import Page, clamp_limit
from app.core.storage import Storage
from app.modules.files.models import FileStage
from app.modules.journals.deps import Principal, get_principal
from app.modules.journals.submission_settings import submission_settings
from app.modules.submissions.models import Submission, SubmissionStatus
from app.modules.submissions.policies import Access, access_for
from app.modules.submissions.schemas import (
    ContributorIn,
    ContributorOrderIn,
    ContributorOut,
    ContributorUpdate,
    FileOut,
    FileUpdate,
    PublicationUpdate,
    SimilarityCheckOut,
    SubmissionCreate,
    SubmissionOut,
    SubmissionSummary,
    SubmissionUpdate,
    UploadRequest,
    UploadTarget,
    UploadTicketOut,
)
from app.modules.submissions.service import SubmissionService, summary_of

router = APIRouter(prefix="/submissions", tags=["submissions"])


def get_submission_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> SubmissionService:
    return SubmissionService(db, settings, storage)


async def _visible(
    service: SubmissionService, principal: Principal, submission_id: int
) -> tuple[Submission, Access]:
    submission = await service.get(principal.journal, submission_id)
    access = access_for(principal, submission)
    if not access.can_view:
        raise NotFound("Submission not found.")  # do not reveal that it exists
    return submission, access


async def _editable(service: SubmissionService, principal: Principal, submission_id: int) -> Submission:
    submission, access = await _visible(service, principal, submission_id)
    service.require_editable(submission, access)
    return submission


async def _respond(service: SubmissionService, principal: Principal, submission: Submission) -> SubmissionOut:
    await service.db.commit()
    return await service.to_out(principal, submission, access_for(principal, submission))


# ---------------------------------------------------------------------- lists and drafts


@router.get("")
async def list_my_submissions(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> Page[SubmissionSummary]:
    """Submissions the user started or is listed on as an author."""
    rows, next_cursor = await service.list_mine(principal, cursor=cursor, limit=clamp_limit(limit))
    return Page[SubmissionSummary](items=[summary_of(s) for s in rows], next_cursor=next_cursor)


@router.get("/editorial")
async def list_editorial_queue(
    status: str | None = Query(default=SubmissionStatus.QUEUED, max_length=20),
    stage: str | None = Query(default=None, max_length=20),
    section_id: int | None = None,
    assigned: bool = Query(
        default=False, description="Only manuscripts the user is assigned to as an editor"
    ),
    q: str | None = Query(default=None, max_length=200, description="Search by number or title"),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> Page[SubmissionSummary]:
    """Submitted manuscripts the user handles as an editor (never their own)."""
    rows, next_cursor = await service.list_editorial(
        principal,
        status=status or None,
        stage=stage or None,
        section_id=section_id,
        assigned_to_me=assigned,
        q=q,
        cursor=cursor,
        limit=clamp_limit(limit),
    )
    scores = await service.latest_scores([s.id for s in rows])
    threshold = submission_settings(principal.journal).similarity.threshold_percent
    return Page[SubmissionSummary](
        items=[summary_of(s, score=scores.get(s.id), threshold=threshold) for s in rows],
        next_cursor=next_cursor,
    )


@router.post("", status_code=201)
async def create_submission(
    data: SubmissionCreate,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionOut:
    """Start a draft. The signed-in user becomes its first, corresponding author."""
    submission = await service.create_draft(principal, data.section_id)
    return await _respond(service, principal, submission)


@router.get("/{submission_id}")
async def get_submission(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionOut:
    submission, access = await _visible(service, principal, submission_id)
    return await service.to_out(principal, submission, access)


@router.patch("/{submission_id}")
async def update_submission(
    submission_id: int,
    data: SubmissionUpdate,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionOut:
    """Section, checklist and comments for the editor (drafts only). If-Match: the submission's row_version."""
    submission = await _editable(service, principal, submission_id)
    await service.update_draft(principal, submission, data, expected_version=parse_if_match(if_match))
    return await _respond(service, principal, submission)


@router.patch("/{submission_id}/publication")
async def update_publication(
    submission_id: int,
    data: PublicationUpdate,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionOut:
    """Title, abstract, keywords and other metadata. If-Match: the publication's row_version."""
    submission = await _editable(service, principal, submission_id)
    await service.update_publication(submission, data, expected_version=parse_if_match(if_match))
    return await _respond(service, principal, submission)


@router.delete("/{submission_id}", status_code=204)
async def delete_submission(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> None:
    submission = await _editable(service, principal, submission_id)
    await service.delete_draft(principal, submission)
    await service.db.commit()


@router.post("/{submission_id}/submit")
async def submit_submission(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SubmissionOut:
    """Send the manuscript to the journal. Fails with the list of problems if it is incomplete."""
    submission = await _editable(service, principal, submission_id)
    await service.submit(principal, submission)
    return await _respond(service, principal, submission)


# ---------------------------------------------------------------------- contributors


@router.post("/{submission_id}/contributors", status_code=201)
async def add_contributor(
    submission_id: int,
    data: ContributorIn,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> ContributorOut:
    submission = await _editable(service, principal, submission_id)
    contributor = await service.add_contributor(submission, data)
    await service.db.commit()
    return ContributorOut.of(contributor)


@router.patch("/{submission_id}/contributors/{contributor_id}")
async def update_contributor(
    submission_id: int,
    contributor_id: int,
    data: ContributorUpdate,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> ContributorOut:
    submission = await _editable(service, principal, submission_id)
    contributor = await service.update_contributor(submission, contributor_id, data)
    await service.db.commit()
    return ContributorOut.of(contributor)


@router.delete("/{submission_id}/contributors/{contributor_id}", status_code=204)
async def delete_contributor(
    submission_id: int,
    contributor_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> None:
    submission = await _editable(service, principal, submission_id)
    await service.delete_contributor(submission, contributor_id)
    await service.db.commit()


@router.put("/{submission_id}/contributors/order", status_code=204)
async def reorder_contributors(
    submission_id: int,
    data: ContributorOrderIn,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> None:
    submission = await _editable(service, principal, submission_id)
    await service.reorder_contributors(submission, data.contributor_ids)
    await service.db.commit()


# ---------------------------------------------------------------------- files


@router.post("/{submission_id}/files/uploads", status_code=201)
async def request_file_upload(
    submission_id: int,
    data: UploadRequest,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> UploadTicketOut:
    """Step 1 of an upload: returns a signed URL. Send the file there with exactly the headers given."""
    submission = await _editable(service, principal, submission_id)
    record, ticket = await service.request_upload(principal, submission, data)
    await service.db.commit()
    return UploadTicketOut(
        file=FileOut.of(record),
        upload=UploadTarget(
            url=ticket.url, method=ticket.method, headers=ticket.headers, expires_at=ticket.expires_at
        ),
    )


@router.post("/{submission_id}/files/{file_id}/complete")
async def complete_file_upload(
    submission_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> FileOut:
    """Step 3 of an upload: confirm the file arrived. The worker then checks its contents."""
    submission = await _editable(service, principal, submission_id)
    record = await service.files.complete_upload(submission.id, file_id)
    await service.db.commit()
    return FileOut.of(record)


@router.patch("/{submission_id}/files/{file_id}")
async def update_file(
    submission_id: int,
    file_id: int,
    data: FileUpdate,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> FileOut:
    submission = await _editable(service, principal, submission_id)
    record = await service.files.get(submission.id, file_id)
    await service.files.update(record, genre=data.genre, name=data.name)
    await service.db.commit()
    return FileOut.of(record)


@router.delete("/{submission_id}/files/{file_id}", status_code=204)
async def delete_file(
    submission_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> None:
    submission = await _editable(service, principal, submission_id)
    await service.files.delete(await service.files.get(submission.id, file_id))
    await service.db.commit()


@router.get("/{submission_id}/files/{file_id}/download", status_code=302, response_class=RedirectResponse)
async def download_file(
    submission_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> RedirectResponse:
    """Redirects to a short-lived link to the file."""
    submission, access = await _visible(service, principal, submission_id)
    record = await service.files.get(submission.id, file_id)
    if record.file_stage != FileStage.SUBMISSION and not access.is_editor:
        # Files of later stages have their own rules (see the review module).
        raise NotFound("File not found.")
    return RedirectResponse(service.files.download_url(record), status_code=302)


# ---------------------------------------------------------------------- similarity (editors)


@router.post("/{submission_id}/similarity-checks", status_code=201)
async def run_similarity_check(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> SimilarityCheckOut:
    submission, access = await _visible(service, principal, submission_id)
    if not access.is_editor:
        raise Forbidden("Only editors can run similarity checks.")
    check = await service.rerun_similarity(principal, submission)
    await service.db.commit()
    return SimilarityCheckOut.of(check, submission_settings(principal.journal).similarity.threshold_percent)


@router.get(
    "/{submission_id}/similarity-checks/{check_id}/report", status_code=302, response_class=RedirectResponse
)
async def open_similarity_report(
    submission_id: int,
    check_id: int,
    principal: Principal = Depends(get_principal),
    service: SubmissionService = Depends(get_submission_service),
) -> RedirectResponse:
    """Redirects to the provider's full report, when it has one."""
    submission, access = await _visible(service, principal, submission_id)
    if not access.is_editor:
        raise NotFound("Report not found.")
    check = await service.similarity.get(submission.id, check_id)
    url = await service.similarity.report_url(check) if check else None
    if url is None:
        raise NotFound("No report is available for this check.")
    return RedirectResponse(url, status_code=302)
