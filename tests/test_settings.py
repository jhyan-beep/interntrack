import pytest

from app.database import Settings


@pytest.mark.parametrize("prefix", ["postgres://", "postgresql://", "postgresql+psycopg://"])
def test_hosted_postgres_urls_use_psycopg3_without_changing_credentials(prefix: str) -> None:
    suffix = "student:encoded%40password@db.example.com:5432/interntrack?sslmode=require"
    settings = Settings(_env_file=None, database_url=prefix + suffix)
    assert settings.database_url == "postgresql+psycopg://" + suffix


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///C:/workspace/local.db", "postgresql+psycopg2://host/db"])
def test_explicit_other_database_drivers_are_preserved(url: str) -> None:
    assert Settings(_env_file=None, database_url=url).database_url == url

