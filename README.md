# InternTrack

InternTrack is a responsive web application for tracking software engineering internship applications. It combines a React dashboard with a FastAPI and PostgreSQL backend, while staying small enough to explain end to end in an interview.

## Features

- Create, read, update, and delete internship applications
- Filter applications by status and company
- Sort applications by deadline, application date, created date, or company
- View application statistics grouped by status
- Export applications as CSV
- Responsive dashboard for desktop and mobile
- Create and edit applications from an accessible form
- Visual pipeline and upcoming deadline overview
- AI-assisted job-posting import with a review-before-save workflow
- Email and password accounts with HttpOnly cookie sessions
- Email verification and secure password reset links
- Durable email outbox with a retrying background worker
- Opt-in, idempotent application deadline email reminders
- Per-user data isolation across every application endpoint
- Paginated application lists
- Login and registration rate limiting
- Origin-based CSRF protection and strict security response headers
- Liveness and database readiness checks
- Correlated request IDs and production JSON logs
- Spreadsheet-safe CSV exports
- Alembic database migrations
- PostgreSQL support with SQLAlchemy
- Pydantic schemas for request and response validation
- Pytest coverage for the main API workflows
- Docker Compose setup for API, email worker, and PostgreSQL
- Production Compose stack with Caddy-managed HTTPS and non-root containers
- Guarded PostgreSQL backup and restore commands
- Private-beta onboarding, first-party milestone metrics, and in-app feedback
- GitHub Actions CI

## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy 2.0
- Pydantic
- Pytest
- Docker
- React
- TypeScript
- Vite
- Alembic
- PyJWT and Argon2 password hashing
- OpenAI Responses API with Structured Outputs
- Caddy

## Project Structure

```text
app/
  ai.py          Server-side AI extraction and provider error handling
  auth.py        Password hashing, sessions, and current-user dependency
  beta.py        Privacy-conscious milestones, feedback, and activation metrics
  beta_metrics.py  Aggregate beta report CLI without emails or job content
  crud.py        Database operations
  database.py    Settings, engine, sessions, and table creation
  desktop.py     Local SQLite setup, migrations, and packaged API entrypoint
  email_delivery.py  Email templates, outbox queue, SMTP, and retry handling
  email_tokens.py    Single-use verification and password-reset tokens
  email_worker.py    Background outbox processor
  gmail.py       Desktop OAuth, token refresh, metadata sync, and status suggestions
  main.py        FastAPI routes
  models.py      SQLAlchemy models
  observability.py  JSON logging and per-request correlation context
  reminders.py   Deadline reminder selection, templates, and deduplication
  schemas.py     Pydantic request and response schemas
  security.py    Rate limiting, origin checks, and response hardening
frontend/
  src/
    api.ts        Typed API client
    App.tsx       Dashboard and application workflows
    styles.css    Responsive interface styles
desktop/
  scripts/        Reproducible PyInstaller and Windows build scripts
  src-tauri/      Rust desktop shell and NSIS installer configuration
  ui/             Lightweight startup screen
tests/
  conftest.py
  test_applications.py
  test_auth.py
  test_beta.py
  test_email.py
  test_observability.py
  test_reminders.py
  test_security.py
ops/
  backup_postgres.sh   Atomic PostgreSQL custom-format backup
  restore_postgres.sh  Confirmation-guarded database restore
compose.production.yml Production API, worker, database, proxy, and ops services
Caddyfile              Automatic HTTPS reverse proxy
```

## API Overview

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| GET | `/health/live` | Process liveness check |
| GET | `/health/ready` | Database readiness check |
| GET | `/runtime` | Report web/desktop mode and optional feature availability |
| POST | `/auth/register` | Create an account and session |
| POST | `/auth/login` | Sign in |
| POST | `/auth/logout` | Sign out |
| GET | `/auth/me` | View the current account |
| DELETE | `/auth/me` | Delete the current account and its data |
| POST | `/ai/job-draft` | Parse a job posting into a reviewable application draft |
| GET | `/desktop/email/google` | View the local Gmail connection status |
| POST | `/desktop/email/google/connect` | Start the desktop Google OAuth + PKCE flow |
| DELETE | `/desktop/email/google` | Revoke and delete the local Gmail connection |
| POST | `/desktop/email/google/sync` | Review recent Gmail metadata for status suggestions |
| GET | `/desktop/email/microsoft` | View the local Outlook connection status |
| POST | `/desktop/email/microsoft/connect` | Start Microsoft public-client OAuth + PKCE |
| DELETE | `/desktop/email/microsoft` | Delete the local Microsoft connection |
| POST | `/desktop/email/microsoft/sync` | Review recent Outlook metadata for status suggestions |
| GET | `/desktop/reminders/due` | List due, unacknowledged local deadline reminders |
| POST | `/desktop/reminders/{application_id}/acknowledge` | Record a displayed local reminder |
| POST | `/auth/email/verification/request` | Send or resend a verification email |
| POST | `/auth/email/verify` | Verify an email with a single-use token |
| POST | `/auth/password/forgot` | Request a password-reset email |
| POST | `/auth/password/reset` | Set a new password with a single-use token |
| GET | `/reminders/settings` | View deadline reminder preferences |
| PATCH | `/reminders/settings` | Update deadline reminder preferences |
| POST | `/beta/session` | Record one dashboard visit per user and day |
| GET | `/beta/progress` | View private-beta onboarding milestones |
| PUT | `/beta/feedback` | Create or replace the current user's feedback |
| POST | `/applications` | Create an application |
| GET | `/applications` | List applications with filters and sorting |
| GET | `/applications/{application_id}` | Get one application |
| PATCH | `/applications/{application_id}` | Update one application |
| DELETE | `/applications/{application_id}` | Delete one application |
| GET | `/applications/export.csv` | Export applications to CSV |
| GET | `/stats` | View application statistics |

