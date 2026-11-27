"""The editorial workflow over HTTP: the manuscript's workflow page, decisions, editors, discussions."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import Forbidden, NotFound
from app.core.storage import Storage
from app.modules.files.models import FileStage
from app.modules.identity.schemas import UserSummary
from app.modules.journals.deps import Principal, get_principal
from app.modules.notifications.service import email_log
from app.modules.review.schemas import EmailOut
from app.modules.review.views import round_views
from app.modules.submissions.models import Submission, SubmissionStatus
from app.modules.submissions.policies import Access, access_for
from app.modules.submissions.schemas import FileOut, UploadRequest, UploadTarget, UploadTicketOut, Viewer
from app.modules.submissions.service import SubmissionService
from app.modules.workflow import stage_files
from app.modules.workflow.models import Discussion, EditorialDecision
from app.modules.workflow.schemas import (
    DecisionIn,
    DecisionOut,
    DecisionPreview,
    DecisionPreviewIn,
    DiscussionCreate,
    DiscussionOut,
    DiscussionSummary,
    DiscussionUpdate,
    EditorIn,
    EditorOut,
    EmailLogOut,
    MessageCreate,
    MessageOut,
    Person,
    WithdrawIn,
    WorkflowOut,
)
from app.modules.workflow.service import WorkflowService, option_of
from app.modules.workflow.transitions import RULES, Decision

router = APIRouter(prefix="/submissions/{submission_id}", tags=["workflow"])


def get_workflow_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: Storage = Depends(get_storage),
) -> WorkflowService:
    return WorkflowService(db, settings, storage)


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
    if submission.status == SubmissionStatus.DRAFT:
        raise NotFound("Submission not found.")  # drafts have no workflow yet
    access = access_for(principal, submission)
    if not access.can_view:
        raise NotFound("Submission not found.")
    return submission, access


def decision_out(record: EditorialDecision, access: Access, round_numbers: dict[int, int]) -> DecisionOut:
    decision = Decision(record.decision)
    for_editor = access.is_editor
    return DecisionOut(
        id=record.id,
        decision=decision,
        label=RULES[decision].label,
        is_recommendation=record.is_recommendation,
        round_number=round_numbers.get(record.round_id) if record.round_id else None,
        stage_before=record.stage_before,
        stage_after=record.stage_after,
        status_after=record.status_after,
        made_by=UserSummary.of(record.made_by) if record.made_by and for_editor else None,
        reason=record.reason if for_editor or decision == Decision.WITHDRAW else "",
        letter_to=list(record.letter_to),
        letter_subject=record.letter_subject,
        letter_body=record.letter_body,
        created_at=record.created_at,
    )


def discussion_summary(discussion: Discussion) -> DiscussionSummary:
    last = discussion.messages[-1] if discussion.messages else None
    return DiscussionSummary(
        id=discussion.id,
        stage=discussion.stage,
        subject=discussion.subject,
        participants=[UserSummary.of(u) for u in discussion.participants],
        is_closed=discussion.is_closed,
        message_count=len(discussion.messages),
        last_message_at=last.created_at if last else discussion.created_at,
        last_message_by=last.author.full_name if last and last.author else "",
    )


def discussion_out(discussion: Discussion) -> DiscussionOut:
    return DiscussionOut(
        **discussion_summary(discussion).model_dump(),
        messages=[
            MessageOut(
                id=m.id,
                author=UserSummary.of(m.author) if m.author else None,
                body=m.body,
                created_at=m.created_at,
            )
            for m in discussion.messages
        ],
    )


async def workflow_view(
    service: WorkflowService, principal: Principal, submission: Submission, access: Access
) -> WorkflowOut:
    # Copyeditors, typesetters and proofreaders see neither the review nor the decisions.
    in_review_loop = access.is_editor or access.is_author
    rounds = await round_views(service.review, submission, access) if in_review_loop else []
    numbers = {r.id: r.number for r in rounds}
    decisions = [
        decision_out(d, access, numbers)
        for d in await service.decisions(submission)
        if in_review_loop and (access.is_editor or not d.is_recommendation)
    ]
    editors = None
    if access.is_editor or access.production_roles:
        # Everyone working on the manuscript, by role; not shown to the authors.
        editors = [
            EditorOut(
                user=UserSummary.of(p.user),
                role=p.role,
                recommend_only=p.recommend_only,
                assigned_at=p.created_at,
            )
            for p in submission.participants
        ]
    people = [
        Person(user=UserSummary.of(user), role=role)
        for user, role in await service.people(principal.journal, submission)
        if user.id != principal.user.id
    ]
    stage_lists = {
        stage: [
            FileOut.of(f, files_url=stage_files.files_url(submission.id, stage))
            for f in await service.stage_files.list(submission, access, stage)
        ]
        for stage in stage_files.STAGES
    }
    withdraw = RULES[Decision.WITHDRAW]
    return WorkflowOut(
        stage=submission.stage,
        status=submission.status,
        viewer=Viewer.of(access),
        editors=editors,
        available_decisions=await service.options(submission, access),
        decisions=decisions,
        rounds=rounds,
        discussions=[
            discussion_summary(d) for d in await service.discussions(submission, access, principal.user)
        ],
        people=people,
        can_withdraw=access.is_author
        and submission.stage in withdraw.stages
        and submission.status in withdraw.statuses,
        fee_settled=await service.payments.fee_settled(principal.journal, submission),
        copyedit_files=stage_lists[FileStage.COPYEDIT],
        production_files=stage_lists[FileStage.PRODUCTION],
        can_upload={stage: stage_files.may_upload(access, stage) for stage in stage_files.STAGES},
    )


@router.get("/workflow")
async def get_workflow(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowOut:
    """Where the manuscript is and what happened to it, as the viewer may see it."""
    submission, access = await _load(submissions, principal, submission_id)
    return await workflow_view(service, principal, submission, access)


# ---------------------------------------------------------------------- decisions


@router.post("/decisions/preview")
async def preview_decision(
    submission_id: int,
    data: DecisionPreviewIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> DecisionPreview:
    """The letter to the authors as it would be sent, and the files that can go to reviewers."""
    submission, access = await _load(submissions, principal, submission_id)
    rule, letter, to, candidates = await service.preview(
        principal.journal, submission, access, data.decision, principal.user
    )
    return DecisionPreview(
        option=option_of(rule, submission.stage),
        letter=EmailOut(subject=letter.subject, body=letter.body, to=to) if letter else None,
        candidate_files=[FileOut.of(f) for f in candidates],
    )


@router.post("/decisions", status_code=201)
async def record_decision(
    submission_id: int,
    data: DecisionIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowOut:
    submission, access = await _load(submissions, principal, submission_id)
    await service.decide(principal.journal, submission, access, data, principal.user)
    await service.db.commit()
    return await workflow_view(service, principal, submission, access_for(principal, submission))


@router.post("/withdraw")
async def withdraw_submission(
    submission_id: int,
    data: WithdrawIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowOut:
    """The authors withdraw the manuscript. Reviewers still working are told it is no longer needed."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.withdraw(principal.journal, submission, access, data.reason, principal.user)
    await service.db.commit()
    return await workflow_view(service, principal, submission, access)


