"""The public content API: published issues and articles for the journal's site and anyone else.

Reads only the read model (``published_articles``) and published issues. Responses may be cached by
nginx and CDNs; galley downloads redirect to short-lived signed links and are never cached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import get_db, get_settings, get_storage
from app.core.errors import NotFound
from app.core.pagination import Page, clamp_limit, decode_cursor, encode_cursor
from app.core.storage import Storage
from app.modules.files.models import FileStatus
from app.modules.files.service import record_download_name
from app.modules.journals.deps import get_current_journal
from app.modules.journals.models import Journal, Section
from app.modules.publishing.models import Galley, Issue, IssueStatus, PublishedArticle
from app.modules.publishing.snapshot import search_query
from app.modules.submissions.models import Publication, PublicationStatus

public_router = APIRouter(tags=["public"])


# ---------------------------------------------------------------------------- schemas


class PublicAuthor(BaseModel):
    name: str
    given_name: str
    family_name: str
    affiliation: str
    country: str | None
    orcid: str | None
    is_corresponding: bool


class PublicGalley(BaseModel):
    id: int
    label: str
    file_name: str
    content_type: str
    size_bytes: int
    # Relative to the API; redirects to the file.
    download_path: str


class PublicVersion(BaseModel):
    version: int
    published_at: datetime | None
    note: str
    title: str
    galleys: list[PublicGalley]


class PublicDates(BaseModel):
    submitted: datetime | None
    accepted: datetime | None
    published: datetime
    updated: datetime | None


class PublicSection(BaseModel):
    id: int
    title: str


class PublicIssueRef(BaseModel):
    id: int
    volume: int | None
    number: str | None
    year: int | None
    title: str
    label: str
    published_at: datetime | None


class PublicArticle(BaseModel):
    id: int
    slug: str
    url: str
    doi: str | None
    doi_url: str | None
    title: str
    subtitle: str
    abstract: str
    keywords: list[str]
    authors: list[PublicAuthor]
    section: PublicSection
    issue: PublicIssueRef | None
    pages: str
    license_url: str
    copyright_holder: str
    copyright_year: int | None
    references: list[str]
    funding_statement: str
    competing_interests: str
    dates: PublicDates
    version: int
    galleys: list[PublicGalley]
    versions: list[PublicVersion]

    @classmethod
    def of(cls, data: dict[str, Any]) -> Self:
        def galleys(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{**g, "download_path": f"/public/v1/galleys/{g['id']}/download"} for g in items]

        return cls.model_validate(
            {
                **data,
                "galleys": galleys(data["galleys"]),
                "versions": [{**v, "galleys": galleys(v["galleys"])} for v in data["versions"]],
            }
        )


class PublicArticleSummary(BaseModel):
    slug: str
    title: str
    subtitle: str
    authors: list[str]
    doi: str | None
    doi_url: str | None
    pages: str
    section: PublicSection
    issue: PublicIssueRef | None
    published_at: datetime
    abstract: str
    galleys: list[PublicGalley]

    @classmethod
    def of(cls, data: dict[str, Any]) -> Self:
        article = PublicArticle.of(data)
        return cls(
            slug=article.slug,
            title=article.title,
            subtitle=article.subtitle,
            authors=[a.name for a in article.authors],
            doi=article.doi,
            doi_url=article.doi_url,
            pages=article.pages,
            section=article.section,
            issue=article.issue,
            published_at=article.dates.published,
            abstract=article.abstract,
            galleys=article.galleys,
        )


class PublicIssue(BaseModel):
    id: int
    volume: int | None
    number: str | None
    year: int | None
    title: str
    description: str
    label: str
    is_current: bool
    published_at: datetime | None
    article_count: int

    @classmethod
    def of(cls, issue: Issue, article_count: int) -> Self:
        return cls(
            id=issue.id,
            volume=issue.volume,
            number=issue.number,
            year=issue.year,
            title=issue.title,
            description=issue.description,
            label=issue.label,
            is_current=issue.is_current,
            published_at=issue.published_at,
            article_count=article_count,
        )


class PublicIssueSection(BaseModel):
    section: PublicSection
    articles: list[PublicArticleSummary]


class PublicIssueDetail(PublicIssue):
    sections: list[PublicIssueSection]


class SearchResults(Page[PublicArticleSummary]):
    total: int


# ---------------------------------------------------------------------------- helpers


def _cache(response: Response, settings: Settings) -> None:
    seconds = settings.public_cache_seconds
    response.headers["Cache-Control"] = (
        f"public, max-age={seconds}, s-maxage={seconds}, stale-while-revalidate={settings.public_stale_seconds}"
    )


async def _counts(db: AsyncSession, issue_ids: list[int]) -> dict[int, int]:
    if not issue_ids:
        return {}
    rows = await db.execute(
        select(PublishedArticle.issue_id, func.count())
        .where(PublishedArticle.issue_id.in_(issue_ids))
        .group_by(PublishedArticle.issue_id)
    )
    return {issue_id: count for issue_id, count in rows if issue_id is not None}


async def _issue_detail(db: AsyncSession, issue: Issue) -> PublicIssueDetail:
    articles = (
        await db.scalars(
            select(PublishedArticle)
            .where(PublishedArticle.issue_id == issue.id)
            .order_by(PublishedArticle.position, PublishedArticle.id)
        )
    ).all()
    sections: list[PublicIssueSection] = []
    for article in articles:
        summary = PublicArticleSummary.of(article.data)
        if not sections or sections[-1].section.id != summary.section.id:
            sections.append(PublicIssueSection(section=summary.section, articles=[]))
        sections[-1].articles.append(summary)
    return PublicIssueDetail(**PublicIssue.of(issue, len(articles)).model_dump(), sections=sections)


def _published_issues(journal: Journal) -> Any:
    return select(Issue).where(Issue.journal_id == journal.id, Issue.status == IssueStatus.PUBLISHED)


# ---------------------------------------------------------------------------- issues


@public_router.get("/issues")
async def list_public_issues(
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[PublicIssue]:
    """The archive: every published issue, newest first."""
    issues = (
        await db.scalars(_published_issues(journal).order_by(Issue.published_at.desc(), Issue.id.desc()))
    ).all()
    counts = await _counts(db, [i.id for i in issues])
    _cache(response, settings)
    return [PublicIssue.of(issue, counts.get(issue.id, 0)) for issue in issues]


@public_router.get("/issues/current")
async def get_current_issue(
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicIssueDetail:
    issue = await db.scalar(_published_issues(journal).where(Issue.is_current))
    if issue is None:
        raise NotFound("The journal has not published an issue yet.")
    _cache(response, settings)
    return await _issue_detail(db, issue)


@public_router.get("/issues/{issue_id:int}")
async def get_public_issue(
    issue_id: int,
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicIssueDetail:
    issue = await db.scalar(_published_issues(journal).where(Issue.id == issue_id))
    if issue is None:
        raise NotFound("Issue not found.")
    _cache(response, settings)
    return await _issue_detail(db, issue)


@public_router.get("/issues/{volume:int}/{number}")
async def get_issue_by_number(
    volume: int,
    number: str,
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicIssueDetail:
    issue = await db.scalar(_published_issues(journal).where(Issue.volume == volume, Issue.number == number))
    if issue is None:
        raise NotFound("Issue not found.")
    _cache(response, settings)
    return await _issue_detail(db, issue)


# ---------------------------------------------------------------------------- articles


@public_router.get("/articles")
async def list_public_articles(
    response: Response,
    section_id: int | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Page[PublicArticleSummary]:
    """Published articles, newest first (for the home page, feeds and sitemaps)."""
    query = select(PublishedArticle).where(PublishedArticle.journal_id == journal.id)
    if section_id is not None:
        query = query.where(PublishedArticle.section_id == section_id)
    if cursor:
        published_at, article_id = decode_cursor(cursor, size=2)
        when = datetime.fromisoformat(published_at)
        query = query.where(
            or_(
                PublishedArticle.published_at < when,
                and_(PublishedArticle.published_at == when, PublishedArticle.id < int(article_id)),
            )
        )
    limit = clamp_limit(limit)
    rows = (
        await db.scalars(
            query.order_by(PublishedArticle.published_at.desc(), PublishedArticle.id.desc()).limit(limit + 1)
        )
    ).all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor([last.published_at.isoformat(), last.id])
        rows = rows[:limit]
    _cache(response, settings)
    return Page[PublicArticleSummary](
        items=[PublicArticleSummary.of(r.data) for r in rows], next_cursor=next_cursor
    )


@public_router.get("/articles/{slug}")
async def get_public_article(
    slug: str,
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PublicArticle:
    """Everything about a published article, including its earlier versions."""
    article = await db.scalar(
        select(PublishedArticle).where(
            PublishedArticle.journal_id == journal.id, PublishedArticle.slug == slug
        )
    )
    if article is None:
        raise NotFound("Article not found.")
    _cache(response, settings)
    return PublicArticle.of(article.data)


@public_router.get("/search")
async def search_articles(
    response: Response,
    q: str = Query(min_length=1, max_length=200),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SearchResults:
    """Full-text search over titles, keywords, authors and abstracts, best matches first."""
    query = search_query(q)
    condition = and_(
        PublishedArticle.journal_id == journal.id, PublishedArticle.search_vector.op("@@")(query)
    )
    offset = int(decode_cursor(cursor, size=1)[0]) if cursor else 0
    total = await db.scalar(select(func.count()).select_from(PublishedArticle).where(condition)) or 0
    rows = (
        await db.scalars(
            select(PublishedArticle)
            .where(condition)
            .order_by(func.ts_rank(PublishedArticle.search_vector, query).desc(), PublishedArticle.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    _cache(response, settings)
    return SearchResults(
        items=[PublicArticleSummary.of(r.data) for r in rows],
        next_cursor=encode_cursor([offset + limit]) if offset + limit < total else None,
        total=total,
    )


@public_router.get("/sections")
async def list_public_sections(
    response: Response,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[PublicSection]:
    """Sections that have published articles."""
    rows = await db.scalars(
        select(Section)
        .where(
            Section.journal_id == journal.id,
            Section.id.in_(
                select(PublishedArticle.section_id).where(PublishedArticle.journal_id == journal.id)
            ),
        )
        .order_by(Section.sort_order, Section.id)
    )
    _cache(response, settings)
    return [PublicSection(id=s.id, title=s.title) for s in rows]


@public_router.get("/galleys/{galley_id}/download", status_code=302, response_class=RedirectResponse)
async def download_public_galley(
    galley_id: int,
    journal: Journal = Depends(get_current_journal),
    db: AsyncSession = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> RedirectResponse:
    """Redirects to a short-lived link to the file of a published version."""
    galley = await db.get(Galley, galley_id)
    publication = await db.get(Publication, galley.publication_id) if galley else None
    article = (
        await db.scalar(
            select(PublishedArticle).where(
                PublishedArticle.journal_id == journal.id,
                PublishedArticle.submission_id == publication.submission_id,
            )
        )
        if publication is not None
        else None
    )
    if (
        galley is None
        or publication is None
        or article is None
        or publication.status != PublicationStatus.PUBLISHED
        or galley.revision is None
        or galley.revision.status != FileStatus.READY
    ):
        raise NotFound("File not found.")
    url = storage.presign_download(
        galley.revision.storage_key,
        filename=record_download_name(galley.file),
        content_type=galley.revision.content_type,
    )
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
