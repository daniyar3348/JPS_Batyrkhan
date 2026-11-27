"""Letters about decisions, and other e-mails of the editorial workflow.

Decision letters are shown to the editor before sending and can be changed; the templates are the
starting point. Reviewers' comments are added through {reviewerComments}, signed "Reviewer 1",
"Reviewer 2"... (their names only in open review)."""

from __future__ import annotations

from app.modules.journals.email_templates import TemplateSpec, register

GROUP = "Decisions"

LETTER = {
    "submissionNumber": "Manuscript number",
    "submissionTitle": "Title of the manuscript",
    "submissionUrl": "Link to the manuscript in the editorial workspace",
    "editorName": "Name of the editor who made the decision",
}
WITH_REVIEWS = {**LETTER, "reviewerComments": "The reviewers' comments for the authors, one after another"}


def _letter(
    key: str, name: str, description: str, subject: str, body: str, *, reviews: bool = False
) -> TemplateSpec:
    return register(
        TemplateSpec(
            key=key,
            group=GROUP,
            name=name,
            description=description,
            recipient="Authors",
            subject=subject,
            body=body,
            variables=WITH_REVIEWS if reviews else LETTER,
        )
    )


SEND_TO_REVIEW = _letter(
    "decision_send_to_review",
    "Sent to review",
    "The editor sends the manuscript to peer review.",
    "{submissionNumber}: your manuscript is under review",
    "Dear {recipientName},\n\n"
    "Your manuscript “{submissionTitle}” ({submissionNumber}) has passed the editorial check and "
    "has been sent to peer review. We will write to you when the reviews are in.\n\n"
    "You can follow its progress here:\n\n{submissionUrl}\n\n"
    "{editorName}\n{journalName}",
)

ACCEPT = _letter(
    "decision_accept",
    "Accepted",
    "The editor accepts the manuscript.",
    "{submissionNumber}: accepted for publication",
    "Dear {recipientName},\n\n"
    "I am pleased to tell you that your manuscript “{submissionTitle}” has been accepted for "
    "publication in {journalName}.\n\n"
    "{reviewerComments}\n\n"
    "We will contact you about the next steps: copyediting and proofs.\n\n"
    "{editorName}\n{journalName}",
    reviews=True,
)

DESK_DECLINE = _letter(
    "decision_desk_decline",
    "Declined without review",
    "The editor declines the manuscript before peer review.",
    "{submissionNumber}: decision on your manuscript",
    "Dear {recipientName},\n\n"
    "Thank you for submitting “{submissionTitle}” to {journalName}. After an editorial assessment, "
    "I regret that we cannot consider it further. This decision does not necessarily reflect on the "
    "quality of the work: the journal receives many more manuscripts than it can publish, and we "
    "send to review only those that fit its scope best.\n\n"
    "{editorName}\n{journalName}",
)

DECLINE = _letter(
    "decision_decline",
    "Declined after review",
    "The editor declines the manuscript after peer review.",
    "{submissionNumber}: decision on your manuscript",
    "Dear {recipientName},\n\n"
    "Thank you for submitting “{submissionTitle}” to {journalName}. Having considered the reviews, "
    "I regret that we are unable to publish it. The reviewers' comments are below; we hope they "
    "will be useful.\n\n"
    "{reviewerComments}\n\n"
    "{editorName}\n{journalName}",
    reviews=True,
)

REVISIONS = _letter(
    "decision_revisions",
    "Revisions requested",
    "The editor asks for revisions that will not go to another round of review.",
    "{submissionNumber}: revisions requested",
    "Dear {recipientName},\n\n"
    "The reviews of your manuscript “{submissionTitle}” are in. Before we can accept it, please "
    "revise it to address the comments below.\n\n"
    "{reviewerComments}\n\n"
    "Upload the revised manuscript, with a reply to each comment, here:\n\n{submissionUrl}\n\n"
    "{editorName}\n{journalName}",
    reviews=True,
)

RESUBMIT = _letter(
    "decision_resubmit",
    "Revise and resubmit",
    "The editor asks for a revision that will go to another round of review.",
    "{submissionNumber}: please revise and resubmit",
    "Dear {recipientName},\n\n"
    "The reviews of your manuscript “{submissionTitle}” are in. The reviewers see merit in the work "
    "but ask for substantial changes. We invite you to revise it; the revised manuscript will be "
    "reviewed again.\n\n"
    "{reviewerComments}\n\n"
    "Upload the revised manuscript, with a reply to each comment, here:\n\n{submissionUrl}\n\n"
    "{editorName}\n{journalName}",
    reviews=True,
)

