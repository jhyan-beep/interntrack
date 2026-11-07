"""Consistent, local SQLite snapshots for safe desktop upgrades."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


AUTOMATIC_BACKUP_LIMIT = 5
UPGRADE_BACKUP_PREFIX = "interntrack-before-upgrade"
RESTORE_BACKUP_PREFIX = "interntrack-before-restore"
PENDING_RESTORE_NAME = "pending-restore.db"
logger = logging.getLogger("interntrack.desktop_backups")


class DesktopBackupError(RuntimeError):
    """Raised when a trustworthy pre-upgrade snapshot cannot be created."""


@dataclass(frozen=True)
class DesktopSnapshot:
    snapshot_id: str
    kind: str
    path: Path
    created_at: datetime
    size_bytes: int
    revisions: tuple[str, ...]
    valid: bool


def _sqlite_filename(path: Path) -> str:
    """Give SQLite a long-path-safe filename on Windows."""

    filename = str(path.resolve())
    if os.name == "nt" and not filename.startswith("\\\\?\\"):
        return f"\\\\?\\{filename}"
    return filename


def current_sqlite_revisions(database_path: Path) -> set[str]:
    """Return the Alembic revisions recorded in a desktop SQLite database."""

    if not database_path.exists():
        return set()

    try:
        with closing(sqlite3.connect(_sqlite_filename(database_path))) as connection:
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return set()
        raise DesktopBackupError(
            f"Could not inspect the desktop database at {database_path}"
        ) from exc
    except sqlite3.DatabaseError as exc:
        raise DesktopBackupError(
            f"The desktop database at {database_path} could not be opened safely"
        ) from exc

    return {row[0] for row in rows}


def sqlite_database_needs_upgrade(
    database_path: Path,
    expected_revisions: set[str],
) -> bool:
    """Report whether an existing SQLite database differs from Alembic's heads."""

    if not database_path.exists():
        return True
    return current_sqlite_revisions(database_path) != expected_revisions


def _available_backup_path(
    backup_directory: Path,
    created_at: datetime,
    prefix: str,
) -> Path:
    timestamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = backup_directory / f"{prefix}-{timestamp}.db"
    sequence = 2
    while candidate.exists():
        candidate = backup_directory / f"{prefix}-{timestamp}-{sequence}.db"
        sequence += 1
    return candidate


def validate_sqlite_snapshot(snapshot_path: Path) -> set[str]:
    """Verify that a snapshot is readable and internally consistent."""

    try:
        with closing(sqlite3.connect(_sqlite_filename(snapshot_path))) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DesktopBackupError(
            f"The recovery snapshot at {snapshot_path} could not be opened safely"
        ) from exc
    if result != ("ok",):
        detail = result[0] if result else "no result"
        raise DesktopBackupError(f"SQLite integrity check failed: {detail}")
    return current_sqlite_revisions(snapshot_path)


