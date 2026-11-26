from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.jobs import JobContext, periodic, task
from app.modules.identity.service import IdentityService

CLEANUP = "identity.cleanup"


@task(CLEANUP)
async def cleanup(ctx: JobContext, payload: dict[str, Any]) -> None:
    """Remove expired sessions and long-expired one-time tokens."""
    async with ctx.session_factory() as db, db.begin():
        await IdentityService(db, ctx.settings).delete_expired()


periodic(CLEANUP, every=timedelta(hours=6))
