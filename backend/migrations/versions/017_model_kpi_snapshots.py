"""model_kpi_snapshots

Revision ID: 017_model_kpi_snapshots
Revises: 016_calibration_artifacts
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

from app.db_types import UuidType


# revision identifiers, used by Alembic.
revision = "017_model_kpi_snapshots"
down_revision = "016_calibration_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_kpi_snapshots",
        sa.Column("id", UuidType(), nullable=False),
        sa.Column("tenant_id", UuidType(), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("total_scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("labeled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("block_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("otp_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("alert_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("fpr", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_kpi_snapshots_tenant_id", "model_kpi_snapshots", ["tenant_id"], unique=False)
    op.create_index("ix_model_kpi_snapshots_model_type", "model_kpi_snapshots", ["model_type"], unique=False)
    op.create_index("ix_model_kpi_snapshots_created_at", "model_kpi_snapshots", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_kpi_snapshots_created_at", table_name="model_kpi_snapshots")
    op.drop_index("ix_model_kpi_snapshots_model_type", table_name="model_kpi_snapshots")
    op.drop_index("ix_model_kpi_snapshots_tenant_id", table_name="model_kpi_snapshots")
    op.drop_table("model_kpi_snapshots")
