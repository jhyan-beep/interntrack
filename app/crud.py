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


def create_application(db: Session, application_in: ApplicationCreate) -> InternshipApplication:
    application = InternshipApplication(**application_in.model_dump())
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def get_application(db: Session, application_id: int) -> InternshipApplication | None:
    return db.get(InternshipApplication, application_id)


def list_applications(
    db: Session,
    status: ApplicationStatus | None = None,
    company: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[InternshipApplication]:
    statement = select(InternshipApplication)

    if status is not None:
        statement = statement.where(InternshipApplication.status == status)

    if company:
        statement = statement.where(InternshipApplication.company.ilike(f"%{company}%"))

    sort_column = SORT_COLUMNS.get(sort_by, InternshipApplication.created_at)
    order_by = asc(sort_column) if sort_order == "asc" else desc(sort_column)

    statement = statement.order_by(order_by, InternshipApplication.id.asc())
    return list(db.scalars(statement).all())


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


def get_application_stats(db: Session) -> dict:
    total = db.scalar(select(func.count(InternshipApplication.id))) or 0

    status_rows = db.execute(
        select(InternshipApplication.status, func.count(InternshipApplication.id)).group_by(
            InternshipApplication.status
        )
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
                InternshipApplication.status.in_(active_statuses)
            )
        )
        or 0
    )

    upcoming_deadlines = list(
        db.scalars(
            select(InternshipApplication)
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
