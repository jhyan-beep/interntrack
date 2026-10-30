import csv
import html
import math
import os
import webbrowser
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import crud, gmail, outlook
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
from app.desktop_secrets import DesktopJsonSecretStore, DesktopSecretError, DesktopSecretStore
from app.email_delivery import enqueue_email, password_reset_email, verification_email
from app.email_sync import suggest_status_updates
from app.email_tokens import consume_email_token, invalidate_user_tokens, issue_email_token
from app.models import (
    ApplicationStatus,
    DeadlineReminderDelivery,
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
    DesktopAiSettingsRead,
    DesktopAiSettingsUpdate,
    DesktopGoogleConnectionRead,
    DesktopGoogleConnectRead,
    DesktopGoogleConnectRequest,
    DesktopMicrosoftConnectionRead,
    DesktopMicrosoftConnectRead,
    DesktopMicrosoftConnectRequest,
    DesktopDeadlineRemindersRead,
    EmailTokenRequest,
    GmailSyncRead,
    OutlookSyncRead,
    PaginatedApplications,
    PasswordForgotRequest,
    PasswordResetRequest,
    ReminderSettingsRead,
    ReminderSettingsUpdate,
    RuntimeInfo,
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
    version="2.11.0",
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


@app.get("/runtime", response_model=RuntimeInfo)
def runtime_info() -> RuntimeInfo:
    desktop_mode = settings.environment == "desktop"
    return RuntimeInfo(
        mode="desktop" if desktop_mode else "web",
        ai_available=settings.openai_api_key is not None,
        email_features_available=not desktop_mode,
    )


def _desktop_data_directory() -> Path:
    if settings.environment != "desktop" or settings.desktop_data_dir is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return settings.desktop_data_dir


def _desktop_secret_store() -> DesktopSecretStore:
    return DesktopSecretStore(_desktop_data_directory())


def _desktop_google_store(user_id: int) -> DesktopJsonSecretStore:
    return DesktopJsonSecretStore(
        _desktop_data_directory(),
        f"google-oauth-user-{user_id}.dpapi",
    )


def _desktop_microsoft_store(user_id: int) -> DesktopJsonSecretStore:
    return DesktopJsonSecretStore(
        _desktop_data_directory(),
        f"microsoft-oauth-user-{user_id}.dpapi",
    )


def _microsoft_redirect_uri() -> str:
    parsed = urlsplit(settings.app_base_url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"http://localhost{port}/"


@app.get("/desktop/ai-settings", response_model=DesktopAiSettingsRead)
def get_desktop_ai_settings(user: CurrentUser) -> DesktopAiSettingsRead:
    del user
    _desktop_secret_store()
    return DesktopAiSettingsRead(
        configured=settings.openai_api_key is not None,
        model=settings.openai_model,
    )


@app.put("/desktop/ai-settings", response_model=DesktopAiSettingsRead)
def update_desktop_ai_settings(
    update: DesktopAiSettingsUpdate,
    user: CurrentUser,
) -> DesktopAiSettingsRead:
    del user
    api_key = update.api_key.get_secret_value()
    try:
        _desktop_secret_store().save(api_key)
    except DesktopSecretError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not securely save the API key",
        ) from None
    settings.openai_api_key = update.api_key
    os.environ["OPENAI_API_KEY"] = api_key
    return DesktopAiSettingsRead(configured=True, model=settings.openai_model)


@app.delete("/desktop/ai-settings", status_code=status.HTTP_204_NO_CONTENT)
def delete_desktop_ai_settings(user: CurrentUser) -> Response:
    del user
    try:
        _desktop_secret_store().delete()
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not remove the saved API key",
        ) from None
    settings.openai_api_key = None
    os.environ.pop("OPENAI_API_KEY", None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/desktop/email/google", response_model=DesktopGoogleConnectionRead)
def get_desktop_google_connection(user: CurrentUser) -> DesktopGoogleConnectionRead:
    try:
        tokens = _desktop_google_store(user.id).load()
    except DesktopSecretError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not read the saved Gmail connection",
        ) from None
    return DesktopGoogleConnectionRead(
        configured=bool(settings.google_oauth_client_id or (tokens or {}).get("client_id")),
        connected=bool(tokens and (tokens.get("refresh_token") or tokens.get("access_token"))),
        account_email=(tokens or {}).get("account_email"),
        scope=(tokens or {}).get("scope"),
    )


@app.post("/desktop/email/google/connect", response_model=DesktopGoogleConnectRead)
def connect_desktop_google(
    connection: DesktopGoogleConnectRequest,
    user: CurrentUser,
) -> DesktopGoogleConnectRead:
    store = _desktop_google_store(user.id)
    try:
        existing = store.load()
    except DesktopSecretError:
        existing = None
    client_id = connection.client_id or settings.google_oauth_client_id or (existing or {}).get(
        "client_id"
    )
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A Google Desktop OAuth client ID is required",
        )
    redirect_uri = f"{settings.app_base_url.rstrip('/')}/"
    try:
        authorization_url, expires_at = gmail.create_authorization_url(
            user.id,
            client_id,
            redirect_uri,
            login_hint=user.email,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        browser_opened = webbrowser.open(authorization_url, new=2)
    except webbrowser.Error:
        browser_opened = False
    return DesktopGoogleConnectRead(
        authorization_url=authorization_url,
        expires_at=expires_at,
        browser_opened=browser_opened,
    )


def _oauth_callback_page(title: str, message: str, success: bool) -> str:
    color = "#216845" if success else "#a53a2f"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(title)}</title></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f5f0;color:#17233c;font-family:system-ui,sans-serif">
