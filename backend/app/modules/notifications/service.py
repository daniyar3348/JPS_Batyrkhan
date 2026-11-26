"""Queue e-mails for delivery by the worker."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import enqueue
from app.modules.notifications.tasks import SEND_EMAIL


async def queue_email(db: AsyncSession, *, to: str, subject: str, text: str, html: str | None = None) -> None:
    """The e-mail is sent only if the current transaction commits."""
    await enqueue(db, SEND_EMAIL, {"to": to, "subject": subject, "text": text, "html": html})
