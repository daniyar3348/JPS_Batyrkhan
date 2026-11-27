"""Files of the copyediting and production stages, and who may see and add them.

Copyediting: the copyeditor, the editors and the authors exchange versions of the text.
Production: the layout editor and the editors prepare the typesetting sources; proofreaders read them.
Galleys (what readers download) belong to the publishing module.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.errors import Conflict, Forbidden, NotFound
from app.core.storage import PresignedUpload
from app.modules.files.models import FileStage, SubmissionFile
from app.modules.files.service import FileService
from app.modules.identity.models import User
from app.modules.journals.models import Journal
from app.modules.journals.submission_settings import submission_settings
from app.modules.submissions.models import ParticipantRole, Stage, Submission, SubmissionStatus
from app.modules.submissions.policies import Access
from app.modules.submissions.schemas import UploadRequest

STAGES = (FileStage.COPYEDIT, FileStage.PRODUCTION)


def files_url(submission_id: int, stage: str) -> str:
    return f"/api/v1/submissions/{submission_id}/stage-files/{stage}"


def may_view(access: Access, stage: str) -> bool:
    if access.is_editor or access.production_roles:
        return True
    return stage == FileStage.COPYEDIT and access.is_author


def may_upload(access: Access, stage: str) -> bool:
    if access.can_manage:
        return True
    if stage == FileStage.COPYEDIT:
        return access.is_author or ParticipantRole.COPYEDITOR in access.production_roles
    return ParticipantRole.LAYOUT_EDITOR in access.production_roles


def _check_open(submission: Submission, stage: str) -> None:
    if submission.status not in (SubmissionStatus.QUEUED, SubmissionStatus.SCHEDULED):
        raise Conflict("The article is not being prepared any more.", code="stage_closed")
    allowed = {
        FileStage.COPYEDIT: (Stage.COPYEDITING, Stage.PRODUCTION),
        FileStage.PRODUCTION: (Stage.PRODUCTION,),
    }
    if submission.stage not in allowed[stage]:
        raise Conflict("The article has not reached this stage.", code="stage_closed")


class StageFiles:
    def __init__(self, files: FileService) -> None:
        self.files = files

    async def list(self, submission: Submission, access: Access, stage: str) -> Sequence[SubmissionFile]:
        if not may_view(access, stage):
            return []
        return await self.files.list(submission.id, file_stage=stage)

    async def request_upload(
        self,
        journal: Journal,
        submission: Submission,
        access: Access,
        stage: str,
        data: UploadRequest,
        user: User,
    ) -> tuple[SubmissionFile, PresignedUpload]:
        if not may_upload(access, stage):
            raise Forbidden("You cannot add files at this stage.")
        _check_open(submission, stage)
        return await self.files.request_upload(
            journal_id=journal.id,
            submission_id=submission.id,
            genre=data.genre,
            file_name=data.file_name,
            size=data.size,
            max_size_mb=submission_settings(journal).max_file_size_mb,
            uploaded_by_id=user.id,
            file_stage=stage,
        )

    async def get(self, submission: Submission, access: Access, stage: str, file_id: int) -> SubmissionFile:
        if not may_view(access, stage):
            raise NotFound("File not found.")
        record = await self.files.get(submission.id, file_id)
        if record.file_stage != stage:
            raise NotFound("File not found.")
        return record

    async def delete(
        self, submission: Submission, access: Access, stage: str, file_id: int, user: User
    ) -> None:
        record = await self.get(submission, access, stage, file_id)
        if not (access.can_manage or record.uploaded_by_id == user.id):
            raise Forbidden("Only the person who added the file, or an editor, can remove it.")
        _check_open(submission, stage)
        await self.files.delete(record)
