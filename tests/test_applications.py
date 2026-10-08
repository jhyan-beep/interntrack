from fastapi.testclient import TestClient


DEFAULT_DEADLINE = "2099-10-15"
EARLIER_DEADLINE = "2099-10-01"
LATER_DEADLINE = "2099-11-20"


def make_application(
    client: TestClient,
    company: str = "OpenAI",
    role: str = "Software Engineer Intern",
    status: str = "applied",
    application_date: str = "2026-09-24",
    deadline: str | None = DEFAULT_DEADLINE,
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
    response = client.post("/applications", json=payload)
    assert response.status_code == 201
    return response.json()


def test_dashboard_serves_web_ui(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "InternTrack" in response.text
    assert "/static/app.js" in response.text


def test_help_page_serves_user_tutorial(client: TestClient) -> None:
    response = client.get("/help")

    assert response.status_code == 200
    assert "Start tracking applications" in response.text
    assert "Deploy on Render" in response.text


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_and_get_application(client: TestClient) -> None:
    created = make_application(client)

    response = client.get(f"/applications/{created['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["company"] == "OpenAI"
    assert data["role"] == "Software Engineer Intern"
    assert data["status"] == "applied"


def test_list_applications_filters_by_status_and_company(client: TestClient) -> None:
    make_application(client, company="OpenAI", status="applied")
    make_application(client, company="Google", status="saved")
    make_application(client, company="OpenAI Research", status="interview")

    response = client.get("/applications?status=applied&company=openai")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["company"] == "OpenAI"


def test_list_applications_sorts_by_deadline(client: TestClient) -> None:
    make_application(client, company="Later Co", deadline=LATER_DEADLINE)
    make_application(client, company="Soon Co", deadline=EARLIER_DEADLINE)

    response = client.get("/applications?sort_by=deadline&sort_order=asc")

    assert response.status_code == 200
    data = response.json()
    assert [item["company"] for item in data] == ["Soon Co", "Later Co"]


def test_update_application_status(client: TestClient) -> None:
    created = make_application(client, status="applied")

    response = client.patch(f"/applications/{created['id']}", json={"status": "interview"})

    assert response.status_code == 200
    assert response.json()["status"] == "interview"


def test_update_rejects_deadline_before_existing_application_date(client: TestClient) -> None:
    created = make_application(
        client,
        application_date="2026-09-24",
        deadline="2026-10-15",
    )

    response = client.patch(f"/applications/{created['id']}", json={"deadline": "2026-09-01"})

    assert response.status_code == 422
    assert response.json()["detail"] == "deadline cannot be before application_date"
    current = client.get(f"/applications/{created['id']}").json()
    assert current["deadline"] == "2026-10-15"


def test_update_rejects_application_date_after_existing_deadline(client: TestClient) -> None:
    created = make_application(
        client,
        application_date="2026-09-24",
        deadline="2026-10-15",
    )

    response = client.patch(
        f"/applications/{created['id']}",
        json={"application_date": "2026-10-20"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "deadline cannot be before application_date"
    current = client.get(f"/applications/{created['id']}").json()
    assert current["application_date"] == "2026-09-24"


def test_stats_returns_counts_and_upcoming_deadlines(client: TestClient) -> None:
    make_application(client, company="OpenAI", status="applied", deadline=DEFAULT_DEADLINE)
    make_application(client, company="Google", status="interview", deadline=EARLIER_DEADLINE)
    make_application(client, company="Meta", status="rejected", deadline=None)

    response = client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_applications"] == 3
    assert data["active_applications"] == 2
    assert data["by_status"] == {"applied": 1, "interview": 1, "rejected": 1}
    assert [item["company"] for item in data["upcoming_deadlines"]] == ["Google", "OpenAI"]


def test_export_applications_csv(client: TestClient) -> None:
    make_application(client, company="OpenAI")

    response = client.get("/applications/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "company,role,status" in response.text
    assert "OpenAI,Software Engineer Intern,applied" in response.text


def test_delete_application(client: TestClient) -> None:
    created = make_application(client)

    delete_response = client.delete(f"/applications/{created['id']}")
    get_response = client.get(f"/applications/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404
