from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.model_kpi import ModelKpiSnapshot
from app.models.model_registry import InferenceTrace, ModelRegistry, TenantMapper
from app.models.tenant import TenantBank
from app.services.alerting import send_alert


def _parse_model_types() -> list[str]:
    raw = str(settings.auto_cutover_model_types or "fraud,care")
    vals = [v.strip().lower() for v in raw.split(",") if v.strip()]
    return [v for v in vals if v in {"fraud", "care"}] or ["fraud", "care"]


async def run_model_cutover_executor(*, force_execute: bool = False) -> dict:
    enabled = bool(settings.auto_cutover_enabled) or bool(force_execute)
    dry_run = bool(settings.auto_cutover_dry_run) and not bool(force_execute)
    if not enabled:
        return {"enabled": False, "dry_run": dry_run, "scanned": 0, "eligible": 0, "executed": 0}

    scanned = 0
    eligible = 0
    executed = 0
    model_types = _parse_model_types()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    require_no_prior = bool(settings.auto_cutover_require_no_prior_execution)
    min_labeled = int(settings.auto_promotion_min_labeled)

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(TenantBank).where(TenantBank.is_active.is_(True)))).scalars().all()
        for bank in tenants:
            cfg = dict(bank.tone_config or {})
            cutover_status = dict(cfg.get("cutover_status") or {})
            for model_type in model_types:
                scanned += 1
                blockers: list[str] = []
                mapper = (
                    await db.execute(
                        select(TenantMapper).where(
                            TenantMapper.tenant_id == bank.id,
                            TenantMapper.model_type == model_type,
                            TenantMapper.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                model = (
                    await db.execute(
                        select(ModelRegistry).where(
                            ModelRegistry.tenant_id == bank.id,
                            ModelRegistry.model_type == model_type,
                            ModelRegistry.status == "active",
                        )
                    )
                ).scalar_one_or_none()
                if not settings.strict_mapper_enforcement:
                    blockers.append("strict_mapper_enforcement_disabled")
                if settings.allow_model_fallback:
                    blockers.append("allow_model_fallback_enabled")
                if not mapper:
                    blockers.append("missing_active_mapper")
                if not model:
                    blockers.append("missing_active_model")
                if model:
                    lineage = {}
                    if isinstance(model.metadata_json, dict):
                        lineage = model.metadata_json.get("lineage") or {}
                    for req in ("dataset_version", "contract_version", "mapper_version", "artifact_uri"):
                        if not isinstance(lineage, dict) or not lineage.get(req):
                            blockers.append(f"missing_lineage_{req}")
                fallback_count = 0
                trace_rows = (
                    await db.execute(
                        select(InferenceTrace.trace_json).where(
                            InferenceTrace.tenant_id == bank.id,
                            InferenceTrace.model_type == model_type,
                            InferenceTrace.created_at >= cutoff,
                        )
                    )
                ).all()
                for (tjson,) in trace_rows:
                    if isinstance(tjson, dict) and str(tjson.get("route_source") or "").lower() == "fallback":
                        fallback_count += 1
                if fallback_count > 0:
                    blockers.append("fallback_traces_present_24h")
                latest_snapshot = (
                    await db.execute(
                        select(ModelKpiSnapshot)
                        .where(
                            ModelKpiSnapshot.tenant_id == bank.id,
                            ModelKpiSnapshot.model_type == model_type,
                            ModelKpiSnapshot.window_days == 30,
                        )
                        .order_by(ModelKpiSnapshot.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if latest_snapshot is None:
                    blockers.append("missing_kpi_snapshot")
                else:
                    if int(latest_snapshot.labeled_count or 0) < min_labeled:
                        blockers.append("labeled_count_below_threshold")
                previous = cutover_status.get(model_type) if isinstance(cutover_status.get(model_type), dict) else None
                if require_no_prior and previous and previous.get("executed_at"):
                    blockers.append("already_executed")

                if blockers:
                    continue
                eligible += 1
                if dry_run:
                    db.add(
                        AuditLog(
                            tenant_id=bank.id,
                            event_type="TENANT_CUTOVER_AUTO_ELIGIBLE",
                            entity_type="tenant",
                            entity_id=bank.id,
                            actor_type="system",
                            actor_id="cutover_executor",
                            event_data={"tenant_id": str(bank.id), "model_type": model_type, "dry_run": True},
                        )
                    )
                    continue

                cutover_status[model_type] = {
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "executed_by": "cutover_executor",
                    "mode": "auto",
                    "strict_mapper_enforcement": bool(settings.strict_mapper_enforcement),
                    "allow_model_fallback": bool(settings.allow_model_fallback),
                }
                cfg["cutover_status"] = cutover_status
                bank.tone_config = cfg
                db.add(
                    AuditLog(
                        tenant_id=bank.id,
                        event_type="TENANT_CUTOVER_AUTO_EXECUTED",
                        entity_type="tenant",
                        entity_id=bank.id,
                        actor_type="system",
                        actor_id="cutover_executor",
                        event_data={"tenant_id": str(bank.id), "model_type": model_type, "dry_run": False},
                    )
                )
                executed += 1
        await db.commit()
    if dry_run and eligible > 0:
        send_alert(
            "TENANT_CUTOVER_AUTO_ELIGIBLE",
            severity="warning",
            payload={"eligible": eligible, "scanned": scanned, "model_types": model_types},
        )
    if (not dry_run) and executed > 0:
        send_alert(
            "TENANT_CUTOVER_AUTO_EXECUTED",
            severity="info",
            payload={"executed": executed, "eligible": eligible, "scanned": scanned, "model_types": model_types},
        )
    return {
        "enabled": True,
        "dry_run": dry_run,
        "scanned": scanned,
        "eligible": eligible,
        "executed": executed,
        "model_types": model_types,
        "require_no_prior_execution": require_no_prior,
    }
