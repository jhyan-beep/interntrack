from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, UniqueConstraint
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


class EmailTokenPurpose(str, Enum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class EmailOutboxStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "deadline_reminder_days BETWEEN 1 AND 30",
            name="ck_users_deadline_reminder_days",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    session_version: Mapped[int] = mapped_column(default=1, server_default="1")
    deadline_reminders_enabled: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
    )
    deadline_reminder_days: Mapped[int] = mapped_column(default=3, server_default="3")
    reminder_timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        server_default="UTC",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    applications: Mapped[list["InternshipApplication"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    email_tokens: Mapped[list["EmailToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    email_messages: Mapped[list["EmailOutbox"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    deadline_reminder_deliveries: Mapped[list["DeadlineReminderDelivery"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    product_events: Mapped[list["ProductEvent"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    beta_feedback: Mapped["BetaFeedback | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class EmailToken(Base):
    __tablename__ = "email_tokens"
    __table_args__ = (
        Index("ix_email_tokens_user_purpose", "user_id", "purpose"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    purpose: Mapped[EmailTokenPurpose] = mapped_column(
        SQLAlchemyEnum(
            EmailTokenPurpose,
            values_callable=lambda enum_values: [purpose.value for purpose in enum_values],
            native_enum=False,
        ),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="email_tokens")


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        Index("ix_email_outbox_status_available", "status", "available_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(200))
    text_body: Mapped[str] = mapped_column(Text)
    html_body: Mapped[str] = mapped_column(Text)
    status: Mapped[EmailOutboxStatus] = mapped_column(
        SQLAlchemyEnum(
            EmailOutboxStatus,
            values_callable=lambda enum_values: [status.value for status in enum_values],
            native_enum=False,
        ),
        default=EmailOutboxStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1_000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    user: Mapped[User | None] = relationship(back_populates="email_messages")


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
    deadline_reminder_deliveries: Mapped[list["DeadlineReminderDelivery"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
    )


class DeadlineReminderDelivery(Base):
    __tablename__ = "deadline_reminder_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "deadline",
            name="uq_deadline_reminder_application_deadline",
        ),
        Index("ix_deadline_reminder_deliveries_user_queued", "user_id", "queued_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("internship_applications.id", ondelete="CASCADE"),
        index=True,
    )
    deadline: Mapped[date] = mapped_column(Date)
    days_before: Mapped[int]
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="deadline_reminder_deliveries")
    application: Mapped[InternshipApplication] = relationship(
        back_populates="deadline_reminder_deliveries"
    )


class ProductEvent(Base):
    __tablename__ = "product_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_name",
            "event_date",
            name="uq_product_events_user_name_date",
        ),
        Index("ix_product_events_name_date", "event_name", "event_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(50))
    event_date: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="product_events")


class BetaFeedback(Base):
    __tablename__ = "beta_feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_beta_feedback_rating"),
        UniqueConstraint("user_id", name="uq_beta_feedback_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    rating: Mapped[int]
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    user: Mapped[User] = relationship(back_populates="beta_feedback")

