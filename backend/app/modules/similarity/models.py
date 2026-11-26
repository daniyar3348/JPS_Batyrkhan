from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, id_column, utcnow


class CheckStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SimilarityCheck(Base):
    """One run of a manuscript through the similarity (plagiarism) checking service."""

    __tablename__ = "similarity_checks"

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    file_revision_id: Mapped[int] = mapped_column(ForeignKey("file_revisions.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default=CheckStatus.QUEUED)
    external_id: Mapped[str | None] = mapped_column(String(200))
    score_percent: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(500))
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    completed_at: Mapped[datetime | None]
