"""Keyset (cursor) pagination helpers."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.errors import ValidationFailed

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

T = TypeVar("T")


class Page(BaseModel, Generic[T]):  # noqa: UP046 - Pydantic generic models need typing.Generic
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(values: Sequence[Any]) -> str:
    raw = json.dumps(list(values), separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, size: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("The cursor is invalid.", code="invalid_cursor") from exc
    if not isinstance(values, list) or len(values) != size:
        raise ValidationFailed("The cursor is invalid.", code="invalid_cursor")
    return values


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))
