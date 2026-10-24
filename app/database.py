from functools import lru_cache
from typing import Generator

from pydantic import model_validator
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def require_production_secret(self) -> "Settings":
        if self.environment == "production" and (
            self.secret_key == "development-only-change-me-32-chars"
            or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return self


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


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

