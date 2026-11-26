"""Similarity checking services behind one interface.

A real provider (Crossref Similarity Check / iThenticate, or another service with an API) is added as a
new class once the journal has access; nothing else changes. The fake provider lets the whole flow be
developed and tested without an account.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.storage import Storage


@dataclass(frozen=True)
class ProviderResult:
    status: str  # "processing", "completed" or "failed"
    score_percent: int | None = None
    error: str | None = None


class SimilarityProvider(Protocol):
    name: str

    async def submit(self, *, storage: Storage, key: str, filename: str, title: str) -> str:
        """Send the document; return the provider's id for it."""
        ...

    async def fetch(self, external_id: str) -> ProviderResult: ...

    async def report_url(self, external_id: str) -> str | None:
        """A short-lived link to the full report, if the provider has one."""
        ...


class FakeSimilarityProvider:
    """Development only: a stable score derived from the file's checksum, available on the first poll."""

    name = "fake"

    async def submit(self, *, storage: Storage, key: str, filename: str, title: str) -> str:
        digest = await storage.digest(key)
        return f"fake-{digest.sha256[:16]}"

    async def fetch(self, external_id: str) -> ProviderResult:
        score = int(external_id.removeprefix("fake-"), 16) % 45
        return ProviderResult(status="completed", score_percent=score)

    async def report_url(self, external_id: str) -> str | None:
        return None


def get_provider(settings: Settings) -> SimilarityProvider | None:
    if settings.similarity_provider == "fake":
        return FakeSimilarityProvider()
    return None
