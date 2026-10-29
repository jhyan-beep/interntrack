"""Add opt-in deadline reminders and idempotent delivery records.

Revision ID: 20261029_0003
Revises: 20261028_0002
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261029_0003"
down_revision: str | None = "20261028_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "deadline_reminders_enabled",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "deadline_reminder_days",
                sa.Integer(),
                server_default=sa.text("3"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "reminder_timezone",
                sa.String(length=64),
                server_default=sa.text("'UTC'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_users_deadline_reminder_days",
            "deadline_reminder_days BETWEEN 1 AND 30",
        )

    with op.batch_alter_table("email_outbox") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_email_outbox_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_email_outbox_user_id", ["user_id"])

    op.create_table(
        "deadline_reminder_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["internship_applications.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "deadline",
            name="uq_deadline_reminder_application_deadline",
        ),
    )
    op.create_index(
        "ix_deadline_reminder_deliveries_user_id",
        "deadline_reminder_deliveries",
        ["user_id"],
    )
    op.create_index(
        "ix_deadline_reminder_deliveries_application_id",
        "deadline_reminder_deliveries",
        ["application_id"],
    )
    op.create_index(
        "ix_deadline_reminder_deliveries_user_queued",
        "deadline_reminder_deliveries",
        ["user_id", "queued_at"],
    )


def downgrade() -> None:
    op.drop_table("deadline_reminder_deliveries")
    with op.batch_alter_table("email_outbox") as batch_op:
        batch_op.drop_index("ix_email_outbox_user_id")
        batch_op.drop_constraint("fk_email_outbox_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_deadline_reminder_days", type_="check")
        batch_op.drop_column("reminder_timezone")
        batch_op.drop_column("deadline_reminder_days")
        batch_op.drop_column("deadline_reminders_enabled")
