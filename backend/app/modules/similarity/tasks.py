from __future__ import annotations

from typing import Any

from app.core.jobs import JobContext, task
from app.modules.similarity.service import POLL_CHECK, RUN_CHECK, SimilarityService


async def give_up(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    async with ctx.session_factory() as db, db.begin():
        await SimilarityService(db, ctx.settings, ctx.storage).give_up(int(payload["check_id"]))


@task(RUN_CHECK, on_give_up=give_up)
async def run_check(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await SimilarityService(db, ctx.settings, ctx.storage).run(int(payload["check_id"]))


@task(POLL_CHECK, on_give_up=give_up)
async def poll_check(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await SimilarityService(db, ctx.settings, ctx.storage).poll(
            int(payload["check_id"]), int(payload["attempt"])
        )
