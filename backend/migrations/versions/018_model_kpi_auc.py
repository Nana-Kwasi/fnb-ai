"""add auc to model_kpi_snapshots

Revision ID: 018_model_kpi_auc
Revises: 017_model_kpi_snapshots
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa


revision = "018_model_kpi_auc"
down_revision = "017_model_kpi_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_kpi_snapshots", sa.Column("auc", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_kpi_snapshots", "auc")
