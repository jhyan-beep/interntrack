"""Exercise the installed Windows shell on a disposable GitHub-hosted runner."""

import argparse
import os
import socket
import time
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from smoke_sidecar import Client, require


API_URL = "http://127.0.0.1:8765"


def require_hosted_workspace(launcher: Path, output: Path) -> None:
    require(
        os.name == "nt"
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("RUNNER_OS") == "Windows",
        "Native desktop verification requires a disposable GitHub-hosted Windows runner",
    )
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(launcher.is_relative_to(root) and launcher.is_file(), "Launcher must be installed inside RUNNER_TEMP")
    require(output != root and output.is_relative_to(root), "Diagnostics must be inside RUNNER_TEMP")


def eventually(predicate, message: str, timeout: float = 45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.2)
    raise RuntimeError(message)


def installed_processes(launcher: Path):
    import psutil

    found = []
    for process in psutil.process_iter(["exe"]):
        try:
            if process.info["exe"] and Path(process.info["exe"]).resolve() == launcher:
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    require(len(found) <= 1, "More than one installed shell is running")
    return found


def api_children(app, sidecar: Path):
    import psutil

    found = []
    for process in app.children(recursive=True):
        try:
            if Path(process.exe()).resolve() == sidecar:
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def stopped(processes) -> bool:
    return all(not process.is_running() for process in processes)


def port_free() -> bool:
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 8765))
        except OSError:
            return False
    return True


