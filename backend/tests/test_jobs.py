from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import utcnow
from app.core.jobs import Job, JobContext, PeriodicRun, Worker, enqueue, periodic, slot_start, task

CALLS: list[dict[str, Any]] = []
GAVE_UP: list[tuple[dict[str, Any], str]] = []


async def note_give_up(ctx: JobContext, payload: dict[str, Any], error: str) -> None:
    GAVE_UP.append((payload, error))


@task("test.record", max_attempts=3, on_give_up=note_give_up)
async def record(ctx: JobContext, payload: dict[str, Any]) -> None:
    CALLS.append(payload)
    if payload.get("fail"):
        raise RuntimeError("boom")


periodic("test.record", every=timedelta(hours=1), payload={"periodic": True})


@pytest.fixture(autouse=True)
def reset_calls() -> None:
    CALLS.clear()
    GAVE_UP.clear()


@pytest.fixture
def worker(app: FastAPI, settings: Settings) -> Worker:
    return Worker(JobContext(session_factory=app.state.session_factory, settings=settings))


async def test_jobs_run_only_when_the_transaction_commits(db: AsyncSession, worker: Worker):
    await enqueue(db, "test.record", {"n": 1})
    await db.rollback()
    await enqueue(db, "test.record", {"n": 2})
    await db.commit()

    await worker.run_until_empty()
    assert {"n": 2} in CALLS and {"n": 1} not in CALLS
    statuses = (await db.scalars(select(Job.status).where(Job.task == "test.record"))).all()
    assert "succeeded" in statuses


async def test_failed_jobs_are_retried_then_marked_failed(db: AsyncSession, worker: Worker):
    job = await enqueue(db, "test.record", {"fail": True})
    await db.commit()
    job_id = job.id

    for attempt in range(1, 4):
        await worker.run_once()
        db.expire_all()
        current = await db.get(Job, job_id)
        assert current is not None and current.attempts == attempt
        if attempt < 3:
            assert GAVE_UP == []
            assert current.status == "queued"
            assert current.run_at > utcnow()
            assert current.last_error == "RuntimeError: boom"
            await db.execute(update(Job).where(Job.id == job_id).values(run_at=utcnow()))  # skip the backoff
            await db.commit()
        else:
            assert current.status == "failed"
            assert current.finished_at is not None
            assert GAVE_UP == [({"fail": True}, "RuntimeError: boom")]


async def test_delayed_jobs_wait(db: AsyncSession, worker: Worker):
    await enqueue(db, "test.record", {"later": True}, delay=timedelta(hours=1))
    await db.commit()
    await worker.run_until_empty()
    assert {"later": True} not in CALLS


async def test_stale_running_jobs_are_recovered(db: AsyncSession, worker: Worker):
    job = await enqueue(db, "test.record", {"n": 3})
    await db.commit()
    await db.execute(
        update(Job).where(Job.id == job.id).values(status="running", locked_at=utcnow() - timedelta(hours=1))
    )
    await db.commit()
    await worker.run_until_empty()
    assert {"n": 3} in CALLS


async def test_periodic_tasks_are_queued_once_per_slot(app: FastAPI, settings: Settings, db: AsyncSession):
    for _ in range(2):  # two workers, same time slot
        await Worker(
            JobContext(session_factory=app.state.session_factory, settings=settings)
        ).run_until_empty()
    assert CALLS.count({"periodic": True}) == 1
    count = await db.scalar(
        select(func.count()).select_from(PeriodicRun).where(PeriodicRun.task == "test.record")
    )
    assert count == 1


def test_slot_start() -> None:
    now = datetime(2026, 11, 26, 13, 47, tzinfo=UTC)
    assert slot_start(now, timedelta(hours=1)) == datetime(2026, 11, 26, 13, 0, tzinfo=UTC)
    assert slot_start(now, timedelta(days=1)) == datetime(2026, 11, 26, tzinfo=UTC)


async def test_unknown_task_is_rejected(db: AsyncSession):
    with pytest.raises(KeyError):
        await enqueue(db, "does.not.exist")
