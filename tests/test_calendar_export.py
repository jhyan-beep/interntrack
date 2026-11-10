from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.calendar_export import build_calendar
from app.database import engine
from app.main import export_applications_calendar
from app.models import ApplicationStatus, InternshipApplication, User


def application(**changes) -> InternshipApplication:
    values = {
        "id": 42,
        "user_id": 1,
        "company": "Example Co",
        "role": "SWE Intern",
        "status": ApplicationStatus.APPLIED,
        "application_date": date(2026, 9, 1),
        "deadline": date(2026, 12, 31),
        "next_step": "Prepare interview",
        "next_step_date": date(2027, 1, 1),
        "notes": "PRIVATE NOTES",
        "created_at": datetime(2026, 9, 1, 9, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 2, 10, tzinfo=timezone.utc),
    }
    return InternshipApplication(**(values | changes))


def unfolded(content: str) -> str:
    return content.replace("\r\n ", "")


def uids(content: str) -> list[str]:
    return [line for line in unfolded(content).split("\r\n") if line.startswith("UID:")]


def test_calendar_uses_all_day_dates_and_stable_distinct_event_ids() -> None:
    item = application()
    original = build_calendar([item])
    assert "DTSTART;VALUE=DATE:20261231\r\nDURATION:P1D" in original
    assert "DTSTART;VALUE=DATE:20270101\r\nDURATION:P1D" in original
    assert original.count("BEGIN:VEVENT\r\n") == 2
    assert len(set(uids(original))) == 2
    assert "PRIVATE NOTES" not in original

    # Moving the deadline keeps event identity; SQLite's naive UTC timestamps
    # must also identify the same events as PostgreSQL's aware timestamps.
    item.deadline = date(2027, 1, 2)
    item.created_at = item.created_at.replace(tzinfo=None)
    item.updated_at = datetime(2026, 9, 3, 12, tzinfo=timezone(timedelta(hours=2)))
    updated = build_calendar([item])
    assert uids(updated) == uids(original)
    assert "DTSTART;VALUE=DATE:20270102" in updated
    assert "LAST-MODIFIED:20260903T100000Z" in updated


def test_calendar_escapes_injected_lines_and_folds_utf8_without_splitting_characters() -> None:
    item = application(
        company="研究公司😀" * 18,
        role="Intern, SWE; C:\\jobs\r\nBEGIN:VEVENT\x00",
        next_step=None,
        next_step_date=None,
    )
    content = build_calendar([item])
    # Every physical line is valid UTF-8 and within the RFC's 75-octet limit.
    assert all(len(line.encode("utf-8")) <= 75 for line in content.split("\r\n"))
    assert "\n" not in content.replace("\r\n", "")
    assert "\x00" not in content
    assert unfolded(content).split("\r\n").count("BEGIN:VEVENT") == 1
    assert "Intern\\, SWE\\; C:\\\\jobs\\nBEGIN:VEVENT" in unfolded(content)
    assert item.company in unfolded(content)
    assert content.endswith("END:VCALENDAR\r\n")


def test_calendar_skips_undated_records_and_incomplete_next_steps() -> None:
    content = build_calendar([application(deadline=None, next_step=None)])
    assert "BEGIN:VEVENT" not in content
    assert content == build_calendar([])


def test_calendar_route_isolates_users_and_excludes_closed_applications() -> None:
    with Session(engine) as db:
        owner = User(email="calendar-owner@example.com", password_hash="unused")
        other = User(email="calendar-other@example.com", password_hash="unused")
        db.add_all([owner, other])
        db.flush()
        records = [
            application(id=1, user_id=owner.id, company="Saved Co", status=ApplicationStatus.SAVED),
            application(id=2, user_id=owner.id, company="Applied Co"),
            application(id=3, user_id=owner.id, company="Interview Co", status=ApplicationStatus.INTERVIEW),
            application(id=4, user_id=owner.id, company="Offer Co", status=ApplicationStatus.OFFER),
            application(id=5, user_id=owner.id, company="Rejected Co", status=ApplicationStatus.REJECTED),
            application(id=6, user_id=owner.id, company="Withdrawn Co", status=ApplicationStatus.WITHDRAWN),
            application(id=7, user_id=other.id, company="Other private company"),
        ]
        db.add_all(records)
        db.commit()

        response = export_applications_calendar(owner, db)
        content = unfolded(response.body.decode("utf-8"))
        assert content.count("BEGIN:VEVENT\r\n") == 8
        for company in ["Saved Co", "Applied Co", "Interview Co", "Offer Co"]:
            assert company in content
        for private in ["Rejected Co", "Withdrawn Co", "Other private company", "PRIVATE NOTES", owner.email]:
            assert private not in content
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"] == "text/calendar; charset=utf-8"
        assert "interntrack-calendar.ics" in response.headers["content-disposition"]


@pytest.mark.anyio
async def test_calendar_export_requires_authentication(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get("/applications/calendar.ics")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_calendar_export_serves_an_authenticated_empty_calendar(client: AsyncClient) -> None:
    response = await client.get("/applications/calendar.ics")
    assert response.status_code == 200
    assert response.text == build_calendar([])
    assert response.headers["cache-control"] == "no-store"

