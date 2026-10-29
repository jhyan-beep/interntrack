import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.database import Settings, get_settings


pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "secret_key",
    [
        "development-only-change-me-32-chars",
        "replace-with-a-long-random-value-before-deploying",
        "too-short",
    ],
)
async def test_production_rejects_unsafe_session_secrets(secret_key: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key=secret_key)


async def test_health_endpoints_and_security_headers(
    anonymous_client: AsyncClient,
) -> None:
    response = await anonymous_client.get(
        "/health/ready",
        headers={"X-Request-ID": "test-request-123"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["x-request-id"] == "test-request-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


async def test_untrusted_origin_cannot_change_state(
    anonymous_client: AsyncClient,
) -> None:
    response = await anonymous_client.post(
        "/auth/register",
        headers={"Origin": "https://attacker.example"},
        json={"email": "student@example.com", "password": "securepass123"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted request origin"}
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)
async def test_trusted_origin_receives_credentialed_cors_headers(
    anonymous_client: AsyncClient,
    origin: str,
) -> None:
    response = await anonymous_client.post(
        "/auth/register",
        headers={"Origin": origin},
        json={"email": "student@example.com", "password": "securepass123"},
    )

    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["cache-control"] == "no-store"


async def test_login_is_rate_limited_by_identity(
    anonymous_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_per_identity", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_per_ip", 100)

    responses = [
        await anonymous_client.post(
            "/auth/login",
            json={"email": "unknown@example.com", "password": "wrong-password"},
        )
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert int(responses[-1].headers["retry-after"]) >= 1


async def test_csv_export_neutralizes_spreadsheet_formulas(client: AsyncClient) -> None:
    created = await client.post(
        "/applications",
        json={
            "company": "=1+1",
            "role": "Software Engineer Intern",
            "application_date": "2026-10-28",
            "notes": "@SUM(A1:A2)",
        },
    )
    exported = await client.get("/applications/export.csv")

    assert created.status_code == 201
    assert exported.status_code == 200
    assert "'=1+1" in exported.text
    assert "'@SUM(A1:A2)" in exported.text


async def test_application_notes_have_a_safe_size_limit(client: AsyncClient) -> None:
    response = await client.post(
        "/applications",
        json={
            "company": "Example Company",
            "role": "Software Engineer Intern",
            "application_date": "2026-10-28",
            "notes": "x" * 5_001,
        },
    )

    assert response.status_code == 422

