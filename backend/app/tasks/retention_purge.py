"""
Automated data retention purge task.

Reads each tenant's TenantCompliancePolicy retention settings and deletes
rows older than the configured retention window from:
  - transactions + fraud_scores + fraud_alerts + fraud_outcomes
  - chat_sessions + chat_messages
  - inference_trace
  - audit_logs

Schedule: once daily (registered in main.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.chat import ChatMessage, ChatSession
from app.models.fraud import FraudScore
from app.models.fraud_extra import FraudAlert, FraudOutcome, TransactionFingerprint
from app.models.model_registry import InferenceTrace
from app.models.tenant_extended import TenantCompliancePolicy
from app.models.transaction import Transaction
from app.observability import get_logger as _obs_logger

_logger = _obs_logger(__name__)


async def _purge_tenant(db: AsyncSession, policy: TenantCompliancePolicy, now: datetime) -> Dict[str, int]:
    deleted: Dict[str, int] = {}
    tid = policy.tenant_id

    # ── Transactions + related tables ─────────────────────────────────────────
    if policy.transaction_retention_days and policy.transaction_retention_days > 0:
        cutoff = now - timedelta(days=policy.transaction_retention_days)

        old_tx_q = await db.execute(
            select(Transaction.id).where(
                Transaction.tenant_id == tid,
                Transaction.created_at < cutoff,
            ).limit(5000)
        )
        old_tx_ids = [r[0] for r in old_tx_q.all()]

        if old_tx_ids:
            r1 = await db.execute(delete(FraudScore).where(FraudScore.transaction_id.in_(old_tx_ids)))
            r2 = await db.execute(delete(FraudAlert).where(FraudAlert.transaction_id.in_(old_tx_ids)))
            r3 = await db.execute(delete(FraudOutcome).where(FraudOutcome.transaction_id.in_(old_tx_ids)))
            r4 = await db.execute(delete(TransactionFingerprint).where(TransactionFingerprint.transaction_id.in_(old_tx_ids)))
            r5 = await db.execute(delete(Transaction).where(Transaction.id.in_(old_tx_ids)))
            deleted["transactions"] = r5.rowcount
            deleted["fraud_scores"] = r1.rowcount
            deleted["fraud_alerts"] = r2.rowcount
            deleted["fraud_outcomes"] = r3.rowcount
            deleted["transaction_fingerprints"] = r4.rowcount

    # ── Chat sessions ─────────────────────────────────────────────────────────
    if policy.chat_retention_days and policy.chat_retention_days > 0:
        cutoff = now - timedelta(days=policy.chat_retention_days)
        old_sess_q = await db.execute(
            select(ChatSession.id).where(
                ChatSession.tenant_id == tid,
                ChatSession.started_at < cutoff,
            ).limit(5000)
        )
        old_sess_ids = [r[0] for r in old_sess_q.all()]
        if old_sess_ids:
            r6 = await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(old_sess_ids)))
            r7 = await db.execute(delete(ChatSession).where(ChatSession.id.in_(old_sess_ids)))
            deleted["chat_sessions"] = r7.rowcount
            deleted["chat_messages"] = r6.rowcount

    # ── Audit logs ────────────────────────────────────────────────────────────
    if policy.audit_log_retention_days and policy.audit_log_retention_days > 0:
        cutoff = now - timedelta(days=policy.audit_log_retention_days)
        r8 = await db.execute(
            delete(AuditLog).where(
                AuditLog.tenant_id == tid,
                AuditLog.created_at < cutoff,
            )
        )
        deleted["audit_logs"] = r8.rowcount

    # ── Inference traces ──────────────────────────────────────────────────────
    if policy.fraud_score_retention_days and policy.fraud_score_retention_days > 0:
        cutoff = now - timedelta(days=policy.fraud_score_retention_days)
        r9 = await db.execute(
            delete(InferenceTrace).where(
                InferenceTrace.tenant_id == tid,
                InferenceTrace.created_at < cutoff,
            )
        )
        deleted["inference_traces"] = r9.rowcount

    return deleted


async def run_retention_purge() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    results: Dict[str, Any] = {}

    async with AsyncSessionLocal() as db:
        policies = (await db.execute(select(TenantCompliancePolicy))).scalars().all()
        for policy in policies:
            try:
                deleted = await _purge_tenant(db, policy, now)
                await db.commit()
                if any(v > 0 for v in deleted.values()):
                    results[str(policy.tenant_id)] = deleted
                    _logger.info(
                        "retention_purge_completed",
                        tenant_id=str(policy.tenant_id),
                        deleted=deleted,
                    )
            except Exception as exc:
                await db.rollback()
                _logger.error(
                    "retention_purge_failed",
                    tenant_id=str(policy.tenant_id),
                    error=str(exc),
                )

    return {"purged_tenants": len(results), "details": results}
