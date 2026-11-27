from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow


class FileStatus:
    PENDING_UPLOAD = "pending_upload"  # a signed upload link was issued
    PROCESSING = "processing"  # uploaded; the worker is checking it
    READY = "ready"
    REJECTED = "rejected"  # the contents did not pass the checks


class FileStage:
    """Where in the workflow a file belongs."""

    SUBMISSION = "submission"  # sent by the author with the manuscript
    REVIEW = "review"  # the copy reviewers of a round receive (author metadata removed)
    REVISION = "revision"  # revised files the author sends during a review round
    REVIEW_ATTACHMENT = "review_attachment"  # a reviewer's file sent with their review


class SubmissionFile(TimestampMixin, Base):
    """A file of a submission. Its contents are immutable revisions; the newest one is current."""

    __tablename__ = "submission_files"

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    # Where in the workflow the file belongs: see FileStage.
    file_stage: Mapped[str] = mapped_column(String(30), default="submission", server_default="submission")
    review_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_rounds.id", ondelete="CASCADE"), index=True
    )
    review_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_assignments.id", ondelete="CASCADE"), index=True
    )
    # For reviewers' copies: the file it was made from.
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("submission_files.id", ondelete="SET NULL"))
    genre: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(255))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    revisions: Mapped[list[FileRevision]] = relationship(
        back_populates="file", lazy="selectin", order_by="FileRevision.id", cascade="all, delete-orphan"
    )

    @property
    def current(self) -> FileRevision:
        return self.revisions[-1]


class FileRevision(Base):
    __tablename__ = "file_revisions"
    __table_args__ = (
        Index("ix_file_revisions_pending", "created_at", postgresql_where=text("status = 'pending_upload'")),
    )

    id: Mapped[int] = id_column()
    submission_file_id: Mapped[int] = mapped_column(
        ForeignKey("submission_files.id", ondelete="CASCADE"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(250), unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=FileStatus.PENDING_UPLOAD)
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    # For files shown to the other side of a blind review: whether author/reviewer names were removed
    # from the file's metadata. None when not attempted.
    metadata_removed: Mapped[bool | None]
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    processed_at: Mapped[datetime | None]

    file: Mapped[SubmissionFile] = relationship(back_populates="revisions", lazy="raise")
