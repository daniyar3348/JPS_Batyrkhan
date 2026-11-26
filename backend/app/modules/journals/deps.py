from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings
from app.core.errors import Forbidden
from app.modules.identity.deps import CurrentAuth, get_current_auth
from app.modules.identity.models import AuthSession, User
from app.modules.journals.models import Journal
from app.modules.journals.permissions import Capability, Role, capabilities_for
from app.modules.journals.service import JournalService


@dataclass(frozen=True)
class Principal:
    """The signed-in user together with their roles in the current journal."""

    user: User
    session: AuthSession
    journal: Journal
    roles: frozenset[Role]
    capabilities: frozenset[Capability]

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities


def get_journal_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> JournalService:
    return JournalService(db, settings)


async def get_current_journal(service: JournalService = Depends(get_journal_service)) -> Journal:
    return await service.get_current()


async def get_principal(
    auth: CurrentAuth = Depends(get_current_auth),
    journal: Journal = Depends(get_current_journal),
    service: JournalService = Depends(get_journal_service),
) -> Principal:
    roles = await service.roles_of(journal.id, auth.user.id)
    return Principal(
        user=auth.user,
        session=auth.session,
        journal=journal,
        roles=roles,
        capabilities=capabilities_for(roles),
    )


def require(*capabilities: Capability) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not all(principal.can(capability) for capability in capabilities):
            raise Forbidden()
        return principal

    return dependency
