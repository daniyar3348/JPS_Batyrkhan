from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow
from app.modules.identity.models import User
from app.modules.journals.models import Section


class SubmissionStatus:
    DRAFT = "draft"
    QUEUED = "queued"  # submitted and moving through the editorial stages
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"


class Stage:
    SUBMISSION = "submission"
    REVIEW = "review"
    COPYEDITING = "copyediting"
    PRODUCTION = "production"


class Submission(TimestampMixin, Base):
    """A manuscript's case in the editorial office: where it is, who works on it, what happened."""

    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_queue", "journal_id", "status", "stage", "submitted_at"),
        Index("ix_submissions_submitter", "submitter_id", "created_at"),
    )

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="RESTRICT"), index=True)
    submitter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Assigned when the manuscript is submitted, e.g. JRN-2026-0042.
    number: Mapped[str | None] = mapped_column(String(30), unique=True)
    stage: Mapped[str] = mapped_column(String(20), default=Stage.SUBMISSION, server_default=Stage.SUBMISSION)
    status: Mapped[str] = mapped_column(String(20), default=SubmissionStatus.DRAFT, server_default="draft")
    comments_for_editor: Mapped[str] = mapped_column(Text, default="", server_default="")
    # The checklist items the author confirmed, kept verbatim: the checklist may change later.
    checklist_confirmed: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    submitted_at: Mapped[datetime | None]
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    section: Mapped[Section] = relationship(lazy="selectin")
    submitter: Mapped[User] = relationship(lazy="selectin")
    publications: Mapped[list[Publication]] = relationship(
        back_populates="submission",
        lazy="selectin",
        order_by="Publication.version",
        cascade="all, delete-orphan",
    )

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012

    @property
    def publication(self) -> Publication:
        """The current version of the metadata."""
        return self.publications[-1]


class Publication(TimestampMixin, Base):
    """A version of the article's metadata. Published versions are never changed; corrections add a version."""

    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("submission_id", "version"),)

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    title: Mapped[str] = mapped_column(String(500), default="", server_default="")
    subtitle: Mapped[str] = mapped_column(String(500), default="", server_default="")
    abstract: Mapped[str] = mapped_column(Text, default="", server_default="")
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list, server_default="{}")
    references: Mapped[str] = mapped_column(Text, default="", server_default="")
    funding_statement: Mapped[str] = mapped_column(Text, default="", server_default="")
    competing_interests: Mapped[str] = mapped_column(Text, default="", server_default="")
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    submission: Mapped[Submission] = relationship(back_populates="publications", lazy="raise")
    contributors: Mapped[list[Contributor]] = relationship(
        back_populates="publication",
        lazy="selectin",
        order_by="Contributor.position",
        cascade="all, delete-orphan",
    )

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012


class Contributor(Base):
    """An author of the article. Need not have an account; linked to one by e-mail on submission."""

    __tablename__ = "contributors"

    id: Mapped[int] = id_column()
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    given_name: Mapped[str] = mapped_column(String(100))
    family_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    email: Mapped[str] = mapped_column(String(320))
    affiliation: Mapped[str] = mapped_column(String(300), default="", server_default="")
    country: Mapped[str | None] = mapped_column(String(2))
    orcid: Mapped[str | None] = mapped_column(String(19))
    is_corresponding: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Some contributors are acknowledged but not listed as authors.
    in_byline: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())

    publication: Mapped[Publication] = relationship(back_populates="contributors", lazy="raise")

    @property
    def full_name(self) -> str:
        return f"{self.given_name} {self.family_name}".strip()


class SubmissionCounter(Base):
    """Next manuscript number per journal and year; incremented atomically on submission."""

    __tablename__ = "submission_counters"

    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)
