"""E-mail delivery backends: SMTP for production, console for development, memory for tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import ClassVar, Protocol

import aiosmtplib

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class EmailBackend(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailBackend:
    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "E-mail (console backend)",
            extra={"to": message.to, "subject": message.subject, "body": message.text},
        )


class MemoryEmailBackend:
    outbox: ClassVar[list[EmailMessage]] = []

    async def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


class SmtpEmailBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = self.settings.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime["Date"] = formatdate(localtime=False)
        sender_domain = parseaddr(self.settings.email_from)[1].rpartition("@")[2] or None
        mime["Message-ID"] = make_msgid(domain=sender_domain)
        mime.set_content(message.text)
        if message.html:
            mime.add_alternative(message.html, subtype="html")
        return mime

    async def send(self, message: EmailMessage) -> None:
        password = self.settings.smtp_password.get_secret_value() if self.settings.smtp_password else None
        await aiosmtplib.send(
            self.build(message),
            hostname=self.settings.smtp_host,
            port=self.settings.smtp_port,
            username=self.settings.smtp_username,
            password=password,
            start_tls=self.settings.smtp_starttls and not self.settings.smtp_tls,
            use_tls=self.settings.smtp_tls,
            timeout=30,
        )


def get_email_backend(settings: Settings) -> EmailBackend:
    if settings.email_backend == "smtp":
        return SmtpEmailBackend(settings)
    if settings.email_backend == "memory":
        return MemoryEmailBackend()
    return ConsoleEmailBackend()
