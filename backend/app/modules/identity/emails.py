"""Texts of account e-mails. Editable templates arrive with the notifications module in a later stage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EmailText:
    subject: str
    text: str


def verification(*, name: str, journal_name: str, link: str, hours: int) -> EmailText:
    return EmailText(
        subject=f"Confirm your e-mail address for {journal_name}",
        text=(
            f"Dear {name},\n\n"
            f"Please confirm your e-mail address for your {journal_name} account:\n\n"
            f"{link}\n\n"
            f"This link expires in {hours} hours. If you did not create an account, you can ignore this message.\n\n"
            f"{journal_name}\n"
        ),
    )


def password_reset(*, name: str, journal_name: str, link: str, minutes: int) -> EmailText:
    return EmailText(
        subject=f"Reset your {journal_name} password",
        text=(
            f"Dear {name},\n\n"
            "We received a request to reset the password for your account. To choose a new password, open:\n\n"
            f"{link}\n\n"
            f"This link expires in {minutes} minutes. If you did not ask for this, you can ignore this message; "
            "your password stays the same.\n\n"
            f"{journal_name}\n"
        ),
    )


def invitation(
    *, name: str, journal_name: str, inviter: str, roles: list[str], link: str, days: int
) -> EmailText:
    role_list = ", ".join(roles)
    return EmailText(
        subject=f"Invitation to join {journal_name}",
        text=(
            f"Dear {name},\n\n"
            f"{inviter} has invited you to join {journal_name} as: {role_list}.\n\n"
            f"To accept, choose your password here:\n\n{link}\n\n"
            f"This link expires in {days} days.\n\n"
            f"{journal_name}\n"
        ),
    )
