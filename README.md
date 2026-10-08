# InternTrack

InternTrack is a FastAPI internship application tracker with a built-in web dashboard. It is designed as a clear, interview-friendly project that still feels like a real product: API workflows, request validation, database modeling, testing, Docker, CI, and a usable browser UI.

## Features

- Browser dashboard served by FastAPI
- Create, read, update, and delete internship applications
- Filter applications by status and company
- Sort applications by deadline, application date, created date, or company
- View application statistics grouped by status
- Track upcoming deadlines and active applications
- Export applications as CSV
- PostgreSQL support with SQLAlchemy
- Pydantic schemas for request and response validation
- Pytest coverage for the main API and UI entrypoint
- Docker Compose setup for API plus PostgreSQL
- GitHub Actions CI

## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy 2.0
- Pydantic
- Pytest
- Docker
- HTML, CSS, and vanilla JavaScript

## Project Structure

```text
app/
  crud.py        Database operations
  database.py    Settings, engine, sessions, and table creation
  main.py        FastAPI routes and web UI entrypoint
  models.py      SQLAlchemy models
  schemas.py     Pydantic request and response schemas
  static/        Browser dashboard assets
tests/
  conftest.py
  test_applications.py
```

## Web UI

Start the app and open:

```text
http://localhost:8000/
```

Open the guided tutorial:

```text
http://localhost:8000/help
```

The dashboard supports:

- Pipeline metrics
- Status distribution
- Upcoming deadline list
- Filtering and sorting
- Create/edit/delete application workflows
- CSV export link

## Use InternTrack Without Coding

The easiest path for a non-developer is to deploy it online, then use the hosted URL in a browser.

### Option 1: One-click Render deploy

After this repository is updated on `main`, use this link:

[Deploy InternTrack on Render](https://render.com/deploy?repo=https://github.com/jhyan-beep/interntrack)

Render will ask you to sign in with GitHub and create:

- One web service for InternTrack
- One PostgreSQL database
- A public URL you can open from any browser

When deployment finishes, open the Render-provided URL and start from the tutorial page:

```text
https://your-render-url.onrender.com/help
```

### Option 2: Run on your computer with Docker

Install Docker Desktop, then run:

```bash
cp .env.example .env
docker compose up --build
```

Open:

```text
http://localhost:8000/help
```

## Quick Tutorial

1. Open the dashboard.
2. Select **New application**.
3. Fill in company, role, status, application date, and optional deadline.
4. Add the job posting link in **Source URL**.
5. Use filters and sorting to focus your pipeline.
6. Update statuses as applications move from saved to applied, interview, offer, rejected, or withdrawn.
7. Select **Export CSV** when you want a spreadsheet backup.

## API Overview

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | Web dashboard |
| GET | `/help` | User tutorial |
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

3. Open the dashboard or interactive API docs:

```text
http://localhost:8000/
http://localhost:8000/docs
```

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

## Run Tests

```bash
pytest
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

Built InternTrack, a FastAPI and PostgreSQL internship application tracker with a browser dashboard, CRUD workflows, filtering, sorting, statistics, CSV export, Dockerized local development, GitHub Actions CI, and pytest coverage.
