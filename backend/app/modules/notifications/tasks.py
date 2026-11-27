"""Worker tasks for notifications."""

from __future__ import annotations

from typing import Any

from sqlalchemy import update

from app.core.db import utcnow
from app.core.email import EmailMessage, get_email_backend
from app.core.jobs import JobContext, task
from app.modules.notifications.models import EmailLog, EmailStatus

SEND_EMAIL = "notifications.send_email"


async def _mark_failed(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    if payload.get("log_id") is None:
        return
    async with ctx.session_factory() as db, db.begin():
        await db.execute(
            update(EmailLog)
            .where(EmailLog.id == payload["log_id"])
            .values(status=EmailStatus.FAILED, error=error[:500])
        )


@task(SEND_EMAIL, max_attempts=8, on_give_up=_mark_failed)
async def send_email(ctx: JobContext, payload: dict[str, Any]) -> None:
    message = EmailMessage(
        to=payload["to"], subject=payload["subject"], text=payload["text"], html=payload.get("html")
    )
    await get_email_backend(ctx.settings).send(message)
    if payload.get("log_id") is not None:
        async with ctx.session_factory() as db, db.begin():
            await db.execute(
                update(EmailLog)
                .where(EmailLog.id == payload["log_id"])
                .values(status=EmailStatus.SENT, sent_at=utcnow(), error=None)
            )
