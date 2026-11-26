"""Worker tasks for notifications."""

from __future__ import annotations

from typing import Any

from app.core.email import EmailMessage, get_email_backend
from app.core.jobs import JobContext, task

SEND_EMAIL = "notifications.send_email"


@task(SEND_EMAIL, max_attempts=8)
async def send_email(ctx: JobContext, payload: dict[str, Any]) -> None:
    message = EmailMessage(
        to=payload["to"], subject=payload["subject"], text=payload["text"], html=payload.get("html")
    )
    await get_email_backend(ctx.settings).send(message)
