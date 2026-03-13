"""Initial schema: extensions, tenant_banks, customers, transactions, fraud_scores, chat, knowledge_chunks, audit_logs.

Revision ID: 001
Revises:
Create Date: 2026-03-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Standard extensions; these should exist on most Postgres installs.
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # Detect whether pgvector is actually installed on this server before trying CREATE EXTENSION.
    bind = op.get_bind()
    has_vector_extension = bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
    )
    if has_vector_extension:
        op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    op.create_table(
        "tenant_banks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False),
        sa.Column("api_key_prefix", sa.String(8), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("fraud_threshold", sa.Numeric(4, 3), server_default="0.75"),
        sa.Column("care_model", sa.String(50), server_default="phi3"),
        sa.Column("tone_config", sa.dialects.postgresql.JSONB(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_tenant_api_key", "tenant_banks", ["api_key_hash"], unique=True)

    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("phone_hash", sa.String(64), nullable=True),
        sa.Column("risk_score", sa.Numeric(4, 3), server_default="0.0"),
        sa.Column("account_count", sa.Integer(), server_default="1"),
        sa.Column("is_flagged", sa.Boolean(), server_default="false"),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_customers_tenant", "customers", ["tenant_id"])
    op.create_index("idx_customers_risk", "customers", ["tenant_id", "risk_score"])
    op.create_unique_constraint("uq_customers_tenant_external", "customers", ["tenant_id", "external_id"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("external_tx_id", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("merchant_category", sa.String(50), nullable=True),
        sa.Column("merchant_name", sa.String(255), nullable=True),
        sa.Column("location_country", sa.String(2), nullable=True),
        sa.Column("location_city", sa.String(100), nullable=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("ip_address_hash", sa.String(64), nullable=True),
        sa.Column("channel", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), server_default="PENDING"),
        sa.Column("tx_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_txn_customer", "transactions", ["tenant_id", "customer_id"])
    op.create_index("idx_txn_timestamp", "transactions", ["tenant_id", "tx_timestamp"])
    op.create_index("idx_txn_device", "transactions", ["tenant_id", "device_id"])

    op.create_table(
        "fraud_scores",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("lgbm_score", sa.Numeric(6, 5), nullable=False),
        sa.Column("isolation_score", sa.Numeric(6, 5), nullable=True),
        sa.Column("ensemble_score", sa.Numeric(6, 5), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("confidence", sa.String(6), nullable=False),
        sa.Column("shap_values", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("reason_codes", sa.dialects.postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("feature_vector", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_scores_txn", "fraud_scores", ["transaction_id"])
    op.create_index("idx_scores_decision", "fraud_scores", ["tenant_id", "decision"])
    op.create_index("idx_scores_created", "fraud_scores", ["tenant_id", "created_at"])

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default="ACTIVE"),
        sa.Column("intent_history", sa.dialects.postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("escalated", sa.Boolean(), server_default="false"),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), server_default="{}"),
    )
    op.create_index("idx_chat_tenant", "chat_sessions", ["tenant_id", "started_at"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_chat_session", "chat_messages", ["session_id", "created_at"])

    if has_vector_extension:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
            sa.Column("document_name", sa.String(255), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", Vector(384), nullable=False),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.execute(
            "CREATE INDEX idx_kb_embedding ON knowledge_chunks "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
    else:
        # Fallback schema without pgvector: store embeddings as JSON; no ivfflat index
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant_banks.id"), nullable=False),
            sa.Column("document_name", sa.String(255), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", sa.dialects.postgresql.JSONB(), nullable=True),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    op.create_index("idx_kb_tenant", "knowledge_chunks", ["tenant_id", "category"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=True),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("event_data", sa.dialects.postgresql.JSONB(), server_default="{}"),
        sa.Column("ip_address", sa.dialects.postgresql.INET(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_audit_tenant", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("idx_audit_entity", "audit_logs", ["entity_type", "entity_id"])
    op.execute("CREATE RULE no_update_audit AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
    op.execute("CREATE RULE no_delete_audit AS ON DELETE TO audit_logs DO INSTEAD NOTHING")

    op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fraud_scores ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation_customers ON customers FOR ALL TO CURRENT_USER "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_transactions ON transactions FOR ALL TO CURRENT_USER "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_fraud_scores ON fraud_scores FOR ALL TO CURRENT_USER "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_chat_sessions ON chat_sessions FOR ALL TO CURRENT_USER "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )
    op.execute(
        "CREATE POLICY tenant_isolation_knowledge_chunks ON knowledge_chunks FOR ALL TO CURRENT_USER "
        "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation_knowledge_chunks ON knowledge_chunks")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_chat_sessions ON chat_sessions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_fraud_scores ON fraud_scores")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_transactions ON transactions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_customers ON customers")
    op.execute("ALTER TABLE knowledge_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_sessions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE fraud_scores DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE transactions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customers DISABLE ROW LEVEL SECURITY")
    op.execute("DROP RULE IF EXISTS no_delete_audit ON audit_logs")
    op.execute("DROP RULE IF EXISTS no_update_audit ON audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("knowledge_chunks")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("fraud_scores")
    op.drop_table("transactions")
    op.drop_table("customers")
    op.drop_table("tenant_banks")
