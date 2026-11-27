"""Suggest reviewers for a manuscript (§6.6 of the architecture).

Candidates are the journal's reviewers. Excluded: the manuscript's authors and editors, people
already asked in this round, and anyone who declined it because of a conflict of interest.
Warned about: the same institution as an author, or a refusal in an earlier round.
Ranked by how well their interests match the manuscript, how they reviewed before, and how busy
they are now.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Float, case, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import escape_like
from app.modules.identity.models import User
from app.modules.identity.schemas import UserSummary
from app.modules.journals.models import UserRole
from app.modules.journals.permissions import Role
from app.modules.review.models import (
    OPEN_STATUSES,
    AssignmentStatus,
    DeclineReason,
    ReviewAssignment,
    ReviewRound,
)
from app.modules.review.schemas import Suggestion
from app.modules.submissions.models import ParticipantRole, Submission

WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "of", "on"),
        *("or", "the", "to", "with", "we", "our", "this", "that", "these", "using", "study", "analysis"),
        *("results", "based", "effect", "effects", "new", "between", "their", "its"),
    }
)
LIMIT = 30


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if len(w) > 2 and w not in STOP_WORDS}


@dataclass
class Stats:
    active: int = 0
    completed: int = 0
    declined: int = 0
    invited_total: int = 0
    average_days: float | None = None
    average_rating: float | None = None


async def reviewer_stats(db: AsyncSession, user_ids: Sequence[int]) -> dict[int, Stats]:
    if not user_ids:
        return {}
    completed = ReviewAssignment.status == AssignmentStatus.COMPLETED
    days = extract("epoch", ReviewAssignment.completed_at - ReviewAssignment.responded_at) / 86400
    rows = await db.execute(
        select(
            ReviewAssignment.reviewer_id,
            func.count().filter(ReviewAssignment.status.in_(OPEN_STATUSES)),
            func.count().filter(completed),
            func.count().filter(ReviewAssignment.status == AssignmentStatus.DECLINED),
            func.count().filter(ReviewAssignment.status != AssignmentStatus.CANCELLED),
            func.avg(case((completed, days))),
            func.avg(cast(ReviewAssignment.rating, Float)),
        )
        .where(ReviewAssignment.reviewer_id.in_(list(user_ids)))
        .group_by(ReviewAssignment.reviewer_id)
    )
    return {
        reviewer_id: Stats(
            active=active,
            completed=done,
            declined=declined,
            invited_total=total,
            average_days=float(avg_days) if avg_days is not None else None,
            average_rating=float(avg_rating) if avg_rating is not None else None,
        )
        for reviewer_id, active, done, declined, total, avg_days, avg_rating in rows
    }


def interest_matches(interests: Sequence[str], keywords: Sequence[str]) -> list[str]:
    """Keywords of the manuscript that one of the reviewer's interests covers."""
    matched = []
    lowered = [i.lower().strip() for i in interests if i.strip()]
    for keyword in keywords:
        k = keyword.lower().strip()
        if k and any(k == i or k in i or i in k for i in lowered):
            matched.append(keyword)
    return matched


async def suggest(
    db: AsyncSession,
    *,
    journal_id: int,
    submission: Submission,
    review_round: ReviewRound,
    viewer_id: int,
    query: str | None,
) -> list[Suggestion]:
    publication = submission.publication
    contributors = publication.contributors
    author_emails = {c.email.lower() for c in contributors} | {submission.submitter.email.lower()}
    author_orcids = {c.orcid for c in contributors if c.orcid}
    author_affiliations = {c.affiliation.lower().strip() for c in contributors if c.affiliation.strip()}
    editor_ids = {p.user_id for p in submission.participants if p.role == ParticipantRole.EDITOR} | {
        viewer_id
    }

    history = (
        await db.execute(
            select(
                ReviewAssignment.reviewer_id,
                ReviewAssignment.round_id,
                ReviewAssignment.status,
                ReviewAssignment.decline_reason,
            ).where(ReviewAssignment.submission_id == submission.id)
        )
    ).all()
    asked_now = {
        r
        for r, round_id, status, _ in history
        if round_id == review_round.id and status != AssignmentStatus.CANCELLED
    }
    conflicted = {r for r, _, status, reason in history if reason == DeclineReason.CONFLICT_OF_INTEREST}
    declined_before = {
        r
        for r, round_id, status, _ in history
        if round_id != review_round.id and status == AssignmentStatus.DECLINED
    }

    candidates = (
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            UserRole.journal_id == journal_id,
            UserRole.role == Role.REVIEWER.value,
            User.is_active.is_(True),
        )
    )
    if query and query.strip():
        pattern = f"%{escape_like(query.strip().lower())}%"
        candidates = candidates.where(
            or_(
                func.lower(User.given_name + " " + User.family_name).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"),
                func.lower(User.affiliation).like(pattern, escape="\\"),
                func.lower(func.array_to_string(User.interests, " ")).like(pattern, escape="\\"),
            )
        )
    users = [
        u
        for u in (await db.scalars(candidates)).all()
        if u.email.lower() not in author_emails
        and (u.orcid is None or u.orcid not in author_orcids)
        and u.id not in editor_ids
        and u.id not in asked_now
        and u.id not in conflicted
    ]
    stats = await reviewer_stats(db, [u.id for u in users])
    manuscript_words = words(" ".join([publication.title, publication.abstract, *publication.keywords]))

    suggestions = []
    for user in users:
        s = stats.get(user.id, Stats())
        matched = interest_matches(user.interests, publication.keywords)
        overlap = len(manuscript_words & words(" ".join(user.interests)))
        declined_share = s.declined / s.invited_total if s.invited_total else None
        score = 10.0 * len(matched) + 2.0 * overlap
        if s.average_rating is not None:
            score += s.average_rating
        score -= 3.0 * s.active
        if declined_share is not None:
            score -= 5.0 * declined_share
        warnings = []
        if user.affiliation.strip() and user.affiliation.lower().strip() in author_affiliations:
            warnings.append("Same institution as an author")
        if user.id in declined_before:
            warnings.append("Declined to review this manuscript in an earlier round")
        if s.active >= 3:
            warnings.append(f"Already has {s.active} open reviews")
        suggestions.append(
            Suggestion(
                reviewer=UserSummary.of(user),
                interests=list(user.interests),
                score=round(score, 2),
                matched_keywords=matched,
                warnings=warnings,
                active_reviews=s.active,
                completed_reviews=s.completed,
                average_days=round(s.average_days, 1) if s.average_days is not None else None,
                average_rating=round(s.average_rating, 1) if s.average_rating is not None else None,
                declined_share=round(declined_share, 2) if declined_share is not None else None,
            )
        )
    suggestions.sort(key=lambda item: (-item.score, item.reviewer.full_name))
    return suggestions[:LIMIT]
