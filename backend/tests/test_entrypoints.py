"""The API, the worker and the command line must each load the whole schema and every task on their own.

Tests import ``app.models`` for every run, so a model that only some entry point imports would
pass here and fail in production with "could not find table" on the first query that needs it.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.models import Base

SCRIPT = """
import {module}
from app.core.db import Base
print(",".join(sorted(Base.metadata.tables)))
"""


@pytest.mark.parametrize("module", ["app.worker", "app.main", "app.cli"])
def test_entry_point_loads_every_table(module: str) -> None:
    result = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
        [sys.executable, "-c", SCRIPT.format(module=module)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.strip().split(",") == sorted(Base.metadata.tables)


TASKS = """
import {module}
from app.core.jobs import registered_tasks
print(",".join(sorted(registered_tasks())))
"""


@pytest.mark.parametrize("module", ["app.worker", "app.main", "app.cli"])
def test_entry_point_registers_every_task(module: str) -> None:
    """Services enqueue tasks by name; an unregistered name fails the request (or the command)."""

    def tasks_of(name: str) -> list[str]:
        result = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
            [sys.executable, "-c", TASKS.format(module=name)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return result.stdout.strip().split(",")

    # In a fresh interpreter: tests register tasks of their own in this one.
    assert tasks_of(module) == tasks_of("app.tasks")
