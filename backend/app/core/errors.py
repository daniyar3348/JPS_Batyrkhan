"""Application errors and their RFC 9457 (problem+json) representation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class FieldError(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    """Error body returned by every endpoint (RFC 9457)."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[FieldError] | None = None


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    title = "Bad request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        errors: list[FieldError] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)
        if code:
            self.code = code
        self.errors = errors
        self.headers = headers


class BadRequest(AppError):
    pass


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    title = "You do not have permission to do this"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class PreconditionFailed(AppError):
    status_code = 412
    code = "version_mismatch"
    title = "This item was changed by someone else. Reload it and try again."


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"
    title = "Some fields are invalid"


class PreconditionRequired(AppError):
    status_code = 428
    code = "if_match_required"
    title = "The If-Match header with the current version is required"


class TooManyRequests(AppError):
    status_code = 429
    code = "too_many_requests"
    title = "Too many requests. Try again later."


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Service unavailable"


def problem_response(
    status: int,
    code: str,
    title: str,
    detail: str,
    *,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        type=f"urn:jps:error:{code}", title=title, status=status, detail=detail, code=code, errors=errors
    )
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers
    )


def _field_name(location: tuple[Any, ...]) -> str:
    parts = [str(p) for p in location]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) or "request"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            exc.status_code, exc.code, exc.title, exc.detail, errors=exc.errors, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(
                field=_field_name(tuple(err.get("loc", ()))), message=str(err.get("msg", "Invalid value"))
            )
            for err in exc.errors()
        ]
        return problem_response(
            422, ValidationFailed.code, ValidationFailed.title, "Check the highlighted fields.", errors=errors
        )

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, exc: StaleDataError) -> JSONResponse:
        # Two requests passed the If-Match check at the same time; the second write lost the race.
        return problem_response(
            412, PreconditionFailed.code, PreconditionFailed.title, PreconditionFailed.title
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return problem_response(exc.status_code, code, str(exc.detail), str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return problem_response(
            500, "internal_error", "Internal server error", "Something went wrong on our side."
        )
