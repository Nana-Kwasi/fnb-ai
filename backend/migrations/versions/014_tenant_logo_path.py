"""Add tenant logo path column.

Revision ID: 014
Revises: 013
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenant_banks", sa.Column("logo_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_banks", "logo_path")
