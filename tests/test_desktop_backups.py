import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command

from app import desktop
from app.desktop_backups import (
    DesktopBackupError,
    create_sqlite_snapshot,
    current_sqlite_revisions,
    sqlite_database_needs_upgrade,
)


def _create_database(path: Path, revision: str = "old_revision") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        connection.execute("CREATE TABLE applications (company TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO applications (company) VALUES ('Example Company')"
        )


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
