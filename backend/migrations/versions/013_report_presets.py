"""Add report presets table.

Revision ID: 013
Revises: 012
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_presets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("decision_filter", sa.String(length=32), nullable=False),
        sa.Column("from_date", sa.String(length=10), nullable=False),
        sa.Column("to_date", sa.String(length=10), nullable=False),
        sa.Column("sort_by", sa.String(length=32), nullable=False),
        sa.Column("sort_dir", sa.String(length=8), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_report_presets_tenant_name"),
    )
    op.create_index(op.f("ix_report_presets_tenant_id"), "report_presets", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_report_presets_tenant_id"), table_name="report_presets")
    op.drop_table("report_presets")
