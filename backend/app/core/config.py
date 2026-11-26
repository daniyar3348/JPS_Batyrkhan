"""Application settings, read from environment variables prefixed with ``JPS_``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JPS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://jps:jps@localhost:5432/jps"
    database_pool_size: int = 10

    # The platform serves one journal for now; it is looked up by this slug.
    journal_slug: str = "journal"
    # Public address of the editorial workspace, used in links inside e-mails.
    workspace_url: str = "http://localhost:5173"
    api_docs_enabled: bool = True

    log_level: str = "INFO"
    log_json: bool = True

    session_cookie_name: str = "jps_session"
    cookie_secure: bool = True
    session_idle_days: int = 14
    session_absolute_days: int = 30

    login_max_failures: int = 10
    login_lockout_minutes: int = 15
    password_reset_ttl_minutes: int = 60
    email_verification_ttl_hours: int = 72
    invitation_ttl_days: int = 7
    # Argon2id cost; the defaults follow the RFC 9106 low-memory profile. Tests lower them for speed.
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4

    email_backend: Literal["console", "smtp", "memory"] = "console"
    email_from: str = "Journal <no-reply@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_tls: bool = False

    worker_poll_interval: float = 1.0
    worker_batch_size: int = 10

    @model_validator(mode="after")
    def _check_production(self) -> Self:
        if self.environment != "production":
            return self
        problems = []
        if not self.cookie_secure:
            problems.append("JPS_COOKIE_SECURE must be true")
        if self.email_backend != "smtp":
            problems.append("JPS_EMAIL_BACKEND must be smtp")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
