"""Journal settings, sections, and membership (who has which role in the journal)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, exists, func, literal, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import ensure_version
from app.core.config import Settings
from app.core.db import escape_like
from app.core.errors import Conflict, FieldError, NotFound, ServiceUnavailable, ValidationFailed
from app.core.pagination import decode_cursor, encode_cursor
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.identity.schemas import RegisterIn
from app.modules.identity.service import IdentityService
from app.modules.journals.models import Journal, Section, SectionEditor, UserRole
from app.modules.journals.permissions import ROLE_LABELS, SECTION_EDITOR_ROLES, Role
from app.modules.journals.review_settings import ReviewSettings, review_settings
from app.modules.journals.schemas import InviteIn, JournalUpdate, SectionCreate, SectionUpdate
from app.modules.journals.submission_settings import SubmissionSettings, submission_settings


class JournalService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.audit = AuditService(db)
        self.identity = IdentityService(db, settings)

    # ------------------------------------------------------------------ journal

    async def get_by_slug(self, slug: str) -> Journal | None:
        return await self.db.scalar(select(Journal).where(Journal.slug == slug))

    async def get_current(self) -> Journal:
        journal = await self.get_by_slug(self.settings.journal_slug)
        if journal is None:
            raise ServiceUnavailable(
                "The journal is not set up yet. Run `python -m app.cli bootstrap`.",
                code="journal_not_configured",
            )
        return journal

    async def bootstrap(self, *, slug: str, name: str) -> tuple[Journal, bool]:
        """Create the journal if it does not exist. Returns the journal and whether it was created."""
        journal = await self.get_by_slug(slug)
        if journal is not None:
            return journal, False
        journal = Journal(slug=slug, name=name)
        self.db.add(journal)
        await self.db.flush()
        await self.audit.record(
            "journal.created", "journal", journal.id, actor_id=None, journal_id=journal.id
        )
        return journal, True

    async def update_journal(
        self, journal: Journal, data: JournalUpdate, *, expected_version: int, actor: User
    ) -> Journal:
        ensure_version(journal.version, expected_version)
        changed = {
            field: value
            for field, value in data.model_dump(exclude_unset=True).items()
            if getattr(journal, field) != value
        }
        if not changed:
            return journal
        for field, value in changed.items():
            setattr(journal, field, value)
        await self.db.flush()
        await self.audit.record(
            "journal.updated",
            "journal",
            journal.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"fields": sorted(changed)},
        )
        return journal

    async def update_submission_settings(
        self, journal: Journal, data: SubmissionSettings, *, expected_version: int, actor: User
    ) -> SubmissionSettings:
        before = submission_settings(journal)
        await self._save_settings(journal, "submission", before, data, expected_version, actor)
        return data

    async def update_review_settings(
        self, journal: Journal, data: ReviewSettings, *, expected_version: int, actor: User
    ) -> ReviewSettings:
        before = review_settings(journal)
        await self._save_settings(journal, "review", before, data, expected_version, actor)
        return data

    async def _save_settings(
        self,
        journal: Journal,
        name: str,
        before: SubmissionSettings | ReviewSettings,
        data: SubmissionSettings | ReviewSettings,
        expected_version: int,
        actor: User,
    ) -> None:
        """Replace one part of ``Journal.settings``, checking the version the client edited."""
        ensure_version(journal.version, expected_version)
        if data == before:
            return
        # Assign a new dict so SQLAlchemy notices the change to the JSON column.
        journal.settings = {**journal.settings, name: data.model_dump(mode="json")}
        await self.db.flush()
        changed = sorted(
            field for field in type(data).model_fields if getattr(data, field) != getattr(before, field)
        )
        await self.audit.record(
            f"journal.{name}_settings_updated",
            "journal",
            journal.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"fields": changed},
        )

    # ------------------------------------------------------------------ roles

    async def roles_of(self, journal_id: int, user_id: int) -> frozenset[Role]:
        rows = await self.db.scalars(
            select(UserRole.role).where(UserRole.journal_id == journal_id, UserRole.user_id == user_id)
        )
        return frozenset(Role(role) for role in rows)

    async def users_with_role(self, journal_id: int, role: Role) -> Sequence[User]:
        """Active users who hold a role, for example to notify every editor-in-chief."""
        return (
            await self.db.scalars(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(
                    UserRole.journal_id == journal_id, UserRole.role == role.value, User.is_active.is_(True)
                )
                .order_by(User.id)
            )
        ).all()

    async def roles_by_user(self, journal_id: int, user_ids: Sequence[int]) -> dict[int, list[Role]]:
        result: dict[int, list[Role]] = {user_id: [] for user_id in user_ids}
        if not user_ids:
            return result
        rows = await self.db.execute(
            select(UserRole.user_id, UserRole.role).where(
                UserRole.journal_id == journal_id, UserRole.user_id.in_(user_ids)
            )
        )
        for user_id, role in rows:
            result[user_id].append(Role(role))
        return result

    async def set_roles(
        self, journal: Journal, user: User, roles: Iterable[Role], *, actor: User | None
    ) -> frozenset[Role]:
        new = frozenset(roles)
        current = await self.roles_of(journal.id, user.id)
        added, removed = new - current, current - new
        if not added and not removed:
            return current
        if Role.ADMIN in removed:
            await self._ensure_another_admin(journal, user)
        if removed:
            await self.db.execute(
                delete(UserRole).where(
                    UserRole.journal_id == journal.id,
                    UserRole.user_id == user.id,
                    UserRole.role.in_([role.value for role in removed]),
                )
            )
        for role in sorted(added):
            self.db.add(
                UserRole(
                    journal_id=journal.id,
                    user_id=user.id,
                    role=role.value,
                    granted_by_id=actor.id if actor else None,
                )
            )
        if not new & SECTION_EDITOR_ROLES:
            journal_sections = select(Section.id).where(Section.journal_id == journal.id)
            await self.db.execute(
                delete(SectionEditor).where(
                    SectionEditor.user_id == user.id, SectionEditor.section_id.in_(journal_sections)
                )
            )
        await self.db.flush()
        await self.audit.record(
            "user.roles_changed",
            "user",
            user.id,
            actor_id=actor.id if actor else None,
            journal_id=journal.id,
            data={"added": sorted(added), "removed": sorted(removed)},
        )
        return new

    async def _ensure_another_admin(self, journal: Journal, user: User) -> None:
        others = await self.db.scalar(
            select(func.count())
            .select_from(UserRole)
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.journal_id == journal.id,
                UserRole.role == Role.ADMIN.value,
                UserRole.user_id != user.id,
                User.is_active.is_(True),
            )
        )
        if not others:
            raise Conflict("The journal must keep at least one active administrator.", code="last_admin")

    # ------------------------------------------------------------------ membership

    async def register_member(self, journal: Journal, data: RegisterIn) -> User:
        """Self-registration: every new account is an author, and a reviewer if the person offers to review."""
        user = await self.identity.create_user(
            email=str(data.email),
            password=data.password,
            given_name=data.given_name,
            family_name=data.family_name,
            affiliation=data.affiliation,
            country=data.country,
            interests=data.interests,
        )
        await self.identity.record_consents(user, version=journal.privacy_policy_version)
        roles = [Role.AUTHOR, Role.REVIEWER] if data.wants_to_review else [Role.AUTHOR]
        for role in roles:
            self.db.add(UserRole(journal_id=journal.id, user_id=user.id, role=role.value))
        await self.identity.send_verification_email(user, journal_name=journal.name)
        await self.audit.record(
            "user.registered",
            "user",
            user.id,
            actor_id=user.id,
            journal_id=journal.id,
            data={"roles": sorted(roles)},
        )
        return user

    async def invite_member(self, journal: Journal, data: InviteIn, *, actor: User) -> User:
        user = await self.identity.create_user(
            email=str(data.email),
            password=None,
            given_name=data.given_name,
            family_name=data.family_name,
            affiliation=data.affiliation,
        )
        roles = frozenset(data.roles)
        for role in sorted(roles):
            self.db.add(
                UserRole(journal_id=journal.id, user_id=user.id, role=role.value, granted_by_id=actor.id)
            )
        await self.identity.send_invitation(
            user,
            journal_name=journal.name,
            inviter_name=actor.full_name,
            role_labels=[ROLE_LABELS[role] for role in sorted(roles)],
        )
        await self.audit.record(
            "user.invited",
            "user",
            user.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"roles": sorted(roles)},
        )
        return user

    async def get_member(self, journal: Journal, user_id: int) -> tuple[User, list[Role]]:
        user = await self.identity.get_user(user_id)
        return user, sorted(await self.roles_of(journal.id, user.id))

    async def list_members(
        self, journal: Journal, *, q: str | None, role: Role | None, cursor: str | None, limit: int
    ) -> tuple[list[tuple[User, list[Role]]], str | None]:
        family = func.lower(User.family_name)
        given = func.lower(User.given_name)
        query = select(User, family, given)
        if role is not None:
            query = query.where(
                exists().where(
                    UserRole.user_id == User.id,
                    UserRole.journal_id == journal.id,
                    UserRole.role == role.value,
                )
            )
        if q and q.strip():
            pattern = f"%{escape_like(q.strip().lower())}%"
            query = query.where(
                or_(
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.given_name + " " + User.family_name).like(pattern, escape="\\"),
                    func.lower(User.family_name + " " + User.given_name).like(pattern, escape="\\"),
                    func.lower(User.affiliation).like(pattern, escape="\\"),
                )
            )
        if cursor:
            last_family, last_given, last_id = decode_cursor(cursor, size=3)
            query = query.where(
                tuple_(family, given, User.id)
                > tuple_(literal(str(last_family)), literal(str(last_given)), literal(int(last_id)))
            )
        rows = (await self.db.execute(query.order_by(family, given, User.id).limit(limit + 1))).all()
        next_cursor = None
        if len(rows) > limit:
            last_user, last_family_value, last_given_value = rows[limit - 1]
            next_cursor = encode_cursor([last_family_value, last_given_value, last_user.id])
        users = [row[0] for row in rows[:limit]]
        roles = await self.roles_by_user(journal.id, [user.id for user in users])
        return [(user, sorted(roles[user.id])) for user in users], next_cursor

    async def set_active(self, journal: Journal, user: User, *, active: bool, actor: User) -> None:
        if user.is_active == active:
            return
        if not active:
            if user.id == actor.id:
                raise Conflict("You cannot deactivate your own account.", code="self_deactivation")
            if Role.ADMIN in await self.roles_of(journal.id, user.id):
                await self._ensure_another_admin(journal, user)
        await self.identity.set_active(user, active=active)
        await self.audit.record(
            "user.activated" if active else "user.deactivated",
            "user",
            user.id,
            actor_id=actor.id,
            journal_id=journal.id,
        )

    # ------------------------------------------------------------------ sections

    async def list_sections(self, journal: Journal, *, include_inactive: bool) -> Sequence[Section]:
        query = select(Section).where(Section.journal_id == journal.id)
        if not include_inactive:
            query = query.where(Section.is_active.is_(True))
        return (await self.db.scalars(query.order_by(Section.sort_order, Section.title, Section.id))).all()

    async def get_section(self, journal: Journal, section_id: int) -> Section:
        section = await self.db.scalar(
            select(Section).where(Section.id == section_id, Section.journal_id == journal.id)
        )
        if section is None:
            raise NotFound("Section not found.")
        return section

    async def create_section(self, journal: Journal, data: SectionCreate, *, actor: User) -> Section:
        await self._ensure_unique_abbreviation(journal, data.abbreviation, exclude_id=None)
        section = Section(journal_id=journal.id, **data.model_dump())
        section.editors = []
        self.db.add(section)
        await self._flush_section()
        await self.audit.record(
            "section.created",
            "section",
            section.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"title": section.title},
        )
        return section

    async def update_section(
        self, journal: Journal, section: Section, data: SectionUpdate, *, expected_version: int, actor: User
    ) -> Section:
        ensure_version(section.version, expected_version)
        changed = {
            field: value
            for field, value in data.model_dump(exclude_unset=True).items()
            if getattr(section, field) != value
        }
        if not changed:
            return section
        if "abbreviation" in changed:
            await self._ensure_unique_abbreviation(journal, changed["abbreviation"], exclude_id=section.id)
        for field, value in changed.items():
            setattr(section, field, value)
        await self._flush_section()
        await self.audit.record(
            "section.updated",
            "section",
            section.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"fields": sorted(changed)},
        )
        return section

    async def delete_section(self, journal: Journal, section: Section, *, actor: User) -> None:
        await self.db.delete(section)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # submissions reference the section (ON DELETE RESTRICT)
            raise Conflict(
                "This section has submissions and cannot be deleted. Close it to new submissions instead.",
                code="section_in_use",
            ) from exc
        await self.audit.record(
            "section.deleted",
            "section",
            section.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"title": section.title},
        )

    async def set_section_editors(
        self, journal: Journal, section: Section, user_ids: Sequence[int], *, actor: User
    ) -> Section:
        unique_ids = list(dict.fromkeys(user_ids))
        users = (
            (await self.db.scalars(select(User).where(User.id.in_(unique_ids)))).all() if unique_ids else []
        )
        if len(users) != len(unique_ids):
            raise ValidationFailed("Some of the selected users do not exist.", code="unknown_users")
        roles = await self.roles_by_user(journal.id, unique_ids)
        not_editors = [
            user for user in users if not set(roles[user.id]) & SECTION_EDITOR_ROLES or not user.is_active
        ]
        if not_editors:
            names = ", ".join(user.full_name for user in not_editors)
            raise ValidationFailed(
                f"Only active users with the Editor-in-chief or Section editor role can edit a section: {names}.",
                code="not_an_editor",
            )
        before = {user.id: user.full_name for user in section.editors}
        by_id = {user.id: user for user in users}
        section.editors = [by_id[user_id] for user_id in unique_ids]
        await self.db.flush()
        # Names as they were at the time, so the log stays readable even if accounts change later.
        await self.audit.record(
            "section.editors_changed",
            "section",
            section.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={
                "added": sorted(by_id[i].full_name for i in unique_ids if i not in before),
                "removed": sorted(name for i, name in before.items() if i not in by_id),
            },
        )
        return section

    async def _ensure_unique_abbreviation(
        self, journal: Journal, abbreviation: str, *, exclude_id: int | None
    ) -> None:
        query = select(Section.id).where(
            Section.journal_id == journal.id, func.lower(Section.abbreviation) == abbreviation.lower()
        )
        if exclude_id is not None:
            query = query.where(Section.id != exclude_id)
        if await self.db.scalar(query) is not None:
            raise ValidationFailed(
                "Another section already uses this abbreviation.",
                code="duplicate_abbreviation",
                errors=[FieldError(field="abbreviation", message="Already used by another section")],
            )

    async def _flush_section(self) -> None:
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise Conflict(
                "Another section already uses this abbreviation.", code="duplicate_abbreviation"
            ) from exc
