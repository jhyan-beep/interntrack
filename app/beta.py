from datetime import date, timedelta
from typing import Literal

from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BetaFeedback, InternshipApplication, ProductEvent, User
from app.schemas import BetaFeedbackCreate


ProductEventName = Literal[
    "account_created",
    "dashboard_viewed",
    "application_created",
    "ai_draft_created",
    "reminders_enabled",
    "feedback_submitted",
]


def record_product_event(
    db: Session,
    user_id: int,
    event_name: ProductEventName,
) -> None:
    """Record at most one event of each type per user and calendar day."""
    try:
        with db.begin_nested():
            db.add(ProductEvent(user_id=user_id, event_name=event_name))
            db.flush()
    except IntegrityError:
        # A same-day duplicate is expected when users refresh or retry a request.
        pass


def get_beta_progress(db: Session, user: User) -> dict:
    application_count = (
        db.scalar(
            select(func.count(InternshipApplication.id)).where(
                InternshipApplication.user_id == user.id
            )
        )
        or 0
    )
    ai_import_used = db.scalar(
        select(ProductEvent.id).where(
            ProductEvent.user_id == user.id,
            ProductEvent.event_name == "ai_draft_created",
        )
    ) is not None
    feedback_submitted = db.scalar(
        select(BetaFeedback.id).where(BetaFeedback.user_id == user.id)
    ) is not None
    return {
        "application_count": application_count,
        "email_verified": user.email_verified,
        "ai_import_used": ai_import_used,
        "reminders_enabled": user.deadline_reminders_enabled,
        "feedback_submitted": feedback_submitted,
        "activated": application_count >= 3,
    }


def save_beta_feedback(
    db: Session,
    user_id: int,
    feedback_in: BetaFeedbackCreate,
) -> BetaFeedback:
    feedback = db.scalar(select(BetaFeedback).where(BetaFeedback.user_id == user_id))
    if feedback is None:
        feedback = BetaFeedback(user_id=user_id, **feedback_in.model_dump())
    else:
        feedback.rating = feedback_in.rating
        feedback.comment = feedback_in.comment
    db.add(feedback)
    record_product_event(db, user_id, "feedback_submitted")
    db.commit()
    db.refresh(feedback)
    return feedback


def build_beta_metrics(db: Session, today: date | None = None) -> dict[str, int | float]:
    current_date = today or date.today()
    active_since = current_date - timedelta(days=6)
    activated_users = (
        select(InternshipApplication.user_id)
        .group_by(InternshipApplication.user_id)
        .having(func.count(InternshipApplication.id) >= 3)
        .subquery()
    )

    total_users = db.scalar(select(func.count(User.id))) or 0
    activated_count = db.scalar(select(func.count()).select_from(activated_users)) or 0
    return {
        "total_users": total_users,
        "verified_users": db.scalar(
            select(func.count(User.id)).where(User.email_verified_at.is_not(None))
        )
        or 0,
        "activated_users": activated_count,
        "activation_rate": round(activated_count / total_users, 3) if total_users else 0.0,
        "active_users_7d": db.scalar(
            select(func.count(distinct(ProductEvent.user_id))).where(
                ProductEvent.event_name == "dashboard_viewed",
                ProductEvent.event_date >= active_since,
            )
        )
        or 0,
        "ai_import_users": db.scalar(
            select(func.count(distinct(ProductEvent.user_id))).where(
                ProductEvent.event_name == "ai_draft_created"
            )
        )
        or 0,
        "reminder_users": db.scalar(
            select(func.count(User.id)).where(User.deadline_reminders_enabled.is_(True))
        )
        or 0,
        "feedback_responses": db.scalar(select(func.count(BetaFeedback.id))) or 0,
        "applications": db.scalar(select(func.count(InternshipApplication.id))) or 0,
    }
