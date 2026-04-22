from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import TenantBank
from app.models.audit import AuditLog
from app.services.fraud_drift import compute_tenant_drift

SYSTEM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


async def run_fraud_drift_checks() -> None:
    await _run()


async def _run() -> None:
    async with AsyncSessionLocal() as db:
        tenants = (
            await db.execute(select(TenantBank).where(TenantBank.is_active == True))  # noqa: E712
        ).scalars().all()
        for t in tenants:
            drift = await compute_tenant_drift(db, t.id, recent_limit=600, baseline_limit=3000)
            status = drift.get("status")
            if status in {"green", "yellow", "red"}:
                db.add(
                    AuditLog(
                        tenant_id=SYSTEM_TENANT_ID,
                        event_type="FRAUD_DRIFT_STATUS",
                        entity_type="monitoring",
                        actor_type="scheduler",
                        actor_id="fraud_drift_monitor",
                        event_data={
                            "tenant_id": str(t.id),
                            "status": status,
                            "alerts": drift.get("alerts", []),
                            "features": drift.get("features", []),
                            "checked_at": datetime.utcnow().isoformat(),
                        },
                    )
                )
        await db.commit()
