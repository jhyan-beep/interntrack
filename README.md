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

## Project Structure

```text
app/
  crud.py        Database operations
  database.py    Settings, engine, sessions, and table creation
  main.py        FastAPI routes
  models.py      SQLAlchemy models
  schemas.py     Pydantic request and response schemas
frontend/
  src/
    api.ts        Typed API client
    App.tsx       Dashboard and application workflows
    styles.css    Responsive interface styles
tests/
  conftest.py
  test_applications.py
```

## API Overview

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
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

## Run Locally Without Docker

Create a virtual environment, install dependencies, and point `DATABASE_URL` at a running PostgreSQL database:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
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

Built InternTrack, a responsive React, TypeScript, FastAPI, and PostgreSQL application tracker with CRUD workflows, filtering, analytics, CSV export, Dockerized deployment, GitHub Actions CI, and automated API tests.

## Product Roadmap

The current release is a single-user web application. Before accepting real user data, the next milestone is authentication and per-user data isolation. Planned production work also includes Alembic migrations, pagination, monitoring, automated backups, account deletion, and privacy documentation.


