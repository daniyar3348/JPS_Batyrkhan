"""DOIs of articles: made from the journal's prefix and suffix pattern."""

from __future__ import annotations

import re

from app.modules.journals.models import Journal
from app.modules.journals.publishing_settings import DoiSettings
from app.modules.submissions.models import Submission

_NUMBER = re.compile(r"-(\d{4})-(\d+)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9.\-_;()/]")


def make_doi(settings: DoiSettings, journal: Journal, submission: Submission) -> str:
    """E.g. prefix 10.12345, pattern {journal}.{year}.{number}, manuscript JRN-2026-0042 → 10.12345/jrn.2026.0042."""
    match = _NUMBER.search(submission.number or "")
    submitted = submission.submitted_at or submission.created_at
    year, number = (match.group(1), match.group(2)) if match else (str(submitted.year), str(submission.id))
    journal_code = _UNSAFE.sub("", (journal.abbreviation or journal.slug).lower().replace(" ", ""))
    suffix = (
        settings.suffix_pattern.replace("{journal}", journal_code or "journal")
        .replace("{year}", year)
        .replace("{number}", number)
        .replace("{id}", str(submission.id))
    )
    return f"{settings.prefix}/{suffix}"


def doi_url(doi: str | None) -> str | None:
    return f"https://doi.org/{doi}" if doi else None
