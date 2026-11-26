from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import client_ip_var
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.audit.models import AuditEvent


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        action: str,
        entity_type: str,
        entity_id: int | None,
        *,
        actor_id: int | None,
        journal_id: int | None,
        data: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            journal_id=journal_id,
            data=data or {},
            ip=client_ip_var.get(),
        )
        self.db.add(event)
        return event

    async def list(
        self,
        *,
        journal_id: int,
        entity_type: str | None,
        entity_id: int | None,
        actor_id: int | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[AuditEvent], str | None]:
        query = select(AuditEvent).where(AuditEvent.journal_id == journal_id)
        if entity_type:
            query = query.where(AuditEvent.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == entity_id)
        if actor_id is not None:
            query = query.where(AuditEvent.actor_id == actor_id)
        if cursor:
            (last_id,) = decode_cursor(cursor, size=1)
            query = query.where(AuditEvent.id < int(last_id))
        rows = (await self.db.scalars(query.order_by(AuditEvent.id.desc()).limit(limit + 1))).all()
        next_cursor = encode_cursor([rows[limit - 1].id]) if len(rows) > limit else None
        return rows[:limit], next_cursor
