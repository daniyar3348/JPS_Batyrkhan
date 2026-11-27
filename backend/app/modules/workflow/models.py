from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, id_column, utcnow
from app.modules.identity.models import User


class EditorialDecision(Base):
    """A decision on a manuscript (or a recommendation for one), with the letter sent to the authors."""

    __tablename__ = "editorial_decisions"
    __table_args__ = (Index("ix_editorial_decisions_submission", "submission_id", "created_at"),)

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    round_id: Mapped[int | None] = mapped_column(ForeignKey("review_rounds.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(30))
    is_recommendation: Mapped[bool] = mapped_column(default=False, server_default="false")
    stage_before: Mapped[str] = mapped_column(String(20))
    stage_after: Mapped[str] = mapped_column(String(20))
    status_after: Mapped[str] = mapped_column(String(20))
    made_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Why (reinstating, withdrawing) or the editor's note with a recommendation.
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    letter_to: Mapped[list[str]] = mapped_column(ARRAY(String(320)), default=list, server_default="{}")
    letter_subject: Mapped[str | None] = mapped_column(String(300))
    letter_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())

    made_by: Mapped[User | None] = relationship(lazy="selectin")


class Discussion(TimestampMixin, Base):
    """A conversation about a manuscript between some of the people working on it."""

    __tablename__ = "discussions"

    id: Mapped[int] = id_column()
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(300))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_closed: Mapped[bool] = mapped_column(default=False, server_default="false")

    participants: Mapped[list[User]] = relationship(
        secondary="discussion_participants", lazy="selectin", order_by=(User.family_name, User.given_name)
    )
    messages: Mapped[list[DiscussionMessage]] = relationship(
        lazy="selectin", order_by="DiscussionMessage.id", cascade="all, delete-orphan"
    )


class DiscussionParticipant(Base):
    __tablename__ = "discussion_participants"

    discussion_id: Mapped[int] = mapped_column(
        ForeignKey("discussions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class DiscussionMessage(Base):
    __tablename__ = "discussion_messages"

    id: Mapped[int] = id_column()
    discussion_id: Mapped[int] = mapped_column(ForeignKey("discussions.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())

    author: Mapped[User | None] = relationship(lazy="selectin")
