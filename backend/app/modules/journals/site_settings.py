"""What the journal's public site shows besides articles. Stored in ``Journal.settings["site"]``.

Longer texts (aims and scope, policies, guidelines) are pages of the content module.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.identity.validation import normalize_orcid
from app.modules.journals.models import Journal

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class BoardMember(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    # As printed on the site: "Editor-in-Chief", "Associate Editor", "Editorial Board Member"...
    role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    affiliation: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    country: Short = ""
    orcid: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, value: str | None) -> str | None:
        return normalize_orcid(value) if value else None


class SiteSettings(BaseModel):
    # A line under the journal's name on every page.
    tagline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    # In the order shown; members with the same role are grouped under it.
    editorial_board: list[BoardMember] = Field(default_factory=list, max_length=200)
    # How often the journal publishes, shown on the About page ("Two issues a year, continuous publication").
    publication_frequency: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class SiteSettingsOut(SiteSettings):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: int

    @classmethod
    def of(cls, data: SiteSettings, journal: Journal) -> SiteSettingsOut:
        return cls(**data.model_dump(), version=journal.version)


def site_settings(journal: Journal) -> SiteSettings:
    return SiteSettings.model_validate(journal.settings.get("site", {}))
