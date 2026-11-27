from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow
from app.modules.identity.models import User


class RoundStatus:
    REVIEW = "review"  # reviewers are invited or working
    REVISIONS_REQUESTED = "revisions_requested"  # the author revises; the editor decides without new reviews
    RESUBMIT_REQUESTED = "resubmit_requested"  # the author revises; a new round of reviews follows
    REVISIONS_SUBMITTED = "revisions_submitted"  # the author sent the revised files
    CLOSED = "closed"  # a decision ended the round (accepted, declined, or a new round started)


AWAITING_REVISIONS = frozenset({RoundStatus.REVISIONS_REQUESTED, RoundStatus.RESUBMIT_REQUESTED})


class ReviewRound(Base):
    """One round of peer review of a manuscript. Revisions that need new reviews start the next round."""

    __tablename__ = "review_rounds"
    __table_args__ = (UniqueConstraint("submission_id", "number"),)

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=RoundStatus.REVIEW, server_default="review")
    # The author's reply to the reviewers, sent with the revised files.
    author_response: Mapped[str] = mapped_column(Text, default="", server_default="")
    revisions_submitted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    closed_at: Mapped[datetime | None]


class AssignmentStatus:
    INVITED = "invited"
    ACCEPTED = "accepted"
    DECLINED = "declined"  # the reviewer said no
    CANCELLED = "cancelled"  # the editor withdrew the invitation
    COMPLETED = "completed"


OPEN_STATUSES = frozenset({AssignmentStatus.INVITED, AssignmentStatus.ACCEPTED})


class Recommendation:
    ACCEPT = "accept"
    MINOR_REVISIONS = "minor_revisions"
    MAJOR_REVISIONS = "major_revisions"
    RESUBMIT_ELSEWHERE = "resubmit_elsewhere"
    DECLINE = "decline"
    SEE_COMMENTS = "see_comments"


RECOMMENDATION_LABELS = {
    Recommendation.ACCEPT: "Accept",
    Recommendation.MINOR_REVISIONS: "Minor revisions",
    Recommendation.MAJOR_REVISIONS: "Major revisions",
    Recommendation.RESUBMIT_ELSEWHERE: "Resubmit elsewhere",
    Recommendation.DECLINE: "Decline",
    Recommendation.SEE_COMMENTS: "See comments",
}


class DeclineReason:
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    NO_TIME = "no_time"
    OUTSIDE_EXPERTISE = "outside_expertise"
    OTHER = "other"


class ReviewAssignment(TimestampMixin, Base):
    """A reviewer's part in a round: from the invitation to the finished review."""

    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint("round_id", "reviewer_id"),
        Index("ix_review_assignments_reviewer", "reviewer_id", "status"),
        Index(
            "ix_review_assignments_due",
            "review_due",
            postgresql_where=text("status IN ('invited', 'accepted')"),
        ),
    )

    id: Mapped[int] = id_column()
    round_id: Mapped[int] = mapped_column(ForeignKey("review_rounds.id", ondelete="CASCADE"))
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Authors see "Reviewer 2"; the same person keeps their number in every round.
    reviewer_number: Mapped[int] = mapped_column(SmallInteger)
    method: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=AssignmentStatus.INVITED)
    form_id: Mapped[int | None] = mapped_column(ForeignKey("review_forms.id", ondelete="SET NULL"))
    invited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    invited_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    response_due: Mapped[date]
    review_due: Mapped[date]
    responded_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    decline_reason: Mapped[str | None] = mapped_column(String(30))
    decline_comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    competing_interests: Mapped[str] = mapped_column(Text, default="", server_default="")
    recommendation: Mapped[str | None] = mapped_column(String(30))
    comments_for_author: Mapped[str] = mapped_column(Text, default="", server_default="")
    comments_for_editor: Mapped[str] = mapped_column(Text, default="", server_default="")
    # The form's questions as they were at the invitation, and the reviewer's answers by question id.
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # The editor's rating of the review, 1 to 5; used when suggesting reviewers.
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    acknowledged_at: Mapped[datetime | None]
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    reviewer: Mapped[User] = relationship(foreign_keys=[reviewer_id], lazy="selectin")
    round: Mapped[ReviewRound] = relationship(lazy="selectin")

    __mapper_args__: dict[str, Any] = {"version_id_col": row_version}  # noqa: RUF012


class ReviewForm(TimestampMixin, Base):
    """Questions reviewers answer. Answers are stored with each review, keyed by question id."""

    __tablename__ = "review_forms"

    id: Mapped[int] = id_column()
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"version_id_col": version}  # noqa: RUF012


class ReviewReminder(Base):
    """A reminder already sent, so the hourly job never sends the same one twice."""

    __tablename__ = "review_reminders"
    __table_args__ = (UniqueConstraint("assignment_id", "kind", "offset_days", "due"),)

    id: Mapped[int] = id_column()
    assignment_id: Mapped[int] = mapped_column(ForeignKey("review_assignments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # "response" or "review"
    offset_days: Mapped[int] = mapped_column(Integer)
    # The due date the reminder was about: moving the deadline makes reminders due again.
    due: Mapped[date]
    sent_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
