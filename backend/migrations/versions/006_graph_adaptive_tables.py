"""Graph and adaptive risk tables: graph_nodes, graph_edges, graph_risk_metrics, adaptive_risk_events.

Revision ID: 006
Revises: 005
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float(), server_default="0.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_graph_nodes_tenant", "graph_nodes", ["tenant_id"])
    op.create_unique_constraint("uq_graph_nodes_tenant_node", "graph_nodes", ["tenant_id", "node_id"])

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("edge_type", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_graph_edges_tenant", "graph_edges", ["tenant_id"])
    op.create_index("idx_graph_edges_source", "graph_edges", ["tenant_id", "source_id"])

    op.create_table(
        "graph_risk_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("fraud_cluster_size", sa.Integer(), server_default="0"),
        sa.Column("max_component_size", sa.Integer(), server_default="0"),
        sa.Column("device_cluster_growth", sa.Float(), server_default="0.0"),
        sa.Column("graph_cluster_growth", sa.Float(), server_default="0.0"),
    )
    op.create_index("idx_graph_risk_metrics_tenant", "graph_risk_metrics", ["tenant_id"])
    op.create_index("idx_graph_risk_metrics_computed", "graph_risk_metrics", ["tenant_id", "computed_at"])

    op.create_table(
        "adaptive_risk_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("system_state", sa.String(32), nullable=False),
        sa.Column("block_threshold", sa.Float(), nullable=False),
        sa.Column("otp_threshold", sa.Float(), nullable=False),
        sa.Column("fraud_rate_1h", sa.Float(), server_default="0.0"),
        sa.Column("fraud_rate_24h", sa.Float(), server_default="0.0"),
    )
    op.create_index("idx_adaptive_risk_events_tenant", "adaptive_risk_events", ["tenant_id"])
    op.create_index("idx_adaptive_risk_events_detected", "adaptive_risk_events", ["tenant_id", "detected_at"])


def downgrade() -> None:
    op.drop_table("adaptive_risk_events")
    op.drop_table("graph_risk_metrics")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
