"""Add application next steps and action dates.

Revision ID: 20261107_0005
Revises: 20261029_0004
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261107_0005"
down_revision: str | None = "20261029_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("internship_applications") as batch_op:
        batch_op.add_column(sa.Column("next_step", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("next_step_date", sa.Date(), nullable=True))
        batch_op.create_index(
            "ix_internship_applications_next_step_date",
            ["next_step_date"],
        )
        batch_op.create_index(
            "ix_internship_applications_user_next_step_date",
            ["user_id", "next_step_date"],
        )


def downgrade() -> None:
    with op.batch_alter_table("internship_applications") as batch_op:
        batch_op.drop_index("ix_internship_applications_user_next_step_date")
        batch_op.drop_index("ix_internship_applications_next_step_date")
        batch_op.drop_column("next_step_date")
        batch_op.drop_column("next_step")
