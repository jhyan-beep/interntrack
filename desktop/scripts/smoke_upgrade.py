"""Install two real Windows desktop versions and verify an in-place upgrade."""

import argparse
import hashlib
import os
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from smoke_desktop import (
    API_URL,
    desktop_session,
    eventually,
    installed_processes,
    port_free,
    ready_runtime,
    require_hosted_workspace,
)
from smoke_sidecar import Client, require


def run_nsis(executable: Path, directory_argument: str = "") -> None:
    # NSIS reads the optional /D= and _?= paths verbatim through the end
    # of the command line. Windows list quoting would break paths with spaces.
    command = subprocess.list2cmdline([str(executable), "/S"])
    if directory_argument:
        command += " " + directory_argument
    subprocess.run(command, executable=str(executable), check=True, timeout=120)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


@contextmanager
def installed_workspace(launcher: Path, edge_driver: Path, output: Path, label: str, version: str):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as conditions
    from selenium.webdriver.support.ui import WebDriverWait

    require(port_free(), "Port 8765 is already in use")
    with desktop_session(launcher, edge_driver, output, label) as driver:
        client = Client(API_URL)
        runtime = eventually(lambda: ready_runtime(client, version), f"Installed {version} API did not become ready", timeout=75)
        wait = WebDriverWait(driver, 30)
        wait.until(lambda window: urlsplit(window.current_url).netloc == "127.0.0.1:8765")
        wait.until(conditions.visibility_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))
        shell = installed_processes(launcher)
        require(shell and runtime["desktop_instance_id"].startswith(f"{shell[0].pid}-"), "API belongs to a different shell")
        require(driver.save_screenshot(str(output / f"{label}-sign-in.png")), f"Could not capture {version} sign-in screen")
        yield client
    eventually(port_free, f"{version} did not release port 8765 after test cleanup")


def seed_account(client: Client, label: str, reminder_days: int):
    today = datetime.now(timezone.utc).date()
    email = f"upgrade-{label}@example.com"
    account = client.json("/auth/register", method="POST", expected=201, body={
        "email": email,
        "password": "UpgradeSmokePassword123!",
    })
    record = client.json("/applications", method="POST", expected=201, body={
        "company": f"Upgrade {label.title()} Company",
        "role": "SWE Intern",
        "status": "applied",
        "application_date": today.isoformat(),
        "deadline": (today + timedelta(days=2)).isoformat(),
        "next_step": "Prepare for an interview",
        "next_step_date": today.isoformat(),
    })
    settings = client.json("/reminders/settings", method="PATCH", body={
        "deadline_reminder_days": reminder_days,
        "deadline_reminders_enabled": True,
        "reminder_timezone": "UTC",
    })
    return account, record, settings


def verify_account(client: Client, saved) -> None:
    account, record, settings = saved
    current = client.json("/auth/me")  # Uses the cookie issued by the previous installer.
    require(current["email"] == account["email"] and current["id"] == account["id"], "Upgrade lost the original account/session")
    records = client.json("/applications")
    require(records["total"] == 1 and records["items"] == [record], "Upgrade changed records or account isolation")
    require(client.json("/reminders/settings") == settings, "Upgrade changed the reminder settings")


def verify_due_reminders(client: Client, application_id: int, *kinds: str) -> None:
    due = client.json("/desktop/reminders/due")["items"]
    actual = sorted((item["application_id"], item["kind"]) for item in due)
    expected = sorted((application_id, kind) for kind in kinds)
    require(actual == expected, f"Unexpected queued reminders for application {application_id}: {actual}")


def verify_upgrade(args: argparse.Namespace) -> None:
    previous = args.previous.resolve()
    candidate = args.candidate.resolve()
    edge_driver = args.edge_driver.resolve()
    output = Path(os.environ.get("RUNNER_TEMP", "."), "interntrack-upgrade-smoke").resolve()
    for installer in (previous, candidate):
        require_hosted_workspace(installer, output)
    require(previous != candidate, "Choose two different installer artifacts")
    require(edge_driver.is_file(), "Missing WebView2 driver")
    output.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="InternTrack upgrade ", dir=os.environ["RUNNER_TEMP"]) as temporary:
        install_dir = Path(temporary) / "installed"
        launcher = install_dir / "interntrack-desktop.exe"
        sidecar = install_dir / "interntrack-api.exe"
        uninstaller = install_dir / "uninstall.exe"
        try:
            run_nsis(previous, f"/D={install_dir}")
            require(launcher.is_file() and sidecar.is_file() and uninstaller.is_file(), "Previous installer did not install expected files")
            old_hashes = [sha256(path) for path in (launcher, sidecar)]
            other = Client(API_URL)
            reminder_kinds = ("deadline", "next_step")
            with installed_workspace(launcher, edge_driver, output, "before", args.previous_version) as owner:
                owner_state = seed_account(owner, "owner", 14)
                other_state = seed_account(other, "other", 3)
                verify_account(owner, owner_state)
                verify_account(other, other_state)
                owner_id, other_id = owner_state[1]["id"], other_state[1]["id"]
                verify_due_reminders(owner, owner_id, *reminder_kinds)
                for kind in reminder_kinds:
                    owner.request(f"/desktop/reminders/{owner_id}/acknowledge?kind={kind}", method="POST", expected=204)
                verify_due_reminders(owner, owner_id)
                verify_due_reminders(other, other_id, *reminder_kinds)
            print(f"PASS: {args.previous_version} installed and created two local workspaces")

            # Let the upgrade find the existing installation through NSIS.
            run_nsis(candidate)
            require(uninstaller.is_file(), "Upgrade lost the installed uninstaller")
            require(all(sha256(path) != old for path, old in zip((launcher, sidecar), old_hashes, strict=True)),
                    "Upgrade did not replace both executables in the original installation directory")
            with installed_workspace(launcher, edge_driver, output, "after", args.candidate_version):
                verify_account(owner, owner_state)
                verify_account(other, other_state)
                verify_due_reminders(owner, owner_id)
                verify_due_reminders(other, other_id, *reminder_kinds)
                print("PASS: acknowledged reminders stay cleared and the other account's reminders stay queued after upgrade")
                saved = owner.json(f"/applications/{owner_id}", method="PATCH", body={"status": "interview"})
                require(saved["status"] == "interview", "Upgraded workspace could not edit an existing application")
                verify_account(other, other_state)
            print(
                f"PASS: upgrading from {args.previous_version} to {args.candidate_version} replaced both executables "
                "and preserved both accounts, sessions, records, and reminder settings"
            )
        finally:
            if uninstaller.is_file():
                run_nsis(uninstaller, f"_?={install_dir}")
                require(not launcher.exists() and not sidecar.exists(), "Uninstall left upgraded executables behind")
                print("PASS: the upgraded application uninstalled successfully")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--edge-driver", type=Path, required=True)
    verify_upgrade(parser.parse_args())
