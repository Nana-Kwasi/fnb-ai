import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from sqlalchemy import select, func, and_

from app.database import get_db
from app.config import settings
from app.middleware.auth import resolve_tenant
from app.models import (
    TenantBank,
    Customer,
    Transaction,
    FraudScore,
    FraudAlert,
    CustomerBehaviourProfile,
    Blacklist,
    DeviceFingerprint,
    AuditLog,
    MerchantRisk,
)
from app.models.calibration import CalibrationArtifact
from app.models.model_registry import InferenceTrace, TenantMapper
from app.services.calibration import apply_calibration
from app.services.feature_engine import build_feature_vector
from app.services.fraud_engine import (
    score_and_explain,
    recommended_action,
    MODEL_VERSION,
    _get_models_path,
    resolve_fraud_artifact_bundle_dir,
    resolve_fraud_feature_importances_json_path,
)
from app.services.mapper_validation import validate_and_dry_run
from app.services.model_routing import resolve_model_route, resolve_shadow_candidate
from app.services.tenant_registry_gate import tenant_has_registered_model
from app.services.fraud_ring import (
    update_entity_maps,
    get_tenant_graph_data,
    build_graph_and_rings,
    apply_fraud_outcome,
)
from app.services.transaction_fingerprint import (
    compute_transaction_fingerprint,
    store_fingerprint,
)
from app.observability import (
    FraudScoringTimer,
    record_fraud_decision,
    get_logger as _obs_logger,
)

router = APIRouter()
_logger = _obs_logger(__name__)

DECISION_NORMALIZATION = {
    "REQUEST_OT": "REQUEST_OTP",
    "LIMITED_AP": "LIMITED_APPROVAL",
    "MANUAL_REV": "MANUAL_REVIEW",
    "SOFT_DECLI": "SOFT_DECLINE",
}

