"""Add model registry, tenant mappers, and inference trace.

Revision ID: 015
Revises: 014
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("artifact_uri", sa.String(length=1024), nullable=False),
        sa.Column("feature_contract_version", sa.String(length=64), nullable=False),
        sa.Column("mapper_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_type", "tenant_id", "version", name="uq_model_registry_model_tenant_version"),
    )
    op.create_index(op.f("ix_model_registry_tenant_id"), "model_registry", ["tenant_id"], unique=False)

    op.create_table(
        "tenant_mappers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("mapper_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "model_type", "mapper_version", name="uq_tenant_mappers_tenant_model_mapper"),
    )
    op.create_index(op.f("ix_tenant_mappers_tenant_id"), "tenant_mappers", ["tenant_id"], unique=False)

    op.create_table(
        "inference_trace",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("mapper_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column("trace_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant_banks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_inference_trace_tenant_id"), "inference_trace", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_inference_trace_tenant_id"), table_name="inference_trace")
    op.drop_table("inference_trace")
    op.drop_index(op.f("ix_tenant_mappers_tenant_id"), table_name="tenant_mappers")
    op.drop_table("tenant_mappers")
    op.drop_index(op.f("ix_model_registry_tenant_id"), table_name="model_registry")
    op.drop_table("model_registry")
