from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.identity.models import User
from app.modules.identity.validation import normalize_interests, normalize_orcid

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
OptionalName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Affiliation = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]


def _country_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ValueError("Use a two-letter ISO 3166 country code, for example KZ")
    return code


Country = Annotated[str, AfterValidator(_country_code)]


class UserSummary(BaseModel):
    id: int
    full_name: str
    email: str
    affiliation: str

    @classmethod
    def of(cls, user: User) -> Self:
        return cls(id=user.id, full_name=user.full_name, email=user.email, affiliation=user.affiliation)


class UserOut(BaseModel):
    id: int
    email: str
    given_name: str
    family_name: str
    full_name: str
    affiliation: str
    country: str | None
    orcid: str | None
    biography: str
    interests: list[str]
    email_verified: bool
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> Self:
        return cls(
            id=user.id,
            email=user.email,
            given_name=user.given_name,
            family_name=user.family_name,
            full_name=user.full_name,
            affiliation=user.affiliation,
            country=user.country,
            orcid=user.orcid,
            biography=user.biography,
            interests=list(user.interests),
            email_verified=user.email_verified_at is not None,
            created_at=user.created_at,
        )


class RegisterIn(BaseModel):
    email: EmailStr
    password: Password
    given_name: Name
    family_name: OptionalName = ""
    affiliation: Affiliation = ""
    country: Country | None = None
    interests: list[str] = Field(default_factory=list)
    wants_to_review: bool = False
    accept_privacy_policy: bool
    accept_cross_border_transfer: bool

    _interests = field_validator("interests")(normalize_interests)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not (self.accept_privacy_policy and self.accept_cross_border_transfer):
            raise ValueError("You must accept the privacy policy and the transfer of data abroad to register")
        if self.password.strip().lower() == str(self.email).lower():
            raise ValueError("The password must not be your e-mail address")
        return self


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)]
    password: Annotated[str, StringConstraints(max_length=128)]


class ProfileUpdate(BaseModel):
    given_name: Name | None = None
    family_name: OptionalName | None = None
    affiliation: Affiliation | None = None
    country: Country | None = None
    orcid: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    biography: Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)] | None = None
    interests: list[str] | None = None

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, value: str | None) -> str | None:
        return normalize_orcid(value) if value else None

    @field_validator("interests")
    @classmethod
    def _interests(cls, value: list[str] | None) -> list[str] | None:
        return normalize_interests(value) if value is not None else None

    @field_validator("given_name")
    @classmethod
    def _given_name_required(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Given name cannot be empty")
        return value


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, StringConstraints(max_length=128)]
    new_password: Password


class EmailIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)]


class TokenIn(BaseModel):
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=200)]


class PasswordResetConfirmIn(TokenIn):
    password: Password
    # Required only when accepting an invitation: invited users have not given consent yet.
    accept_privacy_policy: bool = False
    accept_cross_border_transfer: bool = False


class TokenInfoOut(BaseModel):
    kind: str
    email: str
    full_name: str
