"""Password hashing (Argon2id) and opaque tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def configure_password_hashing(*, time_cost: int, memory_kib: int, parallelism: int) -> None:
    global _hasher
    _hasher = PasswordHasher(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism)
    _dummy_hash.cache_clear()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check a password. With no stored hash, still spends the same time so callers do not leak which accounts exist."""
    try:
        return _hasher.verify(password_hash or _dummy_hash(), password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Tokens are stored hashed, so a database leak does not expose live sessions or reset links."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
