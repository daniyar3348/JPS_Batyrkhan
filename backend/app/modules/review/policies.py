"""What each person sees of peer review. Blind review is enforced here: a field the viewer may not
see is never put into the response."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from app.modules.files.models import FileStage, FileStatus, SubmissionFile
from app.modules.identity.schemas import UserSummary
from app.modules.journals.review_settings import ReviewMethod
from app.modules.review.forms import questions_of
from app.modules.review.models import AssignmentStatus, ReviewAssignment, ReviewRound, RoundStatus
from app.modules.review.schemas import (
    AssignmentOut,
    AuthorAnswer,
    AuthorReviewOut,
    ReviewerAssignmentOut,
    ReviewerManuscript,
    ReviewerTask,
    RoundOut,
)
from app.modules.review.service import is_overdue
from app.modules.submissions.models import Submission
from app.modules.submissions.policies import Access
from app.modules.submissions.schemas import FileOut, SectionRef


def round_files_url(submission_id: int, round_id: int) -> str:
    return f"/api/v1/submissions/{submission_id}/review-rounds/{round_id}/files"


def reviewer_files_url(assignment_id: int) -> str:
    return f"/api/v1/reviews/{assignment_id}/files"


def reviews_visible_to_author(review_round: ReviewRound) -> bool:
    """Authors read the reviews once the editor has decided what happens after the round."""
    return review_round.status != RoundStatus.REVIEW


def author_may_download(
    record: SubmissionFile, review_round: ReviewRound, assignments: Iterable[ReviewAssignment]
) -> bool:
    if record.file_stage == FileStage.REVISION:
        return True
    if record.file_stage == FileStage.REVIEW_ATTACHMENT and reviews_visible_to_author(review_round):
        completed = {a.id for a in assignments if a.status == AssignmentStatus.COMPLETED}
        return record.review_assignment_id in completed
    return False


# ---------------------------------------------------------------------- editors


def editor_view(
    assignment: ReviewAssignment, attachments: Sequence[SubmissionFile], last_reminded: datetime | None
) -> AssignmentOut:
    url = round_files_url(assignment.submission_id, assignment.round_id)
    return AssignmentOut(
        id=assignment.id,
        round_id=assignment.round_id,
        round_number=assignment.round.number,
        reviewer=UserSummary.of(assignment.reviewer),
        reviewer_number=assignment.reviewer_number,
        method=ReviewMethod(assignment.method),
        status=assignment.status,
        invited_at=assignment.invited_at,
        response_due=assignment.response_due,
        review_due=assignment.review_due,
        responded_at=assignment.responded_at,
        completed_at=assignment.completed_at,
        overdue=is_overdue(assignment),
        decline_reason=assignment.decline_reason,
        decline_comment=assignment.decline_comment,
        competing_interests=assignment.competing_interests,
        recommendation=assignment.recommendation,
        comments_for_author=assignment.comments_for_author,
        comments_for_editor=assignment.comments_for_editor,
        questions=questions_of(assignment.questions),
        answers=dict(assignment.answers),
        rating=assignment.rating,
        acknowledged_at=assignment.acknowledged_at,
        attachments=[FileOut.of(f, files_url=url) for f in attachments],
        last_reminded_at=last_reminded,
    )


# ---------------------------------------------------------------------- authors


def author_label(assignment: ReviewAssignment) -> str:
    if assignment.method == ReviewMethod.OPEN:
        return assignment.reviewer.full_name
    return f"Reviewer {assignment.reviewer_number}"


def answer_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def author_view(assignment: ReviewAssignment, attachments: Sequence[SubmissionFile]) -> AuthorReviewOut:
    url = round_files_url(assignment.submission_id, assignment.round_id)
    answers = [
        AuthorAnswer(question=q.label, answer=answer_text(assignment.answers[q.id]))
        for q in questions_of(assignment.questions)
        if q.visible_to_author and q.id in assignment.answers
    ]
    return AuthorReviewOut(
        label=author_label(assignment),
        comments=assignment.comments_for_author,
        answers=answers,
        attachments=[
            FileOut.of(f, files_url=url) for f in attachments if f.current.status == FileStatus.READY
        ],
    )


def round_view(
    review_round: ReviewRound,
    access: Access,
    *,
    assignments: Sequence[ReviewAssignment],
    files: Sequence[SubmissionFile],
    last_reminders: dict[int, datetime],
) -> RoundOut:
    url = round_files_url(review_round.submission_id, review_round.id)
    attachments: dict[int, list[SubmissionFile]] = {}
    for record in files:
        if record.file_stage == FileStage.REVIEW_ATTACHMENT and record.review_assignment_id is not None:
            attachments.setdefault(record.review_assignment_id, []).append(record)
    revisions = [FileOut.of(f, files_url=url) for f in files if f.file_stage == FileStage.REVISION]
    if access.is_editor:
        return RoundOut(
            id=review_round.id,
            number=review_round.number,
            status=review_round.status,
            created_at=review_round.created_at,
            closed_at=review_round.closed_at,
            author_response=review_round.author_response,
            revisions_submitted_at=review_round.revisions_submitted_at,
            review_files=[FileOut.of(f, files_url=url) for f in files if f.file_stage == FileStage.REVIEW],
            revision_files=revisions,
            assignments=[
                editor_view(a, attachments.get(a.id, []), last_reminders.get(a.id)) for a in assignments
            ],
            reviews_for_author=None,
        )
    reviews = None
    if reviews_visible_to_author(review_round):
        reviews = [
            author_view(a, attachments.get(a.id, []))
            for a in sorted(assignments, key=lambda a: a.reviewer_number)
            if a.status == AssignmentStatus.COMPLETED
        ]
    return RoundOut(
        id=review_round.id,
        number=review_round.number,
        status=review_round.status,
        created_at=review_round.created_at,
        closed_at=review_round.closed_at,
        author_response=review_round.author_response,
        revisions_submitted_at=review_round.revisions_submitted_at,
        review_files=[],
        revision_files=revisions,
        assignments=None,
        reviews_for_author=reviews,
    )


# ---------------------------------------------------------------------- reviewers


def reviewer_manuscript(submission: Submission, method: str) -> ReviewerManuscript:
    publication = submission.publication
    blind_to_authors = method == ReviewMethod.DOUBLE_BLIND
    section = submission.section
    return ReviewerManuscript(
        title=publication.title,
        subtitle=publication.subtitle,
        abstract=publication.abstract,
        keywords=list(publication.keywords),
        section=SectionRef(id=section.id, title=section.title, abbreviation=section.abbreviation),
        references=publication.references,
        authors=None
        if blind_to_authors
        else [
            f"{c.full_name}" + (f" ({c.affiliation})" if c.affiliation else "")
            for c in publication.contributors
            if c.in_byline
        ],
        # The covering letter often names the authors; double-blind reviewers do not get it.
        comments_for_editor=None if blind_to_authors else submission.comments_for_editor,
    )


def reviewer_task(assignment: ReviewAssignment, submission: Submission) -> ReviewerTask:
    return ReviewerTask(
        id=assignment.id,
        title=submission.publication.title,
        round_number=assignment.round.number,
        status=assignment.status,
        method=ReviewMethod(assignment.method),
        invited_at=assignment.invited_at,
        response_due=assignment.response_due,
        review_due=assignment.review_due,
        overdue=is_overdue(assignment),
        completed_at=assignment.completed_at,
    )


def reviewer_view(
    assignment: ReviewAssignment,
    submission: Submission,
    *,
    review_files: Sequence[SubmissionFile],
    attachments: Sequence[SubmissionFile],
    guidelines: str,
) -> ReviewerAssignmentOut:
    url = reviewer_files_url(assignment.id)
    accepted = assignment.status in (AssignmentStatus.ACCEPTED, AssignmentStatus.COMPLETED)
    questions = questions_of(assignment.questions)
    return ReviewerAssignmentOut(
        id=assignment.id,
        status=assignment.status,
        method=ReviewMethod(assignment.method),
        round_number=assignment.round.number,
        invited_at=assignment.invited_at,
        response_due=assignment.response_due,
        review_due=assignment.review_due,
        overdue=is_overdue(assignment),
        responded_at=assignment.responded_at,
        completed_at=assignment.completed_at,
        can_edit=assignment.status == AssignmentStatus.ACCEPTED
        and assignment.round.status != RoundStatus.CLOSED,
        manuscript=reviewer_manuscript(submission, assignment.method),
        # Until the reviewer accepts, the title and abstract are all they see.
        files=[FileOut.of(f, files_url=url) for f in review_files if f.current.status == FileStatus.READY]
        if accepted
        else [],
        guidelines=guidelines,
        questions=questions,
        answers=dict(assignment.answers),
        recommendation=assignment.recommendation,
        comments_for_author=assignment.comments_for_author,
        comments_for_editor=assignment.comments_for_editor,
        competing_interests=assignment.competing_interests,
        attachments=[FileOut.of(f, files_url=url) for f in attachments],
        row_version=assignment.row_version,
    )
