from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.tenant import TenantBank
from app.services.alerting import send_alert

SYSTEM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
TRAINING_UPLOADS_DIR = Path(__file__).resolve().parents[2] / "app" / "ml" / "data" / "training_uploads"
from app.services.data_plane_verify import (
    verify_analytics_warehouse_isolation,
    verify_local_training_partition,
    verify_read_replica_isolation,
    verify_s3_tenant_prefixes,
)


def _required_tables() -> list[str]:
    raw = str(settings.warehouse_isolation_required_tables or "")
    return [t.strip() for t in raw.split(",") if t.strip()]


async def run_warehouse_isolation_verification() -> dict:
    if not settings.warehouse_isolation_verification_enabled:
        return {"enabled": False, "passed": True, "errors": [], "checked_tables": []}

    tables = _required_tables()
    errors: list[str] = []
    checked: list[str] = []

    async with AsyncSessionLocal() as db:
        is_sqlite = "sqlite" in str(settings.database_url).lower()
        for table in tables:
            checked.append(table)
            if is_sqlite:
                cols = (await db.execute(text(f"PRAGMA table_info({table})"))).all()
                col_names = {str(c[1]) for c in cols}
            else:
                cols = (
                    await db.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_name = :t and table_schema = 'public'"
                        ),
                        {"t": table},
                    )
                ).all()
                col_names = {str(c[0]) for c in cols}
            if not col_names:
                errors.append(f"{table}:missing_table")
                continue
            if "tenant_id" not in col_names:
                errors.append(f"{table}:missing_tenant_id")
                continue
            if table in {"model_registry"}:
                continue
            null_count = (
                await db.execute(
                    text(f"select count(*) from {table} where tenant_id is null")
                )
            ).scalar_one_or_none()
            if int(null_count or 0) > 0:
                errors.append(f"{table}:null_tenant_id_rows={int(null_count or 0)}")

        tenant_rows = (await db.execute(select(TenantBank.id).where(TenantBank.is_active.is_(True)))).all()
        tenant_ids = [r[0] for r in tenant_rows]
        local_train_errs = verify_local_training_partition(training_root=TRAINING_UPLOADS_DIR)
        if settings.warehouse_isolation_require_local_training_layout:
            errors.extend(local_train_errs)
        errors.extend(await verify_read_replica_isolation())
        errors.extend(await verify_analytics_warehouse_isolation())
        errors.extend(verify_s3_tenant_prefixes(tenant_ids=tenant_ids))

        passed = len(errors) == 0
        db.add(
            AuditLog(
                tenant_id=SYSTEM_TENANT_ID,
                event_type="WAREHOUSE_ISOLATION_VERIFIED",
                entity_type="monitoring",
                entity_id=None,
                actor_type="system",
                actor_id="warehouse_isolation_verifier",
                event_data={
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "passed": passed,
                    "errors": errors,
                    "checked_tables": checked,
                },
            )
        )
        await db.commit()

    if not passed:
        send_alert(
            "WAREHOUSE_ISOLATION_FAILED",
            severity="critical",
            payload={"errors": errors, "checked_tables": checked},
        )
    return {"enabled": True, "passed": passed, "errors": errors, "checked_tables": checked}
