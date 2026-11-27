"""Test fixtures. Tests run against a real PostgreSQL database (JPS_TEST_DATABASE_URL), migrated with Alembic."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import EmailMessage, MemoryEmailBackend
from app.core.jobs import JobContext, Worker
from app.main import create_app
from app.models import Base
from app.modules.identity.models import User
from app.modules.identity.service import IdentityService
from app.modules.journals.models import Journal, Section
from app.modules.journals.permissions import Role
from app.modules.journals.service import JournalService

TEST_DATABASE_URL = os.environ.get(
    "JPS_TEST_DATABASE_URL", "postgresql+asyncpg://jps:jps@localhost:5432/jps_test"
)
PASSWORD = "correct-horse-battery"
BACKEND_DIR = Path(__file__).resolve().parents[1]
TABLES = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["database_url"] = url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        _env_file=None,
        storage_backend="local",
        storage_local_path=str(tmp_path_factory.mktemp("storage")),
        similarity_provider="fake",
        payments_test_provider=True,
        environment="test",
        database_url=TEST_DATABASE_URL,
        email_backend="memory",
        cookie_secure=False,
        log_json=False,
        log_level="WARNING",
        workspace_url="http://workspace.test",
        journal_slug="journal",
        argon2_time_cost=1,
        argon2_memory_kib=1024,
        argon2_parallelism=1,
    )


@pytest.fixture(scope="session")
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    config = alembic_config(settings.database_url)
    # Alembic runs its own event loop, so it gets a thread. Down then up also exercises downgrade().
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")
    application = create_app(settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture(autouse=True)
async def clean_database(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
    yield
    async with app.state.engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    MemoryEmailBackend.outbox.clear()
    # Ids restart with every test, so stored files must go too.
    storage_root = Path(settings.storage_local_path)
    if storage_root.exists():
        shutil.rmtree(storage_root)


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def journal(app: FastAPI, settings: Settings, clean_database: None) -> Journal:
    async with app.state.session_factory() as session:
        created, _ = await JournalService(session, settings).bootstrap(
            slug=settings.journal_slug, name="Test Journal"
        )
        await session.commit()
        return created


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        yield http


UserFactory = Callable[..., Awaitable[User]]


@pytest.fixture
def make_user(app: FastAPI, settings: Settings, journal: Journal) -> UserFactory:
    async def factory(
        email: str,
        roles: list[Role] | None = None,
        *,
        password: str | None = PASSWORD,
        given_name: str = "Test",
        family_name: str = "User",
        verified: bool = True,
    ) -> User:
        async with app.state.session_factory() as session:
            identity = IdentityService(session, settings)
            user = await identity.create_user(
                email=email,
                password=password,
                given_name=given_name,
                family_name=family_name,
                email_verified=verified,
            )
            await JournalService(session, settings).set_roles(
                journal, user, roles or [Role.AUTHOR], actor=None
            )
            await session.commit()
            return user

    return factory


ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def signed_in(app: FastAPI) -> AsyncIterator[ClientFactory]:
    """Return a function that signs a user in on a fresh client (with the CSRF header set)."""
    clients: list[AsyncClient] = []

    async def factory(email: str, password: str = PASSWORD) -> AsyncClient:
        http = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        clients.append(http)
        response = await http.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        http.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return http

    yield factory
    for http in clients:
        await http.aclose()


@pytest.fixture
async def admin(make_user: UserFactory, signed_in: ClientFactory) -> AsyncClient:
    await make_user("admin@example.org", [Role.ADMIN], given_name="Ada", family_name="Admin")
    return await signed_in("admin@example.org")


@pytest.fixture
def run_jobs(app: FastAPI, settings: Settings) -> Callable[[], Awaitable[int]]:
    async def run() -> int:
        worker = Worker(
            JobContext(session_factory=app.state.session_factory, settings=settings), schedule_periodic=False
        )
        return await worker.run_until_empty()

    return run


@pytest.fixture
def outbox() -> list[EmailMessage]:
    return MemoryEmailBackend.outbox


def link_token(message: EmailMessage, path: str) -> str:
    """Extract the token from a link like http://workspace.test/<path>?token=..."""
    marker = f"/{path}?token="
    start = message.text.index(marker) + len(marker)
    return message.text[start:].split()[0]


def problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.fixture
async def sections(app: FastAPI, journal: Journal) -> dict[str, Section]:
    async with app.state.session_factory() as db:
        created = {}
        for title, abbreviation in (("Research Articles", "ART"), ("Reviews", "REV")):
            section = Section(journal_id=journal.id, title=title, abbreviation=abbreviation)
            section.editors = []
            db.add(section)
            created[abbreviation] = section
        await db.commit()
        return created


@pytest.fixture
async def author(make_user: UserFactory, signed_in: ClientFactory) -> AsyncClient:
    await make_user("asel@example.org", [Role.AUTHOR], given_name="Asel", family_name="Author")
    return await signed_in("asel@example.org")
