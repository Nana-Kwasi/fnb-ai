"""Add merchant_id to transactions for stable merchant identity.

Revision ID: 008
Revises: 007
Create Date: 2026-03-20
"""

# pylint: disable=no-member

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("merchant_id", sa.String(length=255), nullable=True),
    )
    op.create_index("idx_transactions_tenant_merchant_id", "transactions", ["tenant_id", "merchant_id"])


def downgrade() -> None:
    op.drop_index("idx_transactions_tenant_merchant_id", table_name="transactions")
    op.drop_column("transactions", "merchant_id")

