from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, id_column, utcnow


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = id_column()
    # Always stored lower-case; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Empty for invited users until they accept the invitation and choose a password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    given_name: Mapped[str] = mapped_column(String(100))
    family_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    affiliation: Mapped[str] = mapped_column(String(300), default="", server_default="")
    country: Mapped[str | None] = mapped_column(String(2))
    orcid: Mapped[str | None] = mapped_column(String(19))
    biography: Mapped[str] = mapped_column(Text, default="", server_default="")
    interests: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list, server_default="{}")
    email_verified_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    last_login_at: Mapped[datetime | None]
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None]

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()


class AuthSession(Base):
    """Server-side login session. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = id_column()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class TokenKind:
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105 - a token kind, not a password
    INVITATION = "invitation"


class UserToken(Base):
    """Single-use token sent by e-mail (verification, password reset, invitation)."""

    __tablename__ = "user_tokens"
    __table_args__ = (Index("ix_user_tokens_user_id_kind", "user_id", "kind"),)

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class ConsentKind:
    PRIVACY_POLICY = "privacy_policy"
    # Kazakhstan's personal data law (art. 16) requires consent for transfer abroad: e-mail provider,
    # Crossref, similarity checking, editors and reviewers in other countries.
    CROSS_BORDER_TRANSFER = "cross_border_transfer"


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = id_column()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    version: Mapped[str] = mapped_column(String(20))
    given_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String(45))
