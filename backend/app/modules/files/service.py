"""Uploading, checking and serving submission files.

Upload in three steps, so file contents never pass through the API:
1. ``request_upload`` creates the file record and returns a signed upload URL;
2. the browser sends the file straight to storage;
3. ``complete_upload`` confirms it arrived; the worker then checks the contents (``process_revision``).

Callers are responsible for permission checks: this module only knows submission ids.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.core.errors import Conflict, FieldError, NotFound, ValidationFailed
from app.core.jobs import enqueue
from app.core.storage import PresignedUpload, Storage
from app.modules.files.models import FileRevision, FileStatus, SubmissionFile
from app.modules.files.types import ALLOWED_EXTENSIONS, FILE_TYPES, Genre, content_problem, extension_of

logger = logging.getLogger(__name__)

PROCESS_REVISION = "files.process_revision"
DELETE_OBJECTS = "files.delete_objects"
PENDING_UPLOAD_TTL = timedelta(days=1)


def clean_file_name(name: str) -> str:
    # Browsers may send a full path; keep the last component and drop control characters.
    base = PurePath(name.replace("\\", "/")).name
    cleaned = "".join(char for char in base if char.isprintable()).strip()
    return cleaned[:200]


class FileService:
    def __init__(self, db: AsyncSession, storage: Storage) -> None:
        self.db = db
        self.storage = storage

    async def request_upload(
        self,
        *,
        journal_id: int,
        submission_id: int,
        genre: Genre,
        file_name: str,
        size: int,
        max_size_mb: int,
        uploaded_by_id: int,
        file_stage: str = "submission",
    ) -> tuple[SubmissionFile, PresignedUpload]:
        name = clean_file_name(file_name)
        extension = extension_of(name)
        allowed = ALLOWED_EXTENSIONS[genre]
        if extension not in allowed:
            raise ValidationFailed(
                f"This kind of file accepts: {', '.join(allowed)}.",
                code="file_type_not_allowed",
                errors=[FieldError(field="file_name", message=f"Allowed types: {', '.join(allowed)}")],
            )
        if size <= 0:
            raise ValidationFailed("The file is empty.", code="empty_file")
        if size > max_size_mb * 1024 * 1024:
            raise ValidationFailed(f"Files must be {max_size_mb} MB or smaller.", code="file_too_large")

        file_type = FILE_TYPES[extension]
        key = f"journals/{journal_id}/submissions/{submission_id}/{uuid.uuid4().hex}{extension}"
        record = SubmissionFile(
            submission_id=submission_id,
            file_stage=file_stage,
            genre=genre.value,
            name=name,
            uploaded_by_id=uploaded_by_id,
        )
        record.revisions = [
            FileRevision(
                storage_key=key,
                original_name=name,
                size_bytes=size,
                content_type=file_type.content_type,
                status=FileStatus.PENDING_UPLOAD,
                uploaded_by_id=uploaded_by_id,
            )
        ]
        self.db.add(record)
        await self.db.flush()
        return record, self.storage.presign_upload(key, content_type=file_type.content_type, size=size)

    async def complete_upload(self, submission_id: int, file_id: int) -> SubmissionFile:
        record = await self.get(submission_id, file_id)
        revision = record.current
        if revision.status != FileStatus.PENDING_UPLOAD:
            return record  # already confirmed; confirming twice is harmless
        stored = await self.storage.size(revision.storage_key)
        if stored is None:
            raise Conflict("The file has not arrived yet. Upload it again.", code="upload_missing")
        if stored != revision.size_bytes:
            raise Conflict("The uploaded file is incomplete. Upload it again.", code="upload_incomplete")
        revision.status = FileStatus.PROCESSING
        await enqueue(self.db, PROCESS_REVISION, {"revision_id": revision.id})
        await self.db.flush()
        return record

    async def process_revision(self, revision_id: int) -> None:
        """Worker step: checksum the stored file and check that its contents match its type."""
        revision = await self.db.get(FileRevision, revision_id)
        if revision is None or revision.status != FileStatus.PROCESSING:
            return
        digest = await self.storage.digest(revision.storage_key)
        problem = content_problem(digest.head, extension_of(revision.original_name))
        if digest.size != revision.size_bytes:
            problem = "The stored file does not match the uploaded one. Upload it again."
        revision.sha256 = digest.sha256
        revision.processed_at = utcnow()
        if problem:
            revision.status = FileStatus.REJECTED
            revision.rejection_reason = problem
            await enqueue(self.db, DELETE_OBJECTS, {"keys": [revision.storage_key]})
            logger.info("File rejected", extra={"revision_id": revision.id, "reason": problem})
        else:
            revision.status = FileStatus.READY

    async def give_up_revision(self, revision_id: int) -> None:
        """The worker could not read the stored file after every retry."""
        revision = await self.db.get(FileRevision, revision_id)
        if revision is None or revision.status != FileStatus.PROCESSING:
            return
        revision.status = FileStatus.REJECTED
        revision.rejection_reason = "We could not check this file. Remove it and upload it again."
        revision.processed_at = utcnow()
        logger.warning("File check gave up", extra={"revision_id": revision.id})

    async def list(self, submission_id: int, *, file_stage: str = "submission") -> Sequence[SubmissionFile]:
        return (
            await self.db.scalars(
                select(SubmissionFile)
                .where(SubmissionFile.submission_id == submission_id, SubmissionFile.file_stage == file_stage)
                .order_by(SubmissionFile.id)
            )
        ).all()

    async def get(self, submission_id: int, file_id: int) -> SubmissionFile:
        record = await self.db.scalar(
            select(SubmissionFile).where(
                SubmissionFile.id == file_id, SubmissionFile.submission_id == submission_id
            )
        )
        if record is None:
            raise NotFound("File not found.")
        return record

    async def update(
        self, record: SubmissionFile, *, genre: Genre | None, name: str | None
    ) -> SubmissionFile:
        if genre is not None:
            extension = extension_of(record.current.original_name)
            if extension not in ALLOWED_EXTENSIONS[genre]:
                raise ValidationFailed(
                    f"A {extension} file cannot be used as this kind of file.", code="file_type_not_allowed"
                )
            record.genre = genre.value
        if name is not None:
            cleaned = clean_file_name(name)
            if not cleaned:
                raise ValidationFailed("The file needs a name.", code="empty_name")
            record.name = cleaned
        await self.db.flush()
        return record

    async def delete(self, record: SubmissionFile) -> None:
        keys = [revision.storage_key for revision in record.revisions]
        await self.db.delete(record)
        # Objects are removed after the transaction commits, so a rollback never loses a file.
        await enqueue(self.db, DELETE_OBJECTS, {"keys": keys})
        await self.db.flush()

    async def delete_all(self, submission_id: int) -> None:
        for record in await self.list(submission_id):
            await self.delete(record)

    def download_url(self, record: SubmissionFile) -> str:
        revision = record.current
        if revision.status != FileStatus.READY:
            raise Conflict("This file is not available for download.", code="file_not_ready")
        return self.storage.presign_download(
            revision.storage_key, filename=record_download_name(record), content_type=revision.content_type
        )

    async def delete_abandoned_uploads(self) -> int:
        """Remove files whose upload was never completed."""
        records = (
            (
                await self.db.scalars(
                    select(SubmissionFile)
                    .join(FileRevision, FileRevision.submission_file_id == SubmissionFile.id)
                    .where(
                        FileRevision.status == FileStatus.PENDING_UPLOAD,
                        FileRevision.created_at < utcnow() - PENDING_UPLOAD_TTL,
                    )
                )
            )
            .unique()
            .all()
        )
        for record in records:
            await self.delete(record)
        return len(records)


def record_download_name(record: SubmissionFile) -> str:
    """The display name, with the original extension guaranteed."""
    extension = extension_of(record.current.original_name)
    return record.name if extension_of(record.name) == extension else f"{record.name}{extension}"
