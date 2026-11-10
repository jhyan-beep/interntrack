import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def add_existing_application(client: AsyncClient) -> None:
    response = await client.post(
        "/applications",
        json={
            "company": "Figma",
            "role": "SWE Intern",
            "status": "applied",
            "application_date": "2026-10-01",
            "deadline": "2026-12-01",
        },
    )
    assert response.status_code == 201


async def test_csv_preview_reports_importable_duplicates_and_invalid_rows(
    client: AsyncClient,
) -> None:
    await add_existing_application(client)
    csv_text = """company,role,status,application_date,deadline,location,source_url,notes
Figma,SWE Intern,applied,2026-10-01,2026-12-01,,,duplicate
Linear,Engineering Intern,saved,2026-10-02,2026-12-02,Remote,https://linear.app/jobs,valid
Broken Row,,unknown,not-a-date,,,,
"""

    response = await client.post(
        "/applications/import/preview",
        json={"csv_text": csv_text},
    )

    assert response.status_code == 200
    preview = response.json()
    assert preview["total_rows"] == 3
    assert preview["importable_rows"] == 1
    assert preview["duplicate_rows"] == 1
    assert preview["invalid_rows"] == 1
    assert preview["errors"][0]["row"] == 4
    assert preview["sample"][0]["company"] == "Linear"


async def test_csv_import_is_atomic_when_any_row_is_invalid(client: AsyncClient) -> None:
    csv_text = """company,role,status,application_date
Linear,Engineering Intern,saved,2026-10-02
Bad Date,SWE Intern,applied,October someday
"""

    response = await client.post(
        "/applications/import",
        json={"csv_text": csv_text},
    )

    assert response.status_code == 422
    applications = await client.get("/applications?page_size=100")
    assert applications.json()["total"] == 0


async def test_csv_import_adds_valid_rows_and_skips_duplicates(client: AsyncClient) -> None:
    await add_existing_application(client)
    csv_text = """company,role,status,application_date,deadline,location,source_url,notes
Figma,SWE Intern,applied,2026-10-01,2026-12-01,,,duplicate
Linear,Engineering Intern,saved,2026-10-02,2026-12-02,Remote,https://linear.app/jobs,first
Datadog,Software Engineering Intern,interview,2026-10-03,2026-12-03,New York,https://example.com/datadog,second
"""

    response = await client.post(
        "/applications/import",
        json={"csv_text": csv_text},
    )

    assert response.status_code == 200
    assert response.json() == {
        "imported_applications": 2,
        "skipped_duplicates": 1,
    }
    applications = await client.get("/applications?page_size=100")
    assert applications.json()["total"] == 3


async def test_csv_import_accepts_interntrack_export(client: AsyncClient) -> None:
    await add_existing_application(client)
    exported = await client.get("/applications/export.csv")
    await client.delete("/applications/1")

    preview = await client.post(
        "/applications/import/preview",
        json={"csv_text": exported.text},
    )
    imported = await client.post(
        "/applications/import",
        json={"csv_text": exported.text},
    )

    assert preview.status_code == 200
    assert preview.json()["importable_rows"] == 1
    assert imported.status_code == 200
    assert imported.json()["imported_applications"] == 1


async def test_csv_import_rejects_missing_required_headers(client: AsyncClient) -> None:
    response = await client.post(
        "/applications/import/preview",
        json={"csv_text": "company,status\nOpenAI,applied\n"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Missing required column(s): role"