<main style="max-width:520px;padding:36px;text-align:center"><h1 style="color:{color}">{html.escape(title)}</h1>
<p style="line-height:1.6">{html.escape(message)}</p><p>You can close this browser tab and return to InternTrack.</p></main>
</body></html>"""


@app.get("/", include_in_schema=False)
def desktop_oauth_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> Response:
    if state is None:
        index_file = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _desktop_data_directory()
    provider_name = "Email"
    try:
        if state.startswith("google."):
            provider_name = "Gmail"
            pending = gmail.consume_authorization(state)
            if error or not code:
                raise gmail.GmailAuthorizationError("Gmail access was not granted")
            tokens = gmail.exchange_authorization_code(pending, code)
            store = _desktop_google_store(pending.user_id)
            existing = store.load() or {}
            if not tokens.get("refresh_token") and existing.get("refresh_token"):
                tokens["refresh_token"] = existing["refresh_token"]
            tokens["account_email"] = gmail.fetch_profile_email(str(tokens["access_token"]))
            store.save(tokens)
        elif state.startswith("microsoft."):
            provider_name = "Microsoft Outlook"
            pending = outlook.consume_authorization(state)
            if error or not code:
                raise outlook.OutlookAuthorizationError("Microsoft access was not granted")
            tokens = outlook.exchange_authorization_code(pending, code)
            store = _desktop_microsoft_store(pending.user_id)
            existing = store.load() or {}
            if not tokens.get("refresh_token") and existing.get("refresh_token"):
                tokens["refresh_token"] = existing["refresh_token"]
            tokens["account_email"] = outlook.fetch_profile_email(str(tokens["access_token"]))
            store.save(tokens)
        else:
            raise outlook.OutlookAuthorizationError("Unknown email authorization request")
    except (gmail.GmailProviderError, outlook.OutlookProviderError, DesktopSecretError) as exc:
        return HTMLResponse(
            _oauth_callback_page(f"{provider_name} connection failed", str(exc), False),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return HTMLResponse(
        _oauth_callback_page(
            f"{provider_name} connected",
            f"InternTrack can now review email metadata for {tokens['account_email']}.",
            True,
        )
    )


@app.delete("/desktop/email/google", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_desktop_google(user: CurrentUser) -> Response:
    store = _desktop_google_store(user.id)
    try:
        tokens = store.load()
        if tokens:
            gmail.revoke_tokens(tokens)
        store.delete()
    except (DesktopSecretError, OSError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not remove the Gmail connection",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/desktop/email/google/sync", response_model=GmailSyncRead)
def sync_desktop_google(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> GmailSyncRead:
    store = _desktop_google_store(user.id)
    try:
        tokens = store.load()
        if not tokens:
            raise gmail.GmailAuthorizationError("Connect Gmail before syncing")
        access_token, _ = gmail.ensure_access_token(tokens, store)
        messages = gmail.list_recent_metadata(access_token)
    except gmail.GmailAuthorizationError as exc:
        store.delete()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (gmail.GmailProviderError, DesktopSecretError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    applications = list(
        db.scalars(
            select(InternshipApplication)
            .where(InternshipApplication.user_id == user.id)
            .order_by(InternshipApplication.updated_at.desc())
        )
    )
    suggestions = suggest_status_updates(messages, applications)
    return GmailSyncRead(scanned_messages=len(messages), suggestions=suggestions)


@app.get("/desktop/email/microsoft", response_model=DesktopMicrosoftConnectionRead)
def get_desktop_microsoft_connection(user: CurrentUser) -> DesktopMicrosoftConnectionRead:
    try:
        tokens = _desktop_microsoft_store(user.id).load()
    except DesktopSecretError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not read the saved Microsoft connection",
        ) from None
    return DesktopMicrosoftConnectionRead(
        configured=bool(settings.microsoft_oauth_client_id or (tokens or {}).get("client_id")),
        connected=bool(tokens and (tokens.get("refresh_token") or tokens.get("access_token"))),
        account_email=(tokens or {}).get("account_email"),
        scope=(tokens or {}).get("scope"),
    )


@app.post("/desktop/email/microsoft/connect", response_model=DesktopMicrosoftConnectRead)
def connect_desktop_microsoft(
    connection: DesktopMicrosoftConnectRequest,
    user: CurrentUser,
) -> DesktopMicrosoftConnectRead:
    store = _desktop_microsoft_store(user.id)
    try:
        existing = store.load()
    except DesktopSecretError:
        existing = None
    client_id = (
        connection.client_id
        or settings.microsoft_oauth_client_id
        or (existing or {}).get("client_id")
    )
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A Microsoft Application (client) ID is required",
        )
    try:
        authorization_url, expires_at = outlook.create_authorization_url(
            user.id,
            client_id,
            _microsoft_redirect_uri(),
            login_hint=user.email,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    try:
        browser_opened = webbrowser.open(authorization_url, new=2)
    except webbrowser.Error:
        browser_opened = False
    return DesktopMicrosoftConnectRead(
        authorization_url=authorization_url,
        expires_at=expires_at,
        browser_opened=browser_opened,
    )


@app.delete("/desktop/email/microsoft", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_desktop_microsoft(user: CurrentUser) -> Response:
    try:
        _desktop_microsoft_store(user.id).delete()
    except (DesktopSecretError, OSError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Windows could not remove the Microsoft connection",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/desktop/email/microsoft/sync", response_model=OutlookSyncRead)
def sync_desktop_microsoft(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> OutlookSyncRead:
    store = _desktop_microsoft_store(user.id)
    try:
        tokens = store.load()
        if not tokens:
            raise outlook.OutlookAuthorizationError("Connect Microsoft Outlook before syncing")
        access_token, _ = outlook.ensure_access_token(tokens, store)
        messages = outlook.list_recent_metadata(access_token)
    except outlook.OutlookAuthorizationError as exc:
        store.delete()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (outlook.OutlookProviderError, DesktopSecretError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    applications = list(
        db.scalars(
            select(InternshipApplication)
            .where(InternshipApplication.user_id == user.id)
            .order_by(InternshipApplication.updated_at.desc())
        )
    )
    suggestions = suggest_status_updates(messages, applications)
    return OutlookSyncRead(scanned_messages=len(messages), suggestions=suggestions)


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
        email_verified_at=datetime.now(timezone.utc)
        if settings.environment == "desktop"
        else None,
    )
    db.add(user)
    try:
        db.flush()
        record_product_event(db, user.id, "account_created")
        if settings.environment != "desktop":
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
    if settings.environment == "desktop":
        if not user.email_verified:
            user.email_verified_at = datetime.now(timezone.utc)
            db.add(user)
            db.commit()
        return Response(status_code=status.HTTP_202_ACCEPTED)
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
    if settings.environment == "desktop":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password reset email is unavailable in the desktop app",
        )
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


_ACTIVE_REMINDER_STATUSES = {
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
}


def _desktop_reminder_date(user: User) -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(user.reminder_timezone))


@app.get("/desktop/reminders/due", response_model=DesktopDeadlineRemindersRead)
def get_due_desktop_reminders(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _desktop_data_directory()
    if not user.deadline_reminders_enabled:
        return {"items": []}

    local_date = _desktop_reminder_date(user).date()
    latest_date = local_date + timedelta(days=user.deadline_reminder_days)
    applications = list(
        db.scalars(
            select(InternshipApplication)
            .where(
                InternshipApplication.user_id == user.id,
                InternshipApplication.status.in_(_ACTIVE_REMINDER_STATUSES),
                InternshipApplication.deadline.is_not(None),
                InternshipApplication.deadline >= local_date,
                InternshipApplication.deadline <= latest_date,
            )
            .order_by(InternshipApplication.deadline.asc(), InternshipApplication.id.asc())
            .limit(20)
        )
    )
    delivered = {
        (application_id, deadline)
        for application_id, deadline in db.execute(
            select(
                DeadlineReminderDelivery.application_id,
                DeadlineReminderDelivery.deadline,
            ).where(DeadlineReminderDelivery.user_id == user.id)
        ).all()
    }
    return {
        "items": [
            {
                "application_id": application.id,
                "company": application.company,
                "role": application.role,
                "deadline": application.deadline,
                "days_remaining": (application.deadline - local_date).days,
            }
            for application in applications
            if (application.id, application.deadline) not in delivered
        ]
    }


@app.post(
    "/desktop/reminders/{application_id}/acknowledge",
    status_code=status.HTTP_204_NO_CONTENT,
)
def acknowledge_desktop_reminder(
    application_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    _desktop_data_directory()
    application = db.scalar(
        select(InternshipApplication).where(
            InternshipApplication.id == application_id,
            InternshipApplication.user_id == user.id,
        )
    )
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if not user.deadline_reminders_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Local deadline reminders are disabled",
        )

    local_date = _desktop_reminder_date(user).date()
    days_remaining = (
        (application.deadline - local_date).days if application.deadline is not None else -1
    )
    if (
        application.status not in _ACTIVE_REMINDER_STATUSES
        or days_remaining < 0
        or days_remaining > user.deadline_reminder_days
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application is not currently due for a reminder",
        )

    db.add(
        DeadlineReminderDelivery(
            user_id=user.id,
            application_id=application.id,
            deadline=application.deadline,
            days_before=days_remaining,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    if settings.environment == "desktop" and settings.desktop_data_dir is not None:
        google_store = _desktop_google_store(user.id)
        try:
            tokens = google_store.load()
            if tokens:
                gmail.revoke_tokens(tokens)
            google_store.delete()
        except (DesktopSecretError, OSError):
            pass
        try:
            _desktop_microsoft_store(user.id).delete()
        except (DesktopSecretError, OSError):
            pass
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

