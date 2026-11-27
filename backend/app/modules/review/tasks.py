"""Hourly reminders to reviewers.

Which reminders are due is worked out from the journal's settings and each request's dates. A
reminder is recorded before its e-mail is queued, in the same transaction, under a unique key
(request, kind, day offset, due date): running the job twice, or in two workers, never sends the
same reminder twice. If several reminders became due at once (the worker was down), only the
latest one is sent.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.jobs import JobContext, periodic, task
from app.core.storage import Storage
from app.modules.journals.models import Journal
from app.modules.journals.review_settings import review_settings
from app.modules.review.models import (
    OPEN_STATUSES,
    AssignmentStatus,
    ReviewAssignment,
    ReviewReminder,
    ReviewRound,
    RoundStatus,
)
from app.modules.review.service import ReviewService, today
from app.modules.submissions.models import Submission

logger = logging.getLogger(__name__)

SEND_REMINDERS = "review.send_reminders"


async def send_due_reminders(db: AsyncSession, settings: Settings, storage: Storage) -> int:
    service = ReviewService(db, settings, storage)
    rows = (
        await db.execute(
            select(ReviewAssignment, Journal)
            .join(ReviewRound, ReviewRound.id == ReviewAssignment.round_id)
            .join(Submission, Submission.id == ReviewAssignment.submission_id)
            .join(Journal, Journal.id == Submission.journal_id)
            .where(ReviewAssignment.status.in_(OPEN_STATUSES), ReviewRound.status != RoundStatus.CLOSED)
            .order_by(ReviewAssignment.id)
        )
    ).all()
    sent = 0
    now = today()
    for assignment, journal in rows:
        config = review_settings(journal)
        if not config.reminders_enabled:
            continue
        if assignment.status == AssignmentStatus.INVITED:
            kind, due, offsets = "response", assignment.response_due, config.response_reminder_days
        else:
            kind, due, offsets = "review", assignment.review_due, config.review_reminder_days
        reached = [offset for offset in offsets if now >= due + timedelta(days=offset)]
        if not reached:
            continue
        inserted = set(
            (
                await db.scalars(
                    insert(ReviewReminder)
                    .values(
                        [
                            {"assignment_id": assignment.id, "kind": kind, "offset_days": offset, "due": due}
                            for offset in reached
                        ]
                    )
                    .on_conflict_do_nothing()
                    .returning(ReviewReminder.offset_days)
                )
            ).all()
        )
        if max(reached) not in inserted:
            continue
        submission = await db.get(Submission, assignment.submission_id)
        if submission is None:
            continue
        email = await service.reminder_email(journal, submission, assignment, editor=None)
        await service.mailer.send_rendered(
            email, submission, to_email=assignment.reviewer.email, key=service.reminder_key(assignment)
        )
        sent += 1
    if sent:
        logger.info("Review reminders sent", extra={"count": sent})
    return sent


@task(SEND_REMINDERS)
async def send_reminders(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await send_due_reminders(db, ctx.settings, ctx.storage)


periodic(SEND_REMINDERS, every=timedelta(hours=1))
