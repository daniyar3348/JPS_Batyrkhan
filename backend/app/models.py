"""Import every model so ``Base.metadata`` describes the whole schema (used by Alembic and tests)."""

from app.core.db import Base
from app.core.jobs import Job, PeriodicRun
from app.modules.audit.models import AuditEvent
from app.modules.identity.models import AuthSession, Consent, User, UserToken
from app.modules.journals.models import Journal, Section, SectionEditor, UserRole

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Base",
    "Consent",
    "Job",
    "Journal",
    "PeriodicRun",
    "Section",
    "SectionEditor",
    "User",
    "UserRole",
    "UserToken",
]
