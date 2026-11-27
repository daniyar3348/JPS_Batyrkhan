"""Telling the journal's site which pages to rebuild after something is published or changed.

The site checks the signature: HMAC-SHA256 of the request body with the shared secret, sent as
``X-JPS-Signature: sha256=<hex>``. The body carries the time it was signed, so an old request cannot be
replayed long afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import ClassVar

import httpx

from app.core.config import Settings
from app.core.db import utcnow


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class SiteNotifier:
    # Tests replace the network with httpx.MockTransport.
    transport: ClassVar[httpx.AsyncBaseTransport | None] = None

    def __init__(self, settings: Settings) -> None:
        self.url = settings.site_revalidate_url
        self.secret = settings.site_revalidate_secret

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret)

    async def revalidate(self, paths: list[str]) -> None:
        """Raises on failure, so the job is retried."""
        if self.url is None or self.secret is None or not paths:
            return
        body = json.dumps({"paths": sorted(set(paths)), "sent_at": utcnow().isoformat()}).encode()
        async with httpx.AsyncClient(timeout=20.0, transport=self.transport) as client:
            response = await client.post(
                self.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-JPS-Signature": sign(self.secret.get_secret_value(), body),
                },
            )
        response.raise_for_status()
