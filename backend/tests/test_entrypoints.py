"""The API and the worker must each load the whole schema on their own.

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


@pytest.mark.parametrize("module", ["app.worker", "app.main"])
def test_entry_point_loads_every_table(module: str) -> None:
    result = subprocess.run(  # noqa: S603 - our own interpreter and a fixed script
        [sys.executable, "-c", SCRIPT.format(module=module)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.strip().split(",") == sorted(Base.metadata.tables)