Example list query:

```bash
curl "http://localhost:8000/applications?status=applied&company=google&sort_by=deadline&sort_order=asc"
```

## Run with Docker

1. Copy the environment example:

```bash
cp .env.example .env
```

2. Start the API, email worker, and PostgreSQL:

```bash
docker compose up --build
```

3. Open the web application:

```text
http://localhost:8000
```

The interactive API documentation remains available at `http://localhost:8000/docs`.

The Docker image also uses `/health/ready` for its container health check. Development uses `EMAIL_DELIVERY_MODE=console`, so verification, reset, and deadline reminder emails appear in the `email-worker` logs:

```bash
docker compose logs -f email-worker
```

## Run Locally Without Docker

Create a virtual environment, install dependencies, and point `DATABASE_URL` at a running PostgreSQL database:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Run the email worker in a second terminal:

```bash
python -m app.email_worker
```

On Windows PowerShell, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

In another terminal, run the frontend development server:

```bash
cd frontend
pnpm install
pnpm dev
```

Open `http://localhost:5173`. Vite proxies API requests to FastAPI on port `8000`.

## Build the Windows Desktop App

The desktop edition runs the same React and FastAPI product entirely on the user's computer. A Tauri shell starts a packaged Python sidecar on loopback, Alembic migrates a per-user SQLite database, and the UI is served from that local process. No cloud server or PostgreSQL installation is required for desktop users.

Desktop data is stored in Tauri's per-user local app-data directory. The generated session secret and `interntrack.db` stay there across upgrades. The API only listens on `127.0.0.1`.

To build the installer on Windows, install Python 3.12, Node.js, pnpm, Rust, and the Tauri Windows prerequisites, then run:

```powershell
.\desktop\scripts\build_windows.ps1
```

The NSIS setup executable is created under:

```text
desktop/src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/
```

Pull requests that touch desktop runtime files also run the `Windows Desktop` workflow and upload the setup executable as a GitHub Actions artifact.

Desktop users can enable AI import from **Account settings → AI import** with their own OpenAI API key. The key is encrypted at rest with Windows DPAPI, tied to the current Windows account, and never returned to the frontend after saving. No provider secret is embedded in the installer. Removing the key immediately disables AI import and deletes the encrypted local file.

Desktop users can enable **Local deadline reminders** without an email or cloud service. The installed Tauri app requests Windows notification permission, checks when the app launches, becomes visible, and every 30 minutes while running, then displays one native notification when an active application enters the selected reminder window. A reminder is acknowledged in the local SQLite database only after the notification call succeeds, preventing repeated alerts for the same application deadline while allowing a changed deadline to create a new reminder.

Desktop users can also connect Gmail from **Account settings → Gmail status sync**. InternTrack opens Google authorization in the system browser, uses OAuth PKCE with a loopback callback, and encrypts the resulting tokens with Windows DPAPI. Sync reads only sender, subject, and date metadata from up to 25 recent inbox messages. It never downloads message bodies and never changes an application until the user approves a suggestion.

For beta testing, create a Google Cloud project, enable the Gmail API, configure the OAuth consent screen, add the tester account, and create a **Desktop app** OAuth client. Paste that public client ID into InternTrack when connecting. The app requests the restricted `gmail.metadata` scope; a public commercial release must complete Google's OAuth app verification before distributing this feature broadly. A verified project client ID can be supplied with `GOOGLE_OAUTH_CLIENT_ID` for release builds.

Microsoft Outlook and Microsoft 365 accounts use the same local-first review flow. InternTrack requests the delegated `Mail.ReadBasic` permission and asks Microsoft Graph for only message ID, subject, sender, and received date. Microsoft does not return message bodies, previews, attachments, or extended properties under that permission.

