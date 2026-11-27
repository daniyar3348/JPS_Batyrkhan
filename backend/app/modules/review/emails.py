"""E-mails about peer review. None of the reviewer e-mails can name the authors: their templates do
not offer such placeholders, so a template edited by the journal cannot add them either."""

from __future__ import annotations

from app.modules.journals.email_templates import TemplateSpec, register

GROUP = "Peer review"

FOR_REVIEWER = {
    "submissionTitle": "Title of the manuscript",
    "submissionAbstract": "Abstract of the manuscript",
    "sectionTitle": "Section of the journal",
    "reviewUrl": "Link to the review in the editorial workspace",
    "responseDueDate": "Date by which the reviewer should accept or decline",
    "reviewDueDate": "Date by which the review is due",
    "editorName": "Name of the editor who sends the e-mail",
}

FOR_EDITOR = {
    "submissionNumber": "Manuscript number",
    "submissionTitle": "Title of the manuscript",
    "submissionUrl": "Link to the manuscript in the editorial workspace",
    "reviewerName": "Name of the reviewer",
}

REQUEST = register(
    TemplateSpec(
        key="review_request",
        group=GROUP,
        name="Review request",
        description="Invites a reviewer. The editor can change the text before sending.",
        recipient="Reviewer",
        subject="Invitation to review a manuscript for {journalName}",
        body=(
            "Dear {recipientName},\n\n"
            "I would like to invite you to review the following manuscript submitted to {journalName}:\n\n"
            "  {submissionTitle}\n\n"
            "Abstract:\n{submissionAbstract}\n\n"
            "Please let us know whether you can review it by {responseDueDate}. If you accept, the review "
            "is due on {reviewDueDate}. You can accept or decline, and later send the review, here:\n\n"
            "{reviewUrl}\n\n"
            "{accountNote}"
            "Thank you for considering this request.\n\n"
            "{editorName}\n{journalName}"
        ),
        variables={
            **FOR_REVIEWER,
            "accountNote": "For reviewers new to the journal: a note that a separate e-mail sets up their account",
        },
    )
)

RESPONSE_REMINDER = register(
    TemplateSpec(
        key="review_response_reminder",
        group=GROUP,
        name="Reminder: answer the review request",
        description="Sent automatically when a reviewer has not answered an invitation by its date.",
        recipient="Reviewer",
        subject="Reminder: review request from {journalName}",
        body=(
            "Dear {recipientName},\n\n"
            "On behalf of {journalName}, we asked whether you could review this manuscript:\n\n"
            "  {submissionTitle}\n\n"
            "We would be grateful to hear whether you can do it, even if the answer is no:\n\n"
            "{reviewUrl}\n\n"
            "{journalName}"
        ),
        variables=FOR_REVIEWER,
    )
)

REVIEW_REMINDER = register(
    TemplateSpec(
        key="review_reminder",
        group=GROUP,
        name="Reminder: review due",
        description="Sent automatically before and after the review deadline, or by an editor.",
        recipient="Reviewer",
        subject="Reminder: review due on {reviewDueDate}",
        body=(
            "Dear {recipientName},\n\n"
            "Thank you for agreeing to review this manuscript for {journalName}:\n\n"
            "  {submissionTitle}\n\n"
            "This is a reminder that the review is due on {reviewDueDate}. You can send it here:\n\n"
            "{reviewUrl}\n\n"
            "If you need more time, please reply and let us know.\n\n"
            "{journalName}"
        ),
        variables=FOR_REVIEWER,
    )
)

CANCELLED = register(
    TemplateSpec(
        key="review_cancelled",
        group=GROUP,
        name="Review no longer needed",
        description="Sent when an editor cancels a review request, or a decision makes it unnecessary.",
        recipient="Reviewer",
        subject="Review no longer needed: {submissionTitle}",
        body=(
            "Dear {recipientName},\n\n"
            "We no longer need your review of this manuscript:\n\n"
            "  {submissionTitle}\n\n"
            "Thank you for your time, and we apologise for any inconvenience.\n\n"
            "{journalName}"
        ),
        variables=FOR_REVIEWER,
    )
)

THANKS = register(
    TemplateSpec(
        key="review_thanks",
        group=GROUP,
        name="Thank you for the review",
        description="Sent when the editor acknowledges a finished review.",
        recipient="Reviewer",
        subject="Thank you for your review",
        body=(
            "Dear {recipientName},\n\n"
            "Thank you for your review of this manuscript for {journalName}:\n\n"
            "  {submissionTitle}\n\n"
            "Your help is much appreciated.\n\n"
            "{editorName}\n{journalName}"
        ),
        variables=FOR_REVIEWER,
    )
)

DECLINED_TO_EDITOR = register(
    TemplateSpec(
        key="review_declined_editor",
        group=GROUP,
        name="Reviewer declined (to editors)",
        description="Sent to the manuscript's editors when a reviewer declines.",
        recipient="Editors",
        subject="{submissionNumber}: {reviewerName} declined to review",
        body=(
            "Dear {recipientName},\n\n"
            "{reviewerName} has declined to review {submissionNumber}, “{submissionTitle}”.\n\n"
            "Reason: {declineReason}\n\n"
            "You may want to invite another reviewer:\n\n{submissionUrl}"
        ),
        variables={**FOR_EDITOR, "declineReason": "The reviewer's reason and comment"},
    )
)

COMPLETED_TO_EDITOR = register(
    TemplateSpec(
        key="review_completed_editor",
        group=GROUP,
        name="Review received (to editors)",
        description="Sent to the manuscript's editors when a reviewer sends a review.",
        recipient="Editors",
        subject="{submissionNumber}: review received from {reviewerName}",
        body=(
            "Dear {recipientName},\n\n"
            "{reviewerName} has sent a review of {submissionNumber}, “{submissionTitle}”.\n\n"
            "Recommendation: {recommendation}\n\n"
            "Read it here:\n\n{submissionUrl}"
        ),
        variables={**FOR_EDITOR, "recommendation": "The reviewer's recommendation"},
    )
)

REVISIONS_TO_EDITOR = register(
    TemplateSpec(
        key="revisions_submitted_editor",
        group=GROUP,
        name="Revised manuscript received (to editors)",
        description="Sent to the manuscript's editors when the author sends revised files.",
        recipient="Editors",
        subject="{submissionNumber}: revised manuscript received",
        body=(
            "Dear {recipientName},\n\n"
            "The authors of {submissionNumber}, “{submissionTitle}”, have sent a revised manuscript "
            "(review round {roundNumber}).\n\n"
            "Open it here:\n\n{submissionUrl}"
        ),
        variables={
            "submissionNumber": FOR_EDITOR["submissionNumber"],
            "submissionTitle": FOR_EDITOR["submissionTitle"],
            "submissionUrl": FOR_EDITOR["submissionUrl"],
            "roundNumber": "Number of the review round",
        },
    )
)
