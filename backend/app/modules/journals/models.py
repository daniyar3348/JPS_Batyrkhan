from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow
from app.modules.identity.models import User


class Journal(TimestampMixin, Base):
    __tablename__ = "journals"

    id: Mapped[int] = id_column()
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    abbreviation: Mapped[str] = mapped_column(String(50), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    publisher: Mapped[str] = mapped_column(String(300), default="", server_default="")
    issn_print: Mapped[str | None] = mapped_column(String(9))
    issn_online: Mapped[str | None] = mapped_column(String(9))
    contact_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    contact_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    # Raise this when the privacy policy changes; consents record the version the user accepted.
    privacy_policy_version: Mapped[str] = mapped_column(String(20), default="1", server_default="1")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - optimistic locking on UPDATE


class Section(TimestampMixin, Base):
    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("journal_id", "abbreviation"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    abbreviation: Mapped[str] = mapped_column(String(20))
    policy: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Inactive sections stay visible on published articles but accept no new submissions.
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    editors: Mapped[list[User]] = relationship(
        secondary="section_editors", lazy="selectin", order_by=(User.family_name, User.given_name)
    )

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012 - optimistic locking on UPDATE


class SectionEditor(Base):
    __tablename__ = "section_editors"

    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("journal_id", "user_id", "role"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), index=True)
    granted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class EmailTemplate(Base):
    """The journal's own wording of an e-mail. Without a row the default wording is used."""

    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("journal_id", "key"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(60))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
