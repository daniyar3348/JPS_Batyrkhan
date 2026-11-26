"""Who may see and change a submission, and in which capacity (author or editor)."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.journals.deps import Principal
from app.modules.journals.permissions import Capability
from app.modules.submissions.models import Submission, SubmissionStatus


@dataclass(frozen=True)
class Access:
    is_author: bool
    is_editor: bool
    can_edit: bool

    @property
    def can_view(self) -> bool:
        return self.is_author or self.is_editor


def is_author(principal: Principal, submission: Submission) -> bool:
    user = principal.user
    if submission.submitter_id == user.id:
        return True
    return any(c.user_id == user.id or c.email == user.email for c in submission.publication.contributors)


def is_section_editor(principal: Principal, submission: Submission) -> bool:
    return any(editor.id == principal.user.id for editor in submission.section.editors)


def access_for(principal: Principal, submission: Submission) -> Access:
    is_submitter = submission.submitter_id == principal.user.id
    if submission.status == SubmissionStatus.DRAFT:
        # A draft is private to the person preparing it, editors included.
        return Access(is_author=is_submitter, is_editor=False, can_edit=is_submitter)
    if is_author(principal, submission):
        # An editor never handles their own manuscript as an editor.
        return Access(is_author=True, is_editor=False, can_edit=False)
    editor = principal.can(Capability.SUBMISSIONS_VIEW_ALL) or is_section_editor(principal, submission)
    return Access(is_author=False, is_editor=editor, can_edit=False)
