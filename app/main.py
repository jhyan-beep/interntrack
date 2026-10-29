import csv
import math
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import crud
from app.ai import AiNotConfiguredError, AiProviderError, parse_job_posting
from app.auth import (
    CurrentUser,
    clear_session_cookie,
    get_user_by_email,
    hash_password,
    normalize_email,
    set_session_cookie,
    verify_login_password,
    verify_password,
)
from app.beta import get_beta_progress, record_product_event, save_beta_feedback
from app.database import get_db, get_settings
from app.email_delivery import enqueue_email, password_reset_email, verification_email
from app.email_tokens import consume_email_token, invalidate_user_tokens, issue_email_token
from app.models import (
    ApplicationStatus,
    EmailTokenPurpose,
    InternshipApplication,
    User,
)
from app.observability import configure_logging
from app.schemas import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationStats,
    ApplicationUpdate,
    AiJobDraft,
    AiJobParseRequest,
    BetaFeedbackCreate,
    BetaFeedbackRead,
    BetaProgress,
    DeleteAccountRequest,
    EmailTokenRequest,
    PaginatedApplications,
    PasswordForgotRequest,
    PasswordResetRequest,
    ReminderSettingsRead,
    ReminderSettingsUpdate,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.security import (
    OriginProtectionMiddleware,
    SecurityHeadersMiddleware,
    enforce_auth_rate_limit,
    sanitize_csv_cell,
)

settings = get_settings()
configure_logging(settings)


app = FastAPI(
    title=settings.app_name,
    description="Track software engineering internship applications.",
    version="2.6.0",
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

app.add_middleware(OriginProtectionMiddleware, settings=settings)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware, settings=settings)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def liveness_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def readiness_check(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None
    return {"status": "ready"}


@app.post("/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    enforce_auth_rate_limit(request, "register", normalize_email(user_in.email))
    if get_user_by_email(db, user_in.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=normalize_email(user_in.email),
        password_hash=hash_password(user_in.password),
    )
    db.add(user)
    try:
        db.flush()
        record_product_event(db, user.id, "account_created")
        email_token = issue_email_token(db, user, EmailTokenPurpose.VERIFY_EMAIL)
        enqueue_email(db, verification_email(user.email, email_token), user_id=user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    db.refresh(user)
    set_session_cookie(response, user)
    return user


@app.post("/auth/login", response_model=UserRead)
def login(
    credentials: UserLogin,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    enforce_auth_rate_limit(request, "login", normalize_email(credentials.email))
    user = get_user_by_email(db, credentials.email)
    if not verify_login_password(credentials.password, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    set_session_cookie(response, user)
    return user


@app.post("/auth/email/verification/request", status_code=status.HTTP_202_ACCEPTED)
def request_email_verification(
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    enforce_auth_rate_limit(request, "email_verification", user.email)
    if not user.email_verified:
        email_token = issue_email_token(db, user, EmailTokenPurpose.VERIFY_EMAIL)
        enqueue_email(db, verification_email(user.email, email_token), user_id=user.id)
        db.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)


@app.post("/auth/email/verify", response_model=UserRead)
def verify_email_address(
    token_in: EmailTokenRequest,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    email_token = consume_email_token(db, token_in.token, EmailTokenPurpose.VERIFY_EMAIL)
    if email_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or expired",
        )
    user = db.get(User, email_token.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    user.email_verified_at = datetime.now(timezone.utc)
    invalidate_user_tokens(db, user.id, EmailTokenPurpose.VERIFY_EMAIL)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    request_in: PasswordForgotRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    normalized_email = normalize_email(request_in.email)
    enforce_auth_rate_limit(request, "password_forgot", normalized_email)
    user = get_user_by_email(db, normalized_email)
    if user is not None:
        email_token = issue_email_token(db, user, EmailTokenPurpose.RESET_PASSWORD)
        enqueue_email(db, password_reset_email(user.email, email_token), user_id=user.id)
        db.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)


@app.post("/auth/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    reset_in: PasswordResetRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    enforce_auth_rate_limit(request, "password_reset", reset_in.token)
    email_token = consume_email_token(db, reset_in.token, EmailTokenPurpose.RESET_PASSWORD)
    if email_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset link is invalid or expired",
        )
    user = db.get(User, email_token.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
    user.password_hash = hash_password(reset_in.new_password)
    user.session_version += 1
    invalidate_user_tokens(db, user.id, EmailTokenPurpose.RESET_PASSWORD)
    db.add(user)
    db.commit()
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@app.get("/auth/me", response_model=UserRead)
def get_me(user: CurrentUser) -> User:
    return user


@app.get("/reminders/settings", response_model=ReminderSettingsRead)
def get_reminder_settings(user: CurrentUser) -> User:
    return user


@app.patch("/reminders/settings", response_model=ReminderSettingsRead)
def update_reminder_settings(
    reminder_in: ReminderSettingsUpdate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if reminder_in.deadline_reminders_enabled is True and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email before enabling deadline reminders",
        )
    for field_name, value in reminder_in.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field_name, value)
    if reminder_in.deadline_reminders_enabled is True:
        record_product_event(db, user.id, "reminders_enabled")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/ai/job-draft", response_model=AiJobDraft)
def create_ai_job_draft(
    job_in: AiJobParseRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AiJobDraft:
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email before using AI import",
        )
    enforce_auth_rate_limit(request, "ai_job_parse", str(user.id))
    try:
        draft = parse_job_posting(job_in, user.id)
    except AiNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AiProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    record_product_event(db, user.id, "ai_draft_created")
    db.commit()
    return draft


@app.post("/beta/session", status_code=status.HTTP_204_NO_CONTENT)
def record_beta_session(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    record_product_event(db, user.id, "dashboard_viewed")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/beta/progress", response_model=BetaProgress)
def beta_progress(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return get_beta_progress(db, user)


@app.put("/beta/feedback", response_model=BetaFeedbackRead)
def submit_beta_feedback(
    feedback_in: BetaFeedbackCreate,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    enforce_auth_rate_limit(request, "beta_feedback", str(user.id))
    return save_beta_feedback(db, user.id, feedback_in)


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
    application = crud.create_application(db, application_in, user.id)
    record_product_event(db, user.id, "application_created")
    db.commit()
    return application


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
                sanitize_csv_cell(application.company),
                sanitize_csv_cell(application.role),
                sanitize_csv_cell(application.status.value),
                application.application_date,
                application.deadline or "",
                sanitize_csv_cell(application.location or ""),
                sanitize_csv_cell(application.source_url or ""),
                sanitize_csv_cell(application.notes or ""),
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

