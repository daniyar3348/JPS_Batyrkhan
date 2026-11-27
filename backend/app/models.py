"""Import every model so ``Base.metadata`` describes the whole schema (used by Alembic and tests)."""

from app.core.db import Base
from app.core.jobs import Job, PeriodicRun
from app.modules.audit.models import AuditEvent
from app.modules.files.models import FileRevision, SubmissionFile
from app.modules.identity.models import AuthSession, Consent, User, UserToken
from app.modules.journals.models import EmailTemplate, Journal, Section, SectionEditor, UserRole
from app.modules.notifications.models import EmailLog
from app.modules.payments.models import (
    Invoice,
    InvoiceCounter,
    InvoiceReminder,
    Payment,
    ProviderEvent,
    Refund,
    WaiverRequest,
)
from app.modules.review.models import ReviewAssignment, ReviewForm, ReviewReminder, ReviewRound
from app.modules.similarity.models import SimilarityCheck
from app.modules.submissions.models import (
    Contributor,
    Participant,
    Publication,
    Submission,
    SubmissionCounter,
)
from app.modules.workflow.models import (
    Discussion,
    DiscussionMessage,
    DiscussionParticipant,
    EditorialDecision,
)

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Base",
    "Consent",
    "Contributor",
    "Discussion",
    "DiscussionMessage",
    "DiscussionParticipant",
    "EditorialDecision",
    "EmailLog",
    "EmailTemplate",
    "FileRevision",
    "Invoice",
    "InvoiceCounter",
    "InvoiceReminder",
    "Job",
    "Journal",
    "Participant",
    "Payment",
    "PeriodicRun",
    "ProviderEvent",
    "Publication",
    "Refund",
    "ReviewAssignment",
    "ReviewForm",
    "ReviewReminder",
    "ReviewRound",
    "Section",
    "SectionEditor",
    "SimilarityCheck",
    "Submission",
    "SubmissionCounter",
    "SubmissionFile",
    "User",
    "UserRole",
    "UserToken",
    "WaiverRequest",
]
