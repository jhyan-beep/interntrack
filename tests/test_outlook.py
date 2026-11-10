from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app import main, outlook
from app.database import get_settings
from app.desktop_secrets import DesktopJsonSecretStore
from app.email_sync import EmailMessageMetadata


CLIENT_ID = "11112222-bbbb-3333-cccc-4444dddd5555"


def reversible_store(tmp_path, filename: str = "microsoft-test.dpapi") -> DesktopJsonSecretStore:
    return DesktopJsonSecretStore(
        tmp_path,
        filename,
        protect=lambda value: b"encrypted:" + value[::-1],
        unprotect=lambda value: value.removeprefix(b"encrypted:")[::-1],
    )


def test_microsoft_authorization_uses_public_client_pkce_and_least_privilege_scope() -> None:
    url, expires_at = outlook.create_authorization_url(
        user_id=42,
        client_id=CLIENT_ID,
        redirect_uri="http://localhost:8765/",
        login_hint="student@example.com",
    )
    query = parse_qs(urlparse(url).query)

    assert query["code_challenge_method"] == ["S256"]
    assert query["response_mode"] == ["query"]
    assert "Mail.ReadBasic" in query["scope"][0].split()
    assert "Mail.Read" not in query["scope"][0].split()
    assert query["state"][0].startswith("microsoft.")
    assert expires_at > datetime.now(timezone.utc)

    pending = outlook.consume_authorization(query["state"][0])
    assert pending.user_id == 42
    assert 43 <= len(pending.code_verifier) <= 128


def test_microsoft_tokens_are_encrypted_at_rest(tmp_path) -> None:
    store = reversible_store(tmp_path)
    tokens = {
        "client_id": CLIENT_ID,
        "access_token": "access-token-private",
        "refresh_token": "refresh-token-private",
    }

    store.save(tokens)

    assert store.load() == tokens
    encrypted = store.path.read_bytes()
    assert b"access-token-private" not in encrypted
    assert b"refresh-token-private" not in encrypted


def test_outlook_message_parser_uses_only_selected_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        is_error = False

        @staticmethod
        def json() -> dict:
            return {
                "value": [
                    {
                        "id": "message-1",
                        "subject": "Example Systems interview invitation",
                        "from": {
                            "emailAddress": {
                                "name": "University Recruiting",
                                "address": "recruiting@example.com",
                            }
                        },
                        "receivedDateTime": "2026-10-30T17:00:00Z",
                        "bodyPreview": "This must be ignored",
                    }
                ]
            }

    def fake_get(url, *, params, headers, timeout):
        assert url.endswith("/me/mailFolders/inbox/messages")
        assert params["$select"] == "id,subject,from,receivedDateTime"
        assert "body" not in params["$select"].lower()
        assert headers["Authorization"] == "Bearer access-private"
        assert timeout == 20
        return Response()

    monkeypatch.setattr(outlook.httpx, "get", fake_get)

    messages = outlook.list_recent_metadata("access-private")

    assert messages == [
        EmailMessageMetadata(
            message_id="message-1",
            subject="Example Systems interview invitation",
            sender="University Recruiting <recruiting@example.com>",
            received_at=datetime(2026, 10, 30, 17, 0, tzinfo=timezone.utc),
        )
    ]


@pytest.mark.anyio
async def test_desktop_microsoft_connection_and_sync(
    anonymous_client: AsyncClient,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    store = reversible_store(tmp_path)
    monkeypatch.setattr(settings, "environment", "desktop")
    monkeypatch.setattr(settings, "desktop_data_dir", tmp_path)
    monkeypatch.setattr(settings, "app_base_url", "http://127.0.0.1:8765")
    monkeypatch.setattr(settings, "microsoft_oauth_client_id", None)
    monkeypatch.setattr(main, "_desktop_microsoft_store", lambda _user_id: store)
    monkeypatch.setattr(main, "hash_password", lambda _password: "test-password-hash")
    monkeypatch.setattr(main.webbrowser, "open", lambda _url, new=0: True)

    registered = await anonymous_client.post(
        "/auth/register",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    assert registered.status_code == 201

    connected = await anonymous_client.post(
        "/desktop/email/microsoft/connect",
        json={"client_id": CLIENT_ID},
    )
    assert connected.status_code == 200
    authorization_url = connected.json()["authorization_url"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["redirect_uri"] == ["http://localhost:8765/"]
    state = query["state"][0]
    monkeypatch.setattr(
        outlook,
        "exchange_authorization_code",
        lambda pending, code: {
            "client_id": pending.client_id,
            "access_token": f"access-{code}",
            "refresh_token": "refresh-private",
            "expires_at": 4_102_444_800,
            "scope": outlook.MICROSOFT_SCOPES,
            "token_type": "Bearer",
        },
    )
    monkeypatch.setattr(outlook, "fetch_profile_email", lambda _token: "outlook@example.com")

    callback = await anonymous_client.get(
        "/",
        params={"state": state, "code": "authorization-code"},
    )
    status_response = await anonymous_client.get("/desktop/email/microsoft")

    assert callback.status_code == 200
    assert status_response.json()["connected"] is True
    assert status_response.json()["account_email"] == "outlook@example.com"
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
        outlook,
        "list_recent_metadata",
        lambda _token: [
            EmailMessageMetadata(
                message_id="outlook-1",
                subject="Example Systems interview invitation",
                sender="recruiting@example.com",
                received_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
            )
        ],
    )

    synced = await anonymous_client.post("/desktop/email/microsoft/sync")

    assert synced.status_code == 200
    assert synced.json()["scanned_messages"] == 1
    assert synced.json()["suggestions"][0]["suggested_status"] == "interview"
    assert synced.json()["suggestions"][0]["application_id"] == created.json()["id"]

    disconnected = await anonymous_client.delete("/desktop/email/microsoft")
    assert disconnected.status_code == 204
    assert store.load() is None
