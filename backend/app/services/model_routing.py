from __future__ import annotations

import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.model_registry import InferenceTrace, ModelRegistry, TenantMapper
from app.services.fraud_engine import MODEL_VERSION


@dataclass
class ModelRoute:
    model_type: str
    model_version: str
    mapper_version: str
    contract_version: str
    model_registry_id: str | None
    mapper_id: str | None
    artifact_uri: str | None
    source: str  # tenant|global|fallback


async def resolve_model_route(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    model_type: str,
    strict_mapper: bool = False,
    route_key: str | None = None,
) -> ModelRoute:
    allowlist_raw = (settings.model_fallback_allowlist_tenants or "").strip()
    allowlist: set[str] = {x.strip() for x in allowlist_raw.split(",") if x.strip()}
    # Prefer tenant active model.
    tenant_model = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == model_type,
                ModelRegistry.tenant_id == tenant_id,
                ModelRegistry.status == "active",
            )
        )
    ).scalar_one_or_none()
    if tenant_model:
        if bool(getattr(settings, "canary_rollout_enabled", False)):
            pct = float(getattr(settings, "canary_default_percent", 0.0) or 0.0)
            meta = tenant_model.metadata_json if isinstance(tenant_model.metadata_json, dict) else {}
            pct = float(meta.get("canary_percent", pct) or pct)
            pct = max(0.0, min(100.0, pct))
            if pct > 0:
                shadow = await resolve_shadow_candidate(db, tenant_id=tenant_id, model_type=model_type)
                if shadow:
                    if bool(getattr(settings, "canary_auto_stop_enabled", False)):
                        cutoff = datetime.now(timezone.utc) - timedelta(
                            hours=max(1, int(getattr(settings, "canary_auto_stop_window_hours", 6) or 6))
                        )
                        traces = (
                            await db.execute(
                                select(InferenceTrace.decision, InferenceTrace.trace_json).where(
                                    InferenceTrace.tenant_id == tenant_id,
                                    InferenceTrace.model_type == model_type,
                                    InferenceTrace.created_at >= cutoff,
                                    InferenceTrace.model_version == tenant_model.version,
                                )
                            )
                        ).all()
                        compared = 0
                        disagree = 0
                        for dec, tj in traces:
                            compared_dec = (tj or {}).get("shadow_decision")
                            if compared_dec is None:
                                continue
                            compared += 1
                            if str(compared_dec) != str(dec):
                                disagree += 1
                        min_compared = max(1, int(getattr(settings, "canary_auto_stop_min_compared", 200) or 200))
                        max_disagree = float(getattr(settings, "canary_auto_stop_max_disagree_rate", 0.25) or 0.25)
                        if compared >= min_compared and (disagree / max(1, compared)) > max_disagree:
                            pct = 0.0
                    chooser = f"{tenant_id}:{route_key or uuid.uuid4()}"
                    h = hashlib.sha256(chooser.encode("utf-8")).hexdigest()
                    bucket = (int(h[:8], 16) % 10000) / 100.0
                    if bucket < pct:
                        mapper = (
                            await db.execute(
                                select(TenantMapper).where(
                                    TenantMapper.tenant_id == tenant_id,
                                    TenantMapper.model_type == model_type,
                                    TenantMapper.is_active.is_(True),
                                )
                            )
                        ).scalar_one_or_none()
                        return ModelRoute(
                            model_type=model_type,
                            model_version=shadow.version,
                            mapper_version=(mapper.mapper_version if mapper else shadow.mapper_version),
                            contract_version=(mapper.contract_version if mapper else shadow.feature_contract_version),
                            model_registry_id=str(shadow.id),
                            mapper_id=str(mapper.id) if mapper else None,
                            artifact_uri=shadow.artifact_uri,
                            source="canary",
                        )
        mapper = (
            await db.execute(
                select(TenantMapper).where(
                    TenantMapper.tenant_id == tenant_id,
                    TenantMapper.model_type == model_type,
                    TenantMapper.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        route = ModelRoute(
            model_type=model_type,
            model_version=tenant_model.version,
            mapper_version=(mapper.mapper_version if mapper else tenant_model.mapper_version),
            contract_version=(mapper.contract_version if mapper else tenant_model.feature_contract_version),
            model_registry_id=str(tenant_model.id),
            mapper_id=str(mapper.id) if mapper else None,
            artifact_uri=tenant_model.artifact_uri,
            source="tenant",
        )
        if strict_mapper and mapper is None:
            raise HTTPException(status_code=422, detail="Active tenant mapper required before scoring.")
        return route

    # Fallback to global active model if present.
    global_model = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == model_type,
                ModelRegistry.tenant_id.is_(None),
                ModelRegistry.status == "active",
            )
        )
    ).scalar_one_or_none()
    if global_model:
        mapper = (
            await db.execute(
                select(TenantMapper).where(
                    TenantMapper.tenant_id == tenant_id,
                    TenantMapper.model_type == model_type,
                    TenantMapper.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        route = ModelRoute(
            model_type=model_type,
            model_version=global_model.version,
            mapper_version=(mapper.mapper_version if mapper else global_model.mapper_version),
            contract_version=(mapper.contract_version if mapper else global_model.feature_contract_version),
            model_registry_id=str(global_model.id),
            mapper_id=str(mapper.id) if mapper else None,
            artifact_uri=global_model.artifact_uri,
            source="global",
        )
        if strict_mapper and mapper is None:
            raise HTTPException(status_code=422, detail="Active tenant mapper required before scoring.")
        return route

    # Non-breaking fallback to current engine default.
    if strict_mapper:
        raise HTTPException(
            status_code=422,
            detail="strict_mapper_enforcement: no tenant/global registry route — implicit engine fallback is disabled.",
        )
    if not settings.allow_model_fallback:
        raise HTTPException(status_code=503, detail="No active model route available for tenant.")
    if allowlist and str(tenant_id) not in allowlist:
        raise HTTPException(status_code=503, detail="Fallback model route not allowed for this tenant.")
    return ModelRoute(
        model_type=model_type,
        model_version=MODEL_VERSION if model_type == "fraud" else "care-default",
        mapper_version="mapper-v0",
        contract_version="contract-v0",
        model_registry_id=None,
        mapper_id=None,
        artifact_uri=None,
        source="fallback",
    )


async def resolve_shadow_candidate(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    model_type: str,
) -> ModelRegistry | None:
    return (
        await db.execute(
            select(ModelRegistry)
            .where(
                ModelRegistry.model_type == model_type,
                ModelRegistry.tenant_id == tenant_id,
                ModelRegistry.status == "shadow",
            )
            .order_by(ModelRegistry.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
