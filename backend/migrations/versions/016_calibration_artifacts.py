"""create calibration artifacts table

Revision ID: 016_calibration_artifacts
Revises: 015
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "016_calibration_artifacts"
down_revision = "015"
branch_labels = None
depends_on = None


def _uuid_type():
    bind = op.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def upgrade() -> None:
    op.create_table(
        "calibration_artifacts",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("calibration_version", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("params_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "model_type",
            "model_version",
            "calibration_version",
            name="uq_calibration_tenant_model_modelver_calver",
        ),
    )
    op.create_index(
        "ix_calibration_artifacts_tenant_id",
        "calibration_artifacts",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_calibration_artifacts_tenant_id", table_name="calibration_artifacts")
    op.drop_table("calibration_artifacts")
