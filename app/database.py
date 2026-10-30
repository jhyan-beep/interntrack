from functools import lru_cache
from pathlib import Path
from typing import Generator, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Settings(BaseSettings):
    app_name: str = "InternTrack"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://interntrack:interntrack@localhost:5432/interntrack"
    cors_origins: str = (
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000"
    )
    secret_key: str = "development-only-change-me-32-chars"
    session_cookie_name: str = "interntrack_session"
    session_expire_hours: int = 168
    jwt_issuer: str = "interntrack"
    jwt_audience: str = "interntrack-web"
    allowed_hosts: str = "localhost,127.0.0.1,test"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1)
    auth_rate_limit_per_ip: int = Field(default=20, ge=1)
    auth_rate_limit_per_identity: int = Field(default=10, ge=1)
    app_base_url: str = "http://localhost:8000"
    email_delivery_mode: Literal["console", "smtp"] = "console"
    email_from: str = "InternTrack <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_verification_expire_hours: int = Field(default=24, ge=1, le=168)
    password_reset_expire_minutes: int = Field(default=30, ge=5, le=120)
    email_worker_poll_seconds: int = Field(default=5, ge=1, le=60)
    reminder_scan_interval_seconds: int = Field(default=300, ge=30, le=3_600)
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-luna"
    openai_timeout_seconds: int = Field(default=20, ge=5, le=60)
    desktop_data_dir: Path | None = None
    google_oauth_client_id: str | None = None
    microsoft_oauth_client_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def blank_openai_key_is_unconfigured(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def require_production_secret(self) -> "Settings":
        unsafe_secrets = {
            "development-only-change-me-32-chars",
            "replace-with-a-long-random-value-before-deploying",
        }
        if self.environment == "production" and (
            self.secret_key in unsafe_secrets or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be a unique value of at least 32 characters")
        if self.environment == "production" and self.email_delivery_mode != "smtp":
            raise ValueError("EMAIL_DELIVERY_MODE must be smtp in production")
        if self.email_delivery_mode == "smtp" and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_DELIVERY_MODE is smtp")
        if self.environment == "production" and not self.app_base_url.startswith("https://"):
            raise ValueError("APP_BASE_URL must use https in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


class Base(DeclarativeBase):
    pass


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _engine_options(database_url: str) -> dict:
    options = {"connect_args": _connect_args(database_url)}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        options["poolclass"] = StaticPool
    return options


settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **_engine_options(settings.database_url),
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

