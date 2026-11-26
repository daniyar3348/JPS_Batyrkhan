"""Sign-up, sign-in, sessions, the current user's profile, and e-mailed links."""

from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.deps import get_db, get_settings
from app.core.errors import TooManyRequests, Unauthorized
from app.modules.audit.service import AuditService
from app.modules.identity.deps import CurrentAuth, get_current_auth, get_identity_service
from app.modules.identity.models import AuthSession, TokenKind, User
from app.modules.identity.schemas import (
    ChangePasswordIn,
    EmailIn,
    LoginIn,
    PasswordResetConfirmIn,
    ProfileUpdate,
    RegisterIn,
    TokenIn,
    TokenInfoOut,
    UserOut,
)
from app.modules.identity.service import IdentityService
from app.modules.journals.deps import Principal, get_current_journal, get_journal_service, get_principal
from app.modules.journals.models import Journal
from app.modules.journals.permissions import capabilities_for
from app.modules.journals.schemas import MeOut
from app.modules.journals.service import JournalService

router = APIRouter(tags=["account"])


def _set_session_cookie(response: Response, settings: Settings, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max(0, int((expires_at - utcnow()).total_seconds())),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )


async def _me(journals: JournalService, journal: Journal, user: User, session: AuthSession) -> MeOut:
    roles = await journals.roles_of(journal.id, user.id)
    return MeOut(
        user=UserOut.of(user),
        roles=sorted(roles),
        capabilities=sorted(capabilities_for(roles)),
        csrf_token=session.csrf_token,
    )


async def _sign_in(
    response: Response,
    user: User,
    *,
    db: AsyncSession,
    settings: Settings,
    identity: IdentityService,
    journals: JournalService,
    journal: Journal,
) -> MeOut:
    session, token = await identity.create_session(user)
    await db.commit()
    _set_session_cookie(response, settings, token, session.expires_at)
    return await _me(journals, journal, user, session)


@router.post("/auth/register", status_code=201)
async def register(
    data: RegisterIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: IdentityService = Depends(get_identity_service),
    journals: JournalService = Depends(get_journal_service),
    journal: Journal = Depends(get_current_journal),
) -> MeOut:
    """Create an account (author, optionally reviewer) and sign in. A confirmation e-mail is sent."""
    user = await journals.register_member(journal, data)
    return await _sign_in(
        response, user, db=db, settings=settings, identity=identity, journals=journals, journal=journal
    )


@router.post("/auth/login")
async def login(
    data: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: IdentityService = Depends(get_identity_service),
    journals: JournalService = Depends(get_journal_service),
    journal: Journal = Depends(get_current_journal),
) -> MeOut:
    result = await identity.authenticate(data.email, data.password)
    if result.user is None:
        await db.commit()  # keep the failed-attempt counter
        if result.locked_until is not None:
            seconds = max(1, math.ceil((result.locked_until - utcnow()).total_seconds()))
            raise TooManyRequests(
                f"Too many failed attempts. Try again in {math.ceil(seconds / 60)} minutes or reset your password.",
                code="account_locked",
                headers={"Retry-After": str(seconds)},
            )
        raise Unauthorized("The e-mail address or password is incorrect.", code="invalid_credentials")
    return await _sign_in(
        response, result.user, db=db, settings=settings, identity=identity, journals=journals, journal=journal
    )


@router.post("/auth/logout", status_code=204)
async def logout(
    response: Response,
    auth: CurrentAuth = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: IdentityService = Depends(get_identity_service),
) -> None:
    await identity.revoke_session(auth.session.id)
    await db.commit()
    _clear_session_cookie(response, settings)


@router.post("/auth/verify-email")
async def verify_email(
    data: TokenIn,
    db: AsyncSession = Depends(get_db),
    identity: IdentityService = Depends(get_identity_service),
) -> UserOut:
    user = await identity.verify_email(data.token)
    await db.commit()
    return UserOut.of(user)


@router.post("/auth/password-reset", status_code=202)
async def request_password_reset(
    data: EmailIn,
    db: AsyncSession = Depends(get_db),
    identity: IdentityService = Depends(get_identity_service),
    journal: Journal = Depends(get_current_journal),
) -> None:
    """Send a reset link if the address belongs to an account. The response is the same either way."""
    await identity.request_password_reset(data.email, journal_name=journal.name)
    await db.commit()


@router.post("/auth/token-info")
async def describe_token(
    data: TokenIn, identity: IdentityService = Depends(get_identity_service)
) -> TokenInfoOut:
    """Check an e-mailed link before showing its form, without using it up."""
    kind, user = await identity.describe_token(data.token)
    return TokenInfoOut(kind=kind, email=user.email, full_name=user.full_name)


@router.post("/auth/password-reset/confirm")
async def confirm_password_reset(
    data: PasswordResetConfirmIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: IdentityService = Depends(get_identity_service),
    journals: JournalService = Depends(get_journal_service),
    journal: Journal = Depends(get_current_journal),
) -> MeOut:
    """Set a password from a reset or invitation link and sign in."""
    user, kind = await identity.complete_password_reset(
        data.token,
        data.password,
        accepted_consents=data.accept_privacy_policy and data.accept_cross_border_transfer,
        consent_version=journal.privacy_policy_version,
    )
    action = "user.invitation_accepted" if kind == TokenKind.INVITATION else "user.password_reset"
    await AuditService(db).record(action, "user", user.id, actor_id=user.id, journal_id=journal.id)
    return await _sign_in(
        response, user, db=db, settings=settings, identity=identity, journals=journals, journal=journal
    )


@router.get("/me")
async def get_me(principal: Principal = Depends(get_principal)) -> MeOut:
    return MeOut(
        user=UserOut.of(principal.user),
        roles=sorted(principal.roles),
        capabilities=sorted(principal.capabilities),
        csrf_token=principal.session.csrf_token,
    )


@router.patch("/me")
async def update_me(
    data: ProfileUpdate,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
    identity: IdentityService = Depends(get_identity_service),
) -> UserOut:
    user = await identity.update_profile(principal.user, data)
    await db.commit()
    return UserOut.of(user)


@router.post("/me/password", status_code=204)
async def change_password(
    data: ChangePasswordIn,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
    identity: IdentityService = Depends(get_identity_service),
) -> None:
    """Change the password and sign out every other session."""
    await identity.change_password(
        principal.user,
        current=data.current_password,
        new=data.new_password,
        keep_session_id=principal.session.id,
    )
    await AuditService(db).record(
        "user.password_changed",
        "user",
        principal.user.id,
        actor_id=principal.user.id,
        journal_id=principal.journal.id,
    )
    await db.commit()


@router.post("/me/email-verification", status_code=202)
async def resend_verification_email(
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
    identity: IdentityService = Depends(get_identity_service),
) -> None:
    await identity.resend_verification_email(principal.user, journal_name=principal.journal.name)
    await db.commit()
