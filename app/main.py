import csv
import math
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.auth import (
    CurrentUser,
    clear_session_cookie,
    get_user_by_email,
    hash_password,
    normalize_email,
    set_session_cookie,
    verify_password,
)
from app.database import get_db, get_settings
from app.models import ApplicationStatus, InternshipApplication, User
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStats,
    ApplicationUpdate,
    DeleteAccountRequest,
    PaginatedApplications,
    UserCreate,
    UserLogin,
    UserRead,
)

settings = get_settings()


app = FastAPI(
    title=settings.app_name,
    description="Track software engineering internship applications.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if get_user_by_email(db, user_in.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=normalize_email(user_in.email),
        password_hash=hash_password(user_in.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    db.refresh(user)
    set_session_cookie(response, user.id)
    return user


@app.post("/auth/login", response_model=UserRead)
def login(
    credentials: UserLogin,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = get_user_by_email(db, credentials.email)
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    set_session_cookie(response, user.id)
    return user


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/auth/me", response_model=UserRead)
def get_me(user: CurrentUser) -> User:
    return user


@app.delete("/auth/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    confirmation: DeleteAccountRequest,
    user: CurrentUser,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not verify_password(confirmation.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")
    db.delete(user)
    db.commit()
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.post(
    "/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    application_in: ApplicationCreate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    return crud.create_application(db, application_in, user.id)


@app.get("/applications", response_model=PaginatedApplications)
def list_applications(
    user: CurrentUser,
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
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    applications, total = crud.list_applications(
        db,
        user_id=user.id,
        status=status_filter,
        company=company,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return {
        "items": applications,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@app.get("/applications/export.csv")
def export_applications_csv(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    applications, _ = crud.list_applications(
        db,
        user_id=user.id,
        sort_by="application_date",
        sort_order="desc",
        page_size=100_000,
    )
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
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    application = crud.get_application(db, application_id, user.id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@app.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int,
    application_in: ApplicationUpdate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> InternshipApplication:
    application = crud.get_application(db, application_id, user.id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")

    application_date = application_in.application_date or application.application_date
    deadline = (
        application_in.deadline
        if "deadline" in application_in.model_fields_set
        else application.deadline
    )
    if deadline is not None and deadline < application_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="deadline cannot be before application_date",
        )

    return crud.update_application(db, application, application_in)


@app.delete("/applications/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    application = crud.get_application(db, application_id, user.id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    crud.delete_application(db, application)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/stats", response_model=ApplicationStats)
def get_stats(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return crud.get_application_stats(db, user.id)


frontend_directory = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if settings.environment != "test" and frontend_directory.exists():
    app.mount("/", StaticFiles(directory=frontend_directory, html=True), name="frontend")

