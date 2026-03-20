import hashlib
import secrets
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TenantBank
from app.services.care_engine import summarise_care_events

router = APIRouter()


def generate_api_key(env: str = "live") -> tuple[str, str, str]:
    random_part = secrets.token_urlsafe(24)
    raw_key = f"bankai_{env}_{random_part}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    return raw_key, key_hash, key_prefix


class OnboardIn(BaseModel):
    name: str
    country_code: str


class OnboardOut(BaseModel):
    bank_id: str
    api_key: str


class ApiKeyRotateOut(BaseModel):
    bank_id: str
    api_key: str


class FraudTrainStatusOut(BaseModel):
    state: str
    mode: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class CareMetricsOut(BaseModel):
    window_hours: int
    total_replies: int
    rule_hits: int
    model_suggestions: int
    fuzzy_suggestions: int
    out_of_scope: int
    escalations: int
    rule_hit_rate: float
    suggestion_rate: float
    out_of_scope_rate: float
    escalation_rate: float
    intent_counts: Dict[str, int]
    low_volume_intents: List[str]
    alerts: List[str]


@router.post("/onboard", response_model=OnboardOut)
async def onboard_bank(
    payload: OnboardIn,
    db: AsyncSession = Depends(get_db),
):
    raw_key, key_hash, key_prefix = generate_api_key()
    bank = TenantBank(
        name=payload.name,
        country_code=payload.country_code,
        api_key_hash=key_hash,
        api_key_prefix=key_prefix,
    )
    db.add(bank)
    await db.flush()
    return OnboardOut(bank_id=str(bank.id), api_key=raw_key)


@router.get("/care/metrics", response_model=CareMetricsOut)
async def get_care_metrics(
    window_hours: int = Query(24, ge=1, le=168),
) -> CareMetricsOut:
    data = summarise_care_events(window_hours=window_hours)
    return CareMetricsOut(**data)


class TenantSummary(BaseModel):
    id: str
    name: str
    country_code: str


@router.get("/tenants", response_model=List[TenantSummary])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TenantBank.id, TenantBank.name, TenantBank.country_code).order_by(TenantBank.created_at.desc()))
    return [TenantSummary(id=str(r.id), name=r.name, country_code=r.country_code) for r in result.all()]


