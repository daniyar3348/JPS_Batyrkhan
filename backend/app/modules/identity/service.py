"""Accounts, passwords, login sessions and e-mailed one-time tokens.

This module knows nothing about journals; journal membership and roles live in ``app.modules.journals``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import client_ip_var, user_agent_var
from app.core.db import utcnow
from app.core.errors import BadRequest, Conflict, FieldError, NotFound, TooManyRequests, ValidationFailed
from app.core.security import hash_password, hash_token, new_token, password_needs_rehash, verify_password
from app.modules.identity import emails
from app.modules.identity.models import AuthSession, Consent, ConsentKind, TokenKind, User, UserToken
from app.modules.identity.schemas import ProfileUpdate
from app.modules.notifications.service import queue_email

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
RESEND_INTERVAL = timedelta(minutes=1)
INVALID_LINK = "This link is invalid or has expired. Request a new one."


@dataclass(frozen=True)
class LoginResult:
    user: User | None
    locked_until: datetime | None = None


class IdentityService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------ users

    async def get_user(self, user_id: int) -> User:
        user = await self.db.get(User, user_id)
        if user is None:
            raise NotFound("User not found.")
        return user

    async def get_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email.strip().lower()))

    async def create_user(
        self,
        *,
        email: str,
        password: str | None,
        given_name: str,
        family_name: str = "",
        affiliation: str = "",
        country: str | None = None,
        interests: list[str] | None = None,
        email_verified: bool = False,
    ) -> User:
        email = email.strip().lower()
        if await self.get_by_email(email) is not None:
            raise Conflict("An account with this e-mail address already exists.", code="email_taken")
        user = User(
            email=email,
            password_hash=hash_password(password) if password else None,
            given_name=given_name,
            family_name=family_name,
            affiliation=affiliation,
            country=country,
            interests=interests or [],
            email_verified_at=utcnow() if email_verified else None,
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # a concurrent registration with the same address
            raise Conflict("An account with this e-mail address already exists.", code="email_taken") from exc
        return user

    async def record_consents(self, user: User, *, version: str) -> None:
        ip = client_ip_var.get()
        for kind in (ConsentKind.PRIVACY_POLICY, ConsentKind.CROSS_BORDER_TRANSFER):
            self.db.add(Consent(user_id=user.id, kind=kind, version=version, ip=ip))

    async def update_profile(self, user: User, data: ProfileUpdate) -> User:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.db.flush()
        return user

    async def set_active(self, user: User, *, active: bool) -> None:
        user.is_active = active
        if not active:
            await self.revoke_user_sessions(user.id)
        await self.db.flush()

    # ------------------------------------------------------------------ login and sessions

    async def authenticate(self, email: str, password: str) -> LoginResult:
        """Check credentials. The caller must commit, so failed attempts are counted even when login fails."""
        user = await self.get_by_email(email)
        now = utcnow()
        if user is None or not user.is_active:
            verify_password(None, password)  # same cost as a real check
            return LoginResult(user=None)
        if user.locked_until and user.locked_until > now:
            return LoginResult(user=None, locked_until=user.locked_until)
        if not verify_password(user.password_hash, password):
            user.failed_login_count += 1
            if user.failed_login_count >= self.settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=self.settings.login_lockout_minutes)
                user.failed_login_count = 0
                return LoginResult(user=None, locked_until=user.locked_until)
            return LoginResult(user=None)
        user.failed_login_count = 0
        user.locked_until = None
        if user.password_hash and password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return LoginResult(user=user)

    async def create_session(self, user: User) -> tuple[AuthSession, str]:
        """Start a login session. Every way of signing in (password, registration, reset link) ends here."""
        token = new_token()
        now = utcnow()
        user.last_login_at = now
        session = AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            csrf_token=new_token(24),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=self.settings.session_absolute_days),
            ip=client_ip_var.get(),
            user_agent=user_agent_var.get(),
        )
        self.db.add(session)
        await self.db.flush()
        return session, token

    async def resolve_session(self, token: str) -> tuple[AuthSession, User] | None:
        row = (
            await self.db.execute(
                select(AuthSession, User)
                .join(User, User.id == AuthSession.user_id)
                .where(AuthSession.token_hash == hash_token(token))
            )
        ).first()
        if row is None:
            return None
        session, user = row
        now = utcnow()
        idle_limit = session.last_seen_at + timedelta(days=self.settings.session_idle_days)
        if not user.is_active or session.expires_at <= now or idle_limit <= now:
            return None
        if now - session.last_seen_at > SESSION_TOUCH_INTERVAL:
            # Sliding expiry, written at most every few minutes to keep reads cheap.
            await self.db.execute(
                update(AuthSession).where(AuthSession.id == session.id).values(last_seen_at=now)
            )
            await self.db.commit()
            session.last_seen_at = now
        return session, user

    async def revoke_session(self, session_id: int) -> None:
        await self.db.execute(delete(AuthSession).where(AuthSession.id == session_id))

    async def revoke_user_sessions(self, user_id: int, *, keep_session_id: int | None = None) -> None:
        query = delete(AuthSession).where(AuthSession.user_id == user_id)
        if keep_session_id is not None:
            query = query.where(AuthSession.id != keep_session_id)
        await self.db.execute(query)

    # ------------------------------------------------------------------ passwords

    async def change_password(self, user: User, *, current: str, new: str, keep_session_id: int) -> None:
        if not verify_password(user.password_hash, current):
            raise ValidationFailed(
                "The current password is incorrect.",
                code="wrong_password",
                errors=[FieldError(field="current_password", message="Incorrect password")],
            )
        user.password_hash = hash_password(new)
        await self.revoke_user_sessions(user.id, keep_session_id=keep_session_id)
        await self.db.flush()

    async def request_password_reset(self, email: str, *, journal_name: str) -> None:
        """Always succeeds from the caller's point of view, so it cannot be used to find out who has an account."""
        user = await self.get_by_email(email)
        if user is None or not user.is_active or await self._recently_issued(user, TokenKind.PASSWORD_RESET):
            return
        ttl = timedelta(minutes=self.settings.password_reset_ttl_minutes)
        token = await self._issue_token(user, TokenKind.PASSWORD_RESET, ttl)
        text = emails.password_reset(
            name=user.full_name,
            journal_name=journal_name,
            link=f"{self.settings.workspace_url}/reset-password?token={token}",
            minutes=self.settings.password_reset_ttl_minutes,
        )
        await queue_email(self.db, to=user.email, subject=text.subject, text=text.text)

    async def complete_password_reset(
        self, token: str, password: str, *, accepted_consents: bool, consent_version: str
    ) -> tuple[User, str]:
        """Set a new password from a reset or invitation link. Returns the user and the kind of token used."""
        record, user = await self._find_token(token, (TokenKind.PASSWORD_RESET, TokenKind.INVITATION))
        if record.kind == TokenKind.INVITATION:
            if not accepted_consents:
                raise ValidationFailed(
                    "Accept the privacy policy and the transfer of data abroad to activate your account.",
                    code="consent_required",
                )
            await self.record_consents(user, version=consent_version)
        record.used_at = utcnow()
        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        # Opening a link sent to the address proves the user controls it.
        user.email_verified_at = user.email_verified_at or utcnow()
        await self.revoke_user_sessions(user.id)
        await self.db.flush()
        return user, record.kind

    # ------------------------------------------------------------------ e-mail verification and invitations

    async def send_verification_email(self, user: User, *, journal_name: str) -> None:
        ttl = timedelta(hours=self.settings.email_verification_ttl_hours)
        token = await self._issue_token(user, TokenKind.EMAIL_VERIFICATION, ttl)
        text = emails.verification(
            name=user.full_name,
            journal_name=journal_name,
            link=f"{self.settings.workspace_url}/verify-email?token={token}",
            hours=self.settings.email_verification_ttl_hours,
        )
        await queue_email(self.db, to=user.email, subject=text.subject, text=text.text)

    async def resend_verification_email(self, user: User, *, journal_name: str) -> None:
        if user.email_verified_at is not None:
            raise Conflict("Your e-mail address is already confirmed.", code="already_verified")
        if await self._recently_issued(user, TokenKind.EMAIL_VERIFICATION):
            raise TooManyRequests("A confirmation e-mail was sent less than a minute ago.")
        await self.send_verification_email(user, journal_name=journal_name)

    async def verify_email(self, token: str) -> User:
        record, user = await self._find_token(token, (TokenKind.EMAIL_VERIFICATION,))
        record.used_at = utcnow()
        user.email_verified_at = user.email_verified_at or utcnow()
        await self.db.flush()
        return user

    async def send_invitation(
        self, user: User, *, journal_name: str, inviter_name: str, role_labels: list[str]
    ) -> None:
        ttl = timedelta(days=self.settings.invitation_ttl_days)
        token = await self._issue_token(user, TokenKind.INVITATION, ttl)
        text = emails.invitation(
            name=user.full_name,
            journal_name=journal_name,
            inviter=inviter_name,
            roles=role_labels,
            link=f"{self.settings.workspace_url}/accept-invitation?token={token}",
            days=self.settings.invitation_ttl_days,
        )
        await queue_email(self.db, to=user.email, subject=text.subject, text=text.text)

    async def describe_token(self, token: str) -> tuple[str, User]:
        """Validate a link without using it up, so the page can show who it is for."""
        record, user = await self._find_token(
            token, (TokenKind.PASSWORD_RESET, TokenKind.INVITATION, TokenKind.EMAIL_VERIFICATION), lock=False
        )
        return record.kind, user

    # ------------------------------------------------------------------ tokens

    async def _issue_token(self, user: User, kind: str, ttl: timedelta) -> str:
        now = utcnow()
        # Only the newest link of each kind works.
        await self.db.execute(
            update(UserToken)
            .where(UserToken.user_id == user.id, UserToken.kind == kind, UserToken.used_at.is_(None))
            .values(used_at=now)
        )
        token = new_token()
        self.db.add(
            UserToken(
                user_id=user.id, kind=kind, token_hash=hash_token(token), created_at=now, expires_at=now + ttl
            )
        )
        await self.db.flush()
        return token

    async def _find_token(
        self, token: str, kinds: Iterable[str], *, lock: bool = True
    ) -> tuple[UserToken, User]:
        query = (
            select(UserToken, User)
            .join(User, User.id == UserToken.user_id)
            .where(
                UserToken.token_hash == hash_token(token),
                UserToken.kind.in_(list(kinds)),
                UserToken.used_at.is_(None),
                UserToken.expires_at > utcnow(),
                User.is_active.is_(True),
            )
        )
        if lock:
            # Two simultaneous uses of the same link: the second waits and then finds it used.
            query = query.with_for_update(of=UserToken)
        row = (await self.db.execute(query)).first()
        if row is None:
            raise BadRequest(INVALID_LINK, code="invalid_token")
        record, user = row
        return record, user

    async def _recently_issued(self, user: User, kind: str) -> bool:
        latest = await self.db.scalar(
            select(UserToken.created_at)
            .where(UserToken.user_id == user.id, UserToken.kind == kind)
            .order_by(UserToken.created_at.desc())
            .limit(1)
        )
        return latest is not None and utcnow() - latest < RESEND_INTERVAL

    async def delete_expired(self) -> None:
        now = utcnow()
        await self.db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
        await self.db.execute(
            delete(AuthSession).where(
                AuthSession.last_seen_at < now - timedelta(days=self.settings.session_idle_days)
            )
        )
        await self.db.execute(delete(UserToken).where(UserToken.expires_at < now - timedelta(days=30)))
