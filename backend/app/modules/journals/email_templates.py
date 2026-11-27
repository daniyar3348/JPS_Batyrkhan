"""E-mail templates: defaults defined by each module, wording editable by the journal.

A module registers its templates when it is imported (see ``emails.py`` in the editorial modules).
Placeholders look like ``{recipientName}``. Every template can use the common ones below; a template
lists the extra ones it understands, and an administrator cannot save a placeholder that would never
be filled.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.core.errors import FieldError, NotFound, ValidationFailed
from app.modules.audit.service import AuditService
from app.modules.identity.models import User
from app.modules.journals.models import EmailTemplate, Journal

PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")

COMMON_VARIABLES: dict[str, str] = {
    "recipientName": "Full name of the person the e-mail is sent to",
    "journalName": "Name of the journal",
    "journalContact": "Name and e-mail address of the journal's contact person",
}


@dataclass(frozen=True)
class Rendered:
    subject: str
    body: str


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    group: str
    name: str
    description: str  # when the e-mail is sent
    recipient: str  # who receives it, for the settings page
    subject: str
    body: str
    variables: Mapping[str, str] = field(default_factory=dict)

    @property
    def all_variables(self) -> dict[str, str]:
        return {**COMMON_VARIABLES, **self.variables}


_REGISTRY: dict[str, TemplateSpec] = {}


def register(spec: TemplateSpec) -> TemplateSpec:
    existing = _REGISTRY.get(spec.key)
    if existing is not None and existing != spec:
        raise RuntimeError(f"E-mail template {spec.key!r} is already registered")
    unknown = unknown_placeholders(spec.subject + spec.body, spec)
    if unknown:
        raise RuntimeError(f"Template {spec.key!r} uses undeclared placeholders: {', '.join(unknown)}")
    _REGISTRY[spec.key] = spec
    return spec


def registered() -> list[TemplateSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.group, s.name))


def get_spec(key: str) -> TemplateSpec:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise NotFound("E-mail template not found.") from None


def unknown_placeholders(text: str, spec: TemplateSpec) -> list[str]:
    allowed = spec.all_variables
    return sorted({name for name in PLACEHOLDER.findall(text) if name not in allowed})


def fill(text: str, values: Mapping[str, str]) -> str:
    """Replace known placeholders; anything else is left exactly as written."""
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def common_values(journal: Journal, recipient_name: str) -> dict[str, str]:
    contact = journal.contact_name or journal.name
    if journal.contact_email:
        contact = f"{contact} <{journal.contact_email}>"
    return {"recipientName": recipient_name, "journalName": journal.name, "journalContact": contact}


class EmailTemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.audit = AuditService(db)

    async def _override(self, journal_id: int, key: str) -> EmailTemplate | None:
        return await self.db.scalar(
            select(EmailTemplate).where(EmailTemplate.journal_id == journal_id, EmailTemplate.key == key)
        )

    async def wording(self, journal: Journal, key: str) -> tuple[str, str]:
        spec = get_spec(key)
        override = await self._override(journal.id, key)
        if override is None:
            return spec.subject, spec.body
        return override.subject, override.body

    async def render(
        self, journal: Journal, key: str, *, recipient_name: str, values: Mapping[str, str]
    ) -> Rendered:
        subject, body = await self.wording(journal, key)
        context = {**common_values(journal, recipient_name), **values}
        return Rendered(subject=fill(subject, context).strip(), body=fill(body, context).strip() + "\n")

    async def list(self, journal: Journal) -> list[tuple[TemplateSpec, EmailTemplate | None]]:
        overrides = {
            t.key: t
            for t in (
                await self.db.scalars(select(EmailTemplate).where(EmailTemplate.journal_id == journal.id))
            ).all()
        }
        return [(spec, overrides.get(spec.key)) for spec in registered()]

    async def update(
        self, journal: Journal, key: str, *, subject: str, body: str, actor: User
    ) -> tuple[TemplateSpec, EmailTemplate | None]:
        spec = get_spec(key)
        errors: Sequence[FieldError] = [
            FieldError(
                field=name, message=f"Unknown placeholder: {', '.join('{' + u + '}' for u in unknown)}"
            )
            for name, unknown in (
                ("subject", unknown_placeholders(subject, spec)),
                ("body", unknown_placeholders(body, spec)),
            )
            if unknown
        ]
        if errors:
            raise ValidationFailed(
                "The template uses placeholders this e-mail does not have.",
                code="unknown_placeholder",
                errors=list(errors),
            )
        override = await self._override(journal.id, key)
        if subject == spec.subject and body == spec.body:
            # Saving the default wording is the same as resetting it.
            if override is not None:
                await self.db.delete(override)
            override = None
        elif override is None:
            override = EmailTemplate(
                journal_id=journal.id, key=key, subject=subject, body=body, updated_by_id=actor.id
            )
            self.db.add(override)
        else:
            override.subject = subject
            override.body = body
            override.updated_by_id = actor.id
            override.updated_at = utcnow()
        await self.db.flush()
        await self.audit.record(
            "journal.email_template_updated",
            "journal",
            journal.id,
            actor_id=actor.id,
            journal_id=journal.id,
            data={"template": key},
        )
        return spec, override

    async def reset(self, journal: Journal, key: str, *, actor: User) -> TemplateSpec:
        spec = get_spec(key)
        override = await self._override(journal.id, key)
        if override is not None:
            await self.db.delete(override)
            await self.db.flush()
            await self.audit.record(
                "journal.email_template_reset",
                "journal",
                journal.id,
                actor_id=actor.id,
                journal_id=journal.id,
                data={"template": key},
            )
        return spec


def last_changed(override: EmailTemplate | None) -> datetime | None:
    return override.updated_at if override is not None else None