class TransactionIn(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    currency: str
    merchant_category: str | None = None
    merchant_id: str | None = None
    location: str | None = None
    device_id: str | None = None
    ip_address: str | None = None
    channel: str | None = None
    timestamp: str
    # Optional behavioral biometrics from mobile SDK
    biometrics: dict | None = None


class FraudScoreOut(BaseModel):
    transaction_id: str
    decision: str
    fraud_score: float
    confidence: str
    reasons: list[str]
    recommended_action: str
    processing_time_ms: int


class PredictIn(BaseModel):
    account_id: str
    amount: float
    currency: str = "USD"
    device_id: str | None = None
    ip_address: str | None = None
    location: str | None = None
    merchant_id: str | None = None


class PredictOut(BaseModel):
    risk_score: float
    decision: str
    reason: str
    model_score: float | None = None
    anomaly_score: float | None = None
    rule_score: float | None = None
    processing_time_ms: int


class ScoreDetailOut(BaseModel):
    transaction_id: str
    risk_score: float
    model_score: float
    anomaly_score: float | None
    rule_score: float
    network_risk_score: float | None = None
    graph_risk_score: float | None = None
    decision: str
    reasons: list[str]
    rule_reasons: list[str]
    shap_values: dict
    processing_time_ms: int


class AlertOut(BaseModel):
    alert_id: str
    transaction_id: str
    account_id: str | None
    alert_type: str
    severity: str
    status: str
    created_at: str


class AlertStatusUpdate(BaseModel):
    status: str
    assigned_to: UUID | None = None


class CustomerRiskOut(BaseModel):
    account_id: str
    risk_score: float
    avg_transaction: float | None
    max_transaction: float | None
    usual_location: str | None
    transaction_frequency_7d: float | None


class DeviceCheckOut(BaseModel):
    device_id: str
    is_known: bool
    risk: str
    reason: str | None


class TransactionSummaryOut(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    currency: str
    merchant_category: str | None
    location_country: str | None
    channel: str | None
    status: str
    decision: str | None
    fraud_score: float | None
    created_at: str


class TransactionDetailOut(BaseModel):
    transaction_id: str
    external_tx_id: str | None
    account_id: str
    amount: float
    currency: str
    merchant_category: str | None
    location_country: str | None
    channel: str | None
    status: str
    tx_timestamp: str
    decision: str | None
    confidence: str | None
    fraud_score: float | None
    lgbm_score: float | None
    anomaly_score: float | None
    rule_score: float | None
    model_version: str | None
    processing_time_ms: int | None
    reasons: list[str] | None
    shap_values: dict | None
    feature_vector: dict | None


class NetworkNodeOut(BaseModel):
    id: str
    type: str


class NetworkEdgeOut(BaseModel):
    source: str
    target: str
    rel: str


class NodeRiskOut(BaseModel):
    node_id: str
    risk_score: float


class NetworkGraphOut(BaseModel):
    nodes: list[NetworkNodeOut]
    edges: list[NetworkEdgeOut]
    risk_scores: list[NodeRiskOut] | None = None


class FraudRingOut(BaseModel):
    type: str
    entity_id: str | None
    account_count: int | None
    nodes: list[str] | None
    size: int | None


class NetworkAnalyticsOut(BaseModel):
    accounts_per_device: list[dict]
    fraud_clusters: list[dict]
    shared_ip_usage: list[dict]
    high_risk_merchants: list[dict]


class OutcomeIn(BaseModel):
    transaction_id: str
    classification: str  # CONFIRMED_FRAUD, FALSE_POSITIVE, CONFIRMED_LEGIT
    source: str | None = None
    notes: str | None = None


class MetricsSummaryOut(BaseModel):
    total: int
    by_decision: dict
    avg_ensemble_score: float | None


class FeatureImportanceOut(BaseModel):
    feature: str
    importance_gain: float


class FeatureImportancesMeta(BaseModel):
    """How /api/v1/fraud/feature-importances resolved the JSON file."""

    route_source: str | None = None
    model_version: str | None = None
    artifact_uri: str | None = None
    resolved_from: str
    reason: str | None = None


class FeatureImportancesResponse(BaseModel):
    features: list[FeatureImportanceOut]
    meta: FeatureImportancesMeta


def _location_country(payload: TransactionIn) -> str | None:
    if not payload.location or len(payload.location) < 2:
        return None
    return payload.location[:2].upper()


def _policy_float(cfg: dict, key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _policy_bool(cfg: dict, key: str, default: bool = False) -> bool:
    return bool(cfg.get(key, default))


def _enforce_decision_controls(
    *,
    bank: TenantBank,
    payload: TransactionIn | PredictIn,
    feature_vector: dict,
    ensemble_score: float,
    network_risk_score: float | None,
    decision: str,
) -> tuple[str, list[str]]:
    """
    Enforce hard controls so decisions are policy-backed, not just labels.

    Controls (tenant-configurable via tone_config.fraud_policy):
      - kill_switch (bool): force BLOCK for all transactions.
      - approve_max_amount / approve_max_txn_1h: cap APPROVE before escalating to REQUEST_OTP.
      - request_otp_block_amount / request_otp_block_txn_1h / request_otp_block_network_risk:
        when REQUEST_OTP should be escalated to BLOCK in real-time.
      - limited_approval_max_amount (float): maximum amount allowed for LIMITED_APPROVAL.
      - limited_approval_max_txn_1h (int): max 1h velocity allowed for LIMITED_APPROVAL.
      - limited_approval_escalate_ratio (float): if score is near OTP threshold, escalate to REQUEST_OTP.
      - limited_approval_escalate_network_risk (float): if network risk is high, escalate to REQUEST_OTP.
    """
    cfg = ((bank.tone_config or {}).get("fraud_policy") or {})
    notes: list[str] = []

    if _policy_bool(cfg, "kill_switch", False):
        return "BLOCK", ["Kill switch enabled: all transactions are blocked."]

    amount = float(getattr(payload, "amount", 0.0) or 0.0)
    txn_count_1h = float(feature_vector.get("txn_count_1h", 0.0) or 0.0)
    txn_count_1h_non_challenged = float(feature_vector.get("txn_count_1h_non_challenged", txn_count_1h) or 0.0)
    otp_threshold = _policy_float(cfg, "fraud_otp_threshold", 0.55)

    # APPROVE controls: if safe band is breached, challenge with OTP
    if decision == "APPROVE":
        # Model-first defaults: keep APPROVE overrides effectively disabled
        # unless the tenant explicitly sets stricter caps.
        approve_max_amount = _policy_float(cfg, "approve_max_amount", 1_000_000.0)
        approve_max_txn_1h = _policy_float(cfg, "approve_max_txn_1h", 1_000.0)
        if amount > approve_max_amount:
            return "REQUEST_OTP", [f"Escalated from APPROVE: amount {amount:.2f} exceeds approve cap {approve_max_amount:.2f}."]
        if txn_count_1h_non_challenged > approve_max_txn_1h:
            return "REQUEST_OTP", [f"Escalated from APPROVE: txn_count_1h_non_challenged {txn_count_1h_non_challenged:.0f} exceeds approve cap {approve_max_txn_1h:.0f}."]
        return decision, notes

    # REQUEST_OTP controls: if stronger risk gates are hit, force BLOCK
    if decision == "REQUEST_OTP":
        # Model-first defaults: REQUEST_OTP -> BLOCK requires explicit
        # tightening by tenant policy.
        otp_block_amount = _policy_float(cfg, "request_otp_block_amount", 1_000_000.0)
        otp_block_txn_1h = _policy_float(cfg, "request_otp_block_txn_1h", 1_000.0)
        otp_block_network = _policy_float(cfg, "request_otp_block_network_risk", 0.99)
        if amount > otp_block_amount:
            return "BLOCK", [f"Escalated from REQUEST_OTP: amount {amount:.2f} exceeds block cap {otp_block_amount:.2f}."]
        if txn_count_1h > otp_block_txn_1h:
            return "BLOCK", [f"Escalated from REQUEST_OTP: txn_count_1h {txn_count_1h:.0f} exceeds block cap {otp_block_txn_1h:.0f}."]
        if network_risk_score is not None and float(network_risk_score) >= otp_block_network:
            return "BLOCK", [f"Escalated from REQUEST_OTP: network_risk_score {float(network_risk_score):.3f} exceeds {otp_block_network:.3f}."]
        return decision, notes

    if decision != "LIMITED_APPROVAL":
        return decision, notes

    max_amount = _policy_float(cfg, "limited_approval_max_amount", 250.0)
    max_txn_1h = _policy_float(cfg, "limited_approval_max_txn_1h", 4.0)
    escalate_ratio = _policy_float(cfg, "limited_approval_escalate_ratio", 0.90)
    escalate_network = _policy_float(cfg, "limited_approval_escalate_network_risk", 0.60)

    # Hard limits for limited approvals
    if amount > max_amount:
        return "REQUEST_OTP", [f"Escalated: amount {amount:.2f} exceeds LIMITED_APPROVAL cap {max_amount:.2f}."]
    if txn_count_1h > max_txn_1h:
        return "REQUEST_OTP", [f"Escalated: txn_count_1h {txn_count_1h:.0f} exceeds LIMITED_APPROVAL cap {max_txn_1h:.0f}."]

    # Real-time escalation when risk is close to OTP threshold or network looks risky
    if ensemble_score >= otp_threshold * escalate_ratio:
        return "REQUEST_OTP", [f"Escalated: score {ensemble_score:.3f} is near OTP threshold {otp_threshold:.3f}."]
    if network_risk_score is not None and float(network_risk_score) >= escalate_network:
        return "REQUEST_OTP", [f"Escalated: network_risk_score {float(network_risk_score):.3f} exceeds {escalate_network:.3f}."]

    notes.append(f"LIMITED_APPROVAL enforced with caps (amount<={max_amount:.2f}, txn_count_1h<={max_txn_1h:.0f}).")
    return decision, notes


def _alert_profile_for_decision(decision: str, risk_score: float) -> tuple[str, str] | None:
    """
    Decision-aware alert routing profile.
    Returns (alert_type, severity) or None when no alert should be created.
    """
    if decision == "BLOCK":
        severity = "CRITICAL" if risk_score >= 0.90 else "HIGH"
        return "FRAUD_RISK_BLOCK", severity
    if decision == "REQUEST_OTP":
        severity = "HIGH" if risk_score >= 0.75 else "MEDIUM"
        return "STEP_UP_REQUIRED", severity
    if decision == "MANUAL_REVIEW":
        severity = "HIGH" if risk_score >= 0.70 else "MEDIUM"
        return "MANUAL_REVIEW_QUEUE", severity
    if decision == "SOFT_DECLINE":
        severity = "MEDIUM" if risk_score >= 0.60 else "LOW"
        return "SOFT_DECLINE_REVIEW", severity
    if decision == "LIMITED_APPROVAL":
        if risk_score >= 0.70:
            return "LIMITED_APPROVAL_WATCH", "MEDIUM"
        return None
    return None


def _add_alert_if_needed(
    *,
    db,
    bank: TenantBank,
    customer: Customer,
    txn: Transaction,
    decision: str,
    risk_score: float,
) -> None:
    profile = _alert_profile_for_decision(decision, risk_score)
    if profile is None:
        return
    alert_type, severity = profile
    db.add(
        FraudAlert(
            tenant_id=bank.id,
            transaction_id=txn.id,
            customer_id=customer.id,
            alert_type=alert_type,
            severity=severity,
            status="OPEN",
        )
    )


async def _ensure_customer(db, bank: TenantBank, account_id: str):
    result = await db.execute(
        select(Customer).where(
            Customer.tenant_id == bank.id,
            Customer.external_id == account_id,
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        customer = Customer(tenant_id=bank.id, external_id=account_id)
        db.add(customer)
        await db.flush()
    return customer


def _trace_payload(
    route_source: str,
    model_registry_id: str | None,
    mapper_id: str | None,
    policy_snapshot: dict | None,
    mapper_validation: dict | None = None,
    transaction_id: str | None = None,
) -> dict:
    return {
        "route_source": route_source,
        "model_registry_id": model_registry_id,
        "mapper_id": mapper_id,
        "transaction_id": transaction_id,
        "policy_snapshot": policy_snapshot or {},
        "mapper_validation": mapper_validation or {},
    }


async def _validate_fraud_mapper_contract(
    db,
    *,
    route,
    raw_payload: dict,
) -> tuple[dict | None, dict]:
    if not route.mapper_id:
        # Non-strict mode may use model defaults without an active mapper.
        return None, {"validated": False, "reason": "no_active_mapper"}
    mapper = await db.get(TenantMapper, route.mapper_id)
    if not mapper:
        raise HTTPException(status_code=422, detail={"code": "mapper_not_configured", "errors": ["Active mapper not found."]})
    canonical, errors = validate_and_dry_run(
        model_type="fraud",
        contract_version=route.contract_version or mapper.contract_version,
        mapping_json=dict(mapper.mapping_json or {}),
        raw_payload=raw_payload,
    )
    if errors:
        raise HTTPException(status_code=422, detail={"code": "mapper_contract_validation_failed", "errors": errors})
    return canonical, {
        "validated": True,
        "mapper_id": str(mapper.id),
        "mapper_version": mapper.mapper_version,
        "contract_version": route.contract_version or mapper.contract_version,
    }


async def _resolve_active_calibration(db, *, tenant_id, model_version: str) -> CalibrationArtifact | None:
    return (
        await db.execute(
            select(CalibrationArtifact).where(
                CalibrationArtifact.tenant_id == tenant_id,
                CalibrationArtifact.model_type == "fraud",
                CalibrationArtifact.model_version == model_version,
                CalibrationArtifact.status == "active",
            )
        )
    ).scalar_one_or_none()


def _shadow_decision_from_policy(score: float, policy_snapshot: dict | None) -> str:
    p = dict(policy_snapshot or {})
    block_t = float(p.get("fraud_block_threshold") or 0.85)
    otp_t = float(p.get("fraud_otp_threshold") or 0.65)
    if score >= block_t:
        return "BLOCK"
    if score >= otp_t:
        return "REQUEST_OTP"
    return "APPROVE"


@router.post("/predict", response_model=PredictOut)
async def predict(
    payload: PredictIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    t0 = time.perf_counter()
    tx_ts = datetime.utcnow()
    customer = await _ensure_customer(db, bank, payload.account_id)
    route = await resolve_model_route(
        db,
        tenant_id=bank.id,
        model_type="fraud",
        strict_mapper=bool(settings.strict_mapper_enforcement),
    )
    _canonical_payload, mapper_validation_meta = await _validate_fraud_mapper_contract(
        db,
        route=route,
        raw_payload={
            "transaction_id": f"pred-{int(t0)}",
            "account_id": payload.account_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "channel": "api",
            "device_id": payload.device_id,
            "ip_address": payload.ip_address,
            "merchant_id": payload.merchant_id,
            "location_country": (payload.location[:2].upper() if payload.location and len(payload.location) >= 2 else None),
            "tx_timestamp": tx_ts.isoformat(),
            "velocity_1h": None,
        },
    )
    loc_country = payload.location[:2].upper() if payload.location and len(payload.location) >= 2 else None

    ip_hash = payload.ip_address[:64] if payload.ip_address else None
    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=f"pred-{int(t0)}",
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=None,
        merchant_id=payload.merchant_id,
        device_id=payload.device_id,
        ip_address_hash=ip_hash,
        location_country=loc_country,
        channel="api",
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()

    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, None, payload.merchant_id,
        payload.device_id, "api", tx_ts, float(customer.risk_score),
        location_country=loc_country,
        ip_address=ip_hash,
        biometrics=getattr(payload, "biometrics", None),
    )
    lgbm, iso_sc, rule_sc, network_risk, ensemble, decision, confidence, shap, reason_codes, rule_reasons, _graph_risk, policy_snapshot = await score_and_explain(
        db,
        str(bank.id),
        fv,
        tenant_tone_config=bank.tone_config,
        model_artifact_uri=route.artifact_uri,
        strict_artifact=bool(route.model_registry_id),
    )
    raw_ensemble = float(ensemble)
    calibration = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=route.model_version)
    if calibration:
        ensemble = apply_calibration(
            raw_ensemble,
            method=calibration.method,
            params=dict(calibration.params_json or {}),
        )
    shadow_meta = None
    if settings.shadow_scoring_enabled:
        shadow = await resolve_shadow_candidate(db, tenant_id=bank.id, model_type="fraud")
        if shadow:
            _, _, _, _, shadow_raw_ensemble, _, _, _, _, _, _, _ = await score_and_explain(
                db,
                str(bank.id),
                fv,
                tenant_tone_config=bank.tone_config,
                model_artifact_uri=shadow.artifact_uri,
                strict_artifact=True,
            )
            shadow_cal = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=shadow.version)
            shadow_score = apply_calibration(
                float(shadow_raw_ensemble),
                method=(shadow_cal.method if shadow_cal else "none"),
                params=(dict(shadow_cal.params_json or {}) if shadow_cal else {}),
            )
            shadow_meta = {
                "candidate_model_registry_id": str(shadow.id),
                "candidate_model_version": shadow.version,
                "candidate_score": round(float(shadow_score), 6),
                "candidate_decision": _shadow_decision_from_policy(float(shadow_score), policy_snapshot),
                "candidate_calibration_id": str(shadow_cal.id) if shadow_cal else None,
                "candidate_calibration_method": shadow_cal.method if shadow_cal else "none",
            }
    effective_decision, control_notes = _enforce_decision_controls(
        bank=bank,
        payload=payload,
        feature_vector=fv,
        ensemble_score=float(ensemble),
        network_risk_score=float(network_risk) if network_risk is not None else None,
        decision=decision,
    )
    reason = "; ".join(rule_reasons) if rule_reasons else "; ".join(reason_codes[:3])
    if not reason:
        reason = "Model and rule evaluation"
    if control_notes:
        reason = f"{reason}; {' '.join(control_notes)}"

    decision_db = DECISION_NORMALIZATION.get((effective_decision or ""), (effective_decision or ""))
    confidence_db = (confidence or "")[:6]
    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm)),
        isolation_score=Decimal(str(iso_sc)) if iso_sc is not None else None,
        rule_score=Decimal(str(rule_sc)),
        ensemble_score=Decimal(str(ensemble)),
        decision=decision_db,
        confidence=confidence_db,
        shap_values=shap,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    score_row.model_version = route.model_version or MODEL_VERSION
    db.add(score_row)
    _add_alert_if_needed(
        db=db,
        bank=bank,
        customer=customer,
        txn=txn,
        decision=effective_decision,
        risk_score=float(ensemble),
    )
    await update_entity_maps(db, bank.id, customer.id, payload.device_id, ip_hash, payload.merchant_id, tx_ts)
    fp_id = fv.get("_fingerprint_id") or compute_transaction_fingerprint(
        str(customer.id), payload.device_id, ip_hash, payload.merchant_id,
        float(payload.amount), tx_ts.hour,
    )
    await store_fingerprint(db, bank.id, txn.id, fp_id, payload.device_id, ip_hash, payload.merchant_id)
    db.add(
        InferenceTrace(
            tenant_id=bank.id,
            model_type="fraud",
            model_version=route.model_version,
            mapper_version=route.mapper_version,
            contract_version=route.contract_version,
            decision=effective_decision,
            processing_ms=int((time.perf_counter() - t0) * 1000),
            trace_json=_trace_payload(
                route.source,
                route.model_registry_id,
                route.mapper_id,
                policy_snapshot,
                {
                    **mapper_validation_meta,
                    "calibration_id": str(calibration.id) if calibration else None,
                    "calibration_method": calibration.method if calibration else "none",
                    "shadow": shadow_meta,
                },
                transaction_id=str(txn.id),
            ),
        )
    )
    await db.flush()
    return PredictOut(
        risk_score=round(ensemble, 4),
        decision=effective_decision,
        reason=reason,
        model_score=round(lgbm, 4),
        anomaly_score=round(iso_sc, 4) if iso_sc is not None else None,
        rule_score=round(rule_sc, 4),
        processing_time_ms=int((time.perf_counter() - t0) * 1000),
    )


@router.post("/score", response_model=FraudScoreOut)
async def score_transaction(
    payload: TransactionIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    t0 = time.perf_counter()
    try:
        tx_ts = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
    except Exception:
        tx_ts = datetime.utcnow()

    customer = await _ensure_customer(db, bank, payload.account_id)
    route = await resolve_model_route(
        db,
        tenant_id=bank.id,
        model_type="fraud",
        strict_mapper=bool(settings.strict_mapper_enforcement),
    )
    _canonical_payload, mapper_validation_meta = await _validate_fraud_mapper_contract(
        db,
        route=route,
        raw_payload={
            "transaction_id": payload.transaction_id,
            "account_id": payload.account_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "channel": payload.channel or "api",
            "device_id": payload.device_id,
            "ip_address": payload.ip_address,
            "merchant_id": payload.merchant_id or payload.merchant_category,
            "location_country": _location_country(payload),
            "tx_timestamp": payload.timestamp,
            "velocity_1h": None,
        },
    )
    loc_country = _location_country(payload)

    ip_hash = payload.ip_address[:64] if payload.ip_address else None
    merchant_entity_id = payload.merchant_id or payload.merchant_category
    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=payload.transaction_id,
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=payload.merchant_category,
        merchant_id=merchant_entity_id,
        device_id=payload.device_id,
        ip_address_hash=ip_hash,
        location_country=loc_country,
        channel=payload.channel,
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()

    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, payload.merchant_category, merchant_entity_id,
        payload.device_id, payload.channel, tx_ts, float(customer.risk_score),
        location_country=loc_country,
        ip_address=ip_hash,
        biometrics=getattr(payload, "biometrics", None),
    )

    lgbm_score, iso_score, rule_score_val, network_risk_score, ensemble_score, decision, confidence, shap_values, reason_codes, rule_reasons, graph_risk_score, policy_snapshot = await score_and_explain(
        db,
        str(bank.id),
        fv,
        tenant_tone_config=bank.tone_config,
        model_artifact_uri=route.artifact_uri,
        strict_artifact=bool(route.model_registry_id),
    )
    raw_ensemble = float(ensemble_score)
    calibration = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=route.model_version)
    if calibration:
        ensemble_score = apply_calibration(
            raw_ensemble,
            method=calibration.method,
            params=dict(calibration.params_json or {}),
        )
    shadow_meta = None
    if settings.shadow_scoring_enabled:
        shadow = await resolve_shadow_candidate(db, tenant_id=bank.id, model_type="fraud")
        if shadow:
            _, _, _, _, shadow_raw_ensemble, _, _, _, _, _, _, _ = await score_and_explain(
                db,
                str(bank.id),
                fv,
                tenant_tone_config=bank.tone_config,
                model_artifact_uri=shadow.artifact_uri,
                strict_artifact=True,
            )
            shadow_cal = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=shadow.version)
            shadow_score = apply_calibration(
                float(shadow_raw_ensemble),
                method=(shadow_cal.method if shadow_cal else "none"),
                params=(dict(shadow_cal.params_json or {}) if shadow_cal else {}),
            )
            shadow_meta = {
                "candidate_model_registry_id": str(shadow.id),
                "candidate_model_version": shadow.version,
                "candidate_score": round(float(shadow_score), 6),
                "candidate_decision": _shadow_decision_from_policy(float(shadow_score), policy_snapshot),
                "candidate_calibration_id": str(shadow_cal.id) if shadow_cal else None,
                "candidate_calibration_method": shadow_cal.method if shadow_cal else "none",
            }
    effective_decision, control_notes = _enforce_decision_controls(
        bank=bank,
        payload=payload,
        feature_vector=fv,
        ensemble_score=float(ensemble_score),
        network_risk_score=float(network_risk_score) if network_risk_score is not None else None,
        decision=decision,
    )
    # Persist network_risk_score inside the feature vector for analytics.
    fv["network_risk_score"] = float(network_risk_score)
    if effective_decision == "BLOCK":
        txn.status = "DECLINED"
    elif effective_decision == "REQUEST_OTP":
        txn.status = "PENDING_REVIEW"
    elif effective_decision == "LIMITED_APPROVAL":
        txn.status = "PENDING_REVIEW"

    decision_db = DECISION_NORMALIZATION.get((effective_decision or ""), (effective_decision or ""))
    confidence_db = (confidence or "")[:6]
    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm_score)),
        isolation_score=Decimal(str(iso_score)) if iso_score is not None else None,
        rule_score=Decimal(str(rule_score_val)),
        ensemble_score=Decimal(str(ensemble_score)),
        decision=decision_db,
        confidence=confidence_db,
        shap_values=shap_values,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    score_row.model_version = route.model_version or MODEL_VERSION
    db.add(score_row)

    shadow_mode = bool((bank.tone_config or {}).get("fraud_policy", {}).get("shadow_mode", False))
    if not shadow_mode:
        _add_alert_if_needed(
            db=db,
            bank=bank,
            customer=customer,
            txn=txn,
            decision=effective_decision,
            risk_score=float(ensemble_score),
        )
    await update_entity_maps(
        db, bank.id, customer.id,
        payload.device_id, ip_hash, merchant_entity_id, tx_ts,
    )
    fp_id = fv.get("_fingerprint_id") or compute_transaction_fingerprint(
        str(customer.id), payload.device_id, ip_hash, merchant_entity_id,
        float(payload.amount), tx_ts.hour,
    )
    await store_fingerprint(db, bank.id, txn.id, fp_id, payload.device_id, ip_hash, merchant_entity_id)

    audit = AuditLog(
        tenant_id=bank.id,
        event_type="FRAUD_SCORE",
        entity_type="transaction",
        entity_id=txn.id,
        actor_type="api",
        event_data={
            "transaction_id": payload.transaction_id,
            "decision": effective_decision,
            "ensemble_score": float(ensemble_score),
            "policy_snapshot": policy_snapshot,
            "rule_reasons": rule_reasons,
            "control_notes": control_notes,
        },
    )
    db.add(audit)
    db.add(
        InferenceTrace(
            tenant_id=bank.id,
            model_type="fraud",
            model_version=route.model_version,
            mapper_version=route.mapper_version,
            contract_version=route.contract_version,
            decision=effective_decision,
            processing_ms=int((time.perf_counter() - t0) * 1000),
            trace_json=_trace_payload(
                route.source,
                route.model_registry_id,
                route.mapper_id,
                policy_snapshot,
                {
                    **mapper_validation_meta,
                    "calibration_id": str(calibration.id) if calibration else None,
                    "calibration_method": calibration.method if calibration else "none",
                    "shadow": shadow_meta,
                },
                transaction_id=str(txn.id),
            ),
        )
    )
    await db.flush()
    processing_ms = int((time.perf_counter() - t0) * 1000)

    # Emit Prometheus metrics
    record_fraud_decision(str(bank.id), effective_decision, float(ensemble_score))
    _logger.info(
        "fraud_scored",
        tenant_id=str(bank.id),
        decision=effective_decision,
        ensemble_score=float(ensemble_score),
        processing_ms=processing_ms,
        impossible_travel=float(fv.get("impossible_travel", 0.0)),
        biometric_confidence=float(fv.get("biometric_confidence", 0.5)),
    )

    return FraudScoreOut(
        transaction_id=payload.transaction_id,
        decision=effective_decision,
        fraud_score=float(ensemble_score),
        confidence=confidence,
        reasons=reason_codes + rule_reasons + control_notes,
        recommended_action=recommended_action(effective_decision),
        processing_time_ms=processing_ms,
    )


