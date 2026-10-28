from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import AsyncClient

from app.auth import ALGORITHM
from app.database import get_settings


pytestmark = pytest.mark.anyio


async def register(
    client: AsyncClient,
    email: str,
    password: str = "securepass123",
) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201


async def test_register_sets_http_only_session_cookie(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.post(
        "/auth/register",
        json={"email": "Student@Example.com", "password": "securepass123"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "student@example.com"
    cookie = response.headers["set-cookie"].lower()
    assert "interntrack_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_duplicate_email_is_case_insensitive(anonymous_client: AsyncClient) -> None:
    await register(anonymous_client, "student@example.com")

    response = await anonymous_client.post(
        "/auth/register",
        json={"email": "STUDENT@example.com", "password": "anotherpass123"},
    )

    assert response.status_code == 409


async def test_login_and_logout(anonymous_client: AsyncClient) -> None:
    await register(anonymous_client, "student@example.com")
    await anonymous_client.post("/auth/logout")

    bad_login = await anonymous_client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "wrong-password"},
    )
    good_login = await anonymous_client.post(
        "/auth/login",
        json={"email": "student@example.com", "password": "securepass123"},
    )
    me = await anonymous_client.get("/auth/me")
    logout = await anonymous_client.post("/auth/logout")
    after_logout = await anonymous_client.get("/auth/me")

    assert bad_login.status_code == 401
    assert good_login.status_code == 200
    assert me.json()["email"] == "student@example.com"
    assert logout.status_code == 204
    assert after_logout.status_code == 401


async def test_protected_endpoints_require_authentication(anonymous_client: AsyncClient) -> None:
    for path in ["/applications", "/applications/export.csv", "/stats"]:
        response = await anonymous_client.get(path)
        assert response.status_code == 401


async def test_tampered_session_cookie_is_rejected(anonymous_client: AsyncClient) -> None:
    anonymous_client.cookies.set("interntrack_session", "not.a.valid-token")

    response = await anonymous_client.get("/auth/me")

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("exp", datetime.now(timezone.utc) - timedelta(minutes=1)),
        ("aud", "another-application"),
        ("iss", "another-issuer"),
    ],
)
async def test_invalid_session_claims_are_rejected(
    client: AsyncClient,
    claim: str,
    value: object,
) -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "1",
        "iat": now,
        "exp": now + timedelta(hours=1),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    payload[claim] = value
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    client.cookies.set(settings.session_cookie_name, token)

    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_users_cannot_access_each_others_data(anonymous_client: AsyncClient) -> None:
    await register(anonymous_client, "first@example.com")
    created = await anonymous_client.post(
        "/applications",
        json={
            "company": "Private Company",
            "role": "Software Engineer Intern",
            "application_date": "2026-10-24",
        },
    )
    application_id = created.json()["id"]
    await anonymous_client.post("/auth/logout")
    await register(anonymous_client, "second@example.com")

    get_response = await anonymous_client.get(f"/applications/{application_id}")
    patch_response = await anonymous_client.patch(
        f"/applications/{application_id}",
        json={"status": "offer"},
    )
    delete_response = await anonymous_client.delete(f"/applications/{application_id}")
    list_response = await anonymous_client.get("/applications")
    stats_response = await anonymous_client.get("/stats")
    csv_response = await anonymous_client.get("/applications/export.csv")

    assert get_response.status_code == 404
    assert patch_response.status_code == 404
    assert delete_response.status_code == 404
    assert list_response.json()["total"] == 0
    assert stats_response.json()["total_applications"] == 0
    assert "Private Company" not in csv_response.text


async def test_application_list_is_paginated(client: AsyncClient) -> None:
    for index in range(5):
        response = await client.post(
            "/applications",
            json={
                "company": f"Company {index}",
                "role": "Software Engineer Intern",
                "application_date": "2026-10-24",
            },
        )
        assert response.status_code == 201

    response = await client.get("/applications?page=2&page_size=2&sort_by=company&sort_order=asc")
    invalid_size = await client.get("/applications?page_size=101")

    data = response.json()
    assert response.status_code == 200
    assert data["total"] == 5
    assert data["page"] == 2
    assert data["page_size"] == 2
    assert data["pages"] == 3
    assert [item["company"] for item in data["items"]] == ["Company 2", "Company 3"]
    assert invalid_size.status_code == 422


async def test_delete_account_clears_session(client: AsyncClient) -> None:
    response = await client.request(
        "DELETE",
        "/auth/me",
        json={"password": "securepass123"},
    )
    me = await client.get("/auth/me")

    assert response.status_code == 204
    assert me.status_code == 401
