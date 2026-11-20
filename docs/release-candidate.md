# InternTrack 0.2.0-rc.3

This candidate consolidates the web and desktop work for a controlled Windows beta. It is not a signed stable release.

## Desktop startup recovery

The shell opens the tracker only after the HTTP runtime reports the matching version and per-launch instance ID, and the database readiness endpoint succeeds. A listening TCP port alone is not sufficient. The instance ID is a launch correlation value, not an account credential.

An occupied port, a missing or stopped service, or a one-minute readiness timeout displays a local error page with Retry and Quit controls. Startup errors also reveal a window after hidden autostart. Retry restarts the desktop process without resetting account data. Sidecar processes share a Windows process group so quitting or restarting the shell also stops the frozen API's child process.

The recovery address is the explicit bundled asset URL. WebView2 may report `about:blank` during setup before its first navigation completes; saving that transient URL caused an early startup failure to navigate to a blank page instead of the error screen.

The shell also passes its PID to the frozen API. A Windows monitor holds a synchronization-only process handle and stops the API worker if that shell exits unexpectedly, allowing the PyInstaller bootloader to exit as well. This covers abrupt process termination, where Rust destructors and graceful exit handlers cannot run. Manual standalone API launches omit the parent PID and retain their normal lifetime.

## Integration decisions

- PRs #3–#28 form one continuous ancestry chain from main through the React dashboard, authentication, desktop shell, backups, email integrations, and calendar export. The candidate retains all those commits and their history.
- PR #2 is an alternate earlier implementation. Its vanilla-JavaScript dashboard is superseded by the React app. Its historical date consistency checks are covered by the current schemas/routes and regression tests, including rejecting a changed application date without modifying the record.
- The useful hosted PostgreSQL URL normalization from PR #2 is incorporated in Settings so both Alembic and the API select psycopg 3. Explicit alternative drivers remain unchanged.
- The old Render blueprint is not carried over: it predates the SMTP, HTTPS, secret, and migration requirements in the current production configuration.
- Once the integration PR is merged with its history intact, superseded open PRs can be closed with a link to the consolidated change. Feature branches remain available for reference.

## What the automated gates verify

The standard CI runs PostgreSQL migrations, migration drift checks, pytest, the production frontend build, production Compose validation, and the non-root Docker image build.

The Windows workflow validates the version in Python, Tauri, Cargo, and the desktop package, runs the Rust HTTP readiness tests, builds the frozen API and NSIS installer, and silently installs it into a generated directory on a disposable GitHub-hosted Windows runner. It verifies the installed launcher, API and uninstaller, exercises the installed API with only Windows system directories on its PATH, then silently uninstalls the package. The installer script refuses to run on ordinary local machines or self-hosted runners. The runtime smoke checks exercise:

- Bundled frontend delivery and the exact candidate version.
- Account creation and session authentication.
- Application creation, CSV and calendar export.
- Deadline and next-action reminder selection and acknowledgement.
- Portable backup replacement.
- Process restart with session, application, and reminder history persistence.
- Migration of an Alembic revision 20261107_0005 fixture with two accounts, retaining their data and creating a verified pre-upgrade snapshot.
- Password-confirmed recovery staging, cancellation, restart application, and rollback to the automatic pre-restore snapshot.

The smoke harness uses a Python interpreter, but the application process is the installed standalone executable and cannot find Python on PATH. The migration fixture uses the actual older schema, rather than a second historical installer. These checks verify a hosted-runner silent install and schema/recovery lifecycle; clean-machine graphical installation, cross-version installer upgrades, and native notifications still require the manual gates below.

### Installed desktop window checks

The installer check also runs the installed Tauri launcher through Microsoft Edge WebDriver and its real WebView2 window. The CI-only Python harness uses Selenium and psutil; neither is an application runtime dependency. It refuses to run outside a GitHub-hosted Windows runner, requires the launcher and diagnostics paths to be inside RUNNER_TEMP, and uses only fictional account data. The API/launcher files remain the installed standalone executables. Automation is enabled only in the test driver's child environment, with no test commands or bypasses added to the application.

