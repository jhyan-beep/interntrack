"""Exercise the frozen Windows API with fictional data and no Python on PATH."""

import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


def require(condition, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(self, path: str, method="GET", body=None, expected=200):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Origin": self.base_url, "Content-Type": "application/json"}
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            require(response.status == expected, f"{method} {path}: expected {expected}, got {response.status}")
            return content

    def json(self, path: str, **kwargs):
        return json.loads(self.request(path, **kwargs))


@contextmanager
def running(binary: Path, directory: Path, client: Client, port: int):
    # Only this generated test workspace and this process tree are affected.
    environment = os.environ.copy()
    for name in ("OPENAI_API_KEY", "GOOGLE_OAUTH_CLIENT_ID", "MICROSOFT_OAUTH_CLIENT_ID"):
        environment[name] = ""
    system_root = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join(str(path) for path in (system_root, system_root / "System32"))
    with (directory / "smoke.log").open("ab") as log:
        process = subprocess.Popen(
            [str(binary), "--port", str(port), "--data-dir", str(directory / "data")],
            cwd=directory, env=environment, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            deadline = time.monotonic() + 60
            while True:
                require(process.poll() is None, "Packaged API exited before becoming ready")
                try:
                    client.request("/health/ready")
                    break
                except (URLError, TimeoutError, RuntimeError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Packaged API was not ready within 60 seconds")
                    time.sleep(0.25)
            yield
        finally:
            if process.poll() is None:
                # PyInstaller one-file binaries have a bootloader child.
                subprocess.run(
                    [str(system_root / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
            process.wait(timeout=15)


def smoke(binary: Path, expected_version: str) -> None:
    require(os.name == "nt", "The packaged sidecar smoke test requires Windows")
    require(binary.is_file(), f"Packaged API does not exist: {binary}")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    client = Client(f"http://127.0.0.1:{port}")
    with tempfile.TemporaryDirectory(prefix="interntrack-smoke-") as temporary:
        directory = Path(temporary)
        try:
            with running(binary, directory, client, port):
                runtime = client.json("/runtime")
                require(runtime["app_version"] == expected_version, "Packaged app version differs from release metadata")
                require(runtime["mode"] == "desktop" and not runtime["ai_available"], "Unexpected desktop capabilities")
                html = client.request("/").decode("utf-8")
                asset = re.search(r'src="(/assets/[^"]+\.js)"', html)
                require(asset is not None, "Packaged frontend entrypoint is missing")
                client.request(asset.group(1))
                client.request("/applications/calendar.ics", expected=401)
                user = client.json("/auth/register", method="POST", expected=201, body={
                    "email": "packaged-smoke@example.com", "password": "SmokeTestPassword123!",
                })
                require(user["email_verified"], "Desktop account unexpectedly requires cloud email")
                today = datetime.now(timezone.utc).date()
                application = {
                    "company": "Packaged Smoke Co", "role": "SWE Intern", "status": "applied",
                    "application_date": today.isoformat(),
                    "deadline": (today + timedelta(days=3)).isoformat(),
                    "next_step": "Practice interview", "next_step_date": today.isoformat(),
                    "notes": "PRIVATE_SMOKE_NOTES",
                }
                created = client.json("/applications", method="POST", expected=201, body=application)
                item_path = f"/applications/{created['id']}"
                require(client.json(item_path)["company"] == application["company"], "Created application was not readable")
                updated = client.json(item_path, method="PATCH", body={"status": "interview"})
                require(updated["status"] == "interview", "Application update failed")
                extra = client.json("/applications", method="POST", expected=201, body={**application, "company": "Delete Smoke Co"})
                client.request(f"/applications/{extra['id']}", method="DELETE", expected=204)
                require(client.json("/applications")["total"] == 1, "Application delete failed")
                csv = client.request("/applications/export.csv").decode("utf-8")
                require("Packaged Smoke Co" in csv, "CSV export lost the application")
                calendar = client.request("/applications/calendar.ics").decode("utf-8")
                require(calendar.split("\r\n").count("BEGIN:VEVENT") == 2, "Calendar export should contain two events")
                require("PRIVATE_SMOKE_NOTES" not in calendar, "Calendar export included private notes")
                client.json("/reminders/settings", method="PATCH", body={
                    "deadline_reminders_enabled": True, "deadline_reminder_days": 7, "reminder_timezone": "UTC",
                })
                due = client.json("/desktop/reminders/due")["items"]
                require({item["kind"] for item in due} == {"deadline", "next_step"}, "Packaged reminder selection failed")
                for item in due:
                    client.request(
                        f"/desktop/reminders/{item['application_id']}/acknowledge?kind={item['kind']}",
                        method="POST", expected=204,
                    )
                require(not client.json("/desktop/reminders/due")["items"], "Acknowledged reminders were repeated")
                backup = client.json("/desktop/backups/export")
                client.json("/applications", method="POST", expected=201, body={**application, "company": "Temporary Extra"})
                restored = client.json("/desktop/backups/restore", method="POST", body={
                    "backup": backup, "mode": "replace", "confirm_replace": True,
                })
                require(restored["removed_applications"] == 2 and restored["imported_applications"] == 1, "Backup replacement failed")
                # Portable backups intentionally exclude notification history.
                for item in client.json("/desktop/reminders/due")["items"]:
                    client.request(
                        f"/desktop/reminders/{item['application_id']}/acknowledge?kind={item['kind']}",
                        method="POST", expected=204,
                    )
                print("PASS: bundled frontend, authentication, CRUD, CSV/calendar, reminders, backup restore")
            with running(binary, directory, client, port):
                require(client.json("/auth/me")["email"] == user["email"], "Session secret changed after restart")
                records = client.json("/applications")
                require(records["total"] == 1 and records["items"][0]["company"] == "Packaged Smoke Co", "Workspace did not survive restart")
                require(not client.json("/desktop/reminders/due")["items"], "Reminder history did not survive restart")
                require((directory / "data" / "interntrack.db").is_file(), "Persistent local database was not created")
                print("PASS: restart preserves session, application data, and reminder history")
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
    smoke(args.binary.resolve(), args.expected_version)

