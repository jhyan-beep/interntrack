"""Consistent, local SQLite snapshots for safe desktop upgrades."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


AUTOMATIC_BACKUP_LIMIT = 5
AUTOMATIC_BACKUP_PATTERN = "interntrack-before-upgrade-*.db"
logger = logging.getLogger("interntrack.desktop_backups")


class DesktopBackupError(RuntimeError):
    """Raised when a trustworthy pre-upgrade snapshot cannot be created."""


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


def _available_backup_path(backup_directory: Path, created_at: datetime) -> Path:
    timestamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = backup_directory / f"interntrack-before-upgrade-{timestamp}.db"
    sequence = 2
    while candidate.exists():
        candidate = backup_directory / (
            f"interntrack-before-upgrade-{timestamp}-{sequence}.db"
        )
        sequence += 1
    return candidate


def _check_snapshot(snapshot_path: Path) -> None:
    with closing(sqlite3.connect(_sqlite_filename(snapshot_path))) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        detail = result[0] if result else "no result"
        raise DesktopBackupError(f"SQLite integrity check failed: {detail}")


def _prune_old_snapshots(backup_directory: Path, keep: int) -> None:
    snapshots = sorted(
        backup_directory.glob(AUTOMATIC_BACKUP_PATTERN),
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
    )
    temporary_path = backup_directory / f".{final_path.name}.{uuid4().hex}.tmp"

    try:
        with closing(sqlite3.connect(_sqlite_filename(database_path))) as source:
            with closing(
                sqlite3.connect(_sqlite_filename(temporary_path))
            ) as destination:
                source.backup(destination)
        _check_snapshot(temporary_path)
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
        _prune_old_snapshots(backup_directory, keep)
    except OSError:
        logger.warning(
            "Created database snapshot at %s but could not prune an older snapshot",
            final_path,
            exc_info=True,
        )

    return final_path
