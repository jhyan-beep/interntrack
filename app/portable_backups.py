from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import DeadlineReminderDelivery, InternshipApplication, User
from app.schemas import (
    PortableBackup,
    PortableBackupApplication,
    PortableBackupPreferences,
    PortableBackupPreview,
    PortableBackupRestoreResult,
)


def _application_key(application: InternshipApplication | PortableBackupApplication) -> tuple:
    return (
        application.company.strip().casefold(),
        application.role.strip().casefold(),
        application.application_date,
    )


def create_portable_backup(db: Session, user: User) -> PortableBackup:
    applications = list(
        db.scalars(
            select(InternshipApplication)
            .where(InternshipApplication.user_id == user.id)
            .order_by(InternshipApplication.created_at.asc(), InternshipApplication.id.asc())
        )
    )
    return PortableBackup(
        kind="interntrack-portable-backup",
        schema_version=1,
        exported_at=datetime.now(timezone.utc),
        applications=[PortableBackupApplication.model_validate(item, from_attributes=True) for item in applications],
        preferences=PortableBackupPreferences(
            deadline_reminders_enabled=user.deadline_reminders_enabled,
            deadline_reminder_days=user.deadline_reminder_days,
            reminder_timezone=user.reminder_timezone,
        ),
    )


def preview_portable_backup(
    db: Session,
    user: User,
    backup: PortableBackup,
) -> PortableBackupPreview:
    existing_keys = {
        _application_key(application)
        for application in db.scalars(
            select(InternshipApplication).where(InternshipApplication.user_id == user.id)
        )
    }
    seen_keys = set(existing_keys)
    duplicate_count = 0
    import_count = 0
    for application in backup.applications:
        key = _application_key(application)
        if key in seen_keys:
            duplicate_count += 1
            continue
        seen_keys.add(key)
        import_count += 1
    return PortableBackupPreview(
        current_applications=len(existing_keys),
        backup_applications=len(backup.applications),
        duplicate_applications=duplicate_count,
        merge_import_count=import_count,
    )


def restore_portable_backup(
    db: Session,
    user: User,
    backup: PortableBackup,
    mode: str,
) -> PortableBackupRestoreResult:
    preview = preview_portable_backup(db, user, backup)
    removed_count = 0
    skipped_count = preview.duplicate_applications if mode == "merge" else 0
    existing_keys: set[tuple] = set()

    if mode == "replace":
        backup_keys: set[tuple] = set()
        for application in backup.applications:
            key = _application_key(application)
            if key in backup_keys:
                skipped_count += 1
            backup_keys.add(key)
        removed_count = int(
            db.scalar(
                select(func.count(InternshipApplication.id)).where(
                    InternshipApplication.user_id == user.id
                )
            )
            or 0
        )
        db.execute(
            delete(DeadlineReminderDelivery).where(
                DeadlineReminderDelivery.user_id == user.id
            )
        )
        db.execute(
            delete(InternshipApplication).where(InternshipApplication.user_id == user.id)
        )
    else:
        existing_keys = {
            _application_key(application)
            for application in db.scalars(
                select(InternshipApplication).where(InternshipApplication.user_id == user.id)
            )
        }

    imported_count = 0
    for application in backup.applications:
        key = _application_key(application)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        db.add(
            InternshipApplication(
                user_id=user.id,
                **application.model_dump(),
            )
        )
        imported_count += 1

    user.deadline_reminders_enabled = backup.preferences.deadline_reminders_enabled
    user.deadline_reminder_days = backup.preferences.deadline_reminder_days
    user.reminder_timezone = backup.preferences.reminder_timezone
    db.add(user)
    db.commit()

    return PortableBackupRestoreResult(
        mode=mode,
        imported_applications=imported_count,
        skipped_duplicates=skipped_count,
        removed_applications=removed_count,
        preferences_restored=True,
    )
