# InternTrack 0.2.0-rc.1

This candidate consolidates the web and desktop work for a controlled Windows beta. It is not a signed stable release.

## Integration decisions

- PRs #3–#28 form one continuous ancestry chain from main through the React dashboard, authentication, desktop shell, backups, email integrations, and calendar export. The candidate retains all those commits and their history.
- PR #2 is an alternate earlier implementation. Its vanilla-JavaScript dashboard is superseded by the React app. Its historical date consistency checks are covered by the current schemas/routes and regression tests, including rejecting a changed application date without modifying the record.
- The useful hosted PostgreSQL URL normalization from PR #2 is incorporated in Settings so both Alembic and the API select psycopg 3. Explicit alternative drivers remain unchanged.
- The old Render blueprint is not carried over: it predates the SMTP, HTTPS, secret, and migration requirements in the current production configuration.
- Once the integration PR is merged with its history intact, superseded open PRs can be closed with a link to the consolidated change. Feature branches remain available for reference.

## What the automated gates verify

The standard CI runs PostgreSQL migrations, migration drift checks, pytest, the production frontend build, production Compose validation, and the non-root Docker image build.

The Windows workflow validates the version in Python, Tauri, Cargo, and the desktop package, builds the frozen API and NSIS installer, then runs the frozen executable in an isolated temporary workspace with only Windows system directories on its PATH. The smoke test exercises:

- Bundled frontend delivery and the exact candidate version.
- Account creation and session authentication.
- Application creation, CSV and calendar export.
- Deadline and next-action reminder selection and acknowledgement.
- Portable backup replacement.
- Process restart with session, application, and reminder history persistence.

The smoke harness uses a Python interpreter, but the application process is the standalone executable and cannot find Python on PATH. This is a packaging check, not a claim that a clean-machine graphical install or native notification has already been tested.

## Candidate download

Open the integration PR's **Windows Desktop** check. When it succeeds, download the versioned **InternTrack-Windows-x64-0.2.0-rc.1** artifact. It contains an unsigned installer intended for controlled testing. Do not present this artifact as a signed public stable release.

The signed release workflow remains gated on the signing credentials described in [desktop-release.md](desktop-release.md). Do not push a release tag merely to obtain an unsigned download.

## Manual release gates

Record the machine, Windows version, installer checksum, result, and any issue for each gate. Leave an unchecked gate pending until it has actually been exercised.

- [ ] On a clean Windows x64 machine without Python, install and launch the NSIS package.
- [ ] Confirm the app opens its own window, a second launch focuses the first window, and Quit stops the sidecar.
- [ ] Close to tray, reopen, and verify optional start-with-Windows behavior.
- [ ] Allow native notifications and verify an actual deadline and next-action notification.
- [ ] Upgrade an earlier installed version and verify accounts, records, settings, and recovery points survive.
- [ ] Exercise recovery staging, cancel, restart, and restoration through the installed UI.
- [ ] Complete real AI, Gmail, and Outlook workflows using tester-owned credentials; review authorization denial, expiration, and disconnect.
- [ ] Import a calendar export in each advertised calendar client.
- [ ] Complete Authenticode signing, checksum verification, and draft release review before stable publication.

See the [user guide](user-guide.md) for the tester workflow.

