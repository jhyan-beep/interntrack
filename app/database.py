from functools import lru_cache
from typing import Generator

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Settings(BaseSettings):
    app_name: str = "InternTrack"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://interntrack:interntrack@localhost:5432/interntrack"
    cors_origins: str = "http://localhost:5173"
    secret_key: str = "development-only-change-me-32-chars"
    session_cookie_name: str = "interntrack_session"
    session_expire_hours: int = 168
    jwt_issuer: str = "interntrack"
    jwt_audience: str = "interntrack-web"
    allowed_hosts: str = "localhost,127.0.0.1,test"
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1)
    auth_rate_limit_per_ip: int = Field(default=20, ge=1)
    auth_rate_limit_per_identity: int = Field(default=10, ge=1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