NEW_ROUND = _letter(
    "decision_new_round",
    "New round of review",
    "The editor sends the manuscript to another round of review.",
    "{submissionNumber}: sent for another round of review",
    "Dear {recipientName},\n\n"
    "Thank you for revising “{submissionTitle}”. The manuscript has been sent for another round of "
    "review. We will write to you when the reviews are in.\n\n"
    "{editorName}\n{journalName}",
)

REINSTATE = _letter(
    "decision_reinstate",
    "Reinstated",
    "The editor reinstates a declined manuscript.",
    "{submissionNumber}: your manuscript is being considered again",
    "Dear {recipientName},\n\n"
    "We are writing to let you know that your manuscript “{submissionTitle}” is being considered "
    "again. We apologise for any confusion. You can follow its progress here:\n\n{submissionUrl}\n\n"
    "{editorName}\n{journalName}",
)

RECOMMENDATION = register(
    TemplateSpec(
        key="decision_recommendation",
        group=GROUP,
        name="Recommendation (to editors)",
        description="Sent to the deciding editors when an editor recommends a decision.",
        recipient="Editors",
        subject="{submissionNumber}: {editorName} recommends “{recommendation}”",
        body=(
            "Dear {recipientName},\n\n"
            "{editorName} recommends “{recommendation}” for {submissionNumber}, “{submissionTitle}”.\n\n"
            "{comment}\n\n"
            "Record the decision here:\n\n{submissionUrl}"
        ),
        variables={
            **LETTER,
            "recommendation": "The recommended decision",
            "comment": "The recommending editor's note",
        },
    )
)

WITHDRAWN = register(
    TemplateSpec(
        key="submission_withdrawn_editor",
        group="Submission",
        name="Manuscript withdrawn (to editors)",
        description="Sent to the manuscript's editors when the authors withdraw it.",
        recipient="Editors",
        subject="{submissionNumber} has been withdrawn",
        body=(
            "Dear {recipientName},\n\n"
            "The authors have withdrawn {submissionNumber}, “{submissionTitle}”.\n\n"
            "Their reason: {reason}\n\n{submissionUrl}"
        ),
        variables={
            "submissionNumber": LETTER["submissionNumber"],
            "submissionTitle": LETTER["submissionTitle"],
            "submissionUrl": LETTER["submissionUrl"],
            "reason": "The reason the authors gave",
        },
    )
)

EDITOR_ASSIGNED = register(
    TemplateSpec(
        key="editor_assigned",
        group="Submission",
        name="Editor assigned",
        description="Sent to an editor assigned to handle a manuscript.",
        recipient="Editor",
        subject="You are handling {submissionNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "{assignedBy} has asked you to handle {submissionNumber}, “{submissionTitle}”{roleNote}.\n\n"
            "Open it here:\n\n{submissionUrl}"
        ),
        variables={
            "submissionNumber": LETTER["submissionNumber"],
            "submissionTitle": LETTER["submissionTitle"],
            "submissionUrl": LETTER["submissionUrl"],
            "assignedBy": "Name of the editor who made the assignment",
            "roleNote": "Says whether the editor may decide or only recommend",
        },
    )
)

DISCUSSION_MESSAGE = register(
    TemplateSpec(
        key="discussion_message",
        group="Submission",
        name="New message in a discussion",
        description="Sent to the people in a discussion when someone writes in it.",
        recipient="Discussion participants",
        subject="{submissionNumber}: {discussionSubject}",
        body=(
            "Dear {recipientName},\n\n"
            "{messageAuthor} wrote in the discussion “{discussionSubject}” about {submissionNumber}:\n\n"
            "{messageText}\n\n"
            "Reply here:\n\n{submissionUrl}"
        ),
        variables={
            "submissionNumber": LETTER["submissionNumber"],
            "submissionUrl": LETTER["submissionUrl"],
            "discussionSubject": "Subject of the discussion",
            "messageAuthor": "Name of the person who wrote",
            "messageText": "The message",
        },
    )
)
