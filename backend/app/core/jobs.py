"""Background jobs stored in PostgreSQL.

A job row is inserted in the same transaction as the business change that caused it, so a job exists
if and only if that change was committed. Workers claim jobs with ``FOR UPDATE SKIP LOCKED``, retry
failures with exponential backoff, and recover jobs left running by a crashed worker.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Index, Integer, String, Text, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import Settings
from app.core.db import Base, id_column, utcnow

logger = logging.getLogger(__name__)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_queued_run_at", "run_at", postgresql_where=text("status = 'queued'")),)

    id: Mapped[int] = id_column()
    task: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    run_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    locked_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None]


class PeriodicRun(Base):
    """One row per (task, time slot): guarantees a periodic task is queued once per slot across workers."""

    __tablename__ = "periodic_runs"

    task: Mapped[str] = mapped_column(String(100), primary_key=True)
    slot: Mapped[datetime] = mapped_column(primary_key=True)


@dataclass(frozen=True)
class JobContext:
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


Handler = Callable[[JobContext, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class TaskSpec:
    name: str
    handler: Handler
    max_attempts: int


@dataclass(frozen=True)
class PeriodicSpec:
    task: str
    every: timedelta
    payload: dict[str, Any] = field(default_factory=dict)


_TASKS: dict[str, TaskSpec] = {}
_PERIODIC: list[PeriodicSpec] = []


def task(name: str, *, max_attempts: int = 5) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        if name in _TASKS and _TASKS[name].handler is not handler:
            raise RuntimeError(f"Task {name!r} is already registered")
        _TASKS[name] = TaskSpec(name, handler, max_attempts)
        return handler

    return register


def periodic(task_name: str, *, every: timedelta, payload: Mapping[str, Any] | None = None) -> None:
    if any(spec.task == task_name for spec in _PERIODIC):
        return
    _PERIODIC.append(PeriodicSpec(task_name, every, dict(payload or {})))


def registered_tasks() -> dict[str, TaskSpec]:
    return dict(_TASKS)


async def enqueue(
    db: AsyncSession,
    task_name: str,
    payload: Mapping[str, Any] | None = None,
    *,
    delay: timedelta | None = None,
) -> Job:
    """Add a job to the current transaction. It runs only if the transaction commits."""
    spec = _TASKS.get(task_name)
    if spec is None:
        raise KeyError(f"Unknown task {task_name!r}")
    job = Job(task=task_name, payload=dict(payload or {}), max_attempts=spec.max_attempts)
    if delay:
        job.run_at = utcnow() + delay
    db.add(job)
    return job


def retry_delay(attempts: int) -> timedelta:
    base = min(3600, 15 * 2 ** max(attempts - 1, 0))
    return timedelta(seconds=base + random.uniform(0, 5))  # noqa: S311 - jitter, not security


_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def slot_start(now: datetime, every: timedelta) -> datetime:
    return _EPOCH + ((now - _EPOCH) // every) * every


@dataclass
class _Claimed:
    id: int
    task: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class Worker:
    def __init__(
        self,
        ctx: JobContext,
        *,
        batch_size: int = 10,
        poll_interval: float = 1.0,
        stale_after: timedelta = timedelta(minutes=15),
        schedule_periodic: bool = True,
    ) -> None:
        self.ctx = ctx
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.stale_after = stale_after
        self.schedule_periodic = schedule_periodic
        self._last_housekeeping: datetime | None = None

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("Worker started", extra={"tasks": sorted(_TASKS)})
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("Worker iteration failed")
                processed = 0
            if processed == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_interval)
        logger.info("Worker stopped")

    async def run_once(self) -> int:
        await self._housekeeping()
        claimed = await self._claim()
        for job in claimed:
            await self._execute(job)
        return len(claimed)

    async def run_until_empty(self, *, max_rounds: int = 100) -> int:
        """Process jobs that are due until none are left. Used by tests and CLI commands."""
        total = 0
        for _ in range(max_rounds):
            processed = await self.run_once()
            total += processed
            if processed == 0:
                break
        return total

    async def _housekeeping(self) -> None:
        now = utcnow()
        if self._last_housekeeping and now - self._last_housekeeping < timedelta(seconds=30):
            return
        self._last_housekeeping = now
        async with self.ctx.session_factory() as db, db.begin():
            await db.execute(
                update(Job)
                .where(Job.status == "running", Job.locked_at < now - self.stale_after)
                .values(
                    status="queued",
                    locked_at=None,
                    last_error="Recovered after the worker stopped responding",
                )
            )
            for spec in _PERIODIC if self.schedule_periodic else []:
                inserted = await db.execute(
                    insert(PeriodicRun)
                    .values(task=spec.task, slot=slot_start(now, spec.every))
                    .on_conflict_do_nothing()
                    .returning(PeriodicRun.task)
                )
                if inserted.first() is not None:
                    await enqueue(db, spec.task, spec.payload)

    async def _claim(self) -> list[_Claimed]:
        async with self.ctx.session_factory() as db, db.begin():
            jobs = (
                await db.scalars(
                    select(Job)
                    .where(Job.status == "queued", Job.run_at <= func.now())
                    .order_by(Job.run_at, Job.id)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            now = utcnow()
            claimed = []
            for job in jobs:
                job.status = "running"
                job.locked_at = now
                job.attempts += 1
                claimed.append(_Claimed(job.id, job.task, dict(job.payload), job.attempts, job.max_attempts))
            return claimed

    async def _execute(self, job: _Claimed) -> None:
        spec = _TASKS.get(job.task)
        try:
            if spec is None:
                raise LookupError(f"No handler registered for task {job.task!r}")
            await spec.handler(self.ctx, job.payload)
        except Exception as exc:
            final = job.attempts >= job.max_attempts
            logger.exception(
                "Job failed",
                extra={"job_id": job.id, "task": job.task, "attempt": job.attempts, "final": final},
            )
            values: dict[str, Any] = {"last_error": f"{type(exc).__name__}: {exc}"[:2000], "locked_at": None}
            if final:
                values |= {"status": "failed", "finished_at": utcnow()}
            else:
                values |= {"status": "queued", "run_at": utcnow() + retry_delay(job.attempts)}
            async with self.ctx.session_factory() as db, db.begin():
                await db.execute(update(Job).where(Job.id == job.id).values(**values))
        else:
            async with self.ctx.session_factory() as db, db.begin():
                await db.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(status="succeeded", finished_at=utcnow(), locked_at=None, last_error=None)
                )


@task("core.cleanup_jobs")
async def cleanup_jobs(ctx: JobContext, payload: dict[str, Any]) -> None:
    """Delete finished jobs and old periodic markers so the tables stay small."""
    now = utcnow()
    async with ctx.session_factory() as db, db.begin():
        await db.execute(
            delete(Job).where(Job.status == "succeeded", Job.finished_at < now - timedelta(days=7))
        )
        await db.execute(
            delete(Job).where(Job.status == "failed", Job.finished_at < now - timedelta(days=90))
        )
        await db.execute(delete(PeriodicRun).where(PeriodicRun.slot < now - timedelta(days=30)))


periodic("core.cleanup_jobs", every=timedelta(days=1))
