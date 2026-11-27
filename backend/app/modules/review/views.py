"""Assemble review data for one viewer (the rules about what they may see are in ``policies.py``)."""

from __future__ import annotations

from app.modules.review.policies import round_view
from app.modules.review.schemas import RoundOut
from app.modules.review.service import ReviewService
from app.modules.submissions.models import Submission
from app.modules.submissions.policies import Access


async def round_views(service: ReviewService, submission: Submission, access: Access) -> list[RoundOut]:
    rounds = await service.rounds(submission.id)
    if not rounds:
        return []
    assignments = await service.assignments(submission.id)
    files = await service.files.list_for_rounds([r.id for r in rounds])
    reminders = await service.last_reminders([a.id for a in assignments]) if access.is_editor else {}
    return [
        round_view(
            review_round,
            access,
            assignments=[a for a in assignments if a.round_id == review_round.id],
            files=[f for f in files if f.review_round_id == review_round.id],
            last_reminders=reminders,
        )
        for review_round in rounds
    ]
