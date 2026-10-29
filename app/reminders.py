import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.email_delivery import OutgoingEmail, enqueue_email
from app.models import (
    ApplicationStatus,
    DeadlineReminderDelivery,
    InternshipApplication,
    User,
)


ACTIVE_REMINDER_STATUSES = {
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
}


def _subject_text(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def deadline_reminder_email(
    application: InternshipApplication,
    days_remaining: int,
) -> OutgoingEmail:
    day_label = "today" if days_remaining == 0 else (
        "tomorrow" if days_remaining == 1 else f"in {days_remaining} days"
    )
    company = _subject_text(application.company)
    role = _subject_text(application.role)
    safe_company = html.escape(company)
    safe_role = html.escape(role)
    safe_deadline = html.escape(application.deadline.isoformat())
    posting_text = ""
    posting_html = ""
    if application.source_url:
        safe_url = html.escape(application.source_url, quote=True)
        posting_text = f"\nJob posting: {application.source_url}"
        posting_html = f'<p><a href="{safe_url}">Open job posting</a></p>'

    return OutgoingEmail(
        to_email=application.user.email,
        subject=f"InternTrack deadline {day_label}: {company} — {role}"[:200],
        text_body=(
            f"Your {role} application at {company} has a deadline {day_label} "
            f"({application.deadline.isoformat()}).{posting_text}\n\n"
            "Open InternTrack to review your application. You can change reminder settings "
            "from your account."
        ),
        html_body=(
            "<h1>Application deadline reminder</h1>"
            f"<p>Your <strong>{safe_role}</strong> application at "
            f"<strong>{safe_company}</strong> has a deadline {html.escape(day_label)}.</p>"
            f"<p>Deadline: <strong>{safe_deadline}</strong></p>"
            f"{posting_html}"
            "<p>Open InternTrack to review your application. You can change reminder "
            "settings from your account.</p>"
        ),
    )


def enqueue_due_deadline_reminders(now: datetime | None = None) -> int:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    utc_date = current_time.astimezone(timezone.utc).date()
    earliest_date = utc_date - timedelta(days=1)
    latest_date = utc_date + timedelta(days=31)
    queued = 0

    with SessionLocal() as db:
        applications = list(
            db.scalars(
                select(InternshipApplication)
                .options(joinedload(InternshipApplication.user))
                .join(User)
                .where(
                    User.email_verified_at.is_not(None),
                    User.deadline_reminders_enabled.is_(True),
                    InternshipApplication.status.in_(ACTIVE_REMINDER_STATUSES),
                    InternshipApplication.deadline.is_not(None),
                    InternshipApplication.deadline >= earliest_date,
                    InternshipApplication.deadline <= latest_date,
                )
                .order_by(InternshipApplication.deadline.asc(), InternshipApplication.id.asc())
                .limit(1_000)
            ).all()
        )

        for application in applications:
            assert application.deadline is not None
            local_date = current_time.astimezone(
                ZoneInfo(application.user.reminder_timezone)
            ).date()
            days_remaining = (application.deadline - local_date).days
            if days_remaining < 0:
                continue
            if days_remaining > application.user.deadline_reminder_days:
                continue

            delivery = DeadlineReminderDelivery(
                user_id=application.user_id,
                application_id=application.id,
                deadline=application.deadline,
                days_before=days_remaining,
            )
            try:
                with db.begin_nested():
                    db.add(delivery)
                    db.flush()
            except IntegrityError:
                continue

            enqueue_email(
                db,
                deadline_reminder_email(application, days_remaining),
                user_id=application.user_id,
            )
            queued += 1

        db.commit()
    return queued
