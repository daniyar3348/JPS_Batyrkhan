"""Peer review over HTTP: editors manage rounds and reviewers, reviewers write reviews, authors revise."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import ensure_version, etag_for, parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import Forbidden, NotFound
from app.core.storage import PresignedUpload, Storage
from app.modules.files.models import FileStage, SubmissionFile
from app.modules.journals.deps import Principal, get_principal, require
from app.modules.journals.email_templates import Rendered
from app.modules.journals.permissions import Capability, Role
from app.modules.journals.review_settings import review_settings
from app.modules.review import policies, suggestions
from app.modules.review.forms import ReviewFormIn, questions_of
from app.modules.review.models import ReviewAssignment, ReviewForm, ReviewRound
from app.modules.review.policies import reviewer_files_url, round_files_url
from app.modules.review.schemas import (
    AcceptIn,
    AcknowledgeIn,
    AssignmentOut,
    CancelIn,
    DatesIn,
    DeclineIn,
    EmailOut,
    InvitationPreviewIn,
    RemindIn,
    ReviewerAssignmentOut,
    ReviewerInviteIn,
    ReviewerTask,
    ReviewFilesIn,
    ReviewFormOut,
    ReviewIn,
    RevisionsIn,
    RoundOut,
    Suggestion,
)
from app.modules.review.service import ReviewService
from app.modules.review.views import round_views
from app.modules.submissions.models import Submission
from app.modules.submissions.policies import Access, access_for
from app.modules.submissions.schemas import FileOut, UploadRequest, UploadTarget, UploadTicketOut
from app.modules.submissions.service import SubmissionService

router = APIRouter(tags=["review"])

EDITORIAL_ROLES = frozenset({Role.ADMIN, Role.EDITOR_IN_CHIEF, Role.SECTION_EDITOR})


def get_review_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> ReviewService:
    return ReviewService(db, settings, storage)


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
    # Peer review is for the editors and the authors; copyeditors and typesetters never see it.
    if not (access.is_editor or access.is_author):
        raise NotFound("Submission not found.")
    return submission, access


async def _managed(
    submissions: SubmissionService, principal: Principal, submission_id: int
) -> tuple[Submission, Access]:
    submission, access = await _load(submissions, principal, submission_id)
    if not access.can_manage:
        raise Forbidden("Only the manuscript's editors can do this.")
    return submission, access


def _ticket(record: SubmissionFile, ticket: PresignedUpload, files_url: str) -> UploadTicketOut:
    return UploadTicketOut(
        file=FileOut.of(record, files_url=files_url),
        upload=UploadTarget(
            url=ticket.url, method=ticket.method, headers=ticket.headers, expires_at=ticket.expires_at
        ),
    )


def _email(rendered: Rendered, to: str) -> EmailOut:
    return EmailOut(subject=rendered.subject, body=rendered.body, to=[to])


async def _assignment_out(service: ReviewService, assignment: ReviewAssignment) -> AssignmentOut:
    attachments = await service.files.list(
        assignment.submission_id, file_stage=FileStage.REVIEW_ATTACHMENT, review_assignment_id=assignment.id
    )
    reminders = await service.last_reminders([assignment.id])
    return policies.editor_view(assignment, attachments, reminders.get(assignment.id))


# ---------------------------------------------------------------------- rounds (editors and authors)


@router.get("/submissions/{submission_id}/review-rounds")
async def list_review_rounds(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> list[RoundOut]:
    """Editors see every request and review. Authors see the reviews once the editor has decided."""
    submission, access = await _load(submissions, principal, submission_id)
    return await round_views(service, submission, access)


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/files")
async def add_review_files(
    submission_id: int,
    round_id: int,
    data: ReviewFilesIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> list[RoundOut]:
    """Give the round's reviewers more files. Copies are made without the authors' names in metadata."""
    submission, access = await _managed(submissions, principal, submission_id)
    review_round = await service.require_current(submission, round_id)
    await service.add_review_files(principal.journal, submission, review_round, data.file_ids, principal.user)
    await service.db.commit()
    return await round_views(service, submission, access)


@router.delete("/submissions/{submission_id}/review-rounds/{round_id}/files/{file_id}", status_code=204)
async def remove_review_file(
    submission_id: int,
    round_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    submission, _ = await _managed(submissions, principal, submission_id)
    review_round = await service.require_current(submission, round_id)
    await service.remove_review_file(submission, review_round, file_id)
    await service.db.commit()
    return Response(status_code=204)


@router.get(
    "/submissions/{submission_id}/review-rounds/{round_id}/files/{file_id}/download",
    status_code=302,
    response_class=RedirectResponse,
)
async def download_round_file(
    submission_id: int,
    round_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> RedirectResponse:
    submission, access = await _load(submissions, principal, submission_id)
    review_round = await service.get_round(submission, round_id)
    record = await service.files.get(submission.id, file_id)
    if record.review_round_id != review_round.id:
        raise NotFound("File not found.")
    if not access.is_editor:
        assignments = await service.assignments(submission.id, round_id=review_round.id)
        if not policies.author_may_download(record, review_round, assignments):
            raise NotFound("File not found.")
    return RedirectResponse(service.files.download_url(record), status_code=302)


# ---------------------------------------------------------------------- reviewers (editors)


@router.get("/submissions/{submission_id}/review-rounds/{round_id}/suggestions")
async def suggest_reviewers(
    submission_id: int,
    round_id: int,
    q: str | None = Query(
        default=None, max_length=200, description="Search by name, e-mail, affiliation, interests"
    ),
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> list[Suggestion]:
    """The journal's reviewers who may review this manuscript, best matches first, with warnings."""
    submission, _ = await _managed(submissions, principal, submission_id)
    review_round = await service.get_round(submission, round_id)
    return await suggestions.suggest(
        service.db,
        journal_id=principal.journal.id,
        submission=submission,
        review_round=review_round,
        viewer_id=principal.user.id,
        query=q,
    )


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/invitation-preview")
async def preview_invitation(
    submission_id: int,
    round_id: int,
    data: InvitationPreviewIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> EmailOut:
    """The invitation e-mail as it would be sent. {reviewUrl} is filled in when it is sent."""
    submission, _ = await _managed(submissions, principal, submission_id)
    await service.require_current(submission, round_id)
    rendered, to = await service.preview_invitation(
        principal.journal,
        submission,
        reviewer_id=data.reviewer_id,
        new_reviewer=data.new_reviewer,
        response_due=data.response_due,
        review_due=data.review_due,
        editor=principal.user,
    )
    return _email(rendered, to)


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/reviewers", status_code=201)
async def invite_reviewer(
    submission_id: int,
    round_id: int,
    data: ReviewerInviteIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> AssignmentOut:
    """Invite one of the journal's reviewers, or a new person (they also get an account invitation)."""
    submission, _ = await _managed(submissions, principal, submission_id)
    review_round = await service.require_current(submission, round_id)
    assignment = await service.invite(principal.journal, submission, review_round, data, principal.user)
    await service.db.commit()
    return await _assignment_out(service, assignment)


async def _managed_assignment(
    submissions: SubmissionService,
    service: ReviewService,
    principal: Principal,
    submission_id: int,
    assignment_id: int,
) -> tuple[Submission, ReviewAssignment]:
    submission, _ = await _managed(submissions, principal, submission_id)
    return submission, await service.get_assignment(submission, assignment_id)


@router.patch("/submissions/{submission_id}/review-assignments/{assignment_id}")
async def change_review_dates(
    submission_id: int,
    assignment_id: int,
    data: DatesIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> AssignmentOut:
    _, assignment = await _managed_assignment(submissions, service, principal, submission_id, assignment_id)
    await service.set_dates(assignment, data.response_due, data.review_due)
    await service.db.commit()
    return await _assignment_out(service, assignment)


@router.post("/submissions/{submission_id}/review-assignments/{assignment_id}/cancel")
async def cancel_review(
    submission_id: int,
    assignment_id: int,
    data: CancelIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> AssignmentOut:
    submission, assignment = await _managed_assignment(
        submissions, service, principal, submission_id, assignment_id
    )
    await service.cancel(principal.journal, submission, assignment, principal.user, notify=data.notify)
    await service.db.commit()
    return await _assignment_out(service, assignment)


@router.post("/submissions/{submission_id}/review-assignments/{assignment_id}/reminder-preview")
async def preview_reminder(
    submission_id: int,
    assignment_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> EmailOut:
    submission, assignment = await _managed_assignment(
        submissions, service, principal, submission_id, assignment_id
    )
    rendered = await service.reminder_email(principal.journal, submission, assignment, principal.user)
    return _email(rendered, assignment.reviewer.email)


@router.post("/submissions/{submission_id}/review-assignments/{assignment_id}/remind")
async def remind_reviewer(
    submission_id: int,
    assignment_id: int,
    data: RemindIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> AssignmentOut:
    submission, assignment = await _managed_assignment(
        submissions, service, principal, submission_id, assignment_id
    )
    await service.remind(
        principal.journal,
        submission,
        assignment,
        Rendered(subject=data.email.subject, body=data.email.body),
        principal.user,
    )
    await service.db.commit()
    return await _assignment_out(service, assignment)


@router.post("/submissions/{submission_id}/review-assignments/{assignment_id}/thanks-preview")
async def preview_thanks(
    submission_id: int,
    assignment_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> EmailOut:
    submission, assignment = await _managed_assignment(
        submissions, service, principal, submission_id, assignment_id
    )
    rendered = await service.thanks_email(principal.journal, submission, assignment, principal.user)
    return _email(rendered, assignment.reviewer.email)


@router.post("/submissions/{submission_id}/review-assignments/{assignment_id}/acknowledge")
async def acknowledge_review(
    submission_id: int,
    assignment_id: int,
    data: AcknowledgeIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> AssignmentOut:
    """Rate a finished review (1 to 5, used when suggesting reviewers) and thank the reviewer."""
    submission, assignment = await _managed_assignment(
        submissions, service, principal, submission_id, assignment_id
    )
    email = None
    if data.send_thanks:
        email = (
            Rendered(subject=data.email.subject, body=data.email.body)
            if data.email is not None
            else await service.thanks_email(principal.journal, submission, assignment, principal.user)
        )
    await service.acknowledge(
        principal.journal, submission, assignment, rating=data.rating, email=email, actor=principal.user
    )
    await service.db.commit()
    return await _assignment_out(service, assignment)


# ---------------------------------------------------------------------- revisions (authors)


async def _author_round(
    submissions: SubmissionService,
    service: ReviewService,
    principal: Principal,
    submission_id: int,
    round_id: int,
) -> tuple[Submission, Access, ReviewRound]:
    submission, access = await _load(submissions, principal, submission_id)
    if not access.is_author:
        raise Forbidden("Only the manuscript's authors can send revisions.")
    return submission, access, await service.require_current(submission, round_id)


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/revisions/uploads", status_code=201)
async def request_revision_upload(
    submission_id: int,
    round_id: int,
    data: UploadRequest,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> UploadTicketOut:
    submission, _, review_round = await _author_round(
        submissions, service, principal, submission_id, round_id
    )
    record, ticket = await service.request_revision_upload(
        principal.journal, submission, review_round, data, principal.user
    )
    await service.db.commit()
    return _ticket(record, ticket, round_files_url(submission.id, review_round.id))


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/revisions/{file_id}/complete")
async def complete_revision_upload(
    submission_id: int,
    round_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> FileOut:
    submission, _, review_round = await _author_round(
        submissions, service, principal, submission_id, round_id
    )
    record = await service.revision_file(submission, review_round, file_id)
    record = await service.files.complete_upload(submission.id, record.id)
    await service.db.commit()
    return FileOut.of(record, files_url=round_files_url(submission.id, review_round.id))


@router.delete("/submissions/{submission_id}/review-rounds/{round_id}/revisions/{file_id}", status_code=204)
async def delete_revision_file(
    submission_id: int,
    round_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    submission, _, review_round = await _author_round(
        submissions, service, principal, submission_id, round_id
    )
    service.require_awaiting_revisions(review_round)
    await service.files.delete(await service.revision_file(submission, review_round, file_id))
    await service.db.commit()
    return Response(status_code=204)


@router.post("/submissions/{submission_id}/review-rounds/{round_id}/revisions/submit")
async def submit_revisions(
    submission_id: int,
    round_id: int,
    data: RevisionsIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> list[RoundOut]:
    """Send the revised files and the reply to the reviewers to the editors."""
    submission, access, review_round = await _author_round(
        submissions, service, principal, submission_id, round_id
    )
    await service.submit_revisions(principal.journal, submission, review_round, data.response, principal.user)
    await service.db.commit()
    return await round_views(service, submission, access)


# ---------------------------------------------------------------------- reviewers


async def _my_review(
    service: ReviewService, submissions: SubmissionService, principal: Principal, assignment_id: int
) -> tuple[ReviewAssignment, Submission]:
    assignment = await service.for_reviewer(principal.user, assignment_id)
    submission = await submissions.get(principal.journal, assignment.submission_id)
    return assignment, submission


async def _reviewer_out(
    service: ReviewService, principal: Principal, assignment: ReviewAssignment, submission: Submission
) -> ReviewerAssignmentOut:
    review_files = await service.files.list(
        submission.id, file_stage=FileStage.REVIEW, review_round_id=assignment.round_id
    )
    attachments = await service.files.list(
        submission.id, file_stage=FileStage.REVIEW_ATTACHMENT, review_assignment_id=assignment.id
    )
    return policies.reviewer_view(
        assignment,
        submission,
        review_files=review_files,
        attachments=attachments,
        guidelines=review_settings(principal.journal).reviewer_guidelines,
    )


@router.get("/reviews")
async def list_my_reviews(
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> list[ReviewerTask]:
    """Review requests sent to the signed-in user, newest first."""
    result = []
    for assignment in await service.reviewer_tasks(principal.user, principal.journal):
        submission = await submissions.get(principal.journal, assignment.submission_id)
        result.append(policies.reviewer_task(assignment, submission))
    return result


@router.get("/reviews/{assignment_id}")
async def get_my_review(
    assignment_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> ReviewerAssignmentOut:
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    return await _reviewer_out(service, principal, assignment, submission)


@router.post("/reviews/{assignment_id}/accept")
async def accept_review(
    assignment_id: int,
    data: AcceptIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> ReviewerAssignmentOut:
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    await service.accept(principal.journal, submission, assignment, data.competing_interests)
    await service.db.commit()
    return await _reviewer_out(service, principal, assignment, submission)


@router.post("/reviews/{assignment_id}/decline")
async def decline_review(
    assignment_id: int,
    data: DeclineIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> ReviewerAssignmentOut:
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    await service.decline(principal.journal, submission, assignment, data.reason, data.comment)
    await service.db.commit()
    return await _reviewer_out(service, principal, assignment, submission)


@router.put("/reviews/{assignment_id}/draft")
async def save_review_draft(
    assignment_id: int,
    data: ReviewIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> ReviewerAssignmentOut:
    """Save the review without sending it."""
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    await service.save_draft(assignment, data)
    await service.db.commit()
    return await _reviewer_out(service, principal, assignment, submission)


@router.post("/reviews/{assignment_id}/submit")
async def submit_review(
    assignment_id: int,
    data: ReviewIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> ReviewerAssignmentOut:
    """Send the review to the editors. It cannot be changed afterwards."""
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    await service.submit_review(principal.journal, submission, assignment, data)
    await service.db.commit()
    return await _reviewer_out(service, principal, assignment, submission)


@router.post("/reviews/{assignment_id}/files/uploads", status_code=201)
async def request_attachment_upload(
    assignment_id: int,
    data: UploadRequest,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> UploadTicketOut:
    """Attach a file to the review, e.g. an annotated manuscript. The reviewer's name is removed from it."""
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    record, ticket = await service.request_attachment(
        principal.journal, submission, assignment, data, principal.user
    )
    await service.db.commit()
    return _ticket(record, ticket, reviewer_files_url(assignment.id))


@router.post("/reviews/{assignment_id}/files/{file_id}/complete")
async def complete_attachment_upload(
    assignment_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> FileOut:
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    service.require_editable(assignment)
    record = await service.attachment(submission, assignment, file_id)
    record = await service.files.complete_upload(submission.id, record.id)
    await service.db.commit()
    return FileOut.of(record, files_url=reviewer_files_url(assignment.id))


@router.delete("/reviews/{assignment_id}/files/{file_id}", status_code=204)
async def delete_attachment(
    assignment_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    service.require_editable(assignment)
    await service.files.delete(await service.attachment(submission, assignment, file_id))
    await service.db.commit()
    return Response(status_code=204)


@router.get(
    "/reviews/{assignment_id}/files/{file_id}/download", status_code=302, response_class=RedirectResponse
)
async def download_review_file(
    assignment_id: int,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: ReviewService = Depends(get_review_service),
) -> RedirectResponse:
    """The round's files for reviewers (after accepting), and the reviewer's own attachments."""
    assignment, submission = await _my_review(service, submissions, principal, assignment_id)
    record = await service.files.get(submission.id, file_id)
    own = record.file_stage == FileStage.REVIEW_ATTACHMENT and record.review_assignment_id == assignment.id
    for_round = (
        record.file_stage == FileStage.REVIEW
        and record.review_round_id == assignment.round_id
        and assignment.status in ("accepted", "completed")
    )
    if not (own or for_round):
        raise NotFound("File not found.")
    return RedirectResponse(service.files.download_url(record), status_code=302)


# ---------------------------------------------------------------------- review forms


def _form_out(form: ReviewForm) -> ReviewFormOut:
    return ReviewFormOut(
        id=form.id,
        title=form.title,
        description=form.description,
        questions=questions_of(form.questions),
        is_active=form.is_active,
        is_default=form.is_default,
        version=form.version,
    )


@router.get("/journal/review-forms", tags=["journal"])
async def list_review_forms(
    principal: Principal = Depends(get_principal),
    service: ReviewService = Depends(get_review_service),
) -> list[ReviewFormOut]:
    if not principal.roles & EDITORIAL_ROLES:
        raise Forbidden()
    forms = await service.forms(principal.journal)
    await service.db.commit()  # the default form is created on first use
    return [_form_out(f) for f in forms]


@router.post("/journal/review-forms", tags=["journal"], status_code=201)
async def create_review_form(
    data: ReviewFormIn,
    principal: Principal = Depends(require(Capability.JOURNAL_SETTINGS_EDIT)),
    service: ReviewService = Depends(get_review_service),
) -> ReviewFormOut:
    form = await service.create_form(principal.journal, data, principal.user)
    await service.db.commit()
    return _form_out(form)


@router.put("/journal/review-forms/{form_id}", tags=["journal"])
async def update_review_form(
    form_id: int,
    data: ReviewFormIn,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require(Capability.JOURNAL_SETTINGS_EDIT)),
    service: ReviewService = Depends(get_review_service),
) -> ReviewFormOut:
    """Changes apply to new invitations; reviewers already invited keep the questions they were sent."""
    form = await service.get_form(principal.journal, form_id)
    ensure_version(form.version, parse_if_match(if_match))
    await service.update_form(principal.journal, form, data)
    await service.db.commit()
    response.headers["ETag"] = etag_for(form.version)
    return _form_out(form)


@router.delete("/journal/review-forms/{form_id}", tags=["journal"], status_code=204)
async def delete_review_form(
    form_id: int,
    principal: Principal = Depends(require(Capability.JOURNAL_SETTINGS_EDIT)),
    service: ReviewService = Depends(get_review_service),
) -> Response:
    form = await service.get_form(principal.journal, form_id)
    await service.delete_form(principal.journal, form)
    await service.db.commit()
    return Response(status_code=204)
