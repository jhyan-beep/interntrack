import re
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app import email_delivery
from app.database import SessionLocal, get_settings
from app.email_delivery import process_outbox_batch
from app.models import EmailOutbox, EmailOutboxStatus, EmailToken


pytestmark = pytest.mark.anyio


def latest_email_token(parameter: str) -> str:
    with SessionLocal() as db:
        message = db.scalar(select(EmailOutbox).order_by(EmailOutbox.id.desc()).limit(1))
        assert message is not None
        match = re.search(rf"[?&]{parameter}=([^\s]+)", message.text_body)
        assert match is not None
        return match.group(1)


async def test_registration_queues_verification_and_token_is_single_use(
    anonymous_client: AsyncClient,
) -> None:
    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    token = latest_email_token("verify_token")
    verified = await anonymous_client.post("/auth/email/verify", json={"token": token})
    reused = await anonymous_client.post("/auth/email/verify", json={"token": token})

    assert registered.status_code == 201
    assert registered.json()["email_verified"] is False
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    assert reused.status_code == 400


async def test_verification_resend_invalidates_previous_link(client: AsyncClient) -> None:
    original_token = latest_email_token("verify_token")

    response = await client.post("/auth/email/verification/request")
    replacement_token = latest_email_token("verify_token")
    original_response = await client.post(
        "/auth/email/verify",
        json={"token": original_token},
    )
    replacement_response = await client.post(
        "/auth/email/verify",
        json={"token": replacement_token},
    )

    assert response.status_code == 202
    assert original_token != replacement_token
    assert original_response.status_code == 400
    assert replacement_response.status_code == 200


async def test_verification_resend_is_rate_limited(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_per_identity", 1)
    monkeypatch.setattr(settings, "auth_rate_limit_per_ip", 100)

    first = await client.post("/auth/email/verification/request")
    second = await client.post("/auth/email/verification/request")

    assert first.status_code == 202
    assert second.status_code == 429


async def test_forgot_password_is_generic_and_reset_invalidates_sessions(
    anonymous_client: AsyncClient,
) -> None:
    await anonymous_client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    old_session = anonymous_client.cookies.get("interntrack_session")

    known = await anonymous_client.post(
        "/auth/password/forgot",
        json={"email": "student@example.com"},
    )
    reset_token = latest_email_token("reset_token")
    with SessionLocal() as db:
        before_unknown = db.scalar(select(func.count(EmailOutbox.id)))
    unknown = await anonymous_client.post(
        "/auth/password/forgot",
        json={"email": "missing@example.com"},
    )
    with SessionLocal() as db:
        after_unknown = db.scalar(select(func.count(EmailOutbox.id)))

    reset = await anonymous_client.post(
        "/auth/password/reset",
        json={"token": reset_token, "new_password": "new-secure-pass123"},
    )
    anonymous_client.cookies.set("interntrack_session", old_session)
    old_session_response = await anonymous_client.get("/auth/me")
    old_password = await anonymous_client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    new_password = await anonymous_client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "new-secure-pass123"},
    )

    assert known.status_code == 202
    assert unknown.status_code == 202
    assert before_unknown == after_unknown
    assert reset.status_code == 204
    assert old_session_response.status_code == 401
    assert old_password.status_code == 401
    assert new_password.status_code == 200


async def test_expired_reset_token_is_rejected(client: AsyncClient) -> None:
    await client.post("/auth/password/forgot", json={"email": "student@example.com"})
    token = latest_email_token("reset_token")
    with SessionLocal() as db:
        email_token = db.scalar(select(EmailToken).order_by(EmailToken.id.desc()).limit(1))
        assert email_token is not None
        email_token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    response = await client.post(
        "/auth/password/reset",
        json={"token": token, "new_password": "new-secure-pass123"},
    )

    assert response.status_code == 400


async def test_email_worker_sends_and_redacts_outbox_body(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_ids: list[int] = []

    def fake_send(message: EmailOutbox, _settings) -> None:
        sent_ids.append(message.id)

    monkeypatch.setattr(email_delivery, "_send_message", fake_send)
    processed = process_outbox_batch()

    with SessionLocal() as db:
        message = db.scalar(select(EmailOutbox).order_by(EmailOutbox.id.asc()).limit(1))
        assert message is not None
        assert message.status == EmailOutboxStatus.SENT
        assert message.text_body == ""
        assert message.html_body == ""

    assert processed == 1
    assert sent_ids

