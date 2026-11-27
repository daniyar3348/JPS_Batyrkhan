from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.content.models import Announcement, Page

# Addresses the site uses for its own pages; a page cannot take them.
RESERVED_SLUGS = frozenset(
    {
        "about",
        "announcements",
        "api",
        "articles",
        "current",
        "editorial-board",
        "feed",
        "issues",
        "login",
        "robots",
        "search",
        "sitemap",
        "submit",
    }
)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
Body = Annotated[str, StringConstraints(max_length=100_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PageIn(BaseModel):
    slug: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=80)]
    title: Title
    body: Body = ""
    position: int = Field(default=0, ge=0, le=10000)
    in_menu: bool = True
    is_published: bool = False

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError("Use lower-case letters, digits and hyphens, e.g. author-guidelines")
        if value in RESERVED_SLUGS:
            raise ValueError(f"“{value}” is used by the site itself; choose another address")
        return value


class PageOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    slug: str
    title: str
    body: str
    position: int
    in_menu: bool
    is_published: bool
    row_version: int
    updated_at: datetime

    @classmethod
    def of(cls, page: Page) -> Self:
        return cls(
            id=page.id,
            slug=page.slug,
            title=page.title,
            body=page.body,
            position=page.position,
            in_menu=page.in_menu,
            is_published=page.is_published,
            row_version=page.row_version,
            updated_at=page.updated_at,
        )


class AnnouncementIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    body: Body = ""
    # Publish now (true) or keep as a draft (false). Published announcements keep their date.
    published: bool = False


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    title: str
    summary: str
    body: str
    published_at: datetime | None
    row_version: int
    updated_at: datetime

    @classmethod
    def of(cls, item: Announcement) -> Self:
        return cls(
            id=item.id,
            title=item.title,
            summary=item.summary,
            body=item.body,
            published_at=item.published_at,
            row_version=item.row_version,
            updated_at=item.updated_at,
        )


# ---------------------------------------------------------------------------- public


class PublicPageLink(BaseModel):
    slug: str
    title: str
    in_menu: bool


class PublicPage(BaseModel):
    slug: str
    title: str
    body: str
    updated_at: datetime


class PublicAnnouncement(BaseModel):
    id: int
    title: str
    summary: str
    body: str
    published_at: datetime
