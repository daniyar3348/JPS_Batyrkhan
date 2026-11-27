"""How the journal runs peer review. Stored in ``Journal.settings["review"]``."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.journals.models import Journal


class ReviewMethod(StrEnum):
    DOUBLE_BLIND = "double_blind"  # neither side knows the other
    SINGLE_BLIND = "single_blind"  # reviewers know the authors
    OPEN = "open"  # both sides know each other


def _offsets(values: list[int]) -> list[int]:
    return sorted(set(values))


class ReviewSettings(BaseModel):
    method: ReviewMethod = ReviewMethod.DOUBLE_BLIND
    response_days: int = Field(
        default=7, ge=1, le=60, description="Days a reviewer has to answer an invitation"
    )
    review_days: int = Field(default=28, ge=1, le=180, description="Days a reviewer has to send the review")
    reminders_enabled: bool = True
    # Days after the response deadline on which an unanswered invitation is followed up.
    response_reminder_days: list[Annotated[int, Field(ge=0, le=30)]] = Field(
        default_factory=lambda: [1], max_length=5
    )
    # Days relative to the review deadline (negative: before it) on which reviewers are reminded.
    review_reminder_days: list[Annotated[int, Field(ge=-30, le=60)]] = Field(
        default_factory=lambda: [-3, 0, 3, 7], max_length=8
    )
    reviewer_guidelines: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] = ""

    _normalize_response = field_validator("response_reminder_days")(_offsets)
    _normalize_review = field_validator("review_reminder_days")(_offsets)


def review_settings(journal: Journal) -> ReviewSettings:
    return ReviewSettings.model_validate(journal.settings.get("review", {}))


class ReviewSettingsOut(ReviewSettings):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: int

    @classmethod
    def of(cls, data: ReviewSettings, journal: Journal) -> ReviewSettingsOut:
        return cls(**data.model_dump(), version=journal.version)
