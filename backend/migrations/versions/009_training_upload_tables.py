"""Add training upload tables for manual model training.

Revision ID: 009
Revises: 008
Create Date: 2026-03-20
"""
# pylint: disable=no-member

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "training_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=True),
        sa.Column("model_type", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(length=20), server_default="UPLOADED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_training_uploads_model_created", "training_uploads", ["model_type", "created_at"])

    op.create_table(
        "training_upload_rows",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("upload_id", sa.Uuid(), sa.ForeignKey("training_uploads.id"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_training_upload_rows_upload", "training_upload_rows", ["upload_id", "row_index"])


def downgrade() -> None:
    op.drop_index("idx_training_upload_rows_upload", table_name="training_upload_rows")
    op.drop_table("training_upload_rows")
    op.drop_index("idx_training_uploads_model_created", table_name="training_uploads")
    op.drop_table("training_uploads")

