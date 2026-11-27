"""Shapes of review data. Each viewer gets their own shape, built in ``policies.py``:
editors see everything, reviewers see their own review and the manuscript as blind review allows,
authors see reviewers' comments for them under "Reviewer N" once the editor has decided."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.identity.schemas import Affiliation, Name, OptionalName, UserSummary
from app.modules.journals.review_settings import ReviewMethod
from app.modules.review.forms import Question
from app.modules.submissions.schemas import FileOut, SectionRef

LongText = Annotated[str, StringConstraints(max_length=50000)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
RecommendationValue = Literal[
    "accept", "minor_revisions", "major_revisions", "resubmit_elsewhere", "decline", "see_comments"
]
DeclineReasonValue = Literal["conflict_of_interest", "no_time", "outside_expertise", "other"]


class Defaults(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# ---------------------------------------------------------------------- editor side


class AssignmentOut(Defaults):
    """A review request and the review, as the manuscript's editors see it."""

    id: int
    round_id: int
    round_number: int
    reviewer: UserSummary
    reviewer_number: int
    method: ReviewMethod
    status: str
    invited_at: datetime
    response_due: date
    review_due: date
    responded_at: datetime | None
    completed_at: datetime | None
    overdue: bool
    decline_reason: str | None
    decline_comment: str
    competing_interests: str
    recommendation: str | None
    comments_for_author: str
    comments_for_editor: str
    questions: list[Question]
    answers: dict[str, Any]
    rating: int | None
    acknowledged_at: datetime | None
    attachments: list[FileOut]
    last_reminded_at: datetime | None


class RoundOut(Defaults):
    id: int
    number: int
    status: str
    created_at: datetime
    closed_at: datetime | None
    author_response: str
    revisions_submitted_at: datetime | None
    review_files: list[FileOut]
    revision_files: list[FileOut]
    # Editors: every request. Authors: finished reviews, once the editor has decided on the round.
    assignments: list[AssignmentOut] | None
    reviews_for_author: list[AuthorReviewOut] | None


class NewReviewer(BaseModel):
    email: EmailStr
    given_name: Name
    family_name: OptionalName = ""
    affiliation: Affiliation = ""


class EmailText(BaseModel):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=50000)]


class ReviewerInviteIn(BaseModel):
    reviewer_id: int | None = None
    new_reviewer: NewReviewer | None = None
    method: ReviewMethod | None = None
    response_due: date | None = None
    review_due: date | None = None
    form_id: int | None = None
    # The text the editor approved; None sends the template as it is.
    email: EmailText | None = None


class InvitationPreviewIn(BaseModel):
    reviewer_id: int | None = None
    new_reviewer: NewReviewer | None = None
    response_due: date | None = None
    review_due: date | None = None


class EmailOut(BaseModel):
    subject: str
    body: str
    to: list[str] = Field(default_factory=list)


class DatesIn(BaseModel):
    response_due: date
    review_due: date


class CancelIn(BaseModel):
    notify: bool = True


class RemindIn(BaseModel):
    email: EmailText


class AcknowledgeIn(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    send_thanks: bool = True
    email: EmailText | None = None


class ReviewFilesIn(BaseModel):
    file_ids: list[int] = Field(min_length=1, max_length=50)


class Suggestion(Defaults):
    reviewer: UserSummary
    interests: list[str]
    score: float
    matched_keywords: list[str]
    warnings: list[str]
    active_reviews: int
    completed_reviews: int
    average_days: float | None
    average_rating: float | None
    declined_share: float | None


# ---------------------------------------------------------------------- reviewer side


class ReviewerManuscript(Defaults):
    """The manuscript as a reviewer may see it under the review method."""

    title: str
    subtitle: str
    abstract: str
    keywords: list[str]
    section: SectionRef
    references: str
    # Present only when the review is not double-blind.
    authors: list[str] | None
    comments_for_editor: str | None


class ReviewerTask(Defaults):
    """A line in the reviewer's list."""

    id: int
    title: str
    round_number: int
    status: str
    method: ReviewMethod
    invited_at: datetime
    response_due: date
    review_due: date
    overdue: bool
    completed_at: datetime | None


class ReviewerAssignmentOut(Defaults):
    id: int
    status: str
    method: ReviewMethod
    round_number: int
    invited_at: datetime
    response_due: date
    review_due: date
    overdue: bool
    responded_at: datetime | None
    completed_at: datetime | None
    # True while the reviewer can still change the review (accepted and not yet sent).
    can_edit: bool
    manuscript: ReviewerManuscript
    # Files arrive after the reviewer accepts.
    files: list[FileOut]
    guidelines: str
    questions: list[Question]
    answers: dict[str, Any]
    recommendation: str | None
    comments_for_author: str
    comments_for_editor: str
    competing_interests: str
    attachments: list[FileOut]
    row_version: int


class AcceptIn(BaseModel):
    competing_interests: Comment = ""


class DeclineIn(BaseModel):
    reason: DeclineReasonValue
    comment: Comment = ""


class ReviewIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    recommendation: RecommendationValue | None = None
    comments_for_author: LongText = ""
    comments_for_editor: LongText = ""


# ---------------------------------------------------------------------- author side


class AuthorReviewOut(Defaults):
    """A finished review as the authors see it."""

    label: str  # "Reviewer 2", or the reviewer's name in open review
    comments: str
    answers: list[AuthorAnswer]
    attachments: list[FileOut]


class AuthorAnswer(Defaults):
    question: str
    answer: str


class RevisionsIn(BaseModel):
    response: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50000)] = ""


# ---------------------------------------------------------------------- forms


class ReviewFormOut(Defaults):
    id: int
    title: str
    description: str
    questions: list[Question]
    is_active: bool
    is_default: bool
    version: int


RoundOut.model_rebuild()
AuthorReviewOut.model_rebuild()
