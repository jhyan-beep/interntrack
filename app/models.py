from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import Date, DateTime, ForeignKey, Index
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ApplicationStatus(str, Enum):
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    applications: Mapped[list["InternshipApplication"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class InternshipApplication(Base):
    __tablename__ = "internship_applications"
    __table_args__ = (
        Index("ix_internship_applications_user_created", "user_id", "created_at", "id"),
        Index("ix_internship_applications_user_status", "user_id", "status"),
        Index("ix_internship_applications_user_deadline", "user_id", "deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    company: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(120))
    status: Mapped[ApplicationStatus] = mapped_column(
        SQLAlchemyEnum(
            ApplicationStatus,
            values_callable=lambda enum_values: [status.value for status in enum_values],
            native_enum=False,
        ),
        default=ApplicationStatus.SAVED,
        index=True,
    )
    application_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    user: Mapped[User] = relationship(back_populates="applications")

