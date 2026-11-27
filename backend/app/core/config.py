"""Application settings, read from environment variables prefixed with ``JPS_``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "development-only-secret-change-me"  # noqa: S105 - rejected in production


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

    # Signs short-lived links (file uploads and downloads with local storage). Must be secret in production.
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)

    # Files: "s3" in production (any S3-compatible service); "local" keeps them on disk for development.
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "var/storage"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "jps-files"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    # "path" suits most S3-compatible services that are not Amazon; "virtual" is Amazon's default.
    s3_addressing_style: Literal["auto", "path", "virtual"] = "path"
    upload_url_ttl_seconds: int = 900
    download_url_ttl_seconds: int = 300

    # Similarity (plagiarism) checking service. "fake" returns made-up scores, for development only.
    similarity_provider: Literal["disabled", "fake"] = "disabled"

    # Payments. The test provider simulates a card payment page with signed notifications (development only).
    payments_test_provider: bool = False
    # PayPal (REST API). The webhook id is shown in the PayPal developer dashboard next to the webhook URL.
    paypal_mode: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: str | None = None
    paypal_client_secret: SecretStr | None = None
    paypal_webhook_id: str | None = None

    @model_validator(mode="after")
    def _check_production(self) -> Self:
        if self.environment != "production":
            return self
        problems = []
        if not self.cookie_secure:
            problems.append("JPS_COOKIE_SECURE must be true")
        if self.email_backend != "smtp":
            problems.append("JPS_EMAIL_BACKEND must be smtp")
        secret = self.secret_key.get_secret_value()
        if secret == DEV_SECRET_KEY or len(secret) < 32:
            problems.append("JPS_SECRET_KEY must be a random value of at least 32 characters")
        if self.storage_backend != "s3":
            problems.append("JPS_STORAGE_BACKEND must be s3")
        if self.similarity_provider == "fake":
            problems.append("JPS_SIMILARITY_PROVIDER must not be fake")
        if self.payments_test_provider:
            problems.append("JPS_PAYMENTS_TEST_PROVIDER must be false")
        if self.paypal_client_id and self.paypal_mode != "live":
            problems.append("JPS_PAYPAL_MODE must be live")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
