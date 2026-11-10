from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app import main
from app.beta import build_beta_metrics
from app.database import SessionLocal
from app.models import BetaFeedback, ProductEvent, User
from app.schemas import AiJobDraft


pytestmark = pytest.mark.anyio
JOB_TEXT = (
    "Example Systems is hiring a Software Engineer Intern to build Python, FastAPI, "
    "PostgreSQL, and React features with an experienced product engineering team. "
    "This is a paid hybrid internship for currently enrolled university students."
)


def verify_test_user() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()


async def add_application(client: AsyncClient, company: str) -> None:
    response = await client.post(
        "/applications",
        json={
            "company": company,
            "role": "Software Engineer Intern",
            "status": "saved",
            "application_date": date.today().isoformat(),
            "deadline": None,
            "location": "Davis, CA",
            "source_url": None,
            "notes": None,
        },
    )
    assert response.status_code == 201


async def test_beta_progress_starts_with_privacy_safe_defaults(client: AsyncClient) -> None:
    response = await client.get("/beta/progress")

    assert response.status_code == 200
    assert response.json() == {
        "application_count": 0,
        "email_verified": False,
        "ai_import_used": False,
        "reminders_enabled": False,
        "feedback_submitted": False,
        "activated": False,
    }


async def test_dashboard_session_is_deduplicated_per_day(client: AsyncClient) -> None:
    assert (await client.post("/beta/session")).status_code == 204
    assert (await client.post("/beta/session")).status_code == 204

    with SessionLocal() as db:
        dashboard_events = db.scalar(
            select(func.count(ProductEvent.id)).where(
                ProductEvent.event_name == "dashboard_viewed"
            )
        )
    assert dashboard_events == 1


async def test_beta_milestones_feedback_and_metrics(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_test_user()
    for index in range(3):
        await add_application(client, f"Company {index + 1}")

    draft = AiJobDraft(
        company="Example Systems",
        role="Software Engineer Intern",
        location="Davis, CA",
        deadline=None,
        source_url=None,
        notes="Python and React",
        uncertain_fields=["deadline", "source_url"],
    )
    monkeypatch.setattr(main, "parse_job_posting", lambda _request, _user_id: draft)
    ai_response = await client.post("/ai/job-draft", json={"job_text": JOB_TEXT})
    assert ai_response.status_code == 200

    reminder_response = await client.patch(
        "/reminders/settings",
        json={
            "deadline_reminders_enabled": True,
            "deadline_reminder_days": 3,
            "reminder_timezone": "America/Los_Angeles",
        },
    )
    assert reminder_response.status_code == 200
    assert (await client.post("/beta/session")).status_code == 204

    first_feedback = await client.put(
        "/beta/feedback",
        json={"rating": 4, "comment": "  Add a browser extension.  "},
    )
    updated_feedback = await client.put(
        "/beta/feedback",
        json={"rating": 5, "comment": "Email import would save time."},
    )
    assert first_feedback.status_code == 200
    assert first_feedback.json()["comment"] == "Add a browser extension."
    assert updated_feedback.status_code == 200

    progress = (await client.get("/beta/progress")).json()
    assert progress == {
        "application_count": 3,
        "email_verified": True,
        "ai_import_used": True,
        "reminders_enabled": True,
        "feedback_submitted": True,
        "activated": True,
    }

    with SessionLocal() as db:
        assert db.scalar(select(func.count(BetaFeedback.id))) == 1
        metrics = build_beta_metrics(db)
    assert metrics == {
        "total_users": 1,
        "verified_users": 1,
        "activated_users": 1,
        "activation_rate": 1.0,
        "active_users_7d": 1,
        "ai_import_users": 1,
        "reminder_users": 1,
        "feedback_responses": 1,
        "applications": 3,
    }


async def test_beta_data_is_deleted_with_account(client: AsyncClient) -> None:
    await client.post("/beta/session")
    await client.put("/beta/feedback", json={"rating": 3, "comment": None})

    deleted = await client.request(
        "DELETE",
        "/auth/me",
        json={"password": "securepass123"},
    )
    assert deleted.status_code == 204

    with SessionLocal() as db:
        assert db.scalar(select(func.count(ProductEvent.id))) == 0
        assert db.scalar(select(func.count(BetaFeedback.id))) == 0
