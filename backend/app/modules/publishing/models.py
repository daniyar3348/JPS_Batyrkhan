"""Issues, galleys, the published-article read model, and DOI deposits."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow
from app.modules.files.models import FileRevision, SubmissionFile


class IssueStatus:
    FUTURE = "future"  # being put together; its articles are scheduled
    PUBLISHED = "published"


class Issue(TimestampMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (
        Index(
            "uq_issues_volume_number",
            "journal_id",
            "volume",
            "number",
            unique=True,
            postgresql_where=text("volume IS NOT NULL AND number IS NOT NULL"),
        ),
        # At most one current issue: the one the site's home page shows.
        Index("uq_issues_current", "journal_id", unique=True, postgresql_where=text("is_current")),
        Index("ix_issues_archive", "journal_id", "status", "published_at"),
    )

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    volume: Mapped[int | None] = mapped_column(Integer)
    number: Mapped[str | None] = mapped_column(String(20))
    year: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300), default="", server_default="")
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default=IssueStatus.FUTURE, server_default="future")
    is_current: Mapped[bool] = mapped_column(default=False, server_default="false")
    published_at: Mapped[datetime | None]
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012

    @property
    def label(self) -> str:
        """How the issue is cited: "Vol. 2 No. 1 (2026): Special issue on ..."."""
        parts = []
        if self.volume is not None:
            parts.append(f"Vol. {self.volume}")
        if self.number:
            parts.append(f"No. {self.number}")
        if self.year is not None:
            parts.append(f"({self.year})")
        label = " ".join(parts)
        if self.title:
            label = f"{label}: {self.title}" if label else self.title
        return label or f"Issue {self.id}"


class Galley(Base):
    """A file readers get: the typeset PDF, HTML or XML of one version of the article."""

    __tablename__ = "galleys"

    id: Mapped[int] = id_column()
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(50))
    # A new version starts with the same files; replacing one adds a file, the old version keeps its own.
    file_id: Mapped[int] = mapped_column(ForeignKey("submission_files.id", ondelete="CASCADE"), index=True)
    # The revision readers get, fixed when the version is published so it never changes afterwards.
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("file_revisions.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())

    file: Mapped[SubmissionFile] = relationship(lazy="selectin")
    revision: Mapped[FileRevision | None] = relationship(lazy="selectin")


class PublishedArticle(Base):
    """What readers see of a published article: a snapshot built when it is published or changed.

    The public API and OAI-PMH read only this table, never the editorial tables.
    """

    __tablename__ = "published_articles"
    __table_args__ = (
        UniqueConstraint("journal_id", "slug"),
        Index("ix_published_articles_search", "search_vector", postgresql_using="gin"),
        Index("ix_published_articles_recent", "journal_id", "published_at"),
        Index("ix_published_articles_changed", "journal_id", "updated_at"),
        Index("ix_published_articles_issue", "issue_id", "position"),
    )

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), unique=True)
    # The version readers get by default: the latest published one.
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"))
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("issues.id", ondelete="SET NULL"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"))
    slug: Mapped[str] = mapped_column(String(100))
    doi: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    # Order within the issue: the section's order, then the article's place in it.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # When the first version was published; later versions keep it.
    published_at: Mapped[datetime]
    # Any change readers can see (a new version, a corrected issue); OAI-PMH datestamps use it.
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    search_vector: Mapped[str] = mapped_column(TSVECTOR)


class DepositStatus:
    QUEUED = "queued"  # waiting for the worker
    SUBMITTED = "submitted"  # Crossref took it; its result comes later
    REGISTERED = "registered"
    FAILED = "failed"


class DoiDeposit(Base):
    """One deposit of an article's metadata with Crossref, with what Crossref answered."""

    __tablename__ = "doi_deposits"
    __table_args__ = (Index("ix_doi_deposits_status", "journal_id", "status", "created_at"),)

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    doi: Mapped[str] = mapped_column(String(200))
    # Sent in the deposit; Crossref's result is looked up by it.
    batch_id: Mapped[str] = mapped_column(String(64), unique=True)
    mode: Mapped[str] = mapped_column(String(20))  # fake, test or production (see Settings.crossref_mode)
    status: Mapped[str] = mapped_column(String(20), default=DepositStatus.QUEUED, server_default="queued")
    xml: Mapped[str] = mapped_column(Text, default="", server_default="")
    response: Mapped[str] = mapped_column(Text, default="", server_default="")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    checks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    submitted_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
