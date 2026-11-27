from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.identity.schemas import UserSummary
from app.modules.review.schemas import EmailOut, EmailText, RoundOut
from app.modules.submissions.schemas import FileOut, Viewer
from app.modules.workflow.transitions import Decision

Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class Defaults(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class DecisionOption(Defaults):
    decision: Decision
    label: str
    description: str
    is_recommendation: bool
    needs_files: bool
    needs_reason: bool
    has_letter: bool


class LetterIn(EmailText):
    send: bool = True


class DecisionIn(BaseModel):
    decision: Decision
    # For decisions that start a review round: the files reviewers receive.
    review_file_ids: list[int] = Field(default_factory=list, max_length=50)
    reason: Reason = ""
    # The letter as the editor approved it; None sends the template; send=false sends nothing.
    letter: LetterIn | None = None


class DecisionPreviewIn(BaseModel):
    decision: Decision


class DecisionPreview(Defaults):
    option: DecisionOption
    letter: EmailOut | None
    # Files that can go to reviewers: the manuscript's files and the latest revision.
    candidate_files: list[FileOut]


class DecisionOut(Defaults):
    id: int
    decision: Decision
    label: str
    is_recommendation: bool
    round_number: int | None
    stage_before: str
    stage_after: str
    status_after: str
    made_by: UserSummary | None
    reason: str
    letter_to: list[str]
    letter_subject: str | None
    letter_body: str | None
    created_at: datetime


class EditorOut(Defaults):
    user: UserSummary
    recommend_only: bool
    assigned_at: datetime


class EditorIn(BaseModel):
    user_id: int
    recommend_only: bool = False
    notify: bool = True


class DiscussionSummary(Defaults):
    id: int
    stage: str
    subject: str
    participants: list[UserSummary]
    is_closed: bool
    message_count: int
    last_message_at: datetime
    last_message_by: str


class MessageOut(Defaults):
    id: int
    author: UserSummary | None
    body: str
    created_at: datetime


class DiscussionOut(DiscussionSummary):
    messages: list[MessageOut]


class DiscussionCreate(BaseModel):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    participant_ids: list[int] = Field(min_length=1, max_length=50)


class MessageCreate(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


class DiscussionUpdate(BaseModel):
    is_closed: bool


class Person(Defaults):
    """Someone who can be added to a discussion, and in what capacity."""

    user: UserSummary
    role: str  # "editor" or "author"


class WithdrawIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class EmailLogOut(Defaults):
    id: int
    template_key: str | None
    recipient: str
    subject: str
    body: str
    status: str
    sent_by: str | None
    created_at: datetime
    sent_at: datetime | None


class WorkflowOut(Defaults):
    stage: str
    status: str
    viewer: Viewer
    # Editors only.
    editors: list[EditorOut] | None
    available_decisions: list[DecisionOption]
    # Authors see decisions with the letters sent to them; editors see everything, recommendations too.
    decisions: list[DecisionOut]
    rounds: list[RoundOut]
    discussions: list[DiscussionSummary]
    # Who the viewer can add to a discussion.
    people: list[Person]
    can_withdraw: bool
