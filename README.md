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
- Email and password accounts with HttpOnly cookie sessions
- Per-user data isolation across every application endpoint
- Paginated application lists
- Login and registration rate limiting
- Origin-based CSRF protection and strict security response headers
- Liveness and database readiness checks
- Spreadsheet-safe CSV exports
- Alembic database migrations
- PostgreSQL support with SQLAlchemy
- Pydantic schemas for request and response validation
- Pytest coverage for the main API workflows
- Docker Compose setup for API plus PostgreSQL
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

## Project Structure

```text
app/
  auth.py        Password hashing, sessions, and current-user dependency
  crud.py        Database operations
  database.py    Settings, engine, sessions, and table creation
  main.py        FastAPI routes
  models.py      SQLAlchemy models
  schemas.py     Pydantic request and response schemas
  security.py    Rate limiting, origin checks, and response hardening
frontend/
  src/
    api.ts        Typed API client
    App.tsx       Dashboard and application workflows
    styles.css    Responsive interface styles
tests/
  conftest.py
  test_applications.py
  test_auth.py
  test_security.py
```

## API Overview

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| GET | `/health/live` | Process liveness check |
| GET | `/health/ready` | Database readiness check |
| POST | `/auth/register` | Create an account and session |
| POST | `/auth/login` | Sign in |
| POST | `/auth/logout` | Sign out |
| GET | `/auth/me` | View the current account |
| DELETE | `/auth/me` | Delete the current account and its data |
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

2. Start the API and PostgreSQL:

```bash
docker compose up --build
```

3. Open the web application:

```text
http://localhost:8000
```

The interactive API documentation remains available at `http://localhost:8000/docs`.

The Docker image also uses `/health/ready` for its container health check.

## Run Locally Without Docker

Create a virtual environment, install dependencies, and point `DATABASE_URL` at a running PostgreSQL database:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
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
```

Production mode enables Secure cookies and HSTS, requires an approved `Origin` header for state-changing requests, and disables the interactive API documentation. Terminate HTTPS at the hosting platform or reverse proxy and configure it to preserve the original host and scheme.

The built-in authentication limiter is intentionally small and process-local so the project stays interview-friendly. It protects a single container; a multi-replica commercial deployment should enforce an additional shared limit at the load balancer, API gateway, or Redis layer.

## Authentication and data privacy

Passwords are hashed with Argon2 and never returned by the API. A signed, expiring JWT is stored in an HttpOnly cookie, and every application query is scoped to the authenticated user. Set a unique `SECRET_KEY` of at least 32 characters before running with `ENVIRONMENT=production`.

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

Built InternTrack, a secure multi-user React, TypeScript, FastAPI, and PostgreSQL application tracker with HttpOnly sessions, per-user authorization, rate limiting, analytics, CSV export, Docker health checks, Alembic migrations, and PostgreSQL-backed CI.

## Product Roadmap

The current release supports hardened authenticated workspaces suitable for a controlled beta. Remaining production work includes email verification and password reset, shared rate limiting for multi-replica deployments, centralized monitoring, automated backups, formal privacy documentation, and billing.

