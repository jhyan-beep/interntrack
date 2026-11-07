import csv
from dataclasses import dataclass
from io import StringIO

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InternshipApplication, User
from app.schemas import (
    ApplicationCreate,
    CsvImportPreview,
    CsvImportRowError,
    CsvImportSample,
)

MAX_CSV_ROWS = 5_000
MAX_REPORTED_ERRORS = 20
REQUIRED_COLUMNS = {"company", "role"}
SUPPORTED_COLUMNS = {
    "company",
    "role",
    "status",
    "application_date",
    "deadline",
    "location",
    "source_url",
    "notes",
}


class CsvImportError(ValueError):
    pass


@dataclass
class CsvImportAnalysis:
    preview: CsvImportPreview
    applications: list[ApplicationCreate]


def _application_key(application: InternshipApplication | ApplicationCreate) -> tuple:
    return (
        application.company.strip().casefold(),
        application.role.strip().casefold(),
        application.application_date,
    )


def _normalized_headers(fieldnames: list[str | None] | None) -> list[str]:
    if not fieldnames:
        raise CsvImportError("The CSV file must include a header row")
    headers = [(name or "").strip().lower() for name in fieldnames]
    if len(headers) != len(set(headers)):
        raise CsvImportError("The CSV header contains duplicate column names")
    missing = REQUIRED_COLUMNS - set(headers)
    if missing:
        raise CsvImportError(f"Missing required column(s): {', '.join(sorted(missing))}")
    return headers


def _row_payload(row: dict[str, str | None]) -> dict:
    payload: dict[str, str | None] = {}
    for column in SUPPORTED_COLUMNS:
        value = row.get(column)
        cleaned = value.strip() if isinstance(value, str) else ""
        if column in {"company", "role"}:
            payload[column] = cleaned
        elif cleaned:
            payload[column] = cleaned
    return payload


def _validation_error(row_number: int, error: ValidationError) -> CsvImportRowError:
    first_error = error.errors()[0]
    location = first_error.get("loc", ())
    field = str(location[0]) if location else None
    message = str(first_error.get("msg", "Invalid value"))
    return CsvImportRowError(row=row_number, field=field, message=message)


def analyze_csv_import(db: Session, user: User, csv_text: str) -> CsvImportAnalysis:
    try:
        reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
        headers = _normalized_headers(reader.fieldnames)
        reader.fieldnames = headers
        rows = list(reader)
    except csv.Error as exc:
        raise CsvImportError(f"Could not read CSV: {exc}") from exc

    if len(rows) > MAX_CSV_ROWS:
        raise CsvImportError(f"CSV imports are limited to {MAX_CSV_ROWS:,} rows")

    existing_keys = {
        _application_key(application)
        for application in db.scalars(
            select(InternshipApplication).where(InternshipApplication.user_id == user.id)
        )
    }
    seen_keys = set(existing_keys)
    applications: list[ApplicationCreate] = []
    errors: list[CsvImportRowError] = []
    invalid_count = 0
    duplicate_count = 0

    for row_number, row in enumerate(rows, start=2):
        if None in row:
            invalid_count += 1
            if len(errors) < MAX_REPORTED_ERRORS:
                errors.append(
                    CsvImportRowError(
                        row=row_number,
                        message="This row has more values than the header",
                    )
                )
            continue
        try:
            application = ApplicationCreate.model_validate(_row_payload(row))
        except ValidationError as exc:
            invalid_count += 1
            if len(errors) < MAX_REPORTED_ERRORS:
                errors.append(_validation_error(row_number, exc))
            continue

        key = _application_key(application)
        if key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(key)
        applications.append(application)

    preview = CsvImportPreview(
        total_rows=len(rows),
        importable_rows=len(applications),
        duplicate_rows=duplicate_count,
        invalid_rows=invalid_count,
        errors=errors,
        errors_truncated=invalid_count > len(errors),
        sample=[
            CsvImportSample(
                company=application.company,
                role=application.role,
                status=application.status,
                application_date=application.application_date,
            )
            for application in applications[:5]
        ],
    )
    return CsvImportAnalysis(preview=preview, applications=applications)
