from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app import ai, main
from app.database import SessionLocal, Settings, get_settings
from app.models import User
from app.schemas import AiJobDraft, AiJobParseRequest


pytestmark = pytest.mark.anyio
JOB_TEXT = """
Example Systems is hiring a Software Engineer Intern in Davis, California.
The internship uses Python, FastAPI, PostgreSQL, and React. Candidates will
build product features and automated tests with the engineering team. Apply by
December 15, 2026. This is a hybrid role for currently enrolled students.
""".strip()


def verify_test_user() -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()


def test_blank_openai_key_keeps_ai_optional() -> None:
    assert Settings(openai_api_key="").openai_api_key is None


async def test_ai_import_requires_verified_email(client: AsyncClient) -> None:
    response = await client.post("/ai/job-draft", json={"job_text": JOB_TEXT})

    assert response.status_code == 403
    assert response.json() == {"detail": "Verify your email before using AI import"}


async def test_ai_import_reports_missing_server_configuration(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_test_user()
    monkeypatch.setattr(get_settings(), "openai_api_key", None)

    response = await client.post("/ai/job-draft", json={"job_text": JOB_TEXT})

    assert response.status_code == 503
    assert response.json() == {"detail": "AI import is not configured on this server"}


async def test_ai_import_returns_a_reviewable_draft(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_test_user()
    expected = AiJobDraft(
        company="Example Systems",
        role="Software Engineer Intern",
        location="Davis, California (Hybrid)",
        deadline=date(2026, 12, 15),
        source_url="https://example.com/jobs/123",
        notes="Python, FastAPI, PostgreSQL, React; currently enrolled students.",
        uncertain_fields=[],
    )
    monkeypatch.setattr(main, "parse_job_posting", lambda _request, _user_id: expected)

    response = await client.post(
        "/ai/job-draft",
        json={
            "job_text": JOB_TEXT,
            "source_url": "https://example.com/jobs/123",
        },
    )

    assert response.status_code == 200
    assert response.json()["company"] == "Example Systems"
    assert response.json()["deadline"] == "2026-12-15"


async def test_ai_import_is_rate_limited_per_user(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify_test_user()
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_per_identity", 1)
    monkeypatch.setattr(settings, "auth_rate_limit_per_ip", 100)
    draft = AiJobDraft(
        company="Example Systems",
        role="Software Engineer Intern",
        location=None,
        deadline=None,
        source_url=None,
        notes=None,
        uncertain_fields=["location", "deadline", "source_url", "notes"],
    )
    monkeypatch.setattr(main, "parse_job_posting", lambda _request, _user_id: draft)

    first = await client.post("/ai/job-draft", json={"job_text": JOB_TEXT})
    second = await client.post("/ai/job-draft", json={"job_text": JOB_TEXT})

    assert first.status_code == 200
    assert second.status_code == 429


async def test_ai_service_uses_structured_output_without_storing_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-api-key"))
    monkeypatch.setattr(settings, "openai_model", "gpt-6-luna")

    past_deadline = date.today() - timedelta(days=1)
    parsed = AiJobDraft(
        company="  Example Systems  ",
        role="Software Engineer Intern",
        location="",
        deadline=past_deadline,
        source_url=None,
        notes="  Python and React  ",
        uncertain_fields=["location"],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr(ai, "OpenAI", FakeOpenAI)
    draft = ai.parse_job_posting(
        AiJobParseRequest(
            job_text=JOB_TEXT,
            source_url="https://example.com/jobs/123",
        ),
        user_id=42,
    )

    assert captured["model"] == "gpt-6-luna"
    assert captured["text_format"] is AiJobDraft
    assert captured["store"] is False
    assert "untrusted data" in captured["instructions"]
    assert captured["client"]["api_key"] == "test-api-key"
    assert draft.company == "Example Systems"
    assert draft.location is None
    assert draft.deadline is None
    assert "deadline" in draft.uncertain_fields
    assert draft.source_url == "https://example.com/jobs/123"

