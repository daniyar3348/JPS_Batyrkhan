"""The Alembic migrations must produce exactly the schema the models describe."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI

from app.models import Base
from app.modules.identity.validation import normalize_orcid
from app.modules.journals.validation import normalize_issn


async def test_migrations_match_models(app: FastAPI):
    async with app.state.engine.connect() as connection:
        diff = await connection.run_sync(
            lambda sync: compare_metadata(
                MigrationContext.configure(sync, opts={"compare_type": True}), Base.metadata
            )
        )
    assert diff == [], f"Models and migrations differ; generate a migration: {diff}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0000-0002-1825-0097", "0000-0002-1825-0097"),
        ("https://orcid.org/0000-0001-5109-3700", "0000-0001-5109-3700"),
        ("0000-0002-1694-233x", "0000-0002-1694-233X"),
    ],
)
def test_valid_orcid(raw: str, expected: str) -> None:
    assert normalize_orcid(raw) == expected


@pytest.mark.parametrize("raw", ["0000-0002-1825-0098", "1234", "0000 0002 1825 0097"])
def test_invalid_orcid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_orcid(raw)


def test_issn() -> None:
    assert normalize_issn("0317-8471") == "0317-8471"
    assert normalize_issn("03178471") == "0317-8471"
    assert normalize_issn("2434-561x") == "2434-561X"
    for bad in ("0317-8472", "123-4567"):
        with pytest.raises(ValueError):
            normalize_issn(bad)
