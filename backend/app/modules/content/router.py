"""The public site's pages and announcements: editing them, and serving them to the site."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import etag_for, parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings
from app.modules.content.schemas import (
    AnnouncementIn,
    AnnouncementOut,
    PageIn,
    PageOut,
    PublicAnnouncement,
    PublicPage,
    PublicPageLink,
)
from app.modules.content.service import ContentService
from app.modules.journals.deps import Principal, get_current_journal, require
from app.modules.journals.models import Journal
from app.modules.journals.permissions import Capability

router = APIRouter(prefix="/site", tags=["site"])
public_router = APIRouter(tags=["public"])
MANAGE = require(Capability.SITE_MANAGE)


def get_content_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ContentService:
    return ContentService(db, settings)


# ---------------------------------------------------------------------- pages


@router.get("/pages")
async def list_pages(
    principal: Principal = Depends(MANAGE), service: ContentService = Depends(get_content_service)
) -> list[PageOut]:
    return [PageOut.of(page) for page in await service.pages(principal.journal)]


@router.post("/pages", status_code=201)
async def create_page(
    data: PageIn,
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> PageOut:
    page = await service.create_page(principal.journal, data, principal.user)
    await service.db.commit()
    return PageOut.of(page)


@router.get("/pages/{page_id}")
async def get_page(
    page_id: int,
    response: Response,
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> PageOut:
    page = await service.page(principal.journal, page_id)
    response.headers["ETag"] = etag_for(page.row_version)
    return PageOut.of(page)


@router.put("/pages/{page_id}")
async def update_page(
    page_id: int,
    data: PageIn,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> PageOut:
    """Replace the page. If-Match: its row_version."""
    page = await service.page(principal.journal, page_id)
    await service.update_page(
        principal.journal, page, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await service.db.commit()
    response.headers["ETag"] = etag_for(page.row_version)
    return PageOut.of(page)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: int,
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> Response:
    page = await service.page(principal.journal, page_id)
    await service.delete_page(principal.journal, page, principal.user)
    await service.db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------- announcements


@router.get("/announcements")
async def list_announcements(
    principal: Principal = Depends(MANAGE), service: ContentService = Depends(get_content_service)
) -> list[AnnouncementOut]:
    """Drafts first, then published announcements, newest first."""
    items = await service.announcements(principal.journal, published_only=False, limit=500)
    return [AnnouncementOut.of(item) for item in items]


@router.post("/announcements", status_code=201)
async def create_announcement(
    data: AnnouncementIn,
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> AnnouncementOut:
    item = await service.create_announcement(principal.journal, data, principal.user)
    await service.db.commit()
    return AnnouncementOut.of(item)


@router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    data: AnnouncementIn,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> AnnouncementOut:
    """Replace the announcement. If-Match: its row_version."""
    item = await service.announcement(principal.journal, announcement_id)
    await service.update_announcement(
        principal.journal, item, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await service.db.commit()
    return AnnouncementOut.of(item)


@router.delete("/announcements/{announcement_id}", status_code=204)
async def delete_announcement(
    announcement_id: int,
    principal: Principal = Depends(MANAGE),
    service: ContentService = Depends(get_content_service),
) -> Response:
    item = await service.announcement(principal.journal, announcement_id)
    await service.delete_announcement(principal.journal, item, principal.user)
    await service.db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------- public


def _cache(response: Response, settings: Settings) -> None:
    seconds = settings.public_cache_seconds
    response.headers["Cache-Control"] = (
        f"public, max-age={seconds}, s-maxage={seconds}, stale-while-revalidate={settings.public_stale_seconds}"
    )


@public_router.get("/pages")
async def list_public_pages(
    response: Response,
    journal: Journal = Depends(get_current_journal),
    service: ContentService = Depends(get_content_service),
) -> list[PublicPageLink]:
    """Published pages in menu order (pages outside the menu are linked from elsewhere)."""
    _cache(response, service.settings)
    return [
        PublicPageLink(slug=p.slug, title=p.title, in_menu=p.in_menu)
        for p in await service.pages(journal, published_only=True)
    ]


@public_router.get("/pages/{slug}")
async def get_public_page(
    slug: str,
    response: Response,
    journal: Journal = Depends(get_current_journal),
    service: ContentService = Depends(get_content_service),
) -> PublicPage:
    page = await service.published_page(journal, slug)
    _cache(response, service.settings)
    return PublicPage(slug=page.slug, title=page.title, body=page.body, updated_at=page.updated_at)


def _public(item: object) -> PublicAnnouncement:
    return PublicAnnouncement.model_validate(item, from_attributes=True)


@public_router.get("/announcements")
async def list_public_announcements(
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    journal: Journal = Depends(get_current_journal),
    service: ContentService = Depends(get_content_service),
) -> list[PublicAnnouncement]:
    """Published announcements, newest first."""
    _cache(response, service.settings)
    return [_public(item) for item in await service.announcements(journal, published_only=True, limit=limit)]


@public_router.get("/announcements/{announcement_id}")
async def get_public_announcement(
    announcement_id: int,
    response: Response,
    journal: Journal = Depends(get_current_journal),
    service: ContentService = Depends(get_content_service),
) -> PublicAnnouncement:
    item = await service.announcement(journal, announcement_id, published_only=True)
    _cache(response, service.settings)
    return _public(item)
