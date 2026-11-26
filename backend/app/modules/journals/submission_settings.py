"""How the journal accepts submissions. Stored in ``Journal.settings["submission"]``."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.config import Settings
from app.modules.files.types import ALLOWED_EXTENSIONS
from app.modules.journals.models import Journal

ChecklistItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]

DEFAULT_CHECKLIST = [
    "The manuscript has not been published before and is not under consideration by another journal.",
    "All authors have approved the manuscript and agree to its submission.",
    "The manuscript file is in Word, OpenDocument, RTF, LaTeX or PDF format.",
    "The text follows the style and reference requirements in the author guidelines.",
    "DOIs are given for references wherever they exist.",
]


class SimilaritySettings(BaseModel):
    enabled: bool = False
    # Manuscripts at or above this overall similarity are flagged for the editor's attention.
    threshold_percent: int = Field(default=30, ge=1, le=100)


class SubmissionSettings(BaseModel):
    checklist: list[ChecklistItem] = Field(default_factory=lambda: list(DEFAULT_CHECKLIST), max_length=20)
    author_guidelines: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] = ""
    max_file_size_mb: int = Field(default=50, ge=1, le=200)
    abstract_max_words: int = Field(default=300, ge=50, le=2000)
    keywords_min: int = Field(default=3, ge=0, le=20)
    keywords_max: int = Field(default=8, ge=1, le=30)
    # Manuscript numbers look like JRN-2026-0042.
    number_prefix: str = Field(default="JRN", pattern=r"^[A-Z0-9]{2,10}$")
    similarity: SimilaritySettings = Field(default_factory=SimilaritySettings)

    @model_validator(mode="after")
    def _check_keywords(self) -> Self:
        if self.keywords_min > self.keywords_max:
            raise ValueError("The minimum number of keywords cannot exceed the maximum")
        return self


def submission_settings(journal: Journal) -> SubmissionSettings:
    return SubmissionSettings.model_validate(journal.settings.get("submission", {}))


class SubmissionSettingsOut(SubmissionSettings):
    # In responses every field is always present, defaults included.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: int
    # Whether a similarity checking service is configured on the server.
    similarity_available: bool
    # Accepted file extensions for each kind of file.
    allowed_file_types: dict[str, list[str]]

    @classmethod
    def of(cls, data: SubmissionSettings, journal: Journal, settings: Settings) -> SubmissionSettingsOut:
        return cls(
            **data.model_dump(),
            version=journal.version,
            similarity_available=settings.similarity_provider != "disabled",
            allowed_file_types={
                genre.value: list(extensions) for genre, extensions in ALLOWED_EXTENSIONS.items()
            },
        )