@router.post("/tenants/{tenant_id}/api-key", response_model=ApiKeyRotateOut)
async def rotate_tenant_api_key(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a fresh API key for an existing tenant bank.
    Old key stops working immediately after rotation.
    """
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    raw_key, key_hash, key_prefix = generate_api_key()
    bank.api_key_hash = key_hash
    bank.api_key_prefix = key_prefix
    await db.flush()
    return ApiKeyRotateOut(bank_id=str(bank.id), api_key=raw_key)


class FraudPolicyOut(BaseModel):
    model_weight: float | None = None
    iso_weight: float | None = None
    rule_weight: float | None = None
    network_weight: float | None = None
    fraud_block_threshold: float | None = None
    fraud_otp_threshold: float | None = None
    shadow_mode: bool | None = None
    kill_switch: bool | None = None
    limited_approval_max_amount: float | None = None
    limited_approval_max_txn_1h: float | None = None
    limited_approval_escalate_ratio: float | None = None
    limited_approval_escalate_network_risk: float | None = None
    approve_max_amount: float | None = None
    approve_max_txn_1h: float | None = None
    request_otp_block_amount: float | None = None
    request_otp_block_txn_1h: float | None = None
    request_otp_block_network_risk: float | None = None
    velocity_zscore_threshold: float | None = None
    challenged_txn_1h_threshold: int | None = None
    # Tenant-tunable heuristic fallback for when no DB fraud rules exist.
    heuristic_amount_threshold: float | None = None
    heuristic_velocity_1h_threshold: int | None = None
    heuristic_suspicious_countries: list[str] | None = None
    # Rolling percentile-based dynamic thresholds (segment/corridor/channel).
    dynamic_threshold_enabled: bool | None = None
    dynamic_threshold_min_samples: int | None = None
    dynamic_threshold_block_percentile: float | None = None
    dynamic_threshold_otp_percentile: float | None = None


class FraudPolicyUpdate(BaseModel):
    model_weight: float | None = None
    iso_weight: float | None = None
    rule_weight: float | None = None
    network_weight: float | None = None
    fraud_block_threshold: float | None = None
    fraud_otp_threshold: float | None = None
    shadow_mode: bool | None = None
    kill_switch: bool | None = None
    limited_approval_max_amount: float | None = None
    limited_approval_max_txn_1h: float | None = None
    limited_approval_escalate_ratio: float | None = None
    limited_approval_escalate_network_risk: float | None = None
    approve_max_amount: float | None = None
    approve_max_txn_1h: float | None = None
    request_otp_block_amount: float | None = None
    request_otp_block_txn_1h: float | None = None
    request_otp_block_network_risk: float | None = None
    velocity_zscore_threshold: float | None = None
    challenged_txn_1h_threshold: int | None = None
    # Tenant-tunable heuristic fallback for when no DB fraud rules exist.
    heuristic_amount_threshold: float | None = None
    heuristic_velocity_1h_threshold: int | None = None
    heuristic_suspicious_countries: list[str] | None = None
    # Rolling percentile-based dynamic thresholds (segment/corridor/channel).
    dynamic_threshold_enabled: bool | None = None
    dynamic_threshold_min_samples: int | None = None
    dynamic_threshold_block_percentile: float | None = None
    dynamic_threshold_otp_percentile: float | None = None


@router.get("/tenants/{tenant_id}/fraud-policy", response_model=FraudPolicyOut)
async def get_fraud_policy(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    policy = (bank.tone_config or {}).get("fraud_policy") or {}
    return FraudPolicyOut(
        model_weight=policy.get("model_weight"),
        iso_weight=policy.get("iso_weight"),
        rule_weight=policy.get("rule_weight"),
        network_weight=policy.get("network_weight"),
        fraud_block_threshold=policy.get("fraud_block_threshold"),
        fraud_otp_threshold=policy.get("fraud_otp_threshold"),
        shadow_mode=policy.get("shadow_mode"),
        kill_switch=policy.get("kill_switch"),
        limited_approval_max_amount=policy.get("limited_approval_max_amount"),
        limited_approval_max_txn_1h=policy.get("limited_approval_max_txn_1h"),
        limited_approval_escalate_ratio=policy.get("limited_approval_escalate_ratio"),
        limited_approval_escalate_network_risk=policy.get("limited_approval_escalate_network_risk"),
        approve_max_amount=policy.get("approve_max_amount"),
        approve_max_txn_1h=policy.get("approve_max_txn_1h"),
        request_otp_block_amount=policy.get("request_otp_block_amount"),
        request_otp_block_txn_1h=policy.get("request_otp_block_txn_1h"),
        request_otp_block_network_risk=policy.get("request_otp_block_network_risk"),
        velocity_zscore_threshold=policy.get("velocity_zscore_threshold"),
        challenged_txn_1h_threshold=policy.get("challenged_txn_1h_threshold"),
        heuristic_amount_threshold=policy.get("heuristic_amount_threshold"),
        heuristic_velocity_1h_threshold=policy.get("heuristic_velocity_1h_threshold"),
        heuristic_suspicious_countries=policy.get("heuristic_suspicious_countries"),
        dynamic_threshold_enabled=policy.get("dynamic_threshold_enabled"),
        dynamic_threshold_min_samples=policy.get("dynamic_threshold_min_samples"),
        dynamic_threshold_block_percentile=policy.get("dynamic_threshold_block_percentile"),
        dynamic_threshold_otp_percentile=policy.get("dynamic_threshold_otp_percentile"),
    )


@router.patch("/tenants/{tenant_id}/fraud-policy", response_model=FraudPolicyOut)
async def update_fraud_policy(
    tenant_id: uuid.UUID,
    payload: FraudPolicyUpdate,
    db: AsyncSession = Depends(get_db),
):
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if bank.tone_config is None:
        bank.tone_config = {}
    policy = dict(bank.tone_config.get("fraud_policy") or {})
    update = payload.model_dump(exclude_unset=True)
    for k, v in update.items():
        if v is not None:
            policy[k] = v
    bank.tone_config = {**(bank.tone_config or {}), "fraud_policy": policy}
    await db.flush()
    return FraudPolicyOut(
        model_weight=policy.get("model_weight"),
        iso_weight=policy.get("iso_weight"),
        rule_weight=policy.get("rule_weight"),
        network_weight=policy.get("network_weight"),
        fraud_block_threshold=policy.get("fraud_block_threshold"),
        fraud_otp_threshold=policy.get("fraud_otp_threshold"),
        shadow_mode=policy.get("shadow_mode"),
        kill_switch=policy.get("kill_switch"),
        limited_approval_max_amount=policy.get("limited_approval_max_amount"),
        limited_approval_max_txn_1h=policy.get("limited_approval_max_txn_1h"),
        limited_approval_escalate_ratio=policy.get("limited_approval_escalate_ratio"),
        limited_approval_escalate_network_risk=policy.get("limited_approval_escalate_network_risk"),
        approve_max_amount=policy.get("approve_max_amount"),
        approve_max_txn_1h=policy.get("approve_max_txn_1h"),
        request_otp_block_amount=policy.get("request_otp_block_amount"),
        request_otp_block_txn_1h=policy.get("request_otp_block_txn_1h"),
        request_otp_block_network_risk=policy.get("request_otp_block_network_risk"),
        velocity_zscore_threshold=policy.get("velocity_zscore_threshold"),
        challenged_txn_1h_threshold=policy.get("challenged_txn_1h_threshold"),
        heuristic_amount_threshold=policy.get("heuristic_amount_threshold"),
        heuristic_velocity_1h_threshold=policy.get("heuristic_velocity_1h_threshold"),
        heuristic_suspicious_countries=policy.get("heuristic_suspicious_countries"),
        dynamic_threshold_enabled=policy.get("dynamic_threshold_enabled"),
        dynamic_threshold_min_samples=policy.get("dynamic_threshold_min_samples"),
        dynamic_threshold_block_percentile=policy.get("dynamic_threshold_block_percentile"),
        dynamic_threshold_otp_percentile=policy.get("dynamic_threshold_otp_percentile"),
    )


@router.post("/trigger-fraud-train")
async def trigger_fraud_train():
    """
    Start fraud model retrain in the background (from labelled data).

    Implementation detail:
      - Spawns a separate Python process running `python -m app.ml.train`
      - Uses FRAUD_TRAIN_MODE=real so it trains from historical data + labels
      - This avoids mixing FastAPI's event loop with the async training loop.
    """
    import os
    import subprocess
    env = os.environ.copy()
    env.setdefault("FRAUD_TRAIN_MODE", "real")
    env.setdefault("FRAUD_TRAIN_LIMIT", "5000")
    # Fire-and-forget subprocess; errors are logged to its own stderr.
    subprocess.Popen(
        ["python", "-m", "app.ml.train"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "started", "message": "Fraud training job started in background process."}


@router.get("/fraud-train-status", response_model=FraudTrainStatusOut)
async def fraud_train_status() -> FraudTrainStatusOut:
    """
    Lightweight status endpoint for fraud model training.

    Reads models/fraud/train_status.json if present; otherwise reports idle.
    """
    import os
    from pathlib import Path
    model_path_env = os.getenv("MODEL_PATH", "")
    if model_path_env and model_path_env != "/models":
        out_dir = Path(model_path_env).parent / "fraud"
    else:
        out_dir = Path(__file__).resolve().parents[3] / "models" / "fraud"
    status_path = out_dir / "train_status.json"
    if not status_path.exists():
        return FraudTrainStatusOut(state="idle")
    try:
        import json
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return FraudTrainStatusOut(
            state=str(data.get("state") or "unknown"),
            mode=data.get("mode"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )
    except Exception:
        return FraudTrainStatusOut(state="unknown")
