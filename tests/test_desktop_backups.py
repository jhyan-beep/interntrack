import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from httpx import AsyncClient

from app import desktop, main
from app.database import get_settings
from app.desktop_backups import (
    DesktopBackupError,
    apply_pending_restore,
    cancel_pending_restore,
    create_sqlite_snapshot,
    current_sqlite_revisions,
    has_pending_restore,
    list_desktop_snapshots,
    stage_desktop_restore,
    sqlite_database_needs_upgrade,
)


def _create_database(path: Path, revision: str = "old_revision") -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        connection.execute("CREATE TABLE applications (company TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO applications (company) VALUES ('Example Company')"
        )
        connection.commit()


def test_sqlite_snapshot_is_consistent_and_preserves_source(tmp_path: Path) -> None:
    database_path = tmp_path / "interntrack.db"
    _create_database(database_path)

    snapshot = create_sqlite_snapshot(
        database_path,
        tmp_path / "automatic-backups",
        created_at=datetime(2026, 11, 7, 20, 30, tzinfo=timezone.utc),
    )

    assert snapshot is not None
    assert snapshot.name == "interntrack-before-upgrade-20261107T203000Z.db"
    with sqlite3.connect(snapshot) as connection:
        company = connection.execute("SELECT company FROM applications").fetchone()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    assert company == ("Example Company",)
    assert integrity == ("ok",)
    assert database_path.exists()


def test_snapshot_retention_keeps_the_five_newest_files(tmp_path: Path) -> None:
    database_path = tmp_path / "interntrack.db"
    backup_directory = tmp_path / "automatic-backups"
    _create_database(database_path)
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)

    for offset in range(7):
        create_sqlite_snapshot(
            database_path,
            backup_directory,
            created_at=start + timedelta(days=offset),
        )

    snapshots = sorted(backup_directory.glob("interntrack-before-upgrade-*.db"))
    assert len(snapshots) == 5
    assert snapshots[0].name.endswith("20261103T000000Z.db")
    assert snapshots[-1].name.endswith("20261107T000000Z.db")


def test_missing_database_does_not_create_a_snapshot(tmp_path: Path) -> None:
    backup_directory = tmp_path / "automatic-backups"

    snapshot = create_sqlite_snapshot(
        tmp_path / "missing.db",
        backup_directory,
    )

    assert snapshot is None
    assert not backup_directory.exists()


def test_upgrade_check_compares_recorded_and_expected_revisions(tmp_path: Path) -> None:
    database_path = tmp_path / "interntrack.db"
    _create_database(database_path, revision="current_revision")

    assert current_sqlite_revisions(database_path) == {"current_revision"}
    assert not sqlite_database_needs_upgrade(database_path, {"current_revision"})
    assert sqlite_database_needs_upgrade(database_path, {"next_revision"})


def test_corrupt_database_is_not_silently_replaced(tmp_path: Path) -> None:
    database_path = tmp_path / "interntrack.db"
    database_path.write_bytes(b"not a sqlite database")

    with pytest.raises(DesktopBackupError, match="could not be opened safely"):
        current_sqlite_revisions(database_path)

    assert database_path.read_bytes() == b"not a sqlite database"


