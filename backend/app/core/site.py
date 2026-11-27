"""Telling the journal's public site that pages changed. Any module may ask; the worker sends the request.

The site rebuilds the listed paths (Next.js on-demand revalidation). ``EVERYTHING`` asks it to rebuild
every page, e.g. after the journal's name or its menu changed.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.jobs import enqueue

REVALIDATE_SITE = "publishing.revalidate_site"  # handled in app.modules.publishing.tasks
EVERYTHING = "*"


async def request_revalidation(db: AsyncSession, settings: Settings, paths: Iterable[str]) -> None:
    """Queue the request in the current transaction; nothing is queued while no site is configured."""
    unique = sorted(set(paths))
    if settings.site_revalidate_url and settings.site_revalidate_secret and unique:
        await enqueue(db, REVALIDATE_SITE, {"paths": unique})
