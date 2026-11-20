import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows process handles are used by the desktop shell")
def test_worker_stays_alive_with_parent_and_exits_when_parent_is_killed(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    worker = None
    try:
        worker = subprocess.Popen(
            [sys.executable, "-c", (
                "import sys, time; from pathlib import Path; "
                "from app.desktop_process import monitor_desktop_parent; "
                "monitor_desktop_parent(int(sys.argv[1])); "
                "Path(sys.argv[2]).touch(); time.sleep(60)"
            ), str(parent.pid), str(ready)],
            cwd=Path(__file__).resolve().parents[1],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            assert worker.poll() is None, "Parent monitor failed before the worker became ready"
            time.sleep(0.05)
        assert ready.exists(), "Worker did not start its parent monitor"
        assert worker.poll() is None
        parent.kill()
        parent.wait(timeout=5)
        assert worker.wait(timeout=5) == 0
    finally:
        for process in (worker, parent):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows process handles are used by the desktop shell")
def test_worker_does_not_start_if_parent_has_already_exited() -> None:
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    parent.kill()
    parent.wait(timeout=5)
    worker = subprocess.run(
        [sys.executable, "-c", (
            "import sys; from app.desktop_process import monitor_desktop_parent; "
            "monitor_desktop_parent(int(sys.argv[1])); print('UNEXPECTED_START')"
        ), str(parent.pid)],
        cwd=Path(__file__).resolve().parents[1],
        creationflags=subprocess.CREATE_NO_WINDOW,
        capture_output=True, timeout=5,
    )
    assert worker.returncode == 0
    assert b"UNEXPECTED_START" not in worker.stdout
