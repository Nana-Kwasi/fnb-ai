from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.tenant import TenantBank
from app.models.training_data import TrainingUpload
from app.services.alerting import send_alert

SYSTEM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def run_tenant_finetune_scout() -> dict:
    if not settings.auto_tenant_finetune_scout_enabled:
        return {"enabled": False, "scanned": 0, "eligible_hits": 0}

    min_rows = max(100, int(settings.auto_tenant_finetune_scout_min_rows))
    eligible_pairs: list[dict] = []
    n_tenants = 0

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(TenantBank.id).where(TenantBank.is_active.is_(True)))).all()
        n_tenants = len(tenants)
        for (tenant_id,) in tenants:
            for model_type in ("fraud", "care"):
                uploads = (
                    await db.execute(
                        select(TrainingUpload)
                        .where(TrainingUpload.model_type == model_type)
                        .order_by(TrainingUpload.created_at.desc())
                        .limit(200)
                    )
                ).scalars().all()
                rows_available = 0
                quality_score = None
                for u in uploads:
                    meta = u.meta if isinstance(u.meta, dict) else {}
                    if str(meta.get("tenant_id")) == str(tenant_id):
                        rows_available += int(u.row_count or 0)
                        sm = meta.get("eval_summary") if isinstance(meta.get("eval_summary"), dict) else None
                        if sm and quality_score is None:
                            try:
                                quality_score = float(sm.get("accuracy")) if sm.get("accuracy") is not None else None
                            except (TypeError, ValueError):
                                quality_score = None
                reasons: list[str] = []
                if rows_available < min_rows:
                    reasons.append("insufficient_labeled_volume")
                if quality_score is not None and quality_score < 0.65:
                    reasons.append("quality_below_threshold")
                if not reasons:
                    eligible_pairs.append(
                        {
                            "tenant_id": str(tenant_id),
                            "model_type": model_type,
                            "rows_available": rows_available,
                            "quality_score": quality_score,
                        }
                    )

        db.add(
            AuditLog(
                tenant_id=SYSTEM_TENANT_ID,
                event_type="TENANT_FINETUNE_SCOUT",
                entity_type="monitoring",
                actor_type="system",
                actor_id="tenant_finetune_scout",
                event_data={
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "min_rows": min_rows,
                    "eligible": eligible_pairs,
                },
            )
        )
        await db.commit()

    if eligible_pairs:
        send_alert(
            "TENANT_FINETUNE_ELIGIBLE",
            severity="info",
            payload={"count": len(eligible_pairs), "items": eligible_pairs[:50]},
        )
    return {"enabled": True, "scanned": n_tenants * 2, "eligible_hits": len(eligible_pairs)}
