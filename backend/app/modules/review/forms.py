"""Review forms: the questions reviewers answer, and checking their answers.

Each invitation keeps a copy of the form's questions as they were when the reviewer was invited,
so editing a form later never changes what a reviewer was asked or how their answers read.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.errors import FieldError, ValidationFailed

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Option = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
QUESTION_ID = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_ANSWER = 20000


class QuestionType(StrEnum):
    TEXT = "text"  # one line
    TEXTAREA = "textarea"  # paragraphs
    CHOICE = "choice"  # one of the options
    CHECKBOXES = "checkboxes"  # any of the options


class Question(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: Annotated[str, StringConstraints(pattern=QUESTION_ID.pattern)] = ""
    type: QuestionType
    label: Label
    help: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    options: list[Option] = Field(default_factory=list, max_length=20)
    required: bool = False
    # Answers to hidden questions are for the editors only.
    visible_to_author: bool = True

    @model_validator(mode="after")
    def _check_options(self) -> Self:
        if self.type in (QuestionType.CHOICE, QuestionType.CHECKBOXES):
            if len(self.options) < 2:
                raise ValueError("A question with choices needs at least two options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("Options must be different")
        else:
            self.options = []
        return self


class ReviewFormIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""
    questions: list[Question] = Field(max_length=40)
    is_active: bool = True
    is_default: bool = False

    @model_validator(mode="after")
    def _ids(self) -> Self:
        """New questions get an id; ids stay unique so answers can be matched to questions."""
        seen: set[str] = set()
        for question in self.questions:
            if not question.id or question.id in seen:
                question.id = f"q_{uuid.uuid4().hex[:10]}"
            seen.add(question.id)
        return self


DEFAULT_FORM = ReviewFormIn(
    title="Standard review",
    description="Questions every reviewer answers. Comments for the authors and for the editor follow them.",
    is_default=True,
    questions=[
        Question(
            id="summary",
            type=QuestionType.TEXTAREA,
            label="Summarize the manuscript's main question, methods and findings in a few sentences.",
            required=True,
        ),
        Question(
            id="originality",
            type=QuestionType.CHOICE,
            label="How original is the work?",
            options=["Highly original", "Moderately original", "Little new", "Not original"],
            required=True,
            visible_to_author=False,
        ),
        Question(
            id="methods",
            type=QuestionType.TEXTAREA,
            label="Are the methods appropriate and described well enough for others to repeat the work?",
            required=True,
        ),
        Question(
            id="conclusions",
            type=QuestionType.CHOICE,
            label="Do the conclusions follow from the results?",
            options=["Yes", "Partly", "No"],
            required=True,
        ),
        Question(
            id="presentation",
            type=QuestionType.CHOICE,
            label="How clear are the writing, figures and tables?",
            options=["Excellent", "Good", "Needs improvement", "Poor"],
            visible_to_author=False,
        ),
    ],
)


def questions_of(raw: Sequence[dict[str, Any]]) -> list[Question]:
    return [Question.model_validate(item) for item in raw]


def clean_answers(questions: Sequence[Question], answers: dict[str, Any]) -> dict[str, Any]:
    """Keep answers to known questions, in the right shape. Raises on answers that cannot be right."""
    result: dict[str, Any] = {}
    errors: list[FieldError] = []
    for question in questions:
        if question.id not in answers or answers[question.id] in (None, "", []):
            continue
        value = answers[question.id]
        field = f"answers.{question.id}"
        if question.type in (QuestionType.TEXT, QuestionType.TEXTAREA):
            if not isinstance(value, str):
                errors.append(FieldError(field=field, message="Write the answer as text"))
            elif len(value) > MAX_ANSWER:
                errors.append(FieldError(field=field, message="The answer is too long"))
            elif value.strip():
                result[question.id] = value.strip()
        elif question.type == QuestionType.CHOICE:
            if value not in question.options:
                errors.append(FieldError(field=field, message="Choose one of the options"))
            else:
                result[question.id] = value
        else:
            if not isinstance(value, list) or any(item not in question.options for item in value):
                errors.append(FieldError(field=field, message="Choose from the options"))
            else:
                result[question.id] = [option for option in question.options if option in value]
    if errors:
        raise ValidationFailed("Some answers are not valid.", code="invalid_answers", errors=errors)
    return result


def missing_answers(questions: Sequence[Question], answers: dict[str, Any]) -> list[FieldError]:
    return [
        FieldError(field=f"answers.{q.id}", message="This question needs an answer")
        for q in questions
        if q.required and q.id not in answers
    ]
