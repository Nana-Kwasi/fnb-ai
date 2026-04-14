"""create job_runs table

Revision ID: 019_job_runs
Revises: 018_model_kpi_auc
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa

# pylint: disable=no-member

revision = "019_job_runs"
down_revision = "018_model_kpi_auc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("trigger_source", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_job_runs_job_name", "job_runs", ["job_name"])
    op.create_index("ix_job_runs_request_id", "job_runs", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_request_id", table_name="job_runs")
    op.drop_index("ix_job_runs_job_name", table_name="job_runs")
    op.drop_table("job_runs")

