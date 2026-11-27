"""Queue e-mails for delivery by the worker, and keep a copy of correspondence about manuscripts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import enqueue
from app.modules.notifications.models import EmailLog
from app.modules.notifications.tasks import SEND_EMAIL

REDACTED = "[personal link removed]"


async def queue_email(
    db: AsyncSession,
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    submission_id: int | None = None,
    template_key: str | None = None,
    sent_by_id: int | None = None,
    redact: Iterable[str] = (),
) -> None:
    """The e-mail is sent only if the current transaction commits.

    With ``submission_id`` a copy goes to the manuscript's e-mail log. Values in ``redact`` (personal
    sign-in links) are replaced in that copy, so editors reading the log cannot use them.
    """
    payload: dict[str, object] = {"to": to, "subject": subject, "text": text, "html": html}
    if submission_id is not None:
        body = text
        for secret in redact:
            if secret:
                body = body.replace(secret, REDACTED)
        entry = EmailLog(
            submission_id=submission_id,
            template_key=template_key,
            recipient=to,
            subject=subject[:500],
            body=body,
            sent_by_id=sent_by_id,
        )
        db.add(entry)
        await db.flush()
        payload["log_id"] = entry.id
    await enqueue(db, SEND_EMAIL, payload)


async def email_log(db: AsyncSession, submission_id: int) -> Sequence[EmailLog]:
    return (
        await db.scalars(
            select(EmailLog)
            .where(EmailLog.submission_id == submission_id)
            .order_by(EmailLog.created_at.desc(), EmailLog.id.desc())
        )
    ).all()
