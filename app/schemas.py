from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import ApplicationStatus


class ApplicationBase(BaseModel):
    company: str = Field(..., min_length=1, max_length=120)
    role: str = Field(..., min_length=1, max_length=120)
    status: ApplicationStatus = ApplicationStatus.SAVED
    application_date: date = Field(default_factory=date.today)
    deadline: date | None = None
    location: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    notes: str | None = None

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
    notes: str | None = None

    @model_validator(mode="after")
    def deadline_cannot_be_before_application_date(self) -> "ApplicationUpdate":
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