@router.post("/score/detail", response_model=ScoreDetailOut)
async def score_transaction_detail(
    payload: TransactionIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    t0 = time.perf_counter()
    try:
        tx_ts = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
    except Exception:
        tx_ts = datetime.utcnow()
    customer = await _ensure_customer(db, bank, payload.account_id)
    route = await resolve_model_route(
        db,
        tenant_id=bank.id,
        model_type="fraud",
        strict_mapper=bool(settings.strict_mapper_enforcement),
    )
    _canonical_payload, mapper_validation_meta = await _validate_fraud_mapper_contract(
        db,
        route=route,
        raw_payload={
            "transaction_id": payload.transaction_id,
            "account_id": payload.account_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "channel": payload.channel or "api",
            "device_id": payload.device_id,
            "ip_address": payload.ip_address,
            "merchant_id": payload.merchant_id or payload.merchant_category,
            "location_country": _location_country(payload),
            "tx_timestamp": payload.timestamp,
            "velocity_1h": None,
        },
    )
    loc_country = _location_country(payload)
    ip_hash = payload.ip_address[:64] if payload.ip_address else None
    merchant_entity_id = payload.merchant_id or payload.merchant_category
    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=payload.transaction_id,
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=payload.merchant_category,
        merchant_id=merchant_entity_id,
        device_id=payload.device_id,
        ip_address_hash=ip_hash,
        location_country=loc_country,
        channel=None,
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()
    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, payload.merchant_category, merchant_entity_id,
        payload.device_id, payload.channel, tx_ts, float(customer.risk_score),
        location_country=loc_country,
        ip_address=ip_hash,
        biometrics=getattr(payload, "biometrics", None),
    )
    lgbm_score, iso_score, rule_score_val, network_risk_score, ensemble_score, decision, confidence, shap_values, reason_codes, rule_reasons, graph_risk_score, policy_snapshot = await score_and_explain(
        db,
        str(bank.id),
        fv,
        tenant_tone_config=bank.tone_config,
        model_artifact_uri=route.artifact_uri,
        strict_artifact=bool(route.model_registry_id),
    )
    raw_ensemble = float(ensemble_score)
    calibration = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=route.model_version)
    if calibration:
        ensemble_score = apply_calibration(
            raw_ensemble,
            method=calibration.method,
            params=dict(calibration.params_json or {}),
        )
    shadow_meta = None
    if settings.shadow_scoring_enabled:
        shadow = await resolve_shadow_candidate(db, tenant_id=bank.id, model_type="fraud")
        if shadow:
            _, _, _, _, shadow_raw_ensemble, _, _, _, _, _, _, _ = await score_and_explain(
                db,
                str(bank.id),
                fv,
                tenant_tone_config=bank.tone_config,
                model_artifact_uri=shadow.artifact_uri,
                strict_artifact=True,
            )
            shadow_cal = await _resolve_active_calibration(db, tenant_id=bank.id, model_version=shadow.version)
            shadow_score = apply_calibration(
                float(shadow_raw_ensemble),
                method=(shadow_cal.method if shadow_cal else "none"),
                params=(dict(shadow_cal.params_json or {}) if shadow_cal else {}),
            )
            shadow_meta = {
                "candidate_model_registry_id": str(shadow.id),
                "candidate_model_version": shadow.version,
                "candidate_score": round(float(shadow_score), 6),
                "candidate_decision": _shadow_decision_from_policy(float(shadow_score), policy_snapshot),
                "candidate_calibration_id": str(shadow_cal.id) if shadow_cal else None,
                "candidate_calibration_method": shadow_cal.method if shadow_cal else "none",
            }
    effective_decision, control_notes = _enforce_decision_controls(
        bank=bank,
        payload=payload,
        feature_vector=fv,
        ensemble_score=float(ensemble_score),
        network_risk_score=float(network_risk_score) if network_risk_score is not None else None,
        decision=decision,
    )
    fv["network_risk_score"] = float(network_risk_score)
    await update_entity_maps(db, bank.id, customer.id, payload.device_id, ip_hash, merchant_entity_id, tx_ts)
    fp_id = fv.get("_fingerprint_id") or compute_transaction_fingerprint(
        str(customer.id), payload.device_id, ip_hash, merchant_entity_id,
        float(payload.amount), tx_ts.hour,
    )
    await store_fingerprint(db, bank.id, txn.id, fp_id, payload.device_id, ip_hash, merchant_entity_id)
    decision_db = DECISION_NORMALIZATION.get((effective_decision or ""), (effective_decision or ""))
    confidence_db = (confidence or "")[:6]
    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm_score)),
        isolation_score=Decimal(str(iso_score)) if iso_score is not None else None,
        rule_score=Decimal(str(rule_score_val)),
        ensemble_score=Decimal(str(ensemble_score)),
        decision=decision_db,
        confidence=confidence_db,
        shap_values=shap_values,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    score_row.model_version = route.model_version or MODEL_VERSION
    db.add(score_row)
    shadow_mode = bool((bank.tone_config or {}).get("fraud_policy", {}).get("shadow_mode", False))
    if not shadow_mode:
        _add_alert_if_needed(
            db=db,
            bank=bank,
            customer=customer,
            txn=txn,
            decision=effective_decision,
            risk_score=float(ensemble_score),
        )
    db.add(
        InferenceTrace(
            tenant_id=bank.id,
            model_type="fraud",
            model_version=route.model_version,
            mapper_version=route.mapper_version,
            contract_version=route.contract_version,
            decision=effective_decision,
            processing_ms=int((time.perf_counter() - t0) * 1000),
            trace_json=_trace_payload(
                route.source,
                route.model_registry_id,
                route.mapper_id,
                policy_snapshot,
                {
                    **mapper_validation_meta,
                    "calibration_id": str(calibration.id) if calibration else None,
                    "calibration_method": calibration.method if calibration else "none",
                    "shadow": shadow_meta,
                },
                transaction_id=str(txn.id),
            ),
        )
    )
    await db.flush()
    return ScoreDetailOut(
        transaction_id=payload.transaction_id,
        risk_score=float(ensemble_score),
        model_score=float(lgbm_score),
        anomaly_score=float(iso_score) if iso_score is not None else None,
        rule_score=float(rule_score_val),
        network_risk_score=float(network_risk_score),
        graph_risk_score=float(graph_risk_score),
        decision=effective_decision,
        reasons=reason_codes + control_notes,
        rule_reasons=rule_reasons,
        shap_values=shap_values,
        processing_time_ms=int((time.perf_counter() - t0) * 1000),
    )


