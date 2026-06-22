"""Add Cloudinary URLs/public_ids to report_jobs.

Revision ID: 022_report_job_cloudinary_urls
Revises: 021_tenant_extended
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "022_report_job_cloudinary_urls"
down_revision = "021_tenant_extended"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_jobs", sa.Column("artifact_pdf_url", sa.Text(), nullable=True))
    op.add_column("report_jobs", sa.Column("artifact_xlsx_url", sa.Text(), nullable=True))
    op.add_column("report_jobs", sa.Column("artifact_pdf_public_id", sa.Text(), nullable=True))
    op.add_column("report_jobs", sa.Column("artifact_xlsx_public_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_jobs", "artifact_xlsx_public_id")
    op.drop_column("report_jobs", "artifact_pdf_public_id")
    op.drop_column("report_jobs", "artifact_xlsx_url")
    op.drop_column("report_jobs", "artifact_pdf_url")