# ---------------------------------------------------------------------- people working on it


@router.get("/participant-candidates")
async def list_participant_candidates(
    submission_id: int,
    role: Literal["editor", "copyeditor", "layout_editor", "proofreader"] = "editor",
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> list[UserSummary]:
    """People with the journal role for this kind of work who could be assigned to the manuscript."""
    submission, access = await _load(submissions, principal, submission_id)
    if not access.can_manage:
        raise Forbidden()
    return [UserSummary.of(u) for u in await service.candidates(principal.journal, submission, role)]


@router.post("/participants", status_code=201)
async def assign_participant(
    submission_id: int,
    data: EditorIn,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowOut:
    """Assign an editor, copyeditor, layout editor or proofreader."""
    submission, access = await _load(submissions, principal, submission_id)
    await service.assign(principal.journal, submission, access, data, principal.user)
    await service.db.commit()
    return await workflow_view(service, principal, submission, access_for(principal, submission))


@router.delete("/participants/{role}/{user_id}")
async def unassign_participant(
    submission_id: int,
    role: Literal["editor", "copyeditor", "layout_editor", "proofreader"],
    user_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowOut:
    submission, access = await _load(submissions, principal, submission_id)
    await service.unassign(principal.journal, submission, access, user_id, role, principal.user)
    await service.db.commit()
    access = access_for(principal, submission)
    if not access.can_view:
        raise NotFound("Submission not found.")  # the editor removed themselves
    return await workflow_view(service, principal, submission, access)


# ---------------------------------------------------------------------- copyediting and production files

StageName = Literal["copyedit", "production"]


@router.post("/stage-files/{stage}/uploads", status_code=201)
async def request_stage_upload(
    submission_id: int,
    stage: StageName,
    data: UploadRequest,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> UploadTicketOut:
    submission, access = await _load(submissions, principal, submission_id)
    record, ticket = await service.stage_files.request_upload(
        principal.journal, submission, access, stage, data, principal.user
    )
    await service.db.commit()
    return UploadTicketOut(
        file=FileOut.of(record, files_url=stage_files.files_url(submission.id, stage)),
        upload=UploadTarget(
            url=ticket.url, method=ticket.method, headers=ticket.headers, expires_at=ticket.expires_at
        ),
    )


@router.post("/stage-files/{stage}/{file_id}/complete")
async def complete_stage_upload(
    submission_id: int,
    stage: StageName,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> FileOut:
    submission, access = await _load(submissions, principal, submission_id)
    record = await service.stage_files.get(submission, access, stage, file_id)
    if not stage_files.may_upload(access, stage):
        raise Forbidden()
    record = await service.files.complete_upload(submission.id, record.id)
    await service.db.commit()
    return FileOut.of(record, files_url=stage_files.files_url(submission.id, stage))


@router.delete("/stage-files/{stage}/{file_id}", status_code=204)
async def delete_stage_file(
    submission_id: int,
    stage: StageName,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> Response:
    submission, access = await _load(submissions, principal, submission_id)
    await service.stage_files.delete(submission, access, stage, file_id, principal.user)
    await service.db.commit()
    return Response(status_code=204)


@router.get("/stage-files/{stage}/{file_id}/download", status_code=302, response_class=RedirectResponse)
async def download_stage_file(
    submission_id: int,
    stage: StageName,
    file_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> RedirectResponse:
    submission, access = await _load(submissions, principal, submission_id)
    record = await service.stage_files.get(submission, access, stage, file_id)
    return RedirectResponse(service.files.download_url(record), status_code=302)


# ---------------------------------------------------------------------- discussions


@router.post("/discussions", status_code=201)
async def start_discussion(
    submission_id: int,
    data: DiscussionCreate,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> DiscussionOut:
    submission, access = await _load(submissions, principal, submission_id)
    discussion = await service.create_discussion(principal.journal, submission, access, data, principal.user)
    await service.db.commit()
    return discussion_out(discussion)


@router.get("/discussions/{discussion_id}")
async def get_discussion(
    submission_id: int,
    discussion_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> DiscussionOut:
    submission, access = await _load(submissions, principal, submission_id)
    return discussion_out(await service.get_discussion(submission, access, principal.user, discussion_id))


@router.post("/discussions/{discussion_id}/messages", status_code=201)
async def post_message(
    submission_id: int,
    discussion_id: int,
    data: MessageCreate,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> DiscussionOut:
    submission, access = await _load(submissions, principal, submission_id)
    discussion = await service.get_discussion(submission, access, principal.user, discussion_id)
    await service.add_message(principal.journal, submission, discussion, data.body, principal.user)
    await service.db.commit()
    return discussion_out(discussion)


@router.patch("/discussions/{discussion_id}")
async def update_discussion(
    submission_id: int,
    discussion_id: int,
    data: DiscussionUpdate,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> DiscussionOut:
    submission, access = await _load(submissions, principal, submission_id)
    discussion = await service.get_discussion(submission, access, principal.user, discussion_id)
    await service.set_closed(discussion, access, principal.user, data.is_closed)
    await service.db.commit()
    return discussion_out(discussion)


# ---------------------------------------------------------------------- history


@router.get("/emails")
async def list_emails(
    submission_id: int,
    principal: Principal = Depends(get_principal),
    submissions: SubmissionService = Depends(get_submission_service),
    service: WorkflowService = Depends(get_workflow_service),
) -> list[EmailLogOut]:
    """Every e-mail sent about the manuscript, newest first. Editors only."""
    submission, access = await _load(submissions, principal, submission_id)
    if not access.is_editor:
        raise Forbidden()
    rows = await email_log(service.db, submission.id)
    senders = {u.id: u.full_name for u in [p.user for p in submission.participants]}
    result = []
    for row in rows:
        sender = None
        if row.sent_by_id is not None:
            sender = senders.get(row.sent_by_id)
            if sender is None:
                user = await service.journals.identity.get_user(row.sent_by_id)
                sender = senders[row.sent_by_id] = user.full_name
        result.append(
            EmailLogOut(
                id=row.id,
                template_key=row.template_key,
                recipient=row.recipient,
                subject=row.subject,
                body=row.body,
                status=row.status,
                sent_by=sender,
                created_at=row.created_at,
                sent_at=row.sent_at,
            )
        )
    return result
