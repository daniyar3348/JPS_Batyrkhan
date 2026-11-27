"""Worker tasks for payments: captures, refunds, reminders, and the daily reconciliation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.jobs import JobContext, periodic, task
from app.modules.payments.service import CAPTURE, PROCESS_REFUND, PaymentService

SEND_REMINDERS = "payments.send_reminders"
RECONCILE = "payments.reconcile"


@task(CAPTURE)
async def capture(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PaymentService(db, ctx.settings).capture(int(payload["payment_id"]))


async def give_up_refund(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PaymentService(db, ctx.settings).give_up_refund(int(payload["refund_id"]), error)


@task(PROCESS_REFUND, max_attempts=6, on_give_up=give_up_refund)
async def process_refund(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PaymentService(db, ctx.settings).process_refund(int(payload["refund_id"]))


@task(SEND_REMINDERS)
async def send_reminders(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PaymentService(db, ctx.settings).send_reminders()


@task(RECONCILE)
async def reconcile(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PaymentService(db, ctx.settings).reconcile()


periodic(SEND_REMINDERS, every=timedelta(hours=6))
periodic(RECONCILE, every=timedelta(hours=24))
