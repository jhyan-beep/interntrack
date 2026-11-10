"""Create users and user-owned internship applications.

Revision ID: 20261024_0001
Revises:
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261024_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "internship_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "saved",
                "applied",
                "interview",
                "offer",
                "rejected",
                "withdrawn",
                name="applicationstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("application_date", sa.Date(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('saved', 'applied', 'interview', 'offer', 'rejected', 'withdrawn')",
            name="ck_internship_applications_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internship_applications_id", "internship_applications", ["id"])
    op.create_index("ix_internship_applications_company", "internship_applications", ["company"])
    op.create_index(
        "ix_internship_applications_application_date",
        "internship_applications",
        ["application_date"],
    )
    op.create_index("ix_internship_applications_deadline", "internship_applications", ["deadline"])
    op.create_index("ix_internship_applications_status", "internship_applications", ["status"])
    op.create_index("ix_internship_applications_user_id", "internship_applications", ["user_id"])
    op.create_index(
        "ix_internship_applications_user_created",
        "internship_applications",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_internship_applications_user_status",
        "internship_applications",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_internship_applications_user_deadline",
        "internship_applications",
        ["user_id", "deadline"],
    )


def downgrade() -> None:
    op.drop_table("internship_applications")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
