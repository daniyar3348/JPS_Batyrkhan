from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.modules.identity.models import User
from app.modules.identity.schemas import Affiliation, Name, OptionalName, UserOut, UserSummary
from app.modules.journals.models import Journal, Section
from app.modules.journals.permissions import Capability, Role
from app.modules.journals.site_settings import BoardMember
from app.modules.journals.validation import normalize_issn

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
SectionTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Abbreviation = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
SectionAbbreviation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
PolicyVersion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class JournalOut(BaseModel):
    id: int
    slug: str
    name: str
    abbreviation: str
    description: str
    publisher: str
    issn_print: str | None
    issn_online: str | None
    contact_name: str
    contact_email: str
    privacy_policy_version: str
    version: int
    updated_at: datetime

    @classmethod
    def of(cls, journal: Journal) -> Self:
        return cls.model_validate(journal, from_attributes=True)


class JournalUpdate(BaseModel):
    """Only the fields present in the request are changed."""

    name: Title | None = None
    abbreviation: Abbreviation | None = None
    description: LongText | None = None
    publisher: ShortText | None = None
    issn_print: str | None = None
    issn_online: str | None = None
    contact_name: ShortText | None = None
    contact_email: EmailStr | None = None
    privacy_policy_version: PolicyVersion | None = None

    @field_validator("issn_print", "issn_online")
    @classmethod
    def _issn(cls, value: str | None) -> str | None:
        return normalize_issn(value) if value and value.strip() else None

    @field_validator("name", "privacy_policy_version")
    @classmethod
    def _required(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field cannot be empty")
        return value


class PublicSectionOut(BaseModel):
    id: int
    title: str
    abbreviation: str
    policy: str


class PublicSectionFee(BaseModel):
    section_id: int
    section_title: str
    amount: Decimal


class PublicFees(BaseModel):
    """The publication fee as authors see it before submitting (charged only after acceptance)."""

    charged: bool
    currency: str
    amount: Decimal
    vat_percent: Decimal
    section_fees: list[PublicSectionFee]
    waiver_policy: str


class PublicJournalOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    abbreviation: str
    description: str
    publisher: str
    issn_print: str | None
    issn_online: str | None
    contact_name: str
    contact_email: str
    sections: list[PublicSectionOut]
    tagline: str = ""
    publication_frequency: str = ""
    editorial_board: list[BoardMember] = Field(default_factory=list)
    site_url: str = ""
    license_url: str = ""
    fees: PublicFees | None = None


class SectionCreate(BaseModel):
    title: SectionTitle
    abbreviation: SectionAbbreviation
    policy: LongText = ""
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)


class SectionUpdate(BaseModel):
    title: SectionTitle | None = None
    abbreviation: SectionAbbreviation | None = None
    policy: LongText | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)

    @field_validator("title", "abbreviation", "policy", "is_active", "sort_order")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be empty")
        return value


class SectionOut(BaseModel):
    id: int
    title: str
    abbreviation: str
    policy: str
    is_active: bool
    sort_order: int
    version: int
    editors: list[UserSummary]

    @classmethod
    def of(cls, section: Section) -> Self:
        return cls(
            id=section.id,
            title=section.title,
            abbreviation=section.abbreviation,
            policy=section.policy,
            is_active=section.is_active,
            sort_order=section.sort_order,
            version=section.version,
            editors=[UserSummary.of(user) for user in section.editors],
        )


class SectionEditorsIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, max_length=50)


class MemberOut(BaseModel):
    id: int
    email: str
    given_name: str
    family_name: str
    full_name: str
    affiliation: str
    country: str | None
    orcid: str | None
    is_active: bool
    email_verified: bool
    has_password: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[Role]

    @classmethod
    def of(cls, user: User, roles: list[Role]) -> Self:
        return cls(
            id=user.id,
            email=user.email,
            given_name=user.given_name,
            family_name=user.family_name,
            full_name=user.full_name,
            affiliation=user.affiliation,
            country=user.country,
            orcid=user.orcid,
            is_active=user.is_active,
            email_verified=user.email_verified_at is not None,
            has_password=user.password_hash is not None,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            roles=sorted(roles),
        )


class RolesIn(BaseModel):
    roles: list[Role] = Field(max_length=len(Role))


class MemberUpdate(BaseModel):
    is_active: bool


class InviteIn(BaseModel):
    email: EmailStr
    given_name: Name
    family_name: OptionalName = ""
    affiliation: Affiliation = ""
    roles: list[Role] = Field(min_length=1, max_length=len(Role))


class MeOut(BaseModel):
    user: UserOut
    roles: list[Role]
    capabilities: list[Capability]
    csrf_token: str


class TemplateVariable(BaseModel):
    name: str
    description: str


class EmailTemplateOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    group: str
    name: str
    description: str
    recipient: str
    subject: str
    body: str
    default_subject: str
    default_body: str
    is_custom: bool
    updated_at: datetime | None = None
    variables: list[TemplateVariable]


class EmailTemplateIn(BaseModel):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
