"""The read model of a published article: everything a reader, the site, Crossref or a harvester needs.

Built inside the transaction that publishes or changes the article, so it is never out of date.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, func, literal, literal_column
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.sql.elements import ColumnElement

from app.modules.files.service import record_download_name
from app.modules.journals.publishing_settings import PublishingSettings
from app.modules.publishing.doi import doi_url
from app.modules.publishing.models import Galley, Issue
from app.modules.submissions.models import Publication, Submission

ENGLISH: ColumnElement[Any] = literal_column("'english'::regconfig")


def slug_of(submission: Submission, publication: Publication) -> str:
    return publication.url_path or (submission.number or str(submission.id)).lower()


def references_of(text: str) -> list[str]:
    """One reference per line; numbering such as "1." or "[1]" is kept as written."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def issue_data(issue: Issue | None) -> dict[str, Any] | None:
    if issue is None:
        return None
    return {
        "id": issue.id,
        "volume": issue.volume,
        "number": issue.number,
        "year": issue.year,
        "title": issue.title,
        "label": issue.label,
        "published_at": issue.published_at.isoformat() if issue.published_at else None,
    }


def galley_data(galley: Galley) -> dict[str, Any]:
    revision = galley.revision or galley.file.current
    return {
        "id": galley.id,
        "label": galley.label,
        "file_name": record_download_name(galley.file),
        "content_type": revision.content_type,
        "size_bytes": revision.size_bytes,
    }


def build(
    *,
    settings: PublishingSettings,
    submission: Submission,
    versions: Sequence[Publication],
    galleys: dict[int, list[Galley]],
    issue: Issue | None,
    accepted_at: datetime | None,
) -> dict[str, Any]:
    """``versions``: the published versions, oldest first; the last one is what readers get."""
    current = versions[-1]
    first_published = versions[0].published_at
    if first_published is None or current.published_at is None:
        raise ValueError("Only published versions have a snapshot")
    slug = slug_of(submission, current)
    authors = [
        {
            "name": c.full_name,
            "given_name": c.given_name,
            "family_name": c.family_name,
            "affiliation": c.affiliation,
            "country": c.country,
            "orcid": c.orcid,
            "is_corresponding": c.is_corresponding,
        }
        for c in current.contributors
        if c.in_byline
    ]
    return {
        "id": submission.id,
        "slug": slug,
        "url": settings.article_url(slug),
        "doi": current.doi,
        "doi_url": doi_url(current.doi),
        "title": current.title,
        "subtitle": current.subtitle,
        "abstract": current.abstract,
        "keywords": list(current.keywords),
        "authors": authors,
        "section": {"id": submission.section.id, "title": submission.section.title},
        "issue": issue_data(issue),
        "pages": current.pages,
        "license_url": current.license_url,
        "copyright_holder": current.copyright_holder,
        "copyright_year": current.copyright_year,
        "references": references_of(current.references),
        "funding_statement": current.funding_statement,
        "competing_interests": current.competing_interests,
        "dates": {
            "submitted": submission.submitted_at.isoformat() if submission.submitted_at else None,
            "accepted": accepted_at.isoformat() if accepted_at else None,
            "published": first_published.isoformat(),
            "updated": current.published_at.isoformat() if current.version > 1 else None,
        },
        "version": current.version,
        "galleys": [galley_data(g) for g in galleys.get(current.id, [])],
        "versions": [
            {
                "version": v.version,
                "published_at": v.published_at.isoformat() if v.published_at else None,
                "note": v.version_note,
                "title": v.title,
                "galleys": [galley_data(g) for g in galleys.get(v.id, [])],
            }
            for v in versions
        ],
    }


def _weighted(text: str, weight: str) -> ColumnElement[Any]:
    return func.setweight(func.to_tsvector(ENGLISH, cast(literal(text), Text)), literal_column(f"'{weight}'"))


def search_vector(data: dict[str, Any]) -> ColumnElement[Any]:
    """Title first, then keywords and authors, then the abstract (PostgreSQL full-text weights A to C)."""
    people = " ".join(a["name"] for a in data["authors"])
    title = f"{data['title']} {data['subtitle']}"
    return (
        _weighted(title, "A")
        .op("||", return_type=TSVECTOR)(_weighted(" ".join(data["keywords"]) + " " + people, "B"))
        .op("||", return_type=TSVECTOR)(_weighted(data["abstract"], "C"))
    )


def search_query(q: str) -> ColumnElement[Any]:
    return func.websearch_to_tsquery(ENGLISH, cast(literal(q), Text))
