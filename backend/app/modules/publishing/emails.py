"""E-mails about publication."""

from __future__ import annotations

from app.modules.journals.email_templates import TemplateSpec, register

ARTICLE_PUBLISHED = register(
    TemplateSpec(
        key="article_published",
        group="Publication",
        name="Article published",
        description="Sent to the authors when their article is published.",
        recipient="Authors",
        subject="“{submissionTitle}” has been published",
        body=(
            "Dear {recipientName},\n\n"
            "Your article “{submissionTitle}” has been published in {journalName}{issueNote}.\n\n"
            "{articleLink}\n\n"
            "Thank you for publishing with us.\n\n{journalName}"
        ),
        variables={
            "submissionNumber": "Manuscript number",
            "submissionTitle": "Title of the article",
            "submissionUrl": "Link to the manuscript in the editorial workspace",
            "issueNote": "The issue, e.g. “, Vol. 2 No. 1 (2026)”; empty without one",
            "articleLink": "The article's DOI link, or its address on the journal's site",
        },
    )
)
