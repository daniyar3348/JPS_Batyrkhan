from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.core.errors import FieldError
from app.modules.files.models import FileStatus, SubmissionFile
from app.modules.files.types import UPLOAD_GENRES, Genre
from app.modules.identity.schemas import Affiliation, Country, Name, OptionalName, UserSummary
from app.modules.identity.validation import normalize_orcid
from app.modules.similarity.models import SimilarityCheck
from app.modules.submissions.models import Contributor, Publication
from app.modules.submissions.policies import Access

Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=30000)]
Statement = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


def normalize_keywords(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        term = " ".join(value.split())
        if term and term.lower() not in seen:
            seen[term.lower()] = term
    if len(seen) > 30:
        raise ValueError("Use at most 30 keywords")
    if any(len(term) > 100 for term in seen.values()):
        raise ValueError("Each keyword must be 100 characters or fewer")
    return list(seen.values())


# ---------------------------------------------------------------------------- inputs


class SubmissionCreate(BaseModel):
    section_id: int


class SubmissionUpdate(BaseModel):
    section_id: int | None = None
    comments_for_editor: Statement | None = None
    checklist_confirmed: list[Annotated[str, StringConstraints(max_length=1000)]] | None = Field(
        default=None, max_length=30
    )


class PublicationUpdate(BaseModel):
    title: Title | None = None
    subtitle: Title | None = None
    abstract: LongText | None = None
    keywords: list[str] | None = None
    references: LongText | None = None
    funding_statement: Statement | None = None
    competing_interests: Statement | None = None

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, value: list[str] | None) -> list[str] | None:
        return normalize_keywords(value) if value is not None else None

    @field_validator(
        "title", "subtitle", "abstract", "references", "funding_statement", "competing_interests"
    )
    @classmethod
    def _not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Send an empty text instead of null")
        return value


class ContributorIn(BaseModel):
    given_name: Name
    family_name: OptionalName = ""
    email: EmailStr
    affiliation: Affiliation = ""
    country: Country | None = None
    orcid: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    is_corresponding: bool = False
    in_byline: bool = True

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, value: str | None) -> str | None:
        return normalize_orcid(value) if value else None


class ContributorUpdate(BaseModel):
    given_name: Name | None = None
    family_name: OptionalName | None = None
    email: EmailStr | None = None
    affiliation: Affiliation | None = None
    country: Country | None = None
    orcid: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    is_corresponding: bool | None = None
    in_byline: bool | None = None

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, value: str | None) -> str | None:
        return normalize_orcid(value) if value else None

    @field_validator("given_name", "family_name", "email", "affiliation", "is_corresponding", "in_byline")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be empty")
        return value


class ContributorOrderIn(BaseModel):
    contributor_ids: list[int] = Field(max_length=100)


class UploadRequest(BaseModel):
    file_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    size: int = Field(gt=0)
    genre: Genre

    @field_validator("genre")
    @classmethod
    def _choosable(cls, value: Genre) -> Genre:
        if value not in UPLOAD_GENRES:
            raise ValueError("Galleys are added to the publication, not uploaded here")
        return value


class FileUpdate(BaseModel):
    genre: Genre | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None

    @field_validator("genre")
    @classmethod
    def _choosable(cls, value: Genre | None) -> Genre | None:
        if value is not None and value not in UPLOAD_GENRES:
            raise ValueError("Galleys are added to the publication, not uploaded here")
        return value


# ---------------------------------------------------------------------------- outputs


class SectionRef(BaseModel):
    id: int
    title: str
    abbreviation: str


class ContributorOut(BaseModel):
    id: int
    position: int
    given_name: str
    family_name: str
    full_name: str
    email: str
    affiliation: str
    country: str | None
    orcid: str | None
    is_corresponding: bool
    in_byline: bool
    has_account: bool

    @classmethod
    def of(cls, contributor: Contributor) -> Self:
        return cls(
            id=contributor.id,
            position=contributor.position,
            given_name=contributor.given_name,
            family_name=contributor.family_name,
            full_name=contributor.full_name,
            email=contributor.email,
            affiliation=contributor.affiliation,
            country=contributor.country,
            orcid=contributor.orcid,
            is_corresponding=contributor.is_corresponding,
            in_byline=contributor.in_byline,
            has_account=contributor.user_id is not None,
        )


