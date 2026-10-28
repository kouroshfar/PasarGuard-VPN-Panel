"""add user site limits

Revision ID: 5a1e7c3d9b20
Revises: c8d2e4f6a1b3
Create Date: 2026-10-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.db.compiles_types import SqliteCompatibleBigInteger

revision = "5a1e7c3d9b20"
down_revision = "c8d2e4f6a1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_site_limits",
        sa.Column("id", SqliteCompatibleBigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", SqliteCompatibleBigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("quota", sa.BigInteger(), nullable=False),
        sa.Column("slow_speed", sa.BigInteger(), nullable=False),
        sa.Column("used_traffic", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("throttled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_site_limits_user_id", "user_site_limits", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_site_limits_user_id", table_name="user_site_limits")
    op.drop_table("user_site_limits")
