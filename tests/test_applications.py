import pytest
from httpx import AsyncClient
from datetime import date, timedelta


pytestmark = pytest.mark.anyio


async def make_application(
    client: AsyncClient,
    company: str = "OpenAI",
    role: str = "Software Engineer Intern",
    status: str = "applied",
    application_date: str = "2026-09-24",
    deadline: str | None = "2026-10-15",
) -> dict:
    payload = {
        "company": company,
        "role": role,
        "status": status,
        "application_date": application_date,
        "deadline": deadline,
        "location": "San Francisco, CA",
        "source_url": "https://example.com/jobs/swe-intern",
        "notes": "Applied through company careers page.",
    }
    response = await client.post("/applications", json=payload)
    assert response.status_code == 201
    return response.json()


async def test_health_check(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_and_get_application(client: AsyncClient) -> None:
    created = await make_application(client)

    response = await client.get(f"/applications/{created['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["company"] == "OpenAI"
    assert data["role"] == "Software Engineer Intern"
    assert data["status"] == "applied"


async def test_list_applications_filters_by_status_and_company(client: AsyncClient) -> None:
    await make_application(client, company="OpenAI", status="applied")
    await make_application(client, company="Google", status="saved")
    await make_application(client, company="OpenAI Research", status="interview")

    response = await client.get("/applications?status=applied&company=openai")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["company"] == "OpenAI"


async def test_list_applications_sorts_by_deadline(client: AsyncClient) -> None:
    await make_application(client, company="Later Co", deadline="2026-11-20")
    await make_application(client, company="Soon Co", deadline="2026-10-01")

    response = await client.get("/applications?sort_by=deadline&sort_order=asc")

    assert response.status_code == 200
    data = response.json()
    assert [item["company"] for item in data] == ["Soon Co", "Later Co"]


async def test_update_application_status(client: AsyncClient) -> None:
    created = await make_application(client, status="applied")

    response = await client.patch(f"/applications/{created['id']}", json={"status": "interview"})

    assert response.status_code == 200
    assert response.json()["status"] == "interview"


async def test_update_rejects_deadline_before_existing_application_date(client: AsyncClient) -> None:
    created = await make_application(client, application_date="2026-09-24")

    response = await client.patch(
        f"/applications/{created['id']}",
        json={"deadline": "2026-09-01"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "deadline cannot be before application_date"


async def test_update_rejects_null_required_field(client: AsyncClient) -> None:
    created = await make_application(client)

    response = await client.patch(f"/applications/{created['id']}", json={"company": None})

    assert response.status_code == 422


async def test_create_rejects_invalid_source_url(client: AsyncClient) -> None:
    response = await client.post(
        "/applications",
        json={
            "company": "Example Co",
            "role": "Software Engineer Intern",
            "application_date": "2026-09-24",
            "source_url": "not-a-url",
        },
    )

    assert response.status_code == 422


async def test_stats_returns_counts_and_upcoming_deadlines(client: AsyncClient) -> None:
    application_date = date.today().isoformat()
    later_deadline = (date.today() + timedelta(days=30)).isoformat()
    sooner_deadline = (date.today() + timedelta(days=7)).isoformat()
    await make_application(
        client,
        company="OpenAI",
        status="applied",
        application_date=application_date,
        deadline=later_deadline,
    )
    await make_application(
        client,
        company="Google",
        status="interview",
        application_date=application_date,
        deadline=sooner_deadline,
    )
    await make_application(
        client,
        company="Meta",
        status="rejected",
        application_date=application_date,
        deadline=None,
    )

    response = await client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_applications"] == 3
    assert data["active_applications"] == 2
    assert data["by_status"] == {"applied": 1, "interview": 1, "rejected": 1}
    assert [item["company"] for item in data["upcoming_deadlines"]] == ["Google", "OpenAI"]


async def test_export_applications_csv(client: AsyncClient) -> None:
    await make_application(client, company="OpenAI")

    response = await client.get("/applications/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "company,role,status" in response.text
    assert "OpenAI,Software Engineer Intern,applied" in response.text


async def test_delete_application(client: AsyncClient) -> None:
    created = await make_application(client)

    delete_response = await client.delete(f"/applications/{created['id']}")
    get_response = await client.get(f"/applications/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


