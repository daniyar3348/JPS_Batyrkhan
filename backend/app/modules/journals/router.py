"""Journal settings, sections, and user administration; plus the public journal profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import etag_for, parse_if_match
from app.core.config import Settings
from app.core.deps import get_db, get_settings
from app.core.errors import Conflict, NotFound
from app.core.pagination import Page, clamp_limit
from app.modules.journals.deps import (
    Principal,
    get_current_journal,
    get_journal_service,
    get_principal,
    require,
)
from app.modules.journals.models import Journal
from app.modules.journals.permissions import ROLE_LABELS, Capability, Role
from app.modules.journals.schemas import (
    InviteIn,
    JournalOut,
    JournalUpdate,
    MemberOut,
    MemberUpdate,
    PublicJournalOut,
    PublicSectionOut,
    RolesIn,
    SectionCreate,
    SectionEditorsIn,
    SectionOut,
    SectionUpdate,
)
from app.modules.journals.service import JournalService
from app.modules.journals.submission_settings import (
    SubmissionSettings,
    SubmissionSettingsOut,
    submission_settings,
)

router = APIRouter()
public_router = APIRouter(tags=["public"])

PUBLIC_CACHE = "public, max-age=60, s-maxage=300, stale-while-revalidate=86400"


# ---------------------------------------------------------------------- journal settings


@router.get("/journal", tags=["journal"])
async def get_journal(response: Response, principal: Principal = Depends(get_principal)) -> JournalOut:
    response.headers["ETag"] = etag_for(principal.journal.version)
    return JournalOut.of(principal.journal)


@router.patch("/journal", tags=["journal"])
async def update_journal(
    data: JournalUpdate,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require(Capability.JOURNAL_SETTINGS_EDIT)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> JournalOut:
    journal = await service.update_journal(
        principal.journal, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await db.commit()
    response.headers["ETag"] = etag_for(journal.version)
    return JournalOut.of(journal)


# ---------------------------------------------------------------------- sections


@router.get("/journal/submission-settings", tags=["journal"])
async def get_submission_settings(
    response: Response,
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> SubmissionSettingsOut:
    """How the journal accepts manuscripts. Readable by every signed-in user (the wizard needs it)."""
    response.headers["ETag"] = etag_for(principal.journal.version)
    return SubmissionSettingsOut.of(submission_settings(principal.journal), principal.journal, settings)


@router.put("/journal/submission-settings", tags=["journal"])
async def update_submission_settings(
    data: SubmissionSettings,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require(Capability.JOURNAL_SETTINGS_EDIT)),
    service: JournalService = Depends(get_journal_service),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> SubmissionSettingsOut:
    if data.similarity.enabled and settings.similarity_provider == "disabled":
        raise Conflict(
            "Similarity checking is not set up on the server, so it cannot be turned on yet.",
            code="similarity_unavailable",
        )
    saved = await service.update_submission_settings(
        principal.journal, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await db.commit()
    response.headers["ETag"] = etag_for(principal.journal.version)
    return SubmissionSettingsOut.of(saved, principal.journal, settings)


@router.get("/sections", tags=["sections"])
async def list_sections(
    principal: Principal = Depends(get_principal), service: JournalService = Depends(get_journal_service)
) -> list[SectionOut]:
    """Administrators see every section; everyone else sees the active ones."""
    sections = await service.list_sections(
        principal.journal, include_inactive=principal.can(Capability.SECTIONS_MANAGE)
    )
    return [SectionOut.of(section) for section in sections]


@router.post("/sections", status_code=201, tags=["sections"])
async def create_section(
    data: SectionCreate,
    response: Response,
    principal: Principal = Depends(require(Capability.SECTIONS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> SectionOut:
    section = await service.create_section(principal.journal, data, actor=principal.user)
    await db.commit()
    response.headers["ETag"] = etag_for(section.version)
    return SectionOut.of(section)


@router.get("/sections/{section_id}", tags=["sections"])
async def get_section(
    section_id: int,
    response: Response,
    principal: Principal = Depends(get_principal),
    service: JournalService = Depends(get_journal_service),
) -> SectionOut:
    section = await service.get_section(principal.journal, section_id)
    if not section.is_active and not principal.can(Capability.SECTIONS_MANAGE):
        raise NotFound("Section not found.")
    response.headers["ETag"] = etag_for(section.version)
    return SectionOut.of(section)


@router.patch("/sections/{section_id}", tags=["sections"])
async def update_section(
    section_id: int,
    data: SectionUpdate,
    response: Response,
    if_match: str | None = Header(default=None),
    principal: Principal = Depends(require(Capability.SECTIONS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> SectionOut:
    section = await service.get_section(principal.journal, section_id)
    section = await service.update_section(
        principal.journal, section, data, expected_version=parse_if_match(if_match), actor=principal.user
    )
    await db.commit()
    response.headers["ETag"] = etag_for(section.version)
    return SectionOut.of(section)


@router.delete("/sections/{section_id}", status_code=204, tags=["sections"])
async def delete_section(
    section_id: int,
    principal: Principal = Depends(require(Capability.SECTIONS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    section = await service.get_section(principal.journal, section_id)
    await service.delete_section(principal.journal, section, actor=principal.user)
    await db.commit()


@router.put("/sections/{section_id}/editors", tags=["sections"])
async def set_section_editors(
    section_id: int,
    data: SectionEditorsIn,
    principal: Principal = Depends(require(Capability.SECTIONS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> SectionOut:
    section = await service.get_section(principal.journal, section_id)
    section = await service.set_section_editors(
        principal.journal, section, data.user_ids, actor=principal.user
    )
    await db.commit()
    return SectionOut.of(section)


# ---------------------------------------------------------------------- users and roles


@router.get("/users", tags=["users"])
async def list_users(
    q: str | None = Query(default=None, max_length=200, description="Search in name, e-mail and affiliation"),
    role: Role | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require(Capability.USERS_VIEW)),
    service: JournalService = Depends(get_journal_service),
) -> Page[MemberOut]:
    members, next_cursor = await service.list_members(
        principal.journal, q=q, role=role, cursor=cursor, limit=clamp_limit(limit)
    )
    return Page[MemberOut](
        items=[MemberOut.of(user, roles) for user, roles in members], next_cursor=next_cursor
    )


@router.post("/users", status_code=201, tags=["users"])
async def invite_user(
    data: InviteIn,
    principal: Principal = Depends(require(Capability.USERS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    """Create an account for someone (for example an editor) and e-mail them a link to set a password."""
    user = await service.invite_member(principal.journal, data, actor=principal.user)
    await db.commit()
    return MemberOut.of(user, sorted(set(data.roles)))


@router.get("/users/{user_id}", tags=["users"])
async def get_user(
    user_id: int,
    principal: Principal = Depends(require(Capability.USERS_VIEW)),
    service: JournalService = Depends(get_journal_service),
) -> MemberOut:
    user, roles = await service.get_member(principal.journal, user_id)
    return MemberOut.of(user, roles)


@router.put("/users/{user_id}/roles", tags=["users"])
async def set_user_roles(
    user_id: int,
    data: RolesIn,
    principal: Principal = Depends(require(Capability.USERS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    user, _ = await service.get_member(principal.journal, user_id)
    roles = await service.set_roles(principal.journal, user, data.roles, actor=principal.user)
    await db.commit()
    return MemberOut.of(user, sorted(roles))


@router.patch("/users/{user_id}", tags=["users"])
async def update_user(
    user_id: int,
    data: MemberUpdate,
    principal: Principal = Depends(require(Capability.USERS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    """Activate or deactivate an account. Deactivation signs the user out everywhere."""
    user, roles = await service.get_member(principal.journal, user_id)
    await service.set_active(principal.journal, user, active=data.is_active, actor=principal.user)
    await db.commit()
    return MemberOut.of(user, roles)


@router.post("/users/{user_id}/invitation", status_code=202, tags=["users"])
async def resend_invitation(
    user_id: int,
    principal: Principal = Depends(require(Capability.USERS_MANAGE)),
    service: JournalService = Depends(get_journal_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    user, roles = await service.get_member(principal.journal, user_id)
    if user.password_hash is not None:
        raise Conflict("This user has already set a password.", code="already_accepted")
    await service.identity.send_invitation(
        user,
        journal_name=principal.journal.name,
        inviter_name=principal.user.full_name,
        role_labels=[ROLE_LABELS[role] for role in roles],
    )
    await db.commit()


# ---------------------------------------------------------------------- public


@public_router.get("/journal")
async def get_public_journal(
    response: Response,
    journal: Journal = Depends(get_current_journal),
    service: JournalService = Depends(get_journal_service),
) -> PublicJournalOut:
    """Journal profile for the public website. Cacheable by CDNs."""
    sections = await service.list_sections(journal, include_inactive=False)
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return PublicJournalOut(
        name=journal.name,
        abbreviation=journal.abbreviation,
        description=journal.description,
        publisher=journal.publisher,
        issn_print=journal.issn_print,
        issn_online=journal.issn_online,
        contact_name=journal.contact_name,
        contact_email=journal.contact_email,
        sections=[
            PublicSectionOut(id=s.id, title=s.title, abbreviation=s.abbreviation, policy=s.policy)
            for s in sections
        ],
    )
