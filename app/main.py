import csv
from contextlib import asynccontextmanager
from io import StringIO
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import crud
from app.database import create_tables, get_db, get_settings
from app.models import ApplicationStatus, InternshipApplication
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStats,
    ApplicationUpdate,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Track software engineering internship applications.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    application_in: ApplicationCreate,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    return crud.create_application(db, application_in)


@app.get("/applications", response_model=list[ApplicationRead])
def list_applications(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[
        ApplicationStatus | None,
        Query(alias="status", description="Filter by application status."),
    ] = None,
    company: Annotated[
        str | None,
        Query(description="Case-insensitive company search."),
    ] = None,
    sort_by: Annotated[
        Literal["deadline", "application_date", "created_at", "company"],
        Query(description="Field used for sorting."),
    ] = "created_at",
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Sort direction."),
    ] = "desc",
) -> list[InternshipApplication]:
    return crud.list_applications(
        db,
        status=status_filter,
        company=company,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@app.get("/applications/export.csv")
def export_applications_csv(
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    applications = crud.list_applications(db, sort_by="application_date", sort_order="desc")
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "company",
            "role",
            "status",
            "application_date",
            "deadline",
            "location",
            "source_url",
            "notes",
            "created_at",
            "updated_at",
        ]
    )

    for application in applications:
        writer.writerow(
            [
                application.id,
                application.company,
                application.role,
                application.status.value,
                application.application_date,
                application.deadline or "",
                application.location or "",
                application.source_url or "",
                application.notes or "",
                application.created_at,
                application.updated_at,
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


@app.get("/applications/{application_id}", response_model=ApplicationRead)
def get_application(
    application_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    application = crud.get_application(db, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@app.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int,
    application_in: ApplicationUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    application = crud.get_application(db, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return crud.update_application(db, application, application_in)


@app.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    application = crud.get_application(db, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    crud.delete_application(db, application)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", response_model=ApplicationStats)
def get_stats(db: Annotated[Session, Depends(get_db)]) -> dict:
    return crud.get_application_stats(db)
