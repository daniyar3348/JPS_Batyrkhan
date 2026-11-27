"""How the journal publishes: the public site's address, licence, copyright and DOIs.
Stored in ``Journal.settings["publishing"]``.

The Crossref account (login and password) is server configuration, not a journal setting: it never
reaches the browser and is not changed through the workspace.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, StringConstraints, ValidationInfo, field_validator

from app.modules.journals.models import Journal

Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]

# Placeholders the DOI suffix may use. {number} is the manuscript's sequence within its year.
SUFFIX_PLACEHOLDERS = {
    "{journal}": "The journal's abbreviation, in lower case (e.g. jrn)",
    "{year}": "The year the manuscript was submitted",
    "{number}": "The manuscript's number within that year, e.g. 0042",
    "{id}": "The manuscript's internal id",
}
_SUFFIX_ALLOWED = re.compile(r"^[A-Za-z0-9.\-_;()/{}]+$")


class DoiSettings(BaseModel):
    enabled: bool = False
    # Given by Crossref when the journal joins, e.g. 10.12345.
    prefix: str = Field(default="", max_length=20)
    suffix_pattern: str = Field(default="{journal}.{year}.{number}", min_length=1, max_length=100)
    # Who Crossref writes to about deposits; printed in every deposit.
    depositor_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=130)] = ""
    depositor_email: EmailStr | Literal[""] = ""

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        value = value.strip()
        if value and not re.fullmatch(r"10\.\d{4,9}", value):
            raise ValueError("A DOI prefix looks like 10.12345")
        return value

    @field_validator("suffix_pattern")
    @classmethod
    def _suffix(cls, value: str) -> str:
        value = value.strip()
        if not _SUFFIX_ALLOWED.match(value):
            raise ValueError("Use letters, digits and . - _ ; ( ) / only, plus the placeholders")
        unknown = set(re.findall(r"\{[^}]*\}", value)) - set(SUFFIX_PLACEHOLDERS)
        if unknown:
            raise ValueError(f"Unknown placeholder: {', '.join(sorted(unknown))}")
        if "{number}" not in value and "{id}" not in value:
            raise ValueError("Include {number} or {id}, so that every article gets its own DOI")
        return value

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.prefix)


class PublishingSettings(BaseModel):
    # The journal's public site, e.g. https://journal.example.org. Article pages are {site_url}/articles/{slug};
    # Crossref and indexers link there, so set it before the first DOI is registered.
    site_url: Url = ""
    license_url: Url = "https://creativecommons.org/licenses/by/4.0/"
    copyright_holder: Literal["authors", "journal"] = "authors"
    doi: DoiSettings = Field(default_factory=DoiSettings)

    @field_validator("site_url", "license_url")
    @classmethod
    def _http(cls, value: str, info: ValidationInfo) -> str:
        # Article addresses are built on the site's address; licence addresses are kept as written
        # (Creative Commons' canonical addresses end with a slash).
        if value and info.field_name == "site_url":
            value = value.rstrip("/")
        if value and not re.fullmatch(r"https?://[^\s/$.?#][^\s]*", value):
            raise ValueError("Enter a full address starting with https://")
        return value

    def article_url(self, slug: str) -> str:
        return f"{self.site_url}/articles/{slug}" if self.site_url else ""

    def issue_url(self, issue_id: int) -> str:
        return f"{self.site_url}/issues/{issue_id}" if self.site_url else ""


def publishing_settings(journal: Journal) -> PublishingSettings:
    return PublishingSettings.model_validate(journal.settings.get("publishing", {}))
