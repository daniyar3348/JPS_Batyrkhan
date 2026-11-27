from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, id_column, utcnow


class EmailStatus:
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EmailLog(Base):
    """A copy of an e-mail about a manuscript, so the editors can see what was sent to whom.

    Only correspondence about manuscripts is kept. Account e-mails (password resets, invitations)
    carry personal links and are never stored.
    """

    __tablename__ = "email_log"
    __table_args__ = (Index("ix_email_log_submission", "submission_id", "created_at"),)

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    template_key: Mapped[str | None] = mapped_column(String(60))
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    sent_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default=EmailStatus.QUEUED, server_default="queued")
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    sent_at: Mapped[datetime | None]