@contextmanager
def desktop_session(launcher: Path, edge_driver: Path, output: Path, name: str):
    # Import optional tooling only after the hosted-runner/path guards have run.
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service

    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith(("WINDOWS_CERTIFICATE", "WINDOWS_TIMESTAMP", "TAURI_SIGNING")) or key in (
            "OPENAI_API_KEY", "GOOGLE_OAUTH_CLIENT_ID", "MICROSOFT_OAUTH_CLIENT_ID", "GH_TOKEN", "GITHUB_TOKEN",
        ):
            environment.pop(key)
    environment["TAURI_WEBVIEW_AUTOMATION"] = "true"
    options = Options()
    options.use_webview = True
    options.binary_location = str(launcher)
    options.page_load_strategy = "eager"
    service = Service(executable_path=str(edge_driver), log_output=str(output / f"{name}-driver.log"), env=environment)
    driver = None
    try:
        driver = webdriver.Edge(service=service, options=options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(8)
        yield driver
    except Exception:
        if driver is not None:
            try:
                (output / f"{name}-failure.txt").write_text(
                    f"URL: {driver.current_url}\n\n{driver.page_source}", encoding="utf-8",
                )
                driver.save_screenshot(str(output / f"{name}-failure.png"))
            except WebDriverException:
                pass
        # Process ownership is useful even when a restarted app has already
        # disconnected the original WebDriver session.
        owners = installed_processes(launcher)
        evidence = [{"pid": app.pid, "children": [child.pid for child in app.children(recursive=True)]} for app in owners]
        (output / f"{name}-processes.txt").write_text(str(evidence), encoding="utf-8")
        raise
    finally:
        # Cleanup is restricted to this test's uniquely installed executable.
        # Assertions below verify shutdown before this fallback can hide a leak.
        for app in installed_processes(launcher):
            descendants = app.children(recursive=True)
            app.kill()
            app.wait(timeout=15)
            for process in descendants:
                if process.is_running():
                    process.kill()
        if driver is not None:
            try:
                driver.quit()
            except WebDriverException:
                pass
        service.stop()


def wait_for_error(driver, code: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as conditions
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, 30).until(conditions.text_to_be_present_in_element((By.ID, "error-code"), code))
    require(driver.find_element(By.ID, "retry").is_displayed(), "Retry is not visible")
    require(driver.find_element(By.ID, "quit").is_enabled(), "Quit is not available")


def ready_runtime(client: Client, version: str, previous_instance=None):
    from urllib.error import URLError

    try:
        runtime = client.json("/runtime")
        if runtime["app_version"] != version or runtime["mode"] != "desktop":
            return False
        instance = runtime.get("desktop_instance_id")
        if not instance or instance == previous_instance:
            return False
        return runtime if client.json("/health/ready")["status"] == "ready" else False
    except (OSError, URLError, RuntimeError):
        return False


def smoke(launcher: Path, edge_driver: Path, version: str, output: Path) -> None:
    import psutil
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as conditions
    from selenium.webdriver.support.ui import WebDriverWait

    sidecar = launcher.parent / "interntrack-api.exe"
    require(sidecar.is_file() and edge_driver.is_file(), "Installed API or Edge WebDriver is missing")
    require(not installed_processes(launcher) and port_free(), "Desktop smoke needs an unused local port 8765")
    output.mkdir(parents=True, exist_ok=True)

    # Test the real bundled error page, its native IPC origin guard, and Quit.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8765))
        listener.listen()
        with desktop_session(launcher, edge_driver, output, "occupied-port") as driver:
            wait_for_error(driver, "port-unavailable")
            startup_url = driver.current_url
            app = eventually(lambda: installed_processes(launcher), "Installed shell did not start")[0]
            require(not api_children(app, sidecar), "A sidecar was launched despite the occupied port")
            require(driver.save_screenshot(str(output / "occupied-port.png")), "Could not capture the error page")
            try:
                driver.find_element(By.ID, "quit").click()
            except WebDriverException:
                pass  # Closing the app may disconnect the WebDriver command.
            eventually(lambda: stopped([app]), "Quit did not stop the installed shell")
    print("PASS: installed shell reports an occupied port; rendered Quit stops it")

    client = Client(API_URL)
    with desktop_session(launcher, edge_driver, output, "normal-start") as driver:
        wait = WebDriverWait(driver, 75)
        wait.until(lambda current: urlsplit(current.current_url).netloc == "127.0.0.1:8765")
        wait.until(conditions.visibility_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))
        runtime = eventually(lambda: ready_runtime(client, version), "Installed shell API did not become ready")
        app = installed_processes(launcher)[0]
        require(runtime["desktop_instance_id"].startswith(f"{app.pid}-"), "Window loaded a different shell's API")
        children = api_children(app, sidecar)
        require(children, "The shell does not own the running API")
        require(driver.save_screenshot(str(output / "normal-start.png")), "Could not capture the installed frontend")

        # Preserve a fictional account/session/record across the native Retry.
        email = f"native-{uuid.uuid4().hex}@example.com"
        client.json("/auth/register", method="POST", expected=201, body={"email": email, "password": "NativeSmokePassword123!"})
        record = client.json("/applications", method="POST", expected=201, body={
            "company": "Native Shell Smoke Co", "role": "SWE Intern", "status": "applied",
            "application_date": date.today().isoformat(),
        })

        # The Quit command is bundled-page-only. Navigate to that real origin to
        # test graceful shutdown while the API is alive; the earlier test clicks
        # the rendered button. No test-only commands are added to the app.
        driver.get(startup_url)
        try:
            driver.execute_async_script("window.__TAURI__.core.invoke('quit_desktop_startup').then(arguments[0], arguments[0]);")
        except WebDriverException:
            pass
        eventually(lambda: stopped([app, *children]) and port_free(), "Quit left a frozen API process or occupied port")
    print("PASS: installed window loads its own frontend; graceful Quit stops the frozen API tree")

    with desktop_session(launcher, edge_driver, output, "service-exit") as driver:
        WebDriverWait(driver, 75).until(lambda current: urlsplit(current.current_url).netloc == "127.0.0.1:8765")
        before = eventually(lambda: ready_runtime(client, version), "Second desktop start was not ready")
        app = installed_processes(launcher)[0]
        children = api_children(app, sidecar)
        owned_ids = {process.pid for process in children}
        listeners = [connection for connection in psutil.net_connections(kind="tcp")
                     if connection.status == psutil.CONN_LISTEN and connection.laddr.port == 8765]
        require(len(listeners) == 1 and listeners[0].pid in owned_ids, "API listener is outside the owned process tree")
        psutil.Process(listeners[0].pid).kill()
        wait_for_error(driver, "service-stopped")
        require(driver.save_screenshot(str(output / "service-stopped.png")), "Could not capture the stopped-service page")
        try:
            driver.find_element(By.ID, "retry").click()
        except WebDriverException:
            pass
        eventually(lambda: stopped([app, *children]), "Retry did not stop the original shell and API")
        after = eventually(lambda: ready_runtime(client, version, before["desktop_instance_id"]), "Retry did not start a fresh ready API", timeout=75)
        restarted = installed_processes(launcher)[0]
        require(after["desktop_instance_id"].startswith(f"{restarted.pid}-"), "Retry attached to an unrelated service")
        require(client.json("/auth/me")["email"] == email, "Native Retry lost the persistent session")
        require(client.json(f"/applications/{record['id']}")["company"] == "Native Shell Smoke Co", "Native Retry lost account records")
        print("PASS: API termination shows the real recovery page; rendered Retry restarts and preserves session/data")

        # A shell crash must also close its Windows job and terminate API children.
        restarted_children = api_children(restarted, sidecar)
        require(restarted_children, "Restarted API is outside the shell's process group")
        # Retain handles before killing the owner, so PID reuse cannot satisfy
        # the test and cleanup still knows these children after reparenting.
        restarted.kill()
        restarted.wait(timeout=15)
        try:
            eventually(lambda: stopped(restarted_children) and port_free(), "Shell termination orphaned frozen API children")
        finally:
            for process in restarted_children:
                if process.is_running():
                    process.kill()
    print("PASS: abrupt shell termination also stops its frozen API children")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--edge-driver", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    launcher, output = args.launcher.resolve(), args.output_directory.resolve()
    require_hosted_workspace(launcher, output)
    smoke(launcher, args.edge_driver.resolve(), args.expected_version, output)


if __name__ == "__main__":
    main()
