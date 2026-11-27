"""Send e-mails about a manuscript: rendered from the journal's templates and kept in its e-mail log."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.journals.email_templates import EmailTemplateService, Rendered
from app.modules.journals.models import Journal
from app.modules.notifications.service import queue_email
from app.modules.submissions.models import Submission


class Mailer:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.templates = EmailTemplateService(db)

    def submission_url(self, submission: Submission) -> str:
        return f"{self.settings.workspace_url}/submissions/{submission.id}"

    def manuscript_values(self, submission: Submission) -> dict[str, str]:
        """Values every e-mail about a manuscript can use. None of them reveals who the authors are."""
        return {
            "submissionNumber": submission.number or "",
            "submissionTitle": submission.publication.title,
            "submissionUrl": self.submission_url(submission),
            "sectionTitle": submission.section.title,
        }

    async def render(
        self,
        journal: Journal,
        key: str,
        submission: Submission,
        *,
        recipient_name: str,
        values: Mapping[str, str] | None = None,
    ) -> Rendered:
        return await self.templates.render(
            journal,
            key,
            recipient_name=recipient_name,
            values={**self.manuscript_values(submission), **(values or {})},
        )

    async def send(
        self,
        journal: Journal,
        key: str,
        submission: Submission,
        *,
        to_name: str,
        to_email: str,
        values: Mapping[str, str] | None = None,
        sent_by_id: int | None = None,
        redact: Iterable[str] = (),
    ) -> None:
        rendered = await self.render(journal, key, submission, recipient_name=to_name, values=values)
        await self.send_rendered(
            rendered, submission, to_email=to_email, key=key, sent_by_id=sent_by_id, redact=redact
        )

    async def send_rendered(
        self,
        rendered: Rendered,
        submission: Submission,
        *,
        to_email: str,
        key: str | None,
        sent_by_id: int | None = None,
        redact: Iterable[str] = (),
    ) -> None:
        """Send wording an editor may have changed; it is logged exactly as sent."""
        await queue_email(
            self.db,
            to=to_email,
            subject=rendered.subject,
            text=rendered.body,
            submission_id=submission.id,
            template_key=key,
            sent_by_id=sent_by_id,
            redact=redact,
        )
