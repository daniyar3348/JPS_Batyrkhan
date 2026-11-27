"""Assembles the module routers into the three API surfaces."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.errors import Problem
from app.core.storage_routes import router as storage_router
from app.modules.audit.router import router as audit_router
from app.modules.identity.router import router as identity_router
from app.modules.journals.deps import get_current_journal
from app.modules.journals.models import Journal
from app.modules.journals.router import public_router as journals_public_router
from app.modules.journals.router import router as journals_router
from app.modules.review.router import router as review_router
from app.modules.submissions.router import router as submissions_router
from app.modules.workflow.router import router as workflow_router

_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "description": description}
    for status, description in {
        400: "Bad request",
        401: "Not signed in",
        403: "Not allowed",
        404: "Not found",
        409: "Conflict",
        412: "Changed by someone else",
        422: "Invalid input",
        428: "If-Match required",
        429: "Too many requests",
        503: "Journal not configured",
    }.items()
}


def build_router() -> APIRouter:
    root = APIRouter()

    workspace = APIRouter(prefix="/api/v1", responses=_ERRORS)
    workspace.include_router(identity_router)
    workspace.include_router(journals_router)
    workspace.include_router(audit_router)
    workspace.include_router(submissions_router)
    workspace.include_router(review_router)
    workspace.include_router(workflow_router)
    root.include_router(workspace)

    public = APIRouter(prefix="/public/v1", responses=_ERRORS)
    public.include_router(journals_public_router)
    root.include_router(public)

    root.include_router(_health_router())
    root.include_router(storage_router)
    return root


def _health_router() -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health")
    async def health() -> dict[str, str]:
        """The process is up."""
        return {"status": "ok"}

    @router.get("/ready", responses={503: {"model": Problem}})
    async def ready(
        db: AsyncSession = Depends(get_db), journal: Journal = Depends(get_current_journal)
    ) -> dict[str, str]:
        """The database is reachable and the journal is configured."""
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "journal": journal.slug}

    return router
