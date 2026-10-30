from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app import gmail, main
from app.database import get_settings
from app.desktop_secrets import DesktopJsonSecretStore
from app.email_sync import EmailMessageMetadata, suggest_status_updates
from app.models import ApplicationStatus


def reversible_store(tmp_path, filename: str = "google-test.dpapi") -> DesktopJsonSecretStore:
    return DesktopJsonSecretStore(
        tmp_path,
        filename,
        protect=lambda value: b"encrypted:" + value[::-1],
        unprotect=lambda value: value.removeprefix(b"encrypted:")[::-1],
    )


def test_google_authorization_uses_pkce_state_and_metadata_scope() -> None:
    url, expires_at = gmail.create_authorization_url(
        user_id=42,
        client_id="123-example.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:8765/",
        login_hint="student@example.com",
    )
    query = parse_qs(urlparse(url).query)

    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == [gmail.GMAIL_METADATA_SCOPE]
    assert query["access_type"] == ["offline"]
    assert query["state"][0]
    assert expires_at > datetime.now(timezone.utc)

    pending = gmail.consume_authorization(query["state"][0])
    assert pending.user_id == 42
    assert 43 <= len(pending.code_verifier) <= 128


def test_google_tokens_are_encrypted_at_rest(tmp_path) -> None:
    store = reversible_store(tmp_path)
    tokens = {
        "client_id": "123-example.apps.googleusercontent.com",
        "access_token": "access-token-private",
        "refresh_token": "refresh-token-private",
    }

    store.save(tokens)

    assert store.load() == tokens
    encrypted = store.path.read_bytes()
    assert b"access-token-private" not in encrypted
    assert b"refresh-token-private" not in encrypted


def test_email_metadata_creates_reviewable_forward_only_suggestion() -> None:
    applications = [
        SimpleNamespace(
            id=7,
            company="Example Systems, Inc.",
            role="Software Engineer Intern",
            status=ApplicationStatus.APPLIED,
        )
    ]
    messages = [
        EmailMessageMetadata(
            message_id="gmail-1",
            subject="Example Systems interview — choose a time",
            sender="University Recruiting <careers@example.com>",
            received_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )
    ]

    suggestions = suggest_status_updates(messages, applications)

    assert len(suggestions) == 1
    assert suggestions[0]["application_id"] == 7
    assert suggestions[0]["suggested_status"] == ApplicationStatus.INTERVIEW
    assert suggestions[0]["subject"] == messages[0].subject


@pytest.mark.anyio
async def test_desktop_gmail_connection_and_sync(
    anonymous_client: AsyncClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    store = reversible_store(tmp_path)
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    monkeypatch.setattr(settings, "app_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "google_oauth_client_id", None)
    monkeypatch.setattr(main, "_desktop_google_store", lambda _user_id: store)
    monkeypatch.setattr(main, "hash_password", lambda _password: "test-password-hash")
    monkeypatch.setattr(main.webbrowser, "open", lambda _url, new=0: True)

    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    assert registered.status_code == 201

    connected = await anonymous_client.post(
        "/desktop/email/google/connect",
        json={"client_id": "123-example.apps.googleusercontent.com"},
    )
    assert connected.status_code == 200
    state = parse_qs(urlparse(connected.json()["authorization_url"]).query)["state"][0]
    monkeypatch.setattr(
        gmail,
        "exchange_authorization_code",
        lambda pending, code: {
            "client_id": pending.client_id,
            "access_token": f"access-{code}",
            "refresh_token": "refresh-private",
            "expires_at": 4_102_444_800,
            "scope": gmail.GMAIL_METADATA_SCOPE,
            "token_type": "Bearer",
        },
    )
    monkeypatch.setattr(gmail, "fetch_profile_email", lambda _token: "gmail@example.com")

    callback = await anonymous_client.get(
        "/",
        params={"state": state, "code": "authorization-code"},
    )
    status_response = await anonymous_client.get("/desktop/email/google")

    assert callback.status_code == 200
    assert status_response.json()["connected"] is True
    assert status_response.json()["account_email"] == "gmail@example.com"
    assert b"refresh-private" not in store.path.read_bytes()

    created = await anonymous_client.post(
        "/applications",
        json={
            "company": "Example Systems",
            "role": "Software Engineer Intern",
            "status": "applied",
            "application_date": "2026-10-01",
        },
    )
    assert created.status_code == 201
    monkeypatch.setattr(
        gmail,
        "list_recent_metadata",
        lambda _token: [
            EmailMessageMetadata(
                message_id="gmail-1",
                subject="Example Systems interview invitation",
                sender="recruiting@example.com",
                received_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
            )
        ],
    )

    synced = await anonymous_client.post("/desktop/email/google/sync")

    assert synced.status_code == 200
    assert synced.json()["scanned_messages"] == 1
    assert synced.json()["suggestions"][0]["suggested_status"] == "interview"
    assert synced.json()["suggestions"][0]["application_id"] == created.json()["id"]
