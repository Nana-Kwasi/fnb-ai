from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.model_kpi import ModelKpiSnapshot
from app.models.tenant import TenantBank
from app.services.alerting import send_alert
from app.services.model_kpis import compute_care_kpis, compute_fraud_kpis


async def run_model_kpi_snapshot(window_days: int = 30) -> dict:
    created = 0
    stale_pairs: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(settings.model_kpi_snapshot_max_stale_hours)))

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(TenantBank.id).where(TenantBank.is_active.is_(True)))).all()
        for (tenant_id,) in tenants:
            for mt in ("fraud", "care"):
                last = (
                    await db.execute(
                        select(ModelKpiSnapshot)
                        .where(
                            ModelKpiSnapshot.tenant_id == tenant_id,
                            ModelKpiSnapshot.model_type == mt,
                        )
                        .order_by(ModelKpiSnapshot.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last is None or (last.created_at and last.created_at < cutoff):
                    stale_pairs.append(f"{tenant_id}:{mt}")

            kf = await compute_fraud_kpis(db, tenant_id=tenant_id, days=window_days)
            db.add(
                ModelKpiSnapshot(
                    tenant_id=tenant_id,
                    model_type="fraud",
                    window_days=int(window_days),
                    total_scored=kf.total_scored,
                    labeled_count=kf.labeled_count,
                    block_rate=kf.block_rate,
                    otp_rate=kf.otp_rate,
                    alert_rate=kf.alert_rate,
                    precision=kf.precision,
                    recall=kf.recall,
                    fpr=kf.fpr,
                    auc=kf.auc,
                )
            )
            created += 1
            kc = await compute_care_kpis(db, tenant_id=tenant_id, days=window_days)
            db.add(
                ModelKpiSnapshot(
                    tenant_id=tenant_id,
                    model_type="care",
                    window_days=int(window_days),
                    total_scored=kc.total_scored,
                    labeled_count=kc.labeled_count,
                    block_rate=kc.block_rate,
                    otp_rate=kc.otp_rate,
                    alert_rate=kc.alert_rate,
                    precision=kc.precision,
                    recall=kc.recall,
                    fpr=kc.fpr,
                    auc=kc.auc,
                )
            )
            created += 1
        await db.commit()

    if stale_pairs:
        send_alert(
            "KPI_SNAPSHOT_STALE",
            severity="warning",
            payload={"stale_before_run": stale_pairs, "max_stale_hours": int(settings.model_kpi_snapshot_max_stale_hours)},
        )
    return {"created": created, "window_days": int(window_days), "stale_flagged": len(stale_pairs)}