def test_failed_migration_reports_verified_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "interntrack.db"
    _create_database(database_path)

    def fail_upgrade(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(command, "upgrade", fail_upgrade)

    with pytest.raises(RuntimeError, match="verified backup is available") as exc_info:
        desktop.run_migrations(database_path)

    snapshots = list((tmp_path / "automatic-backups").glob("*.db"))
    assert len(snapshots) == 1
    assert str(snapshots[0]) in str(exc_info.value)
    with sqlite3.connect(snapshots[0]) as connection:
        company = connection.execute("SELECT company FROM applications").fetchone()
    assert company == ("Example Company",)


def test_current_database_skips_automatic_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "interntrack.db"
    _create_database(database_path, revision="20261107_0006")
    upgrade_calls = []
    monkeypatch.setattr(command, "upgrade", lambda *args: upgrade_calls.append(args))

    snapshot = desktop.run_migrations(database_path)

    assert snapshot is None
    assert len(upgrade_calls) == 1
    assert not (tmp_path / "automatic-backups").exists()


def test_staged_restore_is_applied_with_a_current_workspace_safety_copy(
    tmp_path: Path,
) -> None:
    current_database = tmp_path / "interntrack.db"
    old_database = tmp_path / "old.db"
    _create_database(current_database, revision="current_revision")
    _create_database(old_database, revision="old_revision")
    snapshot = create_sqlite_snapshot(
        old_database,
        tmp_path / "automatic-backups",
    )
    assert snapshot is not None

    pending = stage_desktop_restore(tmp_path, f"upgrade:{snapshot.name}")

    assert pending.exists()
    assert has_pending_restore(tmp_path)
    assert current_sqlite_revisions(current_database) == {"current_revision"}

    safety_snapshot = apply_pending_restore(current_database)

    assert safety_snapshot is not None
    assert current_sqlite_revisions(current_database) == {"old_revision"}
    assert current_sqlite_revisions(safety_snapshot) == {"current_revision"}
    assert not has_pending_restore(tmp_path)
    recovery_points = list_desktop_snapshots(tmp_path)
    assert {point.kind for point in recovery_points} == {"upgrade", "restore"}


def test_invalid_recovery_snapshot_cannot_be_staged(tmp_path: Path) -> None:
    backup_directory = tmp_path / "automatic-backups"
    backup_directory.mkdir()
    corrupt_snapshot = backup_directory / "interntrack-before-upgrade-corrupt.db"
    corrupt_snapshot.write_bytes(b"not sqlite")

    snapshots = list_desktop_snapshots(tmp_path)

    assert len(snapshots) == 1
    assert snapshots[0].valid is False
    with pytest.raises(DesktopBackupError, match="could not be opened safely"):
        stage_desktop_restore(tmp_path, f"upgrade:{corrupt_snapshot.name}")
    with pytest.raises(DesktopBackupError, match="Unknown recovery snapshot"):
        stage_desktop_restore(tmp_path, "upgrade:../interntrack.db")


def test_pending_restore_can_be_cancelled(tmp_path: Path) -> None:
    pending = tmp_path / "pending-restore.db"
    _create_database(pending)

    assert cancel_pending_restore(tmp_path)
    assert not has_pending_restore(tmp_path)
    assert not cancel_pending_restore(tmp_path)


@pytest.mark.anyio
async def test_desktop_recovery_api_stages_and_cancels_restore(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    old_database = tmp_path / "old.db"
    _create_database(old_database, revision="old_revision")
    snapshot = create_sqlite_snapshot(
        old_database,
        tmp_path / "automatic-backups",
    )
    assert snapshot is not None

    listing = await client.get("/desktop/recovery/snapshots")
    prepared = await client.post(
        "/desktop/recovery/restore",
        json={
            "snapshot_id": f"upgrade:{snapshot.name}",
            "password": "securepass123",
            "confirmation": "RESTORE",
        },
    )
    cancelled = await client.delete("/desktop/recovery/restore")

    assert listing.status_code == 200
    assert listing.json()["snapshots"][0]["valid"] is True
    assert prepared.status_code == 200
    assert prepared.json()["restart_required"] is True
    assert cancelled.status_code == 200
    assert cancelled.json()["pending_restore"] is False


@pytest.mark.anyio
async def test_desktop_recovery_requires_password_and_exact_confirmation(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    old_database = tmp_path / "old.db"
    _create_database(old_database)
    snapshot = create_sqlite_snapshot(old_database, tmp_path / "automatic-backups")
    assert snapshot is not None
    payload = {
        "snapshot_id": f"upgrade:{snapshot.name}",
        "password": "wrong-password",
        "confirmation": "RESTORE",
    }

    wrong_password = await client.post("/desktop/recovery/restore", json=payload)
    payload["password"] = "securepass123"
    payload["confirmation"] = "restore"
    wrong_confirmation = await client.post("/desktop/recovery/restore", json=payload)

    assert wrong_password.status_code == 401
    assert wrong_confirmation.status_code == 422
    assert not has_pending_restore(tmp_path)


@pytest.mark.anyio
async def test_desktop_recovery_is_hidden_in_web_mode(client: AsyncClient) -> None:
    response = await client.get("/desktop/recovery/snapshots")

    assert response.status_code == 404
