"""Texts of submission e-mails. Editable templates arrive with the notifications work in stage 3."""

from __future__ import annotations

from app.modules.identity.emails import EmailText


def received(*, name: str, journal_name: str, number: str, title: str, link: str) -> EmailText:
    return EmailText(
        subject=f"{number}: submission received",
        text=(
            f"Dear {name},\n\n"
            f"Thank you for submitting your manuscript to {journal_name}:\n\n"
            f"  {title}\n  Manuscript number: {number}\n\n"
            "The editors will now check it and decide whether to send it for peer review. "
            f"You can follow its progress here:\n\n{link}\n\n"
            "Please quote the manuscript number in any correspondence.\n\n"
            f"{journal_name}\n"
        ),
    )


def new_for_editor(
    *, name: str, journal_name: str, number: str, title: str, section: str, submitter: str, link: str
) -> EmailText:
    return EmailText(
        subject=f"New submission {number} ({section})",
        text=(
            f"Dear {name},\n\n"
            f"A new manuscript has been submitted to {journal_name}.\n\n"
            f"  {number}: {title}\n  Section: {section}\n  Submitted by: {submitter}\n\n"
            f"Open it in the editorial workspace:\n\n{link}\n"
        ),
    )


def coauthor_notice(
    *, name: str, journal_name: str, number: str, title: str, submitter: str, contact: str
) -> EmailText:
    contact_line = f" please tell the journal at {contact}" if contact else " please tell the journal"
    return EmailText(
        subject=f"You are listed as an author of manuscript {number}",
        text=(
            f"Dear {name},\n\n"
            f"{submitter} has submitted a manuscript to {journal_name} and listed you as an author:\n\n"
            f"  {title}\n  Manuscript number: {number}\n\n"
            f"If you did not agree to be an author of this manuscript,{contact_line}.\n\n"
            f"{journal_name}\n"
        ),
    )