For Microsoft beta testing, register an application in Microsoft Entra, choose the supported account types you intend to test, and add `http://localhost` under **Authentication → Mobile and desktop applications**. Enable public-client flows and add delegated Microsoft Graph permissions `User.Read` and `Mail.ReadBasic`; do not create or embed a client secret. Paste the Application (client) ID into InternTrack, or set `MICROSOFT_OAUTH_CLIENT_ID` in a release build. Disconnecting removes the DPAPI-encrypted tokens from the computer; users can separately revoke the app's consent from their Microsoft account.

Email verification, password-reset email, and cloud email reminders remain disabled in desktop mode. Local Windows reminders and inbox sync do not require a server; inbox sync does not send email, store an email password, or apply a suggested status without confirmation.

## Run Tests

```bash
pytest
cd frontend && pnpm build
```

If `DATABASE_URL` is not set, the tests use an in-memory SQLite database. In CI, tests run against PostgreSQL.

## Production Configuration

Set these values before deploying publicly:

```env
ENVIRONMENT=production
SECRET_KEY=<unique-random-value-with-at-least-32-characters>
CORS_ORIGINS=https://app.example.com
ALLOWED_HOSTS=app.example.com
APP_BASE_URL=https://app.example.com
LOG_LEVEL=INFO
LOG_FORMAT=json
EMAIL_DELIVERY_MODE=smtp
EMAIL_FROM=InternTrack <no-reply@example.com>
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=<smtp-username>
SMTP_PASSWORD=<smtp-password>
SMTP_STARTTLS=true
REMINDER_SCAN_INTERVAL_SECONDS=300
OPENAI_API_KEY=<server-side-project-key>
OPENAI_MODEL=gpt-6-luna
OPENAI_TIMEOUT_SECONDS=20
```

Production mode enables Secure cookies and HSTS, requires an approved `Origin` header for state-changing requests, requires HTTPS action links and SMTP delivery, and disables the interactive API documentation. Terminate HTTPS at the hosting platform or reverse proxy and configure it to preserve the original host and scheme. Store SMTP credentials in the hosting platform's secret manager; never commit them to Git.

The built-in authentication limiter is intentionally small and process-local so the project stays interview-friendly. It protects a single container; a multi-replica commercial deployment should enforce an additional shared limit at the load balancer, API gateway, or Redis layer.

## Production deployment

The production Compose stack runs the API and email worker as a non-root user, keeps PostgreSQL off public host ports, mounts the application containers read-only, and puts Caddy in front of the API for automatic HTTPS.

1. Point the chosen domain's DNS records to the server and allow inbound ports `80` and `443`.
2. Create the production environment file and replace every placeholder. Use a URL-safe PostgreSQL password because it is embedded in `DATABASE_URL` by Compose.

```bash
cp .env.production.example .env.production
```

3. Start the stack:

```bash
docker compose --env-file .env.production -f compose.production.yml up -d --build
docker compose --env-file .env.production -f compose.production.yml ps
```

4. Inspect structured logs using request IDs returned in the `X-Request-ID` response header:

```bash
docker compose --env-file .env.production -f compose.production.yml logs -f api email-worker
```

The API container runs `alembic upgrade head` before serving traffic. For multiple API replicas, run migrations as a single release step instead of allowing every replica to migrate concurrently. `.env.production` is ignored by Git and must remain in the deployment platform's secret storage or on the server with restricted permissions.

## Backups and restore drills

Create an atomic PostgreSQL custom-format backup in the ignored local `backups/` directory:

```bash
docker compose --env-file .env.production -f compose.production.yml --profile ops run --rm backup
```

Schedule that exact command with the host or deployment platform scheduler, then copy backups to encrypted off-site storage. `BACKUP_RETENTION_DAYS` controls local cleanup and defaults to seven days. A backup is not considered reliable until a restore drill has succeeded.

Restore is intentionally guarded and destructive: it replaces matching objects in the configured `interntrack` database. Stop the API and worker, select a backup path inside `/backups`, and supply the exact confirmation value:

```bash
docker compose --env-file .env.production -f compose.production.yml stop api email-worker
BACKUP_FILE=/backups/interntrack_YYYYMMDDTHHMMSSZ.dump \
RESTORE_CONFIRMATION=restore:interntrack \
docker compose --env-file .env.production -f compose.production.yml --profile ops run --rm restore
docker compose --env-file .env.production -f compose.production.yml start api email-worker
```

Practice restores against a disposable environment before using the command on production data.

## AI-assisted import

