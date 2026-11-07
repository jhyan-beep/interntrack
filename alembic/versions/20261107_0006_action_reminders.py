"""Add idempotent local next-action reminder deliveries.

Revision ID: 20261107_0006
Revises: 20261107_0005
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261107_0006"
down_revision: str | None = "20261107_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_reminder_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("next_step_date", sa.Date(), nullable=False),
        sa.Column("next_step", sa.String(length=200), nullable=False),
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
            "next_step_date",
            "next_step",
            name="uq_action_reminder_application_date_step",
        ),
    )
    op.create_index(
        "ix_action_reminder_deliveries_user_id",
        "action_reminder_deliveries",
        ["user_id"],
    )
    op.create_index(
        "ix_action_reminder_deliveries_application_id",
        "action_reminder_deliveries",
        ["application_id"],
    )
    op.create_index(
        "ix_action_reminder_deliveries_user_queued",
        "action_reminder_deliveries",
        ["user_id", "queued_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_action_reminder_deliveries_user_queued",
        table_name="action_reminder_deliveries",
    )
    op.drop_index(
        "ix_action_reminder_deliveries_application_id",
        table_name="action_reminder_deliveries",
    )
    op.drop_index(
        "ix_action_reminder_deliveries_user_id",
        table_name="action_reminder_deliveries",
    )
    op.drop_table("action_reminder_deliveries")
