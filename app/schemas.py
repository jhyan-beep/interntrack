from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    SecretStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.models import ApplicationStatus


http_url_adapter = TypeAdapter(HttpUrl)


def validate_source_url(value: str | None) -> str | None:
    if value is None:
        return None
    return str(http_url_adapter.validate_python(value))


class ApplicationBase(BaseModel):
    company: str = Field(..., min_length=1, max_length=120)
    role: str = Field(..., min_length=1, max_length=120)
    status: ApplicationStatus = ApplicationStatus.SAVED
    application_date: date = Field(default_factory=date.today)
    deadline: date | None = None
    location: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5_000)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str | None) -> str | None:
        return validate_source_url(value)

    @model_validator(mode="after")
    def deadline_cannot_be_before_application_date(self) -> "ApplicationBase":
        if self.deadline is not None and self.deadline < self.application_date:
            raise ValueError("deadline cannot be before application_date")
        return self


class ApplicationCreate(ApplicationBase):
    pass


class ApplicationUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, min_length=1, max_length=120)
    status: ApplicationStatus | None = None
    application_date: date | None = None
    deadline: date | None = None
    location: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5_000)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str | None) -> str | None:
        return validate_source_url(value)

    @model_validator(mode="after")
    def deadline_cannot_be_before_application_date(self) -> "ApplicationUpdate":
        required_fields = {"company", "role", "status", "application_date"}
        for field_name in required_fields & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")

        if (
            self.deadline is not None
            and self.application_date is not None
            and self.deadline < self.application_date
        ):
            raise ValueError("deadline cannot be before application_date")
        return self


class ApplicationRead(ApplicationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpcomingDeadline(BaseModel):
    id: int
    company: str
    role: str
    deadline: date

    model_config = ConfigDict(from_attributes=True)


class ApplicationStats(BaseModel):
    total_applications: int
    active_applications: int
    by_status: dict[str, int]
    upcoming_deadlines: list[UpcomingDeadline]


class PaginatedApplications(BaseModel):
    items: list[ApplicationRead]
    total: int
    page: int
    page_size: int
    pages: int


AiDraftField = Literal["company", "role", "location", "deadline", "source_url", "notes"]


class AiJobParseRequest(BaseModel):
    job_text: str = Field(..., min_length=100, max_length=20_000)
    source_url: str | None = Field(default=None, max_length=500)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str | None) -> str | None:
        return validate_source_url(value)


class AiJobDraft(BaseModel):
    company: str | None = Field(..., max_length=120)
    role: str | None = Field(..., max_length=120)
    location: str | None = Field(..., max_length=120)
    deadline: date | None
    source_url: str | None = Field(..., max_length=500)
    notes: str | None = Field(..., max_length=1_500)
    uncertain_fields: list[AiDraftField]

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str | None) -> str | None:
        return validate_source_url(value)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserRead(BaseModel):
    id: int
    email: str
    email_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuntimeInfo(BaseModel):
    mode: Literal["web", "desktop"]
    ai_available: bool
    email_features_available: bool


class DesktopAiSettingsRead(BaseModel):
    configured: bool
    model: str


class DesktopAiSettingsUpdate(BaseModel):
    api_key: SecretStr = Field(..., max_length=500)

    @field_validator("api_key")
    @classmethod
    def api_key_must_not_be_blank(cls, value: SecretStr) -> SecretStr:
        cleaned = value.get_secret_value().strip()
        if len(cleaned) < 20:
            raise ValueError("API key must be at least 20 characters")
        return SecretStr(cleaned)


class DesktopGoogleConnectionRead(BaseModel):
    configured: bool
    connected: bool
    account_email: str | None = None
    scope: str | None = None


class DesktopGoogleConnectRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=300)

    @field_validator("client_id")
    @classmethod
    def normalize_client_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DesktopGoogleConnectRead(BaseModel):
    authorization_url: str
    expires_at: datetime
    browser_opened: bool


class GmailStatusSuggestion(BaseModel):
    message_id: str
    application_id: int
    company: str
    role: str
    current_status: ApplicationStatus
    suggested_status: ApplicationStatus
    subject: str
    sender: str
    received_at: datetime | None = None
    reason: str


class GmailSyncRead(BaseModel):
    scanned_messages: int
    suggestions: list[GmailStatusSuggestion]


class ReminderSettingsRead(BaseModel):
    deadline_reminders_enabled: bool
    deadline_reminder_days: int
    reminder_timezone: str

    model_config = ConfigDict(from_attributes=True)


class ReminderSettingsUpdate(BaseModel):
    deadline_reminders_enabled: bool | None = None
    deadline_reminder_days: int | None = Field(default=None, ge=1, le=30)
    reminder_timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("reminder_timezone")
    @classmethod
    def reminder_timezone_must_be_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("reminder_timezone must be a valid IANA time zone") from None
        return value


class BetaProgress(BaseModel):
    application_count: int
    email_verified: bool
    ai_import_used: bool
    reminders_enabled: bool
    feedback_submitted: bool
    activated: bool


class BetaFeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BetaFeedbackRead(BaseModel):
    rating: int
    comment: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


class EmailTokenRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)


class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(EmailTokenRequest):
    new_password: str = Field(..., min_length=8, max_length=128)