Verified users can paste a job description and optional posting URL into the AI import dialog. The backend sends the text to the OpenAI Responses API and uses Structured Outputs to produce typed suggestions for company, role, location, deadline, source URL, and notes. InternTrack then opens the normal application form with those suggestions; it never saves an AI result automatically.

The default model is `gpt-6-luna`, selected for a focused extraction workload, and can be changed with `OPENAI_MODEL`. Requests use `store=False`, are input-limited and rate-limited, and treat the posting as untrusted data. `OPENAI_API_KEY` is read only by the backend and must come from the deployment secret manager. If it is absent, normal tracking features continue to work and AI import returns a clear configuration error.

## Deadline reminders

Deadline reminders are opt-in and available only after email verification. Users choose a reminder window from Account settings, and the browser's IANA time zone is stored with that preference so date calculations follow the user's local day. The background worker scans active `saved`, `applied`, and `interview` applications and queues one email when a deadline enters that window. A database uniqueness constraint on application and deadline makes repeated worker scans safe; changing the application's deadline creates a new reminder opportunity.

The scan includes overdue-worker recovery: if the service was unavailable on the exact reminder day, it queues the reminder when it returns as long as the deadline has not passed. `REMINDER_SCAN_INTERVAL_SECONDS` controls the scan cadence and defaults to five minutes.

## Private-beta validation

The dashboard includes a four-step launchpad for adding three applications, verifying email, trying AI import, and enabling reminders. InternTrack records only named milestone events, at most once per user and day. It does not attach job descriptions, browsing history, URLs, or arbitrary metadata to these events.

Beta users can submit a 1–5 rating and an optional comment in the app. A new submission replaces that user's previous response, and both feedback and milestone rows are deleted with the account. Operators can view aggregate validation metrics without exposing emails or comments:

```bash
python -m app.beta_metrics
```

The report includes total, verified, activated, and seven-day active users plus aggregate adoption counts for AI import, reminders, feedback, and applications. “Activated” currently means that a user has tracked at least three applications.

## Authentication and data privacy

Passwords are hashed with Argon2 and never returned by the API. A signed, expiring JWT is stored in an HttpOnly cookie, and every application query is scoped to the authenticated user. Verification and reset tokens are random, single-use, expire automatically, and are stored only as SHA-256 hashes. Password resets increment the user's session version, invalidating existing sessions.

Email is written to a database outbox in the same transaction as the account action. A separate worker sends it through SMTP and retries temporary failures with exponential backoff. After successful delivery, the worker redacts the message bodies so raw action links do not remain in the outbox. Outbox rows are associated with their user so pending mail is removed when an account is deleted. Set a unique `SECRET_KEY` of at least 32 characters before running with `ENVIRONMENT=production`.

If you used an earlier development version that created tables automatically, reset the local Docker volume before the first migration-based startup:

```bash
docker compose down -v
docker compose up --build
```

This reset instruction is only for pre-release development data. Production databases should always be migrated and backed up rather than deleted.

## Data Model

Each application stores:

- Company
- Role
- Status
- Application date
- Optional deadline
- Optional location
- Optional source URL
- Optional notes
- Created and updated timestamps

Supported statuses:

- `saved`
- `applied`
- `interview`
- `offer`
- `rejected`
- `withdrawn`

## Example Resume Bullet

Built InternTrack, a secure multi-user React, TypeScript, FastAPI, and PostgreSQL application tracker with OpenAI Structured Outputs, timezone-aware reminders, privacy-conscious activation analytics, transactional email, JSON logging, non-root containers, Alembic migrations, and PostgreSQL-backed CI.

Packaged InternTrack as a local-first Windows application with Tauri, PyInstaller, FastAPI, SQLite, automated migrations, process lifecycle management, and a GitHub Actions pipeline that produces an installable NSIS artifact.

Integrated privacy-first Gmail OAuth with PKCE, DPAPI-encrypted tokens, metadata-only inbox sync, deterministic application matching, and user-approved status updates without storing email bodies.

Extended the local-first email workflow to Outlook and Microsoft 365 using public-client OAuth with PKCE, least-privilege Microsoft Graph access, encrypted token storage, and provider-independent status matching.

Added idempotent Windows deadline notifications with Tauri permissions, timezone-aware FastAPI queries, SQLite delivery acknowledgements, and retry-safe foreground scheduling without a reminder server.

## Product Roadmap

The current release supports hardened authenticated workspaces, email verification, password recovery, opt-in deadline reminders, reviewable AI-assisted entry, private-beta onboarding and metrics, structured logs, HTTPS deployment configuration, and guarded backup tooling. Remaining launch work includes deploying a pilot, configuring a verified sending domain and transactional-email provider, scheduling encrypted off-site backups, shared rate limiting for multi-replica deployments, centralized alerting, formal privacy documentation, and billing only after retention is validated.

