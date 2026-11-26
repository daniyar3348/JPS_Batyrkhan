"""API application factory. Run with: ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app import models, tasks  # noqa: F401 - the whole schema, and the tasks services enqueue
from app.api import build_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.security import configure_password_hashing
from app.core.storage import create_storage


def _operation_id(route: APIRoute) -> str:
    # Stable, readable names for the generated TypeScript client.
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_format=settings.log_json)
    configure_password_hashing(
        time_cost=settings.argon2_time_cost,
        memory_kib=settings.argon2_memory_kib,
        parallelism=settings.argon2_parallelism,
    )
    engine = create_engine(settings.database_url, pool_size=settings.database_pool_size)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    docs = settings.api_docs_enabled
    app = FastAPI(
        title="Journal Platform API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/openapi.json" if docs else None,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.storage = create_storage(settings)

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(build_router())
    return app
