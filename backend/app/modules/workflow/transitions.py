"""Every editorial decision and what it does, in one table (sections 6.1 and 6.2 of the architecture).

Every change of a manuscript's stage or status goes through ``RULES``: the service looks up the
decision, checks that it is allowed where the manuscript is now, and applies exactly what the rule
says. Adding a decision means adding a row here (and its letter in ``emails.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.modules.review.models import RoundStatus
from app.modules.submissions.models import Stage, SubmissionStatus


class Decision(StrEnum):
    SEND_TO_REVIEW = "send_to_review"
    ACCEPT = "accept"
    DECLINE = "decline"
    REQUEST_REVISIONS = "request_revisions"  # the author revises; the editor decides without new reviews
    RESUBMIT = "resubmit"  # the author revises; the revision goes to a new round of review
    NEW_ROUND = "new_round"
    REINSTATE = "reinstate"  # undo a decline
    RECOMMEND_ACCEPT = "recommend_accept"
    RECOMMEND_REVISIONS = "recommend_revisions"
    RECOMMEND_RESUBMIT = "recommend_resubmit"
    RECOMMEND_DECLINE = "recommend_decline"
    WITHDRAW = "withdraw"  # by the author


class RoundEffect(StrEnum):
    NONE = "none"
    START = "start"  # open a round with copies of the chosen files
    CLOSE = "close"  # end the current round; open requests are cancelled
    REVISIONS = "revisions"  # the current round waits for revisions
    RESUBMIT = "resubmit"  # the current round waits for a revision to review again


QUEUED = frozenset({SubmissionStatus.QUEUED})


@dataclass(frozen=True)
class Rule:
    decision: Decision
    label: str
    description: str
    stages: frozenset[str]
    statuses: frozenset[str] = QUEUED
    to_stage: str | None = None  # None: stays where it is
    to_status: str | None = None
    round: RoundEffect = RoundEffect.NONE
    # The letter to the authors, by the stage the manuscript is in. Empty: no letter.
    letters: Mapping[str, str] = field(default_factory=dict)
    recommendation: bool = False
    needs_reason: bool = False
    # Rounds in these states allow the decision (review stage only); empty means any.
    round_statuses: frozenset[str] = frozenset()

    @property
    def needs_files(self) -> bool:
        return self.round == RoundEffect.START


IN_REVIEW = frozenset({Stage.REVIEW})
BEFORE_COPYEDITING = frozenset({Stage.SUBMISSION, Stage.REVIEW})
OPEN_ROUND = frozenset({RoundStatus.REVIEW, RoundStatus.REVISIONS_SUBMITTED})

RULES: dict[Decision, Rule] = {
    rule.decision: rule
    for rule in [
        Rule(
            Decision.SEND_TO_REVIEW,
            "Send to review",
            "Start the first round of peer review. Choose the files reviewers will receive.",
            stages=frozenset({Stage.SUBMISSION}),
            to_stage=Stage.REVIEW,
            round=RoundEffect.START,
            letters={Stage.SUBMISSION: "decision_send_to_review"},
        ),
        Rule(
            Decision.ACCEPT,
            "Accept",
            "Accept the manuscript for publication. It moves on to copyediting.",
            stages=BEFORE_COPYEDITING,
            to_stage=Stage.COPYEDITING,
            round=RoundEffect.CLOSE,
            letters={Stage.SUBMISSION: "decision_accept", Stage.REVIEW: "decision_accept"},
        ),
        Rule(
            Decision.DECLINE,
            "Decline",
            "Decline the manuscript. It can be reinstated later if this was a mistake.",
            stages=BEFORE_COPYEDITING,
            to_status=SubmissionStatus.DECLINED,
            round=RoundEffect.CLOSE,
            letters={Stage.SUBMISSION: "decision_desk_decline", Stage.REVIEW: "decision_decline"},
        ),
        Rule(
            Decision.REQUEST_REVISIONS,
            "Request revisions",
            "Ask the authors to revise. You will decide on the revision without another round of review.",
            stages=IN_REVIEW,
            round=RoundEffect.REVISIONS,
            letters={Stage.REVIEW: "decision_revisions"},
            round_statuses=OPEN_ROUND,
        ),
        Rule(
            Decision.RESUBMIT,
            "Revise and resubmit",
            "Ask the authors to revise. The revision will go to a new round of review.",
            stages=IN_REVIEW,
            round=RoundEffect.RESUBMIT,
            letters={Stage.REVIEW: "decision_resubmit"},
            round_statuses=OPEN_ROUND,
        ),
        Rule(
            Decision.NEW_ROUND,
            "New review round",
            "Start another round of review, usually with the authors' revised files.",
            stages=IN_REVIEW,
            round=RoundEffect.START,
            letters={Stage.REVIEW: "decision_new_round"},
        ),
        Rule(
            Decision.REINSTATE,
            "Reinstate",
            "Undo the decline and return the manuscript to where it was.",
            stages=BEFORE_COPYEDITING,
            statuses=frozenset({SubmissionStatus.DECLINED}),
            to_status=SubmissionStatus.QUEUED,
            letters={Stage.SUBMISSION: "decision_reinstate", Stage.REVIEW: "decision_reinstate"},
            needs_reason=True,
        ),
        Rule(
            Decision.RECOMMEND_ACCEPT,
            "Recommend accepting",
            "Recommend to the deciding editors that the manuscript is accepted.",
            stages=BEFORE_COPYEDITING,
            recommendation=True,
        ),
        Rule(
            Decision.RECOMMEND_REVISIONS,
            "Recommend revisions",
            "Recommend asking the authors for revisions.",
            stages=IN_REVIEW,
            recommendation=True,
        ),
        Rule(
            Decision.RECOMMEND_RESUBMIT,
            "Recommend revise and resubmit",
            "Recommend asking for a revision that goes to a new round of review.",
            stages=IN_REVIEW,
            recommendation=True,
        ),
        Rule(
            Decision.RECOMMEND_DECLINE,
            "Recommend declining",
            "Recommend declining the manuscript.",
            stages=BEFORE_COPYEDITING,
            recommendation=True,
        ),
        Rule(
            Decision.WITHDRAW,
            "Withdraw",
            "The authors withdraw the manuscript.",
            stages=BEFORE_COPYEDITING,
            to_status=SubmissionStatus.WITHDRAWN,
            round=RoundEffect.CLOSE,
            needs_reason=True,
        ),
    ]
}

EDITOR_DECISIONS = [d for d, r in RULES.items() if not r.recommendation and d != Decision.WITHDRAW]
RECOMMENDATIONS = [d for d, r in RULES.items() if r.recommendation]


def allowed_here(rule: Rule, *, stage: str, status: str, round_status: str | None) -> bool:
    if stage not in rule.stages or status not in rule.statuses:
        return False
    # Decisions tied to the state of the review round need the round to be in one of their states.
    return not rule.round_statuses or round_status in rule.round_statuses
