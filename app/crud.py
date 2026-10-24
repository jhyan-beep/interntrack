from datetime import date

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.models import ApplicationStatus, InternshipApplication
from app.schemas import ApplicationCreate, ApplicationUpdate


SORT_COLUMNS = {
    "deadline": InternshipApplication.deadline,
    "application_date": InternshipApplication.application_date,
    "created_at": InternshipApplication.created_at,
    "company": InternshipApplication.company,
}


def create_application(
    db: Session,
    application_in: ApplicationCreate,
    user_id: int,
) -> InternshipApplication:
    application = InternshipApplication(**application_in.model_dump(), user_id=user_id)
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def get_application(
    db: Session,
    application_id: int,
    user_id: int,
) -> InternshipApplication | None:
    return db.scalar(
        select(InternshipApplication).where(
            InternshipApplication.id == application_id,
            InternshipApplication.user_id == user_id,
        )
    )


def list_applications(
    db: Session,
    user_id: int,
    status: ApplicationStatus | None = None,
    company: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[InternshipApplication], int]:
    filters = [InternshipApplication.user_id == user_id]

    if status is not None:
        filters.append(InternshipApplication.status == status)

    if company:
        filters.append(InternshipApplication.company.ilike(f"%{company}%"))

    total = db.scalar(select(func.count(InternshipApplication.id)).where(*filters)) or 0
    statement = select(InternshipApplication).where(*filters)

    sort_column = SORT_COLUMNS.get(sort_by, InternshipApplication.created_at)
    order_by = asc(sort_column) if sort_order == "asc" else desc(sort_column)

    statement = (
        statement.order_by(order_by, InternshipApplication.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(statement).all()), total


def update_application(
    db: Session,
    application: InternshipApplication,
    application_in: ApplicationUpdate,
) -> InternshipApplication:
    update_data = application_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(application, field, value)

    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def delete_application(db: Session, application: InternshipApplication) -> None:
    db.delete(application)
    db.commit()


def get_application_stats(db: Session, user_id: int) -> dict:
    total = (
        db.scalar(
            select(func.count(InternshipApplication.id)).where(
                InternshipApplication.user_id == user_id
            )
        )
        or 0
    )

    status_rows = db.execute(
        select(InternshipApplication.status, func.count(InternshipApplication.id))
        .where(InternshipApplication.user_id == user_id)
        .group_by(InternshipApplication.status)
    ).all()
    by_status = {status.value: count for status, count in status_rows}

    active_statuses = [
        ApplicationStatus.SAVED,
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
    ]
    active_count = (
        db.scalar(
            select(func.count(InternshipApplication.id)).where(
                InternshipApplication.user_id == user_id,
                InternshipApplication.status.in_(active_statuses)
            )
        )
        or 0
    )

    upcoming_deadlines = list(
        db.scalars(
            select(InternshipApplication)
            .where(InternshipApplication.user_id == user_id)
            .where(InternshipApplication.deadline.is_not(None))
            .where(InternshipApplication.deadline >= date.today())
            .order_by(InternshipApplication.deadline.asc())
            .limit(5)
        ).all()
    )

    return {
        "total_applications": total,
        "active_applications": active_count,
        "by_status": by_status,
        "upcoming_deadlines": upcoming_deadlines,
    }

