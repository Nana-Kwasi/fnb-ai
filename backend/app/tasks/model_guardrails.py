from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.fraud import FraudScore
from app.models.fraud_extra import FraudAlert
from app.models.model_registry import InferenceTrace, ModelRegistry


def _rollback_model_types() -> set[str]:
    raw = (settings.auto_rollback_model_types or "fraud").lower()
    return {x.strip() for x in raw.split(",") if x.strip() in {"fraud", "care"}}


async def _rollback_fraud_models(db, cutoff: datetime) -> None:
    active_rows = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == "fraud",
                ModelRegistry.status == "active",
                ModelRegistry.tenant_id.is_not(None),
            )
        )
    ).scalars().all()

    for row in active_rows:
        tenant_id = row.tenant_id
        if tenant_id is None:
            continue
        total_scored = (
            await db.execute(
                select(func.count()).where(
                    FraudScore.tenant_id == tenant_id,
                    FraudScore.created_at >= cutoff,
                )
            )
        ).scalar_one()
        total_scored = int(total_scored or 0)
        if total_scored < int(settings.auto_rollback_min_scored):
            continue

        block_count = (
            await db.execute(
                select(func.count()).where(
                    FraudScore.tenant_id == tenant_id,
                    FraudScore.created_at >= cutoff,
                    FraudScore.decision == "BLOCK",
                )
            )
        ).scalar_one()
        alert_count = (
            await db.execute(
                select(func.count()).where(
                    FraudAlert.tenant_id == tenant_id,
                    FraudAlert.created_at >= cutoff,
                )
            )
        ).scalar_one()
        block_rate = float(block_count or 0) / float(total_scored)
        alert_rate = float(alert_count or 0) / float(total_scored)

        breach = block_rate > float(settings.auto_rollback_max_block_rate) or alert_rate > float(
            settings.auto_rollback_max_alert_rate
        )
        if not breach:
            continue

        prev = (
            await db.execute(
                select(ModelRegistry)
                .where(
                    ModelRegistry.model_type == "fraud",
                    ModelRegistry.tenant_id == tenant_id,
                    ModelRegistry.id != row.id,
                    ModelRegistry.status.in_(("shadow", "rollback")),
                )
                .order_by(ModelRegistry.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not prev:
            continue

        row.status = "rollback"
        prev.status = "active"
        prev.activated_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                event_type="MODEL_AUTO_ROLLBACK",
                entity_type="model_registry",
                entity_id=prev.id,
                actor_type="system",
                actor_id="guardrail",
                event_data={
                    "model_type": "fraud",
                    "from_model_id": str(row.id),
                    "from_model_version": row.version,
                    "to_model_id": str(prev.id),
                    "to_model_version": prev.version,
                    "window_hours": int(settings.auto_rollback_window_hours),
                    "total_scored": total_scored,
                    "block_rate": round(block_rate, 6),
                    "alert_rate": round(alert_rate, 6),
                },
            )
        )


async def _rollback_care_models(db, cutoff: datetime) -> None:
    active_rows = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == "care",
                ModelRegistry.status == "active",
                ModelRegistry.tenant_id.is_not(None),
            )
        )
    ).scalars().all()

    max_esc = float(settings.auto_rollback_care_max_escalation_rate)
    min_n = int(settings.auto_rollback_min_scored)

    for row in active_rows:
        tenant_id = row.tenant_id
        if tenant_id is None:
            continue
        total = (
            await db.execute(
                select(func.count()).where(
                    InferenceTrace.tenant_id == tenant_id,
                    InferenceTrace.model_type == "care",
                    InferenceTrace.created_at >= cutoff,
                )
            )
        ).scalar_one()
        total = int(total or 0)
        if total < min_n:
            continue

        esc = (
            await db.execute(
                select(func.count()).where(
                    InferenceTrace.tenant_id == tenant_id,
                    InferenceTrace.model_type == "care",
                    InferenceTrace.created_at >= cutoff,
                    InferenceTrace.decision == "HUMAN_ESCALATION",
                )
            )
        ).scalar_one()
        esc = int(esc or 0)
        esc_rate = float(esc) / float(total)
        if esc_rate <= max_esc:
            continue

        prev = (
            await db.execute(
                select(ModelRegistry)
                .where(
                    ModelRegistry.model_type == "care",
                    ModelRegistry.tenant_id == tenant_id,
                    ModelRegistry.id != row.id,
                    ModelRegistry.status.in_(("shadow", "rollback")),
                )
                .order_by(ModelRegistry.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not prev:
            continue

        row.status = "rollback"
        prev.status = "active"
        prev.activated_at = datetime.now(timezone.utc)
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                event_type="MODEL_AUTO_ROLLBACK",
                entity_type="model_registry",
                entity_id=prev.id,
                actor_type="system",
                actor_id="guardrail",
                event_data={
                    "model_type": "care",
                    "from_model_id": str(row.id),
                    "from_model_version": row.version,
                    "to_model_id": str(prev.id),
                    "to_model_version": prev.version,
                    "window_hours": int(settings.auto_rollback_window_hours),
                    "trace_count": total,
                    "human_escalation_count": esc,
                    "escalation_rate": round(esc_rate, 6),
                    "max_escalation_rate": max_esc,
                },
            )
        )


async def run_model_guardrails() -> None:
    if not settings.auto_rollback_enabled:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(settings.auto_rollback_window_hours)))
    types = _rollback_model_types()
    async with AsyncSessionLocal() as db:
        if "fraud" in types:
            await _rollback_fraud_models(db, cutoff)
        if "care" in types:
            await _rollback_care_models(db, cutoff)
        await db.commit()
