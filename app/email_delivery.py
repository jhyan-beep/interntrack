import html
import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, Settings, get_settings
from app.models import EmailOutbox, EmailOutboxStatus


logger = logging.getLogger("interntrack.email")
MAX_EMAIL_ATTEMPTS = 5


@dataclass(frozen=True)
class OutgoingEmail:
    to_email: str
    subject: str
    text_body: str
    html_body: str


def _action_url(parameter: str, token: str) -> str:
    base_url = get_settings().app_base_url.rstrip("/")
    return f"{base_url}/?{parameter}={quote(token)}"


def verification_email(to_email: str, token: str) -> OutgoingEmail:
    url = _action_url("verify_token", token)
    safe_url = html.escape(url, quote=True)
    return OutgoingEmail(
        to_email=to_email,
        subject="Verify your InternTrack email",
        text_body=(
            "Welcome to InternTrack. Verify your email by opening this link:\n\n"
            f"{url}\n\nThis link expires soon. If you did not create this account, ignore this email."
        ),
        html_body=(
            "<h1>Verify your InternTrack email</h1>"
            "<p>Confirm your email so account recovery and reminders reach you.</p>"
            f'<p><a href="{safe_url}">Verify email</a></p>'
            "<p>If you did not create this account, ignore this email.</p>"
        ),
    )


def password_reset_email(to_email: str, token: str) -> OutgoingEmail:
    url = _action_url("reset_token", token)
    safe_url = html.escape(url, quote=True)
    return OutgoingEmail(
        to_email=to_email,
        subject="Reset your InternTrack password",
        text_body=(
            "Reset your InternTrack password by opening this link:\n\n"
            f"{url}\n\nIf you did not request a reset, ignore this email."
        ),
        html_body=(
            "<h1>Reset your InternTrack password</h1>"
            f'<p><a href="{safe_url}">Choose a new password</a></p>'
            "<p>If you did not request a reset, ignore this email.</p>"
        ),
    )


def enqueue_email(
    db: Session,
    email: OutgoingEmail,
    *,
    user_id: int | None = None,
) -> EmailOutbox:
    message = EmailOutbox(
        user_id=user_id,
        to_email=email.to_email,
        subject=email.subject,
        text_body=email.text_body,
        html_body=email.html_body,
    )
    db.add(message)
    db.flush()
    return message


def _send_message(message: EmailOutbox, settings: Settings) -> None:
    if settings.email_delivery_mode == "console":
        logger.warning(
            "Development email to=%s subject=%s\n%s",
            message.to_email,
            message.subject,
            message.text_body,
        )
        return

    assert settings.smtp_host is not None
    email = EmailMessage()
    email["From"] = settings.email_from
    email["To"] = message.to_email
    email["Subject"] = message.subject
    email.set_content(message.text_body)
    email.add_alternative(message.html_body, subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            password = settings.smtp_password.get_secret_value() if settings.smtp_password else ""
            smtp.login(settings.smtp_username, password)
        smtp.send_message(email)


def process_outbox_batch(batch_size: int = 20) -> int:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        messages = list(
            db.scalars(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == EmailOutboxStatus.PENDING,
                    EmailOutbox.available_at <= now,
                )
                .order_by(EmailOutbox.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for message in messages:
            try:
                _send_message(message, settings)
            except Exception as exc:  # The worker records provider/network failures for retry.
                message.attempts += 1
                message.last_error = str(exc)[:1_000]
                if message.attempts >= MAX_EMAIL_ATTEMPTS:
                    message.status = EmailOutboxStatus.FAILED
                else:
                    delay_seconds = min(60 * (2 ** message.attempts), 3_600)
                    message.available_at = now + timedelta(seconds=delay_seconds)
                logger.exception("Email delivery failed message_id=%s", message.id)
            else:
                message.status = EmailOutboxStatus.SENT
                message.sent_at = now
                message.last_error = None
                message.text_body = ""
                message.html_body = ""
            db.add(message)
        db.commit()
        return len(messages)
