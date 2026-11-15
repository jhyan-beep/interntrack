"""Verify old-schema migration and reversible whole-workspace recovery."""

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from argon2 import PasswordHasher

from smoke_sidecar import Client, require, running


PASSWORD = "RecoverySmokePassword123!"
OLD_REVISION = "20261107_0005"


def seed_old_workspace(directory: Path) -> None:
    data = directory / "data"
    data.mkdir()
    database = data / "interntrack.db"
    root = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "DATABASE_URL": "sqlite:///" + database.as_posix(),
        "ENVIRONMENT": "test",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", OLD_REVISION],
        cwd=root, env=environment, check=True, timeout=60,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    now = datetime.now(timezone.utc).isoformat()
    password_hash = PasswordHasher().hash(PASSWORD)
    with closing(sqlite3.connect(database)) as connection:
        for user_id, email, company in (
            (1, "recovery-owner@example.com", "Before upgrade"),
            (2, "recovery-other@example.com", "Other account"),
        ):
            connection.execute(
                "INSERT INTO users (id, email, password_hash, created_at, email_verified_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, password_hash, now, now),
            )
            connection.execute(
                """INSERT INTO internship_applications
                (user_id, company, role, status, application_date, created_at, updated_at)
                VALUES (?, ?, 'SWE Intern', 'applied', ?, ?, ?)""",
                (user_id, company, now[:10], now, now),
            )
        connection.commit()


def recovery_smoke(binary: Path, expected_version: str) -> None:
    require(os.name == "nt", "Frozen desktop recovery verification requires Windows")
    require(binary.is_file(), f"Packaged API does not exist: {binary}")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    client = Client(f"http://127.0.0.1:{port}")
    with tempfile.TemporaryDirectory(prefix="interntrack-recovery-") as temporary:
        directory = Path(temporary)
        seed_old_workspace(directory)
        try:
            with running(binary, directory, client, port):
                require(client.json("/runtime")["app_version"] == expected_version, "Unexpected packaged version")
                client.json("/auth/login", method="POST", body={
                    "email": "recovery-owner@example.com", "password": PASSWORD,
                })
                records = client.json("/applications")
                require(records["total"] == 1 and records["items"][0]["company"] == "Before upgrade", "Migration changed existing records or account isolation")
                settings = client.json("/reminders/settings")
                points = client.json("/desktop/recovery/snapshots")["snapshots"]
                old = next((point for point in points if point["kind"] == "upgrade" and OLD_REVISION in point["revisions"]), None)
                require(old is not None and old["valid"], "No verified snapshot was created before migration")
                item_id = records["items"][0]["id"]
                client.json(f"/applications/{item_id}", method="PATCH", body={"company": "After upgrade"})
                client.json("/applications", method="POST", expected=201, body={
                    "company": "Added after upgrade", "role": "SWE Intern",
                })
                client.json("/reminders/settings", method="PATCH", body={"deadline_reminder_days": 14})
                restore = {"snapshot_id": old["snapshot_id"], "password": PASSWORD, "confirmation": "RESTORE"}
                client.request("/desktop/recovery/restore", method="POST", body={**restore, "password": "wrong"}, expected=401)
                prepared = client.json("/desktop/recovery/restore", method="POST", body=restore)
                require(prepared["pending_restore"] and prepared["restart_required"], "Recovery did not require a restart")
                cancelled = client.json("/desktop/recovery/restore", method="DELETE")
                require(not cancelled["pending_restore"], "Recovery cancellation failed")
                require(client.json("/applications")["total"] == 2, "Staging/cancellation changed live data")
                client.json("/desktop/recovery/restore", method="POST", body=restore)
                secret = (directory / "data" / "secret.key").read_bytes()
                print("PASS: old-schema upgrade preserves accounts/data and creates a verified recovery point")

            with running(binary, directory, client, port):
                records = client.json("/applications")
                require(records["total"] == 1 and records["items"][0]["company"] == "Before upgrade", "Restart did not restore the selected workspace")
                require(client.json("/reminders/settings") == settings, "Reminder preferences were not restored")
                require((directory / "data" / "secret.key").read_bytes() == secret, "Session secret changed during restore")
                require(not client.json("/desktop/recovery/snapshots")["pending_restore"], "Restore request was not consumed")
                other = Client(client.base_url)
                other.json("/auth/login", method="POST", body={
                    "email": "recovery-other@example.com", "password": PASSWORD,
                })
                require(other.json("/applications")["items"][0]["company"] == "Other account", "Whole-workspace recovery lost another account")
                points = client.json("/desktop/recovery/snapshots")["snapshots"]
                rollback = next((point for point in points if point["kind"] == "restore" and point["valid"]), None)
                require(rollback is not None, "Recovery did not preserve a rollback snapshot")
                client.json("/desktop/recovery/restore", method="POST", body={
                    "snapshot_id": rollback["snapshot_id"], "password": PASSWORD, "confirmation": "RESTORE",
                })
                print("PASS: staged restore applies on restart; sessions, settings, and both accounts survive")

            with running(binary, directory, client, port):
                records = client.json("/applications")
                require(records["total"] == 2, "Rollback did not recover the newer workspace")
                require({item["company"] for item in records["items"]} == {"After upgrade", "Added after upgrade"}, "Rollback restored unexpected records")
                require(client.json("/reminders/settings")["deadline_reminder_days"] == 14, "Rollback lost newer preferences")
                print("PASS: recovery can be reversed using the automatic pre-restore snapshot")
            with closing(sqlite3.connect(directory / "data" / "interntrack.db")) as connection:
                require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Recovered database failed integrity check")
        except Exception:
            log = directory / "smoke.log"
            if log.exists():
                print(log.read_text(encoding="utf-8", errors="replace")[-5000:])
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    recovery_smoke(args.binary.resolve(), args.expected_version)
