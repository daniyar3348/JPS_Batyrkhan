"""E-mails sent when a manuscript is submitted. The wording is editable (``journals.email_templates``)."""

from __future__ import annotations

from app.modules.journals.email_templates import TemplateSpec, register

MANUSCRIPT = {
    "submissionNumber": "Manuscript number, e.g. JRN-2026-0042",
    "submissionTitle": "Title of the manuscript",
    "submissionUrl": "Link to the manuscript in the editorial workspace",
}

RECEIVED = register(
    TemplateSpec(
        key="submission_received",
        group="Submission",
        name="Submission received",
        description="Sent to the submitting author when a manuscript is submitted.",
        recipient="Submitting author",
        subject="{submissionNumber}: submission received",
        body=(
            "Dear {recipientName},\n\n"
            "Thank you for submitting your manuscript to {journalName}:\n\n"
            "  {submissionTitle}\n  Manuscript number: {submissionNumber}\n\n"
            "The editors will now check it and decide whether to send it for peer review. "
            "You can follow its progress here:\n\n{submissionUrl}\n\n"
            "Please quote the manuscript number in any correspondence.\n\n"
            "{journalName}"
        ),
        variables=MANUSCRIPT,
    )
)

NEW_FOR_EDITOR = register(
    TemplateSpec(
        key="submission_new_for_editor",
        group="Submission",
        name="New submission (to editors)",
        description="Sent to the editor-in-chief and the section's editors when a manuscript is submitted.",
        recipient="Editors",
        subject="New submission {submissionNumber} ({sectionTitle})",
        body=(
            "Dear {recipientName},\n\n"
            "A new manuscript has been submitted to {journalName}.\n\n"
            "  {submissionNumber}: {submissionTitle}\n  Section: {sectionTitle}\n"
            "  Submitted by: {submitterName}\n\n"
            "Open it in the editorial workspace:\n\n{submissionUrl}"
        ),
        variables={
            **MANUSCRIPT,
            "sectionTitle": "Section of the journal",
            "submitterName": "Name of the submitting author",
        },
    )
)

COAUTHOR_NOTICE = register(
    TemplateSpec(
        key="submission_coauthor_notice",
        group="Submission",
        name="Listed as an author",
        description="Sent to every other author named on a manuscript when it is submitted.",
        recipient="Co-authors",
        subject="You are listed as an author of manuscript {submissionNumber}",
        body=(
            "Dear {recipientName},\n\n"
            "{submitterName} has submitted a manuscript to {journalName} and listed you as an author:\n\n"
            "  {submissionTitle}\n  Manuscript number: {submissionNumber}\n\n"
            "If you did not agree to be an author of this manuscript, please tell the journal: "
            "{journalContact}.\n\n"
            "{journalName}"
        ),
        variables={
            "submissionNumber": MANUSCRIPT["submissionNumber"],
            "submissionTitle": MANUSCRIPT["submissionTitle"],
            "submitterName": "Name of the submitting author",
        },
    )
)
