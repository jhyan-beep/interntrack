from copy import deepcopy
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.database import get_settings

pytestmark = pytest.mark.anyio


def enable_desktop_mode(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)


async def add_application(client: AsyncClient, company: str, role: str = "SWE Intern") -> None:
    response = await client.post(
        "/applications",
        json={
            "company": company,
            "role": role,
            "status": "applied",
            "application_date": "2026-10-01",
            "deadline": "2026-12-01",
            "location": "Remote",
            "source_url": f"https://example.com/{company.lower()}",
            "notes": "Portable test record",
        },
    )
    assert response.status_code == 201


async def test_desktop_backup_exports_only_portable_workspace_data(
    client: AsyncClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    enable_desktop_mode(monkeypatch, tmp_path)
    await add_application(client, "Figma")

    response = await client.get("/desktop/backups/export")

    assert response.status_code == 200
    assert "interntrack-backup-" in response.headers["content-disposition"]
    backup = response.json()
    assert backup["kind"] == "interntrack-portable-backup"
    assert backup["schema_version"] == 1
    assert backup["applications"][0]["company"] == "Figma"
    assert backup["preferences"]["deadline_reminder_days"] == 3
    serialized = response.text.lower()
    for secret_field in ["password", "token", "api_key", "session", "email"]:
        assert secret_field not in serialized


async def test_backup_preview_and_merge_skip_duplicates(
    client: AsyncClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    enable_desktop_mode(monkeypatch, tmp_path)
    await add_application(client, "Figma")
    backup = (await client.get("/desktop/backups/export")).json()
    new_record = deepcopy(backup["applications"][0])
    new_record["company"] = "Linear"
    new_record["source_url"] = "https://example.com/linear"
    backup["applications"].append(new_record)

    preview = await client.post("/desktop/backups/preview", json=backup)
    restored = await client.post(
        "/desktop/backups/restore",
        json={"backup": backup, "mode": "merge", "confirm_replace": False},
    )

    assert preview.status_code == 200
    assert preview.json() == {
        "current_applications": 1,
        "backup_applications": 2,
        "duplicate_applications": 1,
        "merge_import_count": 1,
    }
    assert restored.status_code == 200
    assert restored.json()["imported_applications"] == 1
    assert restored.json()["skipped_duplicates"] == 1
    applications = await client.get("/applications?page_size=100")
    assert applications.json()["total"] == 2


async def test_replace_restore_requires_confirmation_and_replaces_workspace(
    client: AsyncClient,
    monkeypatch,
    tmp_path: Path,
) -> None:
    enable_desktop_mode(monkeypatch, tmp_path)
    await add_application(client, "Old Company")
    backup = (await client.get("/desktop/backups/export")).json()
    backup["applications"][0]["company"] = "Restored Company"
    backup["applications"][0]["source_url"] = "https://example.com/restored"
    backup["preferences"]["deadline_reminder_days"] = 7

    unconfirmed = await client.post(
        "/desktop/backups/restore",
        json={"backup": backup, "mode": "replace", "confirm_replace": False},
    )
    restored = await client.post(
        "/desktop/backups/restore",
        json={"backup": backup, "mode": "replace", "confirm_replace": True},
    )

    assert unconfirmed.status_code == 422
    assert restored.status_code == 200
    assert restored.json()["removed_applications"] == 1
    assert restored.json()["imported_applications"] == 1
    applications = await client.get("/applications?page_size=100")
    assert [item["company"] for item in applications.json()["items"]] == [
        "Restored Company"
    ]
    preferences = await client.get("/reminders/settings")
    assert preferences.json()["deadline_reminder_days"] == 7


async def test_portable_backups_are_not_exposed_in_web_mode(client: AsyncClient) -> None:
    response = await client.get("/desktop/backups/export")
    assert response.status_code == 404