@router.get("/alerts", response_model=list[AlertOut])
async def get_alerts(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    status: str | None = Query(None, description="OPEN, CLOSED"),
    limit: int = Query(50, le=200),
):
    q = select(FraudAlert).where(FraudAlert.tenant_id == bank.id).order_by(FraudAlert.created_at.desc()).limit(limit)
    if status:
        q = q.where(FraudAlert.status == status)
    r = await db.execute(q)
    alerts = list(r.scalars().all())
    out = []
    for a in alerts:
        acc = None
        if a.customer_id:
            c = (await db.execute(select(Customer).where(Customer.id == a.customer_id))).scalar_one_or_none()
            if c:
                acc = c.external_id
        out.append(AlertOut(
            alert_id=str(a.id),
            transaction_id=str(a.transaction_id),
            account_id=acc,
            alert_type=a.alert_type,
            severity=a.severity,
            status=a.status,
            created_at=a.created_at.isoformat() if a.created_at else "",
        ))
    return out


@router.patch("/alerts/{alert_id}", response_model=AlertOut)
async def update_alert_status(
    alert_id: UUID,
    payload: AlertStatusUpdate,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    allowed = {"OPEN", "CLOSED"}
    new_status = str(payload.status or "").upper()
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of: {sorted(allowed)}")

    alert = (
        await db.execute(
            select(FraudAlert).where(FraudAlert.tenant_id == bank.id, FraudAlert.id == alert_id)
        )
    ).scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = new_status
    if payload.assigned_to is not None:
        alert.assigned_to = payload.assigned_to
    await db.flush()

    acc = None
    if alert.customer_id:
        c = (await db.execute(select(Customer).where(Customer.id == alert.customer_id))).scalar_one_or_none()
        if c:
            acc = c.external_id

    return AlertOut(
        alert_id=str(alert.id),
        transaction_id=str(alert.transaction_id),
        account_id=acc,
        alert_type=alert.alert_type,
        severity=alert.severity,
        status=alert.status,
        created_at=alert.created_at.isoformat() if alert.created_at else "",
    )


@router.get("/customer-risk/{account_id}", response_model=CustomerRiskOut)
async def customer_risk(
    account_id: str,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    cust = (await db.execute(select(Customer).where(Customer.tenant_id == bank.id, Customer.external_id == account_id))).scalar_one_or_none()
    if not cust:
        return CustomerRiskOut(account_id=account_id, risk_score=0.0, avg_transaction=None, max_transaction=None, usual_location=None, transaction_frequency_7d=None)
    prof = (await db.execute(
        select(CustomerBehaviourProfile).where(
            CustomerBehaviourProfile.tenant_id == bank.id,
            CustomerBehaviourProfile.customer_id == cust.id,
        )
    )).scalar_one_or_none()
    return CustomerRiskOut(
        account_id=account_id,
        risk_score=float(cust.risk_score),
        avg_transaction=float(prof.avg_transaction) if prof and prof.avg_transaction else None,
        max_transaction=float(prof.max_transaction) if prof and prof.max_transaction else None,
        usual_location=prof.usual_location_country if prof else None,
        transaction_frequency_7d=float(prof.transaction_frequency_7d) if prof and prof.transaction_frequency_7d else None,
    )


@router.post("/device-check", response_model=DeviceCheckOut)
async def device_check(
    payload: PredictIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    device_id = payload.device_id or "unknown"
    black = (await db.execute(
        select(Blacklist).where(
            Blacklist.tenant_id == bank.id,
            Blacklist.entity_type == "device",
            Blacklist.value == device_id,
        )
    )).scalar_one_or_none()
    if black:
        return DeviceCheckOut(device_id=device_id, is_known=False, risk="BLOCKED", reason=black.reason or "Device blacklisted")
    dev = (await db.execute(
        select(DeviceFingerprint).where(
            DeviceFingerprint.tenant_id == bank.id,
            DeviceFingerprint.device_id == device_id,
        )
    )).scalar_one_or_none()
    if dev:
        return DeviceCheckOut(device_id=device_id, is_known=True, risk="LOW", reason=None)
    return DeviceCheckOut(device_id=device_id, is_known=False, risk="NEW_DEVICE", reason="First time seen; may require OTP")


@router.get("/transactions", response_model=list[TransactionSummaryOut])
async def list_transactions(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    account_id: str | None = Query(None, description="Optional customer external_id to filter by account"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0, le=200000),
):
    """
    List recent transactions for this tenant, optionally filtered by customer external_id (account_id).
    Includes latest fraud decision and score if available.
    """
    # Base query: join Transaction -> Customer (for external_id) and left join FraudScore
    tx = Transaction
    cust = Customer
    fs = FraudScore

    stmt = (
        select(
            tx.id,
            cust.external_id,
            tx.amount,
            tx.currency,
            tx.merchant_category,
            tx.location_country,
            tx.channel,
            tx.status,
            tx.tx_timestamp,
            fs.decision,
            fs.ensemble_score,
        )
        .join(cust, cust.id == tx.customer_id)
        .where(tx.tenant_id == bank.id)
        .outerjoin(
            fs,
            fs.transaction_id == tx.id,
        )
        .order_by(tx.tx_timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    if account_id:
        stmt = stmt.where(cust.external_id == account_id)

    res = await db.execute(stmt)
    rows = res.all()
    out: list[TransactionSummaryOut] = []
    decision_norm = DECISION_NORMALIZATION
    for (
        tx_id,
        ext_id,
        amount,
        currency,
        mcc,
        loc_country,
        channel,
        status,
        tx_ts,
        decision,
        ensemble_score,
    ) in rows:
        dec = decision_norm.get(decision, decision)
        out.append(
            TransactionSummaryOut(
                transaction_id=str(tx_id),
                account_id=ext_id,
                amount=float(amount),
                currency=currency,
                merchant_category=mcc,
                location_country=loc_country,
                channel=channel,
                status=status,
                decision=dec,
                fraud_score=float(ensemble_score) if ensemble_score is not None else None,
                created_at=tx_ts.isoformat() if tx_ts else "",
            )
        )
    return out


def _transaction_detail_from_row(row, decision_norm):
    (
        tx_id,
        external_tx_id,
        ext_id,
        amount,
        currency,
        mcc,
        loc_country,
        channel,
        status,
        tx_ts,
        decision,
        confidence,
        ensemble_score,
        lgbm_score,
        iso_score,
        rule_score_val,
        model_version,
        processing_ms,
        reason_codes,
        shap_values,
        feature_vector,
    ) = row
    dec = decision_norm.get(decision, decision)
    return TransactionDetailOut(
        transaction_id=str(tx_id),
        external_tx_id=external_tx_id,
        account_id=ext_id,
        amount=float(amount),
        currency=currency,
        merchant_category=mcc,
        location_country=loc_country,
        channel=channel,
        status=status,
        tx_timestamp=tx_ts.isoformat() if tx_ts else "",
        decision=dec,
        confidence=confidence,
        fraud_score=float(ensemble_score) if ensemble_score is not None else None,
        lgbm_score=float(lgbm_score) if lgbm_score is not None else None,
        anomaly_score=float(iso_score) if iso_score is not None else None,
        rule_score=float(rule_score_val) if rule_score_val is not None else None,
        model_version=model_version,
        processing_time_ms=processing_ms,
        reasons=list(reason_codes) if reason_codes is not None else None,
        shap_values=shap_values,
        feature_vector=feature_vector,
    )


@router.get("/transactions/detail-by-external-id/{external_tx_id}", response_model=TransactionDetailOut)
async def transaction_detail_by_external_id(
    external_tx_id: str,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    """
    Fraud result for a transaction by core-banking (external) transaction id.
    Use this so the bank's core banking team can look up decision, score, reasons by their ledger id (e.g. cb-tr-xxx).
    """
    tx = Transaction
    cust = Customer
    fs = FraudScore
    decision_norm = DECISION_NORMALIZATION
    stmt = (
        select(
            tx.id,
            tx.external_tx_id,
            cust.external_id,
            tx.amount,
            tx.currency,
            tx.merchant_category,
            tx.location_country,
            tx.channel,
            tx.status,
            tx.tx_timestamp,
            fs.decision,
            fs.confidence,
            fs.ensemble_score,
            fs.lgbm_score,
            fs.isolation_score,
            fs.rule_score,
            fs.model_version,
            fs.processing_ms,
            fs.reason_codes,
            fs.shap_values,
            fs.feature_vector,
        )
        .join(cust, cust.id == tx.customer_id)
        .outerjoin(fs, fs.transaction_id == tx.id)
        .where(tx.tenant_id == bank.id, tx.external_tx_id == external_tx_id)
        .limit(1)
    )
    row = (await db.execute(stmt)).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _transaction_detail_from_row(row, decision_norm)


@router.get("/transactions/{transaction_id}/detail", response_model=TransactionDetailOut)
async def transaction_detail(
    transaction_id: str,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    """
    Detailed view for a scored transaction (used by admin UI).
    """
    tx = Transaction
    cust = Customer
    fs = FraudScore
    decision_norm = DECISION_NORMALIZATION

    stmt = (
        select(
            tx.id,
            tx.external_tx_id,
            cust.external_id,
            tx.amount,
            tx.currency,
            tx.merchant_category,
            tx.location_country,
            tx.channel,
            tx.status,
            tx.tx_timestamp,
            fs.decision,
            fs.confidence,
            fs.ensemble_score,
            fs.lgbm_score,
            fs.isolation_score,
            fs.rule_score,
            fs.model_version,
            fs.processing_ms,
            fs.reason_codes,
            fs.shap_values,
            fs.feature_vector,
        )
        .join(cust, cust.id == tx.customer_id)
        .outerjoin(fs, fs.transaction_id == tx.id)
        .where(tx.tenant_id == bank.id, tx.id == transaction_id)
        .limit(1)
    )
    row = (await db.execute(stmt)).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _transaction_detail_from_row(row, decision_norm)


@router.get("/network/graph", response_model=NetworkGraphOut)
async def get_network_graph(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    since_days: int = Query(30, ge=1, le=90),
):
    """Nodes and edges for fraud network visualization (accounts, devices, IPs, merchants); includes risk_scores per node."""
    dev_acc, ip_acc, mer_acc, conns = await get_tenant_graph_data(db, str(bank.id), since_days=since_days)
    G, rings = build_graph_and_rings(dev_acc, ip_acc, mer_acc, conns)
    nodes, edges, risk_scores = [], [], []
    if G is not None:
        for n in G.nodes():
            t = G.nodes[n].get("type", "account")
            nodes.append(NetworkNodeOut(id=n, type=t))
            deg = G.degree(n)
            rs = min(1.0, deg / 5.0) if t in ("device", "ip") else min(1.0, deg / 10.0)
            risk_scores.append(NodeRiskOut(node_id=n, risk_score=round(rs, 4)))
        for u, v, data in G.edges(data=True):
            edges.append(NetworkEdgeOut(source=u, target=v, rel=data.get("rel", "link")))
    else:
        seen = set()
        for dev, acc in dev_acc:
            a, d = f"acc:{acc}", f"dev:{dev}"
            if d not in seen:
                nodes.append(NetworkNodeOut(id=d, type="device"))
                seen.add(d)
            if a not in seen:
                nodes.append(NetworkNodeOut(id=a, type="account"))
                seen.add(a)
            edges.append(NetworkEdgeOut(source=d, target=a, rel="used_device"))
        for ip, acc in ip_acc:
            a, i = f"acc:{acc}", f"ip:{ip}"
            if i not in seen:
                nodes.append(NetworkNodeOut(id=i, type="ip"))
                seen.add(i)
            if a not in seen:
                nodes.append(NetworkNodeOut(id=a, type="account"))
                seen.add(a)
            edges.append(NetworkEdgeOut(source=i, target=a, rel="used_ip"))
    return NetworkGraphOut(nodes=nodes, edges=edges, risk_scores=risk_scores if risk_scores else None)


@router.get("/network/rings", response_model=list[FraudRingOut])
async def get_fraud_rings(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    since_days: int = Query(30, ge=1, le=90),
):
    """Detected device rings, IP rings, merchant hubs, circular flows."""
    dev_acc, ip_acc, mer_acc, conns = await get_tenant_graph_data(db, str(bank.id), since_days=since_days)
    _, rings = build_graph_and_rings(dev_acc, ip_acc, mer_acc, conns)
    return [
        FraudRingOut(
            type=r["type"],
            entity_id=r.get("entity_id"),
            account_count=r.get("account_count"),
            nodes=r.get("nodes"),
            size=r.get("size"),
        )
        for r in rings
    ]


@router.get("/network/analytics", response_model=NetworkAnalyticsOut)
async def get_network_analytics(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    since_days: int = Query(30, ge=1, le=90),
):
    """Aggregates: accounts per device, fraud clusters, shared IP usage, high-risk merchants."""
    dev_acc, ip_acc, _, _ = await get_tenant_graph_data(db, str(bank.id), since_days=since_days)
    dev_counts: dict[str, int] = {}
    for dev, acc in dev_acc:
        dev_counts[dev] = dev_counts.get(dev, 0) + 1
    accounts_per_device = [{"device_id": k, "account_count": v} for k, v in sorted(dev_counts.items(), key=lambda x: -x[1])[:50]]
    ip_counts: dict[str, int] = {}
    for ip, acc in ip_acc:
        ip_counts[ip] = ip_counts.get(ip, 0) + 1
    shared_ip = [{"ip": k, "account_count": v} for k, v in sorted(ip_counts.items(), key=lambda x: -x[1])[:50]]
    mr = (await db.execute(
        select(MerchantRisk.merchant_id, MerchantRisk.fraud_rate, MerchantRisk.total_transactions)
        .where(MerchantRisk.tenant_id == bank.id)
        .order_by(MerchantRisk.fraud_rate.desc())
        .limit(50)
    )).all()
    high_risk_merchants = [{"merchant_id": m, "fraud_rate": float(r), "total_transactions": t} for m, r, t in mr]
    G, rings = build_graph_and_rings(dev_acc, ip_acc, [], [])
    fraud_clusters = [{"type": r["type"], "entity_id": r.get("entity_id"), "account_count": r.get("account_count")} for r in rings]
    return NetworkAnalyticsOut(
        accounts_per_device=accounts_per_device,
        fraud_clusters=fraud_clusters,
        shared_ip_usage=shared_ip,
        high_risk_merchants=high_risk_merchants,
    )


@router.post("/outcome")
async def label_fraud_outcome(
    payload: OutcomeIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    """
    Label a transaction outcome (fraud / legit) and update downstream stats.

    This populates FraudOutcome and bumps MerchantRisk / FingerprintStats fraud aggregates.
    """
    # Basic validation: ensure transaction belongs to this tenant.
    tx = (
        await db.execute(
            select(Transaction).where(
                and_(
                    Transaction.id == payload.transaction_id,
                    Transaction.tenant_id == bank.id,
                )
            )
        )
    ).scalar_one_or_none()
    if not tx:
        return {"status": "error", "detail": "Transaction not found for this tenant"}

    await apply_fraud_outcome(
        db=db,
        tenant_id=str(bank.id),
        transaction_id=str(tx.id),
        classification=payload.classification,
        source=payload.source,
        notes=payload.notes,
    )
    return {"status": "ok"}


@router.get("/metrics/summary", response_model=MetricsSummaryOut)
async def fraud_metrics_summary(
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
    limit: int = Query(500, le=5000),
):
    """
    Lightweight metrics endpoint for dashboards:
      - total scored transactions (sampled)
      - counts per decision
      - average ensemble_score
    """
    fs = FraudScore
    res = await db.execute(
        select(
            fs.decision,
            fs.ensemble_score,
        )
        .where(fs.tenant_id == bank.id)
        .order_by(fs.created_at.desc())
        .limit(limit)
    )
    rows = res.all()
    total = len(rows)
    by_decision: dict[str, int] = {}
    scores: list[float] = []
    for decision, ensemble_score in rows:
        if decision is None:
            continue
        by_decision[decision] = by_decision.get(decision, 0) + 1
        if ensemble_score is not None:
            scores.append(float(ensemble_score))
    avg = float(sum(scores) / len(scores)) if scores else None
    return MetricsSummaryOut(total=total, by_decision=by_decision, avg_ensemble_score=avg)


def _load_sorted_feature_importances(path: Path | str) -> list[FeatureImportanceOut]:
    import json

    p = Path(path)
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    fi = [
        FeatureImportanceOut(
            feature=str(item.get("feature")),
            importance_gain=float(item.get("importance_gain", 0.0)),
        )
        for item in data
        if isinstance(item, dict)
    ]
    fi.sort(key=lambda x: x.importance_gain, reverse=True)
    return fi[:50]


@router.get("/feature-importances", response_model=FeatureImportancesResponse)
async def get_feature_importances(
    bank: TenantBank = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    LightGBM gain importances from ``feature_importances.json`` (as written by ``app.ml.train``),
    preferring the **fraud artifact directory** returned by the same registry routing as live scoring
    (tenant active → global active → engine fallback without URI).

    If the routed bundle has no JSON beside ``lgb_fraud.txt``, falls back to the bundled default
    ``models/fraud`` (or ``MODEL_PATH``) directory so dashboards still show a baseline.

    Requires at least one **fraud** ``ModelRegistry`` row for this tenant.
    """
    if not await tenant_has_registered_model(db, tenant_id=bank.id, model_type="fraud"):
        raise HTTPException(
            status_code=403,
            detail="Register a fraud model for this tenant in Model registry before viewing feature importances.",
        )
    route = None
    try:
        route = await resolve_model_route(db, tenant_id=bank.id, model_type="fraud", strict_mapper=False)
    except HTTPException:
        route = None

    meta_base = FeatureImportancesMeta(
        route_source=route.source if route else None,
        model_version=route.model_version if route else None,
        artifact_uri=route.artifact_uri if route else None,
        resolved_from="none",
        reason=None,
    )

    if route and route.artifact_uri:
        routed_json = resolve_fraud_feature_importances_json_path(route.artifact_uri)
        if routed_json is not None:
            feats = _load_sorted_feature_importances(routed_json)
            return FeatureImportancesResponse(
                features=feats,
                meta=FeatureImportancesMeta(
                    route_source=route.source,
                    model_version=route.model_version,
                    artifact_uri=route.artifact_uri,
                    resolved_from="routed_artifact",
                    reason=None,
                ),
            )
        bdir = resolve_fraud_artifact_bundle_dir(route.artifact_uri)
        reason = "artifact_path_unresolved" if bdir is None else "missing_feature_importances_json"
        meta_base = FeatureImportancesMeta(
            route_source=route.source,
            model_version=route.model_version,
            artifact_uri=route.artifact_uri,
            resolved_from="global_default",
            reason=reason,
        )

    global_path = _get_models_path() / "feature_importances.json"
    feats = _load_sorted_feature_importances(global_path)
    if feats:
        return FeatureImportancesResponse(
            features=feats,
            meta=FeatureImportancesMeta(
                route_source=meta_base.route_source,
                model_version=meta_base.model_version,
                artifact_uri=meta_base.artifact_uri,
                resolved_from="global_default",
                reason=meta_base.reason,
            ),
        )

    return FeatureImportancesResponse(
        features=[],
        meta=FeatureImportancesMeta(
            route_source=meta_base.route_source,
            model_version=meta_base.model_version,
            artifact_uri=meta_base.artifact_uri,
            resolved_from="none",
            reason=meta_base.reason or "no_feature_importances_json_anywhere",
        ),
    )