The harness checks the occupied-port error page and its rendered Quit button; opening the bundled React sign-in page from the shell's own ready API; graceful shutdown of the frozen API tree; the real recovery page after API termination; rendered Retry starting a fresh service while preserving a fictional session and record; and process cleanup after abrupt shell termination. It saves screenshots and driver logs to the **InternTrack-Desktop-Smoke** artifact, including failure screenshots when the driver is available. The diagnostics expire after 14 days. A failed window check blocks the candidate installer upload.

These hosted-runner checks supplement the manual gates. They do not verify tray interaction, native notifications, all timeout cases, or cross-version installer upgrades. See [Microsoft's WebView2 automation guide](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/webdriver) and [Tauri's WebDriver setup](https://tauri.app/develop/tests/webdriver/manual-setup/) for the automation interface and matching Edge WebDriver requirement.

### In-place installer upgrade

The separate [Windows Desktop Upgrade workflow](../.github/workflows/desktop-upgrade.yml) runs two real NSIS installers on a hosted Windows machine. It creates two local accounts in the previous version, upgrades the same installation, opens the new desktop window, and checks that both sessions, isolated application records, and reminder preferences survive. It also edits a preserved record and verifies that the upgraded application uninstalls. The browser screenshots and driver logs are available in the upgrade run.

To repeat the check, run **Windows Desktop Upgrade** with the artifact IDs of two unexpired installers from successful **Windows Desktop** runs in this repository. Use the numeric ID at the end of each artifact link. Tests of changes to the upgrade workflow or harness use the recorded rc.2 and rc.3 artifacts. If they expire, refresh the defaults with a verified pair. Graphical upgrades and tray behavior on a consumer Windows machine remain part of manual acceptance.

The Windows jobs currently use the hosted Windows Server 2022 image because the newer Server 2025 WebView2 automation session can fail before tests connect ([upstream runner report](https://github.com/actions/runner-images/issues/14738)). Driver setup detects the actual installed WebView2 version and reuses a matching driver, or downloads that version from Microsoft's WebDriver distribution. It does not downgrade or bundle a runtime in the application. A passing check on this runner does not complete acceptance on current consumer Windows/WebView2 releases.

## Candidate download

Open the successful **Windows Desktop** check for the current candidate PR (or a manual run at its merged commit), then download **InternTrack-Windows-x64-0.2.0-rc.3**. Confirm that the run uses the intended candidate commit. The artifact contains an unsigned installer intended for controlled testing. Do not present it as a signed public stable release.

The signed release workflow remains gated on the signing credentials described in [desktop-release.md](desktop-release.md). Do not push a release tag merely to obtain an unsigned download.

## Manual release gates

Record the machine, Windows version, installer checksum, result, and any issue for each gate. Leave an unchecked gate pending until it has actually been exercised.

- [ ] On a clean Windows x64 machine without Python, install and launch the NSIS package.
- [ ] Confirm the app opens its own window, a second launch focuses the first window, and Quit stops the sidecar.
- [ ] Occupy port 8765 before launch and verify the error page, then free the port and use Retry. Check that account records survive.
- [ ] Test a failed API start, readiness timeout, and API termination after opening. Verify the visible error, Retry, and Quit, including hidden autostart. Browser fixtures and HTTP unit tests do not complete this native-shell gate.
- [ ] Close to tray, reopen, and verify optional start-with-Windows behavior.
- [ ] Allow native notifications and verify an actual deadline and next-action notification.
- [ ] Upgrade an earlier installed version and verify accounts, records, settings, and recovery points survive.
- [ ] Exercise recovery staging, cancel, restart, and restoration through the installed UI.
- [ ] Complete real AI, Gmail, and Outlook workflows using tester-owned credentials; review authorization denial, expiration, and disconnect.
- [ ] Import a calendar export in each advertised calendar client.
- [ ] Complete Authenticode signing, checksum verification, and draft release review before stable publication.

See the [user guide](user-guide.md) for the tester workflow.

