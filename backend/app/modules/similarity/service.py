"""Running similarity checks in the background. Results are for the editorial office only."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.jobs import enqueue
from app.core.storage import Storage
from app.modules.files.models import FileRevision
from app.modules.similarity.models import CheckStatus, SimilarityCheck
from app.modules.similarity.providers import SimilarityProvider, get_provider

logger = logging.getLogger(__name__)

RUN_CHECK = "similarity.run_check"
POLL_CHECK = "similarity.poll_check"
POLL_INTERVAL = timedelta(seconds=30)
MAX_POLLS = 120  # about an hour; providers usually finish within minutes


class SimilarityService:
    def __init__(self, db: AsyncSession, settings: Settings, storage: Storage) -> None:
        self.db = db
        self.storage = storage
        self.provider: SimilarityProvider | None = get_provider(settings)

    @property
    def available(self) -> bool:
        return self.provider is not None

    async def start(
        self, *, submission_id: int, revision_id: int, requested_by_id: int | None
    ) -> SimilarityCheck:
        if self.provider is None:
            raise RuntimeError("No similarity provider is configured")
        check = SimilarityCheck(
            submission_id=submission_id,
            file_revision_id=revision_id,
            provider=self.provider.name,
            requested_by_id=requested_by_id,
        )
        self.db.add(check)
        await self.db.flush()
        await enqueue(self.db, RUN_CHECK, {"check_id": check.id})
        return check

    async def list(self, submission_id: int) -> Sequence[SimilarityCheck]:
        return (
            await self.db.scalars(
                select(SimilarityCheck)
                .where(SimilarityCheck.submission_id == submission_id)
                .order_by(SimilarityCheck.id.desc())
            )
        ).all()

    async def get(self, submission_id: int, check_id: int) -> SimilarityCheck | None:
        return await self.db.scalar(
            select(SimilarityCheck).where(
                SimilarityCheck.id == check_id, SimilarityCheck.submission_id == submission_id
            )
        )

    async def report_url(self, check: SimilarityCheck) -> str | None:
        if self.provider is None or check.external_id is None or check.status != CheckStatus.COMPLETED:
            return None
        return await self.provider.report_url(check.external_id)

    # Worker steps --------------------------------------------------------------------------------

    async def run(self, check_id: int) -> None:
        check = await self.db.get(SimilarityCheck, check_id)
        if check is None or check.status != CheckStatus.QUEUED:
            return
        if self.provider is None:
            self._fail(check, "The similarity service is not configured.")
            return
        revision = await self.db.get(FileRevision, check.file_revision_id)
        if revision is None:
            self._fail(check, "The file no longer exists.")
            return
        check.external_id = await self.provider.submit(
            storage=self.storage, key=revision.storage_key, filename=revision.original_name, title=""
        )
        check.status = CheckStatus.PROCESSING
        await enqueue(self.db, POLL_CHECK, {"check_id": check.id, "attempt": 1})

    async def poll(self, check_id: int, attempt: int) -> None:
        check = await self.db.get(SimilarityCheck, check_id)
        if check is None or check.status != CheckStatus.PROCESSING or check.external_id is None:
            return
        if self.provider is None:
            self._fail(check, "The similarity service is not configured.")
            return
        result = await self.provider.fetch(check.external_id)
        if result.status == "completed":
            check.status = CheckStatus.COMPLETED
            check.score_percent = result.score_percent
            check.completed_at = utcnow()
        elif result.status == "failed":
            self._fail(check, result.error or "The similarity service could not check this file.")
        elif attempt >= MAX_POLLS:
            self._fail(check, "The similarity service did not return a result in time.")
        else:
            await enqueue(
                self.db, POLL_CHECK, {"check_id": check.id, "attempt": attempt + 1}, delay=POLL_INTERVAL
            )

    async def give_up(self, check_id: int) -> None:
        """The worker could not reach the service after every retry."""
        check = await self.db.get(SimilarityCheck, check_id)
        if check is not None and check.status in (CheckStatus.QUEUED, CheckStatus.PROCESSING):
            self._fail(check, "The similarity service could not be reached. Run the check again later.")

    def _fail(self, check: SimilarityCheck, error: str) -> None:
        check.status = CheckStatus.FAILED
        check.error = error[:500]
        check.completed_at = utcnow()
        logger.warning("Similarity check failed", extra={"check_id": check.id, "error": error})
