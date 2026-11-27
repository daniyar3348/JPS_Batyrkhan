"""Pages and announcements of the public site. Every change tells the site which pages to rebuild."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import ensure_version
from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import Conflict, NotFound
from app.core.site import EVERYTHING, request_revalidation
from app.modules.audit.service import AuditService
from app.modules.content.models import Announcement, Page
from app.modules.content.schemas import AnnouncementIn, PageIn
from app.modules.identity.models import User
from app.modules.journals.models import Journal

# Changing these changes the menu, which is on every page.
MENU_FIELDS = ("slug", "title", "position", "in_menu", "is_published")


class ContentService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ pages

    async def pages(self, journal: Journal, *, published_only: bool = False) -> Sequence[Page]:
        query = select(Page).where(Page.journal_id == journal.id)
        if published_only:
            query = query.where(Page.is_published)
        return (await self.db.scalars(query.order_by(Page.position, Page.title))).all()

    async def page(self, journal: Journal, page_id: int) -> Page:
        page = await self.db.scalar(select(Page).where(Page.id == page_id, Page.journal_id == journal.id))
        if page is None:
            raise NotFound("Page not found.")
        return page

    async def published_page(self, journal: Journal, slug: str) -> Page:
        page = await self.db.scalar(
            select(Page).where(Page.journal_id == journal.id, Page.slug == slug, Page.is_published)
        )
        if page is None:
            raise NotFound("Page not found.")
        return page

    async def _slug_free(self, journal: Journal, slug: str, page_id: int | None = None) -> None:
        query = select(Page.id).where(Page.journal_id == journal.id, Page.slug == slug)
        if page_id is not None:
            query = query.where(Page.id != page_id)
        if await self.db.scalar(query) is not None:
            raise Conflict("Another page already has this address.", code="slug_taken")

    async def create_page(self, journal: Journal, data: PageIn, actor: User) -> Page:
        await self._slug_free(journal, data.slug)
        page = Page(journal_id=journal.id, **data.model_dump())
        self.db.add(page)
        await self.db.flush()
        if page.is_published:
            await request_revalidation(self.db, self.settings, [EVERYTHING])
        await self.audit.record(
            "site.page_created",
            "page",
            page.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"slug": page.slug},
        )
        return page

    async def update_page(
        self, journal: Journal, page: Page, data: PageIn, *, expected_version: int, actor: User
    ) -> Page:
        ensure_version(page.row_version, expected_version)
        await self._slug_free(journal, data.slug, page.id)
        before = {field: getattr(page, field) for field in MENU_FIELDS}
        old_slug, was_published = page.slug, page.is_published
        for field, value in data.model_dump().items():
            setattr(page, field, value)
        await self.db.flush()
        if any(getattr(page, field) != value for field, value in before.items()):
            await request_revalidation(self.db, self.settings, [EVERYTHING])
        elif page.is_published or was_published:
            await request_revalidation(self.db, self.settings, [f"/{old_slug}", f"/{page.slug}"])
        await self.audit.record(
            "site.page_updated",
            "page",
            page.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"slug": page.slug},
        )
        return page

    async def delete_page(self, journal: Journal, page: Page, actor: User) -> None:
        published = page.is_published
        await self.db.delete(page)
        await self.db.flush()
        if published:
            await request_revalidation(self.db, self.settings, [EVERYTHING])
        await self.audit.record(
            "site.page_deleted",
            "page",
            page.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"slug": page.slug},
        )

    # ------------------------------------------------------------------ announcements

    async def announcements(
        self, journal: Journal, *, published_only: bool, limit: int = 100
    ) -> Sequence[Announcement]:
        query = select(Announcement).where(Announcement.journal_id == journal.id)
        if published_only:
            query = query.where(Announcement.published_at.is_not(None))
            query = query.order_by(Announcement.published_at.desc(), Announcement.id.desc())
        else:
            # Drafts first, then the published ones, newest first.
            query = query.order_by(Announcement.published_at.desc().nulls_first(), Announcement.id.desc())
        return (await self.db.scalars(query.limit(limit))).all()

    async def announcement(
        self, journal: Journal, announcement_id: int, *, published_only: bool = False
    ) -> Announcement:
        query = select(Announcement).where(
            Announcement.id == announcement_id, Announcement.journal_id == journal.id
        )
        if published_only:
            query = query.where(Announcement.published_at.is_not(None))
        item = await self.db.scalar(query)
        if item is None:
            raise NotFound("Announcement not found.")
        return item

    async def _announcement_changed(self, item: Announcement) -> None:
        await request_revalidation(
            self.db, self.settings, ["/", "/announcements", f"/announcements/{item.id}", "/feed.xml"]
        )

    async def create_announcement(self, journal: Journal, data: AnnouncementIn, actor: User) -> Announcement:
        item = Announcement(
            journal_id=journal.id,
            title=data.title,
            summary=data.summary,
            body=data.body,
            published_at=utcnow() if data.published else None,
            created_by_id=actor.id,
        )
        self.db.add(item)
        await self.db.flush()
        if item.published_at is not None:
            await self._announcement_changed(item)
        await self.audit.record(
            "site.announcement_created", "announcement", item.id, actor_id=actor.id, journal_id=journal.id
        )
        return item

    async def update_announcement(
        self,
        journal: Journal,
        item: Announcement,
        data: AnnouncementIn,
        *,
        expected_version: int,
        actor: User,
    ) -> Announcement:
        ensure_version(item.row_version, expected_version)
        was_published = item.published_at is not None
        item.title, item.summary, item.body = data.title, data.summary, data.body
        if data.published and item.published_at is None:
            item.published_at = utcnow()
        elif not data.published:
            item.published_at = None
        await self.db.flush()
        if was_published or item.published_at is not None:
            await self._announcement_changed(item)
        await self.audit.record(
            "site.announcement_updated", "announcement", item.id, actor_id=actor.id, journal_id=journal.id
        )
        return item

    async def delete_announcement(self, journal: Journal, item: Announcement, actor: User) -> None:
        was_published = item.published_at is not None
        await self.db.delete(item)
        await self.db.flush()
        if was_published:
            await self._announcement_changed(item)
        await self.audit.record(
            "site.announcement_deleted", "announcement", item.id, actor_id=actor.id, journal_id=journal.id
        )
