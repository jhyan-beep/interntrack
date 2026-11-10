from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import DeadlineReminderDelivery, EmailOutbox, User
from app.reminders import enqueue_due_deadline_reminders


pytestmark = pytest.mark.anyio


def verify_test_user() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()


async def test_reminders_default_to_opted_out(client: AsyncClient) -> None:
    response = await client.get("/reminders/settings")

    assert response.status_code == 200
    assert response.json() == {
        "deadline_reminders_enabled": False,
        "deadline_reminder_days": 3,
        "reminder_timezone": "UTC",
    }


async def test_unverified_user_cannot_enable_reminders(client: AsyncClient) -> None:
    response = await client.patch(
        "/reminders/settings",
        json={
            "deadline_reminders_enabled": True,
            "deadline_reminder_days": 7,
            "reminder_timezone": "America/Los_Angeles",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Verify your email before enabling deadline reminders"


async def test_verified_user_can_update_reminder_settings(client: AsyncClient) -> None:
    verify_test_user()

    response = await client.patch(
        "/reminders/settings",
        json={
            "deadline_reminders_enabled": True,
            "deadline_reminder_days": 7,
            "reminder_timezone": "America/Los_Angeles",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "deadline_reminders_enabled": True,
        "deadline_reminder_days": 7,
        "reminder_timezone": "America/Los_Angeles",
    }


async def test_invalid_reminder_timezone_is_rejected(client: AsyncClient) -> None:
    response = await client.patch(
        "/reminders/settings",
        json={"reminder_timezone": "Not/A-Timezone"},
    )

    assert response.status_code == 422


async def test_due_reminder_is_queued_only_once(client: AsyncClient) -> None:
    verify_test_user()
    current_time = datetime.now(timezone.utc)
    current_date = current_time.date()
    await client.patch(
        "/reminders/settings",
        json={"deadline_reminders_enabled": True, "deadline_reminder_days": 3},
    )
    created = await client.post(
        "/applications",
        json={
            "company": "Example Systems",
            "role": "Software Engineer Intern",
            "status": "saved",
            "application_date": current_date.isoformat(),
            "deadline": (current_date + timedelta(days=2)).isoformat(),
            "location": "Remote",
            "source_url": "https://example.com/jobs/123",
            "notes": None,
        },
    )
    assert created.status_code == 201

    first_scan = enqueue_due_deadline_reminders(now=current_time)
    second_scan = enqueue_due_deadline_reminders(now=current_time)

    with SessionLocal() as db:
        deliveries = db.scalar(select(func.count(DeadlineReminderDelivery.id)))
        reminder_messages = db.scalars(
            select(EmailOutbox).where(EmailOutbox.subject.like("InternTrack deadline%"))
        ).all()

    assert first_scan == 1
    assert second_scan == 0
    assert deliveries == 1
    assert len(reminder_messages) == 1
    assert "Example Systems" in reminder_messages[0].subject
    assert "in 2 days" in reminder_messages[0].subject


async def test_inactive_application_does_not_queue_reminder(client: AsyncClient) -> None:
    verify_test_user()
    current_time = datetime.now(timezone.utc)
    current_date = current_time.date()
    await client.patch(
        "/reminders/settings",
        json={"deadline_reminders_enabled": True, "deadline_reminder_days": 3},
    )
    await client.post(
        "/applications",
        json={
            "company": "Finished Company",
            "role": "Software Engineer Intern",
            "status": "rejected",
            "application_date": current_date.isoformat(),
            "deadline": (current_date + timedelta(days=1)).isoformat(),
            "location": None,
            "source_url": None,
            "notes": None,
        },
    )

    assert enqueue_due_deadline_reminders(now=current_time) == 0


async def test_reminder_uses_user_local_date(client: AsyncClient) -> None:
    verify_test_user()
    current_time = datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc)
    await client.patch(
        "/reminders/settings",
        json={
            "deadline_reminders_enabled": True,
            "deadline_reminder_days": 3,
            "reminder_timezone": "America/Los_Angeles",
        },
    )
    await client.post(
        "/applications",
        json={
            "company": "Timezone Company",
            "role": "Software Engineer Intern",
            "status": "applied",
            "application_date": "2026-10-28",
            "deadline": "2026-10-31",
            "location": None,
            "source_url": None,
            "notes": None,
        },
    )

    assert enqueue_due_deadline_reminders(now=current_time) == 1
    with SessionLocal() as db:
        message = db.scalar(
            select(EmailOutbox).where(EmailOutbox.subject.like("InternTrack deadline%"))
        )
    assert message is not None
    assert "in 3 days" in message.subject


async def test_deleting_account_removes_pending_user_email(client: AsyncClient) -> None:
    with SessionLocal() as db:
        before = db.scalar(select(func.count(EmailOutbox.id)))
    assert before == 1

    deleted = await client.request(
        "DELETE",
        "/auth/me",
        json={"password": "securepass123"},
    )

    with SessionLocal() as db:
        after = db.scalar(select(func.count(EmailOutbox.id)))

    assert deleted.status_code == 204
    assert after == 0
