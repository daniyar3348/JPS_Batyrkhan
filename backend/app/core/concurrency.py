"""Optimistic concurrency: entity versions exposed as ETags and checked through If-Match."""

from __future__ import annotations

import re

from app.core.errors import BadRequest, PreconditionFailed, PreconditionRequired

_ETAG = re.compile(r'^(?:W/)?"(\d+)"$')


def etag_for(version: int) -> str:
    return f'"{version}"'


def parse_if_match(header: str | None) -> int:
    if not header:
        raise PreconditionRequired()
    match = _ETAG.match(header.strip())
    if not match:
        raise BadRequest('If-Match must look like "3".', code="invalid_if_match")
    return int(match.group(1))


def ensure_version(current: int, expected: int) -> None:
    if current != expected:
        raise PreconditionFailed()
