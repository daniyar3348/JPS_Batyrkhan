"""Request-scoped dependencies shared by all modules."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Routers commit explicitly; anything not committed is rolled back."""
    async with request.app.state.session_factory() as session:
        yield session