class PublicationOut(BaseModel):
    id: int
    version: int
    status: str
    title: str
    subtitle: str
    abstract: str
    keywords: list[str]
    references: str
    funding_statement: str
    competing_interests: str
    row_version: int
    contributors: list[ContributorOut]

    @classmethod
    def of(cls, publication: Publication) -> Self:
        return cls(
            id=publication.id,
            version=publication.version,
            status=publication.status,
            title=publication.title,
            subtitle=publication.subtitle,
            abstract=publication.abstract,
            keywords=list(publication.keywords),
            references=publication.references,
            funding_statement=publication.funding_statement,
            competing_interests=publication.competing_interests,
            row_version=publication.row_version,
            contributors=[ContributorOut.of(c) for c in publication.contributors],
        )


class FileOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    genre: Genre
    name: str
    original_name: str
    status: str
    rejection_reason: str | None
    size_bytes: int
    content_type: str
    uploaded_at: datetime
    # Relative URL that redirects to a short-lived download link; null until the file is checked.
    download_url: str | None
    # Files that cross a blind review: whether names were removed from the file's metadata.
    # False means the format could not be cleaned and someone should check the file by hand.
    metadata_removed: bool | None = None

    @classmethod
    def of(cls, record: SubmissionFile, *, files_url: str | None = None) -> Self:
        """``files_url`` is where this viewer downloads files (reviewers use their review's address)."""
        revision = record.current
        ready = revision.status == FileStatus.READY
        base = files_url or f"/api/v1/submissions/{record.submission_id}/files"
        return cls(
            id=record.id,
            genre=Genre(record.genre),
            name=record.name,
            original_name=revision.original_name,
            status=revision.status,
            rejection_reason=revision.rejection_reason,
            size_bytes=revision.size_bytes,
            content_type=revision.content_type,
            uploaded_at=revision.created_at,
            download_url=f"{base}/{record.id}/download" if ready else None,
            metadata_removed=revision.metadata_removed,
        )


class UploadTarget(BaseModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


class UploadTicketOut(BaseModel):
    file: FileOut
    upload: UploadTarget


class SimilarityCheckOut(BaseModel):
    id: int
    status: str
    provider: str
    score_percent: int | None
    # At or above the journal's threshold: the editor should look at the report.
    flagged: bool
    error: str | None
    created_at: datetime
    completed_at: datetime | None

    @classmethod
    def of(cls, check: SimilarityCheck, threshold: int) -> Self:
        return cls(
            id=check.id,
            status=check.status,
            provider=check.provider,
            score_percent=check.score_percent,
            flagged=check.score_percent is not None and check.score_percent >= threshold,
            error=check.error,
            created_at=check.created_at,
            completed_at=check.completed_at,
        )


class Viewer(BaseModel):
    """What the signed-in user may do with this submission."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    is_author: bool
    is_editor: bool
    can_edit: bool
    can_manage: bool
    can_decide: bool
    recommend_only: bool
    # copyeditor, layout_editor, proofreader: the viewer works on the accepted article in these roles.
    production_roles: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, access: Access) -> Viewer:
        return cls(
            is_author=access.is_author,
            is_editor=access.is_editor,
            can_edit=access.can_edit,
            can_manage=access.can_manage,
            can_decide=access.can_decide,
            recommend_only=access.recommend_only,
            production_roles=sorted(access.production_roles),
        )


class SubmissionOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    number: str | None
    status: str
    stage: str
    section: SectionRef
    submitter: UserSummary
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    row_version: int
    comments_for_editor: str
    checklist_confirmed: list[str]
    publication: PublicationOut
    files: list[FileOut]
    # What still prevents submission (drafts only, shown to the submitter).
    problems: list[FieldError]
    viewer: Viewer
    # Editors only.
    similarity_checks: list[SimilarityCheckOut] | None = None


class SubmissionSummary(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    number: str | None
    status: str
    stage: str
    title: str
    authors: str
    section: SectionRef
    created_at: datetime
    submitted_at: datetime | None
    updated_at: datetime
    # Editors only: the latest completed similarity score.
    similarity_score: int | None = None
    similarity_flagged: bool = False
