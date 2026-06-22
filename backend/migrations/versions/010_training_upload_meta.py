"""Add meta JSON to training_uploads for eval + retrain lock.

Revision ID: 010
Revises: 009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("training_uploads", sa.Column("meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("training_uploads", "meta")
