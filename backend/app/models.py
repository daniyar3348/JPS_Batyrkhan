"""Import every model so ``Base.metadata`` describes the whole schema (used by Alembic and tests)."""

from app.core.db import Base
from app.core.jobs import Job, PeriodicRun
from app.modules.audit.models import AuditEvent
from app.modules.files.models import FileRevision, SubmissionFile
from app.modules.identity.models import AuthSession, Consent, User, UserToken
from app.modules.journals.models import Journal, Section, SectionEditor, UserRole
from app.modules.similarity.models import SimilarityCheck
from app.modules.submissions.models import Contributor, Publication, Submission, SubmissionCounter

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Base",
    "Consent",
    "Contributor",
    "FileRevision",
    "Job",
    "Journal",
    "PeriodicRun",
    "Publication",
    "Section",
    "SectionEditor",
    "SimilarityCheck",
    "Submission",
    "SubmissionCounter",
    "SubmissionFile",
    "User",
    "UserRole",
    "UserToken",
]
