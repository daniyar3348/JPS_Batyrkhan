"""Worker tasks for publishing: DOIs, deposits with Crossref, and rebuilding the journal site's pages."""

from __future__ import annotations

from typing import Any

from app.core.jobs import JobContext, task
from app.core.site import REVALIDATE_SITE
from app.modules.publishing.revalidate import SiteNotifier
from app.modules.publishing.service import CHECK_DEPOSIT, DEPOSIT_DOI, PublishingService
from app.modules.workflow.service import RESERVE_DOI


@task(RESERVE_DOI)
async def reserve_doi(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PublishingService(db, ctx.settings, ctx.storage).reserve_doi(int(payload["submission_id"]))


async def give_up_deposit(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PublishingService(db, ctx.settings, ctx.storage).give_up_deposit(
            int(payload["deposit_id"]), error
        )


@task(DEPOSIT_DOI, max_attempts=8, on_give_up=give_up_deposit)
async def deposit_doi(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PublishingService(db, ctx.settings, ctx.storage).run_deposit(int(payload["deposit_id"]))


@task(CHECK_DEPOSIT, max_attempts=8, on_give_up=give_up_deposit)
async def check_deposit(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await PublishingService(db, ctx.settings, ctx.storage).check_deposit(int(payload["deposit_id"]))


@task(REVALIDATE_SITE, max_attempts=6)
async def revalidate_site(ctx: JobContext, payload: dict[str, Any]) -> None:
    await SiteNotifier(ctx.settings).revalidate(list(payload["paths"]))
