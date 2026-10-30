from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient

from app import main
from app.database import get_settings
from app.desktop import configure_desktop_environment, ensure_secret_key
from app.desktop_secrets import DesktopSecretStore


def test_desktop_environment_uses_persistent_local_sqlite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in (
        "ENVIRONMENT",
        "DESKTOP_DATA_DIR",
        "DATABASE_URL",
        "SECRET_KEY",
        "APP_BASE_URL",
        "CORS_ORIGINS",
        "ALLOWED_HOSTS",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    database_path = configure_desktop_environment(tmp_path, 8765)

    assert database_path == tmp_path / "interntrack.db"
    assert database_path.parent.exists()
    assert __import__("os").environ["ENVIRONMENT"] == "desktop"
    assert __import__("os").environ["DATABASE_URL"].endswith("/interntrack.db")
    assert __import__("os").environ["APP_BASE_URL"] == "http://127.0.0.1:8765"
    assert __import__("os").environ["DESKTOP_DATA_DIR"] == str(tmp_path)


def test_desktop_secret_is_reused_between_launches(tmp_path: Path) -> None:
    first = ensure_secret_key(tmp_path)
    second = ensure_secret_key(tmp_path)

    assert first == second
    assert len(first) >= 32


def test_desktop_secret_store_never_writes_plaintext(tmp_path: Path) -> None:
    store = DesktopSecretStore(
        tmp_path,
        protect=lambda value: b"encrypted:" + value[::-1],
        unprotect=lambda value: value.removeprefix(b"encrypted:")[::-1],
    )
    api_key = "sk-test-this-key-must-stay-private"

    store.save(api_key)

    assert store.load() == api_key
    assert api_key.encode("utf-8") not in store.path.read_bytes()
    store.delete()
    assert not store.path.exists()


@pytest.mark.anyio
async def test_desktop_ai_key_can_be_saved_and_removed(
    anonymous_client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    store = DesktopSecretStore(
        tmp_path,
        protect=lambda value: b"encrypted:" + value[::-1],
        unprotect=lambda value: value.removeprefix(b"encrypted:")[::-1],
    )
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(main, "_desktop_secret_store", lambda: store)
    monkeypatch.setattr(main, "hash_password", lambda _password: "test-password-hash")
    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "desktop@example.com", "password": "securepass123"},
    )
    assert registered.status_code == 201
    api_key = "sk-test-desktop-secret-value"

    initial = await anonymous_client.get("/desktop/ai-settings")
    saved = await anonymous_client.put("/desktop/ai-settings", json={"api_key": api_key})
    runtime = await anonymous_client.get("/runtime")

    assert initial.status_code == 200
    assert initial.json()["configured"] is False
    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert api_key not in saved.text
    assert runtime.json()["ai_available"] is True
    assert api_key.encode("utf-8") not in store.path.read_bytes()

    removed = await anonymous_client.delete("/desktop/ai-settings")
    runtime_after_removal = await anonymous_client.get("/runtime")

    assert removed.status_code == 204
    assert runtime_after_removal.json()["ai_available"] is False
    assert not store.path.exists()


@pytest.mark.anyio
async def test_desktop_ai_settings_are_hidden_in_web_mode(
    anonymous_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "hash_password", lambda _password: "test-password-hash")
    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "web@example.com", "password": "securepass123"},
    )
    assert registered.status_code == 201

    response = await anonymous_client.get("/desktop/ai-settings")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_desktop_deadline_reminder_is_acknowledged_only_once(
    anonymous_client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    monkeypatch.setattr(main, "hash_password", lambda _password: "test-password-hash")
    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "reminders@example.com", "password": "securepass123"},
    )
    assert registered.status_code == 201

    enabled = await anonymous_client.patch(
        "/reminders/settings",
        json={
            "deadline_reminders_enabled": True,
            "deadline_reminder_days": 3,
            "reminder_timezone": "UTC",
        },
    )
    assert enabled.status_code == 200
    current_date = datetime.now(timezone.utc).date()

    due = await anonymous_client.post(
        "/applications",
        json={
            "company": "Reminder Company",
            "role": "Software Engineer Intern",
            "status": "applied",
            "application_date": current_date.isoformat(),
            "deadline": (current_date + timedelta(days=1)).isoformat(),
        },
    )
    assert due.status_code == 201
    later = await anonymous_client.post(
        "/applications",
        json={
            "company": "Later Company",
            "role": "Software Engineer Intern",
            "status": "saved",
            "application_date": current_date.isoformat(),
            "deadline": (current_date + timedelta(days=7)).isoformat(),
        },
    )
    assert later.status_code == 201

    first_scan = await anonymous_client.get("/desktop/reminders/due")
    assert first_scan.status_code == 200
    assert first_scan.json()["items"] == [
        {
            "application_id": due.json()["id"],
            "company": "Reminder Company",
            "role": "Software Engineer Intern",
            "deadline": (current_date + timedelta(days=1)).isoformat(),
            "days_remaining": 1,
        }
    ]

    first_ack = await anonymous_client.post(
        f"/desktop/reminders/{due.json()['id']}/acknowledge"
    )
    repeated_ack = await anonymous_client.post(
        f"/desktop/reminders/{due.json()['id']}/acknowledge"
    )
    second_scan = await anonymous_client.get("/desktop/reminders/due")

    assert first_ack.status_code == 204
    assert repeated_ack.status_code == 204
    assert second_scan.json()["items"] == []


@pytest.mark.anyio
async def test_desktop_deadline_reminders_are_hidden_in_web_mode(
    client: AsyncClient,
) -> None:
    response = await client.get("/desktop/reminders/due")

    assert response.status_code == 404
