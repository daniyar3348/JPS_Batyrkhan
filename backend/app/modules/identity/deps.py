from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import tokens_equal
from app.modules.identity.models import AuthSession, User
from app.modules.identity.service import IdentityService

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True)
class CurrentAuth:
    user: User
    session: AuthSession


def get_identity_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> IdentityService:
    return IdentityService(db, settings)


async def get_current_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
    service: IdentityService = Depends(get_identity_service),
) -> CurrentAuth:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise Unauthorized()
    resolved = await service.resolve_session(token)
    if resolved is None:
        raise Unauthorized("Your session has expired. Please sign in again.", code="session_expired")
    session, user = resolved
    if request.method not in SAFE_METHODS:
        # The cookie is sent automatically by the browser; this header is not, so forged cross-site requests fail.
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not tokens_equal(header, session.csrf_token):
            raise Forbidden("The request is missing a valid CSRF token. Reload the page.", code="csrf_failed")
    return CurrentAuth(user=user, session=session)
