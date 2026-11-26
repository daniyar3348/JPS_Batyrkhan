"""Background worker process. Run with: ``python -m app.worker``."""

from __future__ import annotations

import asyncio
import signal

from app import tasks  # noqa: F401 - registers task handlers
from app.core.config import get_settings
from app.core.db import create_engine, create_session_factory
from app.core.jobs import JobContext, Worker
from app.core.logging import configure_logging
from app.core.security import configure_password_hashing


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_format=settings.log_json)
    configure_password_hashing(
        time_cost=settings.argon2_time_cost,
        memory_kib=settings.argon2_memory_kib,
        parallelism=settings.argon2_parallelism,
    )
    engine = create_engine(settings.database_url, pool_size=2)
    worker = Worker(
        JobContext(session_factory=create_session_factory(engine), settings=settings),
        batch_size=settings.worker_batch_size,
        poll_interval=settings.worker_poll_interval,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await worker.run_forever(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