def _prune_old_snapshots(backup_directory: Path, prefix: str, keep: int) -> None:
    snapshots = sorted(
        backup_directory.glob(f"{prefix}-*.db"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    for expired in snapshots[keep:]:
        os.unlink(_sqlite_filename(expired))


def create_sqlite_snapshot(
    database_path: Path,
    backup_directory: Path,
    *,
    created_at: datetime | None = None,
    keep: int = AUTOMATIC_BACKUP_LIMIT,
    prefix: str = UPGRADE_BACKUP_PREFIX,
) -> Path | None:
    """Create and verify an atomic SQLite snapshot, then enforce retention."""

    if not database_path.exists():
        return None
    if keep < 1:
        raise ValueError("keep must be at least 1")

    backup_directory.mkdir(parents=True, exist_ok=True)
    final_path = _available_backup_path(
        backup_directory,
        created_at or datetime.now(timezone.utc),
        prefix,
    )
    temporary_path = backup_directory / f".{final_path.name}.{uuid4().hex}.tmp"

    try:
        with closing(sqlite3.connect(_sqlite_filename(database_path))) as source:
            with closing(
                sqlite3.connect(_sqlite_filename(temporary_path))
            ) as destination:
                source.backup(destination)
        validate_sqlite_snapshot(temporary_path)
        os.replace(_sqlite_filename(temporary_path), _sqlite_filename(final_path))
    except (OSError, sqlite3.Error, DesktopBackupError) as exc:
        try:
            os.unlink(_sqlite_filename(temporary_path))
        except OSError:
            pass
        if isinstance(exc, DesktopBackupError):
            raise
        raise DesktopBackupError(
            f"Could not create a safe database snapshot in {backup_directory}"
        ) from exc

    try:
        _prune_old_snapshots(backup_directory, prefix, keep)
    except OSError:
        logger.warning(
            "Created database snapshot at %s but could not prune an older snapshot",
            final_path,
            exc_info=True,
        )

    return final_path


def _snapshot_locations(data_directory: Path) -> dict[str, tuple[Path, str]]:
    return {
        "upgrade": (data_directory / "automatic-backups", UPGRADE_BACKUP_PREFIX),
        "restore": (data_directory / "recovery-backups", RESTORE_BACKUP_PREFIX),
    }


def list_desktop_snapshots(data_directory: Path) -> list[DesktopSnapshot]:
    """List known recovery points without exposing arbitrary local paths."""

    snapshots: list[DesktopSnapshot] = []
    for kind, (directory, prefix) in _snapshot_locations(data_directory).items():
        if not directory.exists():
            continue
        for path in directory.glob(f"{prefix}-*.db"):
            try:
                revisions = tuple(sorted(validate_sqlite_snapshot(path)))
                valid = True
            except DesktopBackupError:
                revisions = ()
                valid = False
            stat = path.stat()
            snapshots.append(
                DesktopSnapshot(
                    snapshot_id=f"{kind}:{path.name}",
                    kind=kind,
                    path=path,
                    created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                    size_bytes=stat.st_size,
                    revisions=revisions,
                    valid=valid,
                )
            )
    return sorted(snapshots, key=lambda item: item.created_at, reverse=True)


def resolve_desktop_snapshot(data_directory: Path, snapshot_id: str) -> Path:
    """Resolve an allow-listed snapshot identifier inside the desktop data directory."""

    try:
        kind, filename = snapshot_id.split(":", 1)
        directory, prefix = _snapshot_locations(data_directory)[kind]
    except (KeyError, ValueError) as exc:
        raise DesktopBackupError("Unknown recovery snapshot") from exc
    if filename != Path(filename).name or not Path(filename).match(f"{prefix}-*.db"):
        raise DesktopBackupError("Unknown recovery snapshot")
    snapshot_path = directory / filename
    if not snapshot_path.is_file():
        raise DesktopBackupError("Recovery snapshot no longer exists")
    return snapshot_path


def _copy_sqlite_database(source_path: Path, destination_path: Path) -> None:
    temporary_path = destination_path.with_name(
        f".{destination_path.name}.{uuid4().hex}.tmp"
    )
    try:
        with closing(sqlite3.connect(_sqlite_filename(source_path))) as source:
            with closing(
                sqlite3.connect(_sqlite_filename(temporary_path))
            ) as destination:
                source.backup(destination)
        validate_sqlite_snapshot(temporary_path)
        os.replace(_sqlite_filename(temporary_path), _sqlite_filename(destination_path))
    except (OSError, sqlite3.Error, DesktopBackupError) as exc:
        try:
            os.unlink(_sqlite_filename(temporary_path))
        except OSError:
            pass
        if isinstance(exc, DesktopBackupError):
            raise
        raise DesktopBackupError("Could not stage the selected recovery snapshot") from exc


def stage_desktop_restore(data_directory: Path, snapshot_id: str) -> Path:
    """Validate and copy a selected recovery point for the next app launch."""

    snapshot_path = resolve_desktop_snapshot(data_directory, snapshot_id)
    validate_sqlite_snapshot(snapshot_path)
    pending_path = data_directory / PENDING_RESTORE_NAME
    _copy_sqlite_database(snapshot_path, pending_path)
    return pending_path


def cancel_pending_restore(data_directory: Path) -> bool:
    pending_path = data_directory / PENDING_RESTORE_NAME
    try:
        os.unlink(_sqlite_filename(pending_path))
    except FileNotFoundError:
        return False
    return True


def has_pending_restore(data_directory: Path) -> bool:
    return (data_directory / PENDING_RESTORE_NAME).is_file()


def apply_pending_restore(database_path: Path) -> Path | None:
    """Apply a staged restore before SQLAlchemy or Alembic opens the live database."""

    pending_path = database_path.parent / PENDING_RESTORE_NAME
    if not pending_path.exists():
        return None
    validate_sqlite_snapshot(pending_path)

    safety_snapshot = create_sqlite_snapshot(
        database_path,
        database_path.parent / "recovery-backups",
        prefix=RESTORE_BACKUP_PREFIX,
    )
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar_path = Path(f"{database_path}{suffix}")
        try:
            os.unlink(_sqlite_filename(sidecar_path))
        except FileNotFoundError:
            pass
    os.replace(_sqlite_filename(pending_path), _sqlite_filename(database_path))
    return safety_snapshot
