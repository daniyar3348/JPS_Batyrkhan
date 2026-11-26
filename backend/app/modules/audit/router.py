from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.pagination import Page, clamp_limit
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.identity.schemas import UserSummary
from app.modules.journals.deps import Principal, require
from app.modules.journals.permissions import Capability

router = APIRouter(tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int | None
    actor: UserSummary | None
    data: dict[str, Any]
    ip: str | None
    created_at: datetime


@router.get("/audit-events")
async def list_audit_events(
    entity_type: str | None = Query(default=None, max_length=50),
    entity_id: int | None = None,
    actor_id: int | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require(Capability.AUDIT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> Page[AuditEventOut]:
    events, next_cursor = await AuditService(db).list(
        journal_id=principal.journal.id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        cursor=cursor,
        limit=clamp_limit(limit),
    )
    actor_ids = {event.actor_id for event in events if event.actor_id is not None}
    actors = {user.id: user for user in (await db.scalars(select(User).where(User.id.in_(actor_ids)))).all()}
    return Page[AuditEventOut](
        items=[
            AuditEventOut(
                id=event.id,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                actor=UserSummary.of(actors[event.actor_id]) if event.actor_id in actors else None,
                data=event.data,
                ip=event.ip,
                created_at=event.created_at,
            )
            for event in events
        ],
        next_cursor=next_cursor,
    )
