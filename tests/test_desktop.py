from pathlib import Path

from app.desktop import configure_desktop_environment, ensure_secret_key


def test_desktop_environment_uses_persistent_local_sqlite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in (
        "ENVIRONMENT",
        "DATABASE_URL",
        "SECRET_KEY",
        "APP_BASE_URL",
        "CORS_ORIGINS",
        "ALLOWED_HOSTS",
    ):
        monkeypatch.delenv(name, raising=False)

    database_path = configure_desktop_environment(tmp_path, 8765)

    assert database_path == tmp_path / "interntrack.db"
    assert database_path.parent.exists()
    assert __import__("os").environ["ENVIRONMENT"] == "desktop"
    assert __import__("os").environ["DATABASE_URL"].endswith("/interntrack.db")
    assert __import__("os").environ["APP_BASE_URL"] == "http://127.0.0.1:8765"


def test_desktop_secret_is_reused_between_launches(tmp_path: Path) -> None:
    first = ensure_secret_key(tmp_path)
    second = ensure_secret_key(tmp_path)

    assert first == second
    assert len(first) >= 32
