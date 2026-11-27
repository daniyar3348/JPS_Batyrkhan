from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.modules.journals.publishing_settings import PublishingSettings
from app.modules.publishing.models import DoiDeposit, Galley, Issue
from app.modules.submissions.schemas import FileOut, SectionRef, UploadTarget

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
URL_PATH = r"^[a-z0-9][a-z0-9-]{0,99}$"


# ---------------------------------------------------------------------------- issues


class IssueIn(BaseModel):
    volume: int | None = Field(default=None, ge=1, le=100000)
    number: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""

    @field_validator("number")
    @classmethod
    def _blank(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def _identified(self) -> Self:
        if self.volume is None and self.number is None and self.year is None and not self.title:
            raise ValueError("Give the issue a volume, number, year or title")
        return self


class IssueOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    volume: int | None
    number: str | None
    year: int | None
    title: str
    description: str
    label: str
    status: str
    is_current: bool
    published_at: datetime | None
    row_version: int
    article_count: int = 0

    @classmethod
    def of(cls, issue: Issue, *, article_count: int = 0) -> Self:
        return cls(
            id=issue.id,
            volume=issue.volume,
            number=issue.number,
            year=issue.year,
            title=issue.title,
            description=issue.description,
            label=issue.label,
            status=issue.status,
            is_current=issue.is_current,
            published_at=issue.published_at,
            row_version=issue.row_version,
            article_count=article_count,
        )


class IssueArticle(BaseModel):
    submission_id: int
    number: str | None
    title: str
    authors: str
    section: SectionRef
    status: str  # the manuscript's status: queued (not scheduled yet), scheduled, published
    pages: str
    doi: str | None
    fee_settled: bool | None


class IssueDetail(IssueOut):
    articles: list[IssueArticle]


class ArticleOrderIn(BaseModel):
    submission_ids: list[int] = Field(max_length=500)


class IssuePublishIn(BaseModel):
    make_current: bool = True


# ---------------------------------------------------------------------------- galleys


class GalleyOut(BaseModel):
    id: int
    label: str
    position: int
    file: FileOut

    @classmethod
    def of(cls, galley: Galley, submission_id: int) -> Self:
        return cls(
            id=galley.id,
            label=galley.label,
            position=galley.position,
            file=FileOut.of(
                galley.file, files_url=f"/api/v1/submissions/{submission_id}/galleys/{galley.id}/file"
            ),
        )


class GalleyUploadIn(BaseModel):
    label: Label
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    size: int = Field(gt=0)


class GalleyUploadOut(BaseModel):
    galley: GalleyOut
    upload: UploadTarget


class GalleyUpdate(BaseModel):
    label: Label


# ---------------------------------------------------------------------------- the publication screen


class PublishingUpdate(BaseModel):
    """Only the fields sent are changed."""

    issue_id: int | None = None
    pages: Annotated[str, StringConstraints(strip_whitespace=True, max_length=30)] | None = None
    url_path: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None
    license_url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    copyright_holder: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    copyright_year: int | None = Field(default=None, ge=1900, le=2200)
    version_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None

    @field_validator("url_path")
    @classmethod
    def _path(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.lower()
        if not re.fullmatch(URL_PATH, value):
            raise ValueError("Use lower-case letters, digits and hyphens, starting with a letter or digit")
        if value.isdigit():
            raise ValueError("Use at least one letter, so the address is not mistaken for a number")
        return value

    @field_validator("license_url")
    @classmethod
    def _license(cls, value: str | None) -> str | None:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("Enter the licence's full address, starting with https://")
        return value


class Check(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str = ""


class PublicationInfo(BaseModel):
    id: int
    version: int
    status: str
    row_version: int
    doi: str | None
    doi_url: str | None
    url_path: str | None
    slug: str
    article_url: str
    pages: str
    license_url: str
    copyright_holder: str
    copyright_year: int | None
    issue_id: int | None
    version_note: str
    published_at: datetime | None


class VersionOut(BaseModel):
    id: int
    version: int
    status: str
    published_at: datetime | None
    version_note: str


class DepositOut(BaseModel):
    id: int
    publication_id: int
    doi: str
    status: str
    mode: str
    message: str
    created_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def of(cls, deposit: DoiDeposit) -> Self:
        return cls(
            id=deposit.id,
            publication_id=deposit.publication_id,
            doi=deposit.doi,
            status=deposit.status,
            mode=deposit.mode,
            message=deposit.message,
            created_at=deposit.created_at,
            submitted_at=deposit.submitted_at,
            completed_at=deposit.completed_at,
        )


class DepositListItem(DepositOut):
    submission_id: int
    submission_number: str | None
    title: str


class PublishingOut(BaseModel):
    submission_id: int
    stage: str
    status: str
    publication: PublicationInfo
    issue: IssueOut | None
    galleys: list[GalleyOut]
    checks: list[Check]
    # What the publish button does now: schedule into a future issue, or publish at once.
    action: Literal["schedule", "publish", "publish_version"] | None
    ready: bool
    fee_settled: bool | None
    can_edit: bool  # issue, pages, licence...
    can_edit_galleys: bool
    can_publish: bool  # the viewer may press the button (when ready)
    can_unschedule: bool
    can_create_version: bool
    can_discard_version: bool
    versions: list[VersionOut]
    doi_enabled: bool
    can_assign_doi: bool
    can_deposit: bool
    deposits: list[DepositOut]


class VersionIn(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


# ---------------------------------------------------------------------------- settings


class PublishingSettingsOut(BaseModel):
    settings: PublishingSettings
    # Server configuration, shown so the editors know whether deposits really reach Crossref.
    crossref_mode: str
    crossref_account_configured: bool
    site_revalidation_configured: bool
    problems: list[str]
    suffix_placeholders: dict[str, str]
    example_doi: str | None
