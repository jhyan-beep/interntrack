import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_settings
from app.models import EmailToken, EmailTokenPurpose, User


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_email_token(
    db: Session,
    user: User,
    purpose: EmailTokenPurpose,
) -> str:
    now = datetime.now(timezone.utc)
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    settings = get_settings()
    lifetime = (
        timedelta(hours=settings.email_verification_expire_hours)
        if purpose == EmailTokenPurpose.VERIFY_EMAIL
        else timedelta(minutes=settings.password_reset_expire_minutes)
    )
    raw_token = secrets.token_urlsafe(32)
    db.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_token_hash(raw_token),
            expires_at=now + lifetime,
        )
    )
    db.flush()
    return raw_token


def consume_email_token(
    db: Session,
    raw_token: str,
    purpose: EmailTokenPurpose,
) -> EmailToken | None:
    now = datetime.now(timezone.utc)
    token = db.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == _token_hash(raw_token),
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
            EmailToken.expires_at > now,
        )
    )
    if token is None:
        return None
    token.used_at = now
    db.add(token)
    db.flush()
    return token


def invalidate_user_tokens(
    db: Session,
    user_id: int,
    purpose: EmailTokenPurpose,
) -> None:
    db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )

