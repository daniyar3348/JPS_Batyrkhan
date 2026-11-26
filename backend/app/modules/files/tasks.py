from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.jobs import JobContext, periodic, task
from app.modules.files.service import DELETE_OBJECTS, PROCESS_REVISION, FileService

CLEANUP_ABANDONED = "files.cleanup_abandoned"


async def give_up_revision(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    async with ctx.session_factory() as db, db.begin():
        await FileService(db, ctx.storage).give_up_revision(int(payload["revision_id"]))


@task(PROCESS_REVISION, on_give_up=give_up_revision)
async def process_revision(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await FileService(db, ctx.storage).process_revision(int(payload["revision_id"]))


@task(DELETE_OBJECTS, max_attempts=10)
async def delete_objects(ctx: JobContext, payload: dict[str, Any]) -> None:
    for key in payload["keys"]:
        await ctx.storage.delete(key)


@task(CLEANUP_ABANDONED)
async def cleanup_abandoned(ctx: JobContext, payload: dict[str, Any]) -> None:
    async with ctx.session_factory() as db, db.begin():
        await FileService(db, ctx.storage).delete_abandoned_uploads()


periodic(CLEANUP_ABANDONED, every=timedelta(hours=6))
