"""Texts of the journal's public site: pages (aims and scope, policies, guidelines) and announcements."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, id_column


class Page(TimestampMixin, Base):
    __tablename__ = "site_pages"
    __table_args__ = (UniqueConstraint("journal_id", "slug"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    # The page's address on the site: /{slug}.
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    # Markdown. The site renders it without raw HTML.
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    in_menu: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_published: Mapped[bool] = mapped_column(default=False, server_default="false")
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012


class Announcement(TimestampMixin, Base):
    __tablename__ = "announcements"
    __table_args__ = (Index("ix_announcements_published", "journal_id", "published_at"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    # One or two sentences for lists and feeds.
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    body: Mapped[str] = mapped_column(Text, default="", server_default="")  # Markdown
    # None while it is a draft.
    published_at: Mapped[datetime | None]
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012
