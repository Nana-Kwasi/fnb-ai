import time
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from app.database import get_db
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
)
from app.services.feature_engine import build_feature_vector
from app.services.fraud_engine import score_and_explain, recommended_action, MODEL_VERSION

router = APIRouter()

THRESHOLD_BLOCK = 0.85
THRESHOLD_OTP = 0.60


class TransactionIn(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    currency: str
    merchant_category: str | None = None
    location: str | None = None
    device_id: str | None = None
    timestamp: str


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


def _location_country(payload: TransactionIn) -> str | None:
    if not payload.location or len(payload.location) < 2:
        return None
    return payload.location[:2].upper()


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


@router.post("/predict", response_model=PredictOut)
async def predict(
    payload: PredictIn,
    bank: TenantBank = Depends(resolve_tenant),
    db=Depends(get_db),
):
    t0 = time.perf_counter()
    tx_ts = datetime.utcnow()
    customer = await _ensure_customer(db, bank, payload.account_id)
    loc_country = payload.location[:2].upper() if payload.location and len(payload.location) >= 2 else None

    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=f"pred-{int(t0)}",
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=None,
        device_id=payload.device_id,
        location_country=loc_country,
        channel="api",
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()

    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, None,
        payload.device_id, None, tx_ts, float(customer.risk_score),
        location_country=loc_country,
    )
    lgbm, iso_sc, rule_sc, ensemble, decision, confidence, shap, reason_codes, rule_reasons = score_and_explain(
        fv, threshold_block=THRESHOLD_BLOCK, threshold_otp=THRESHOLD_OTP
    )
    reason = "; ".join(rule_reasons) if rule_reasons else "; ".join(reason_codes[:3])
    if not reason:
        reason = "Model and rule evaluation"

    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm)),
        isolation_score=Decimal(str(iso_sc)) if iso_sc is not None else None,
        rule_score=Decimal(str(rule_sc)),
        ensemble_score=Decimal(str(ensemble)),
        decision=decision,
        confidence=confidence,
        shap_values=shap,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(score_row)
    if decision in ("BLOCK", "REQUEST_OTP"):
        alert = FraudAlert(
            tenant_id=bank.id,
            transaction_id=txn.id,
            customer_id=customer.id,
            alert_type="FRAUD_RISK",
            severity="HIGH" if decision == "BLOCK" else "MEDIUM",
            status="OPEN",
        )
        db.add(alert)
    await db.flush()
    return PredictOut(
        risk_score=round(ensemble, 4),
        decision=decision,
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
    loc_country = _location_country(payload)

    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=payload.transaction_id,
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=payload.merchant_category,
        device_id=payload.device_id,
        location_country=loc_country,
        channel=None,
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()

    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, payload.merchant_category,
        payload.device_id, None, tx_ts, float(customer.risk_score),
        location_country=loc_country,
    )

    lgbm_score, iso_score, rule_score_val, ensemble_score, decision, confidence, shap_values, reason_codes, rule_reasons = score_and_explain(
        fv, threshold_block=THRESHOLD_BLOCK, threshold_otp=THRESHOLD_OTP
    )
    if decision == "BLOCK":
        txn.status = "DECLINED"
    elif decision == "REQUEST_OTP":
        txn.status = "PENDING_REVIEW"

    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm_score)),
        isolation_score=Decimal(str(iso_score)) if iso_score is not None else None,
        rule_score=Decimal(str(rule_score_val)),
        ensemble_score=Decimal(str(ensemble_score)),
        decision=decision,
        confidence=confidence,
        shap_values=shap_values,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(score_row)

    if decision in ("BLOCK", "REQUEST_OTP"):
        alert = FraudAlert(
            tenant_id=bank.id,
            transaction_id=txn.id,
            customer_id=customer.id,
            alert_type="FRAUD_RISK",
            severity="HIGH" if decision == "BLOCK" else "MEDIUM",
            status="OPEN",
        )
        db.add(alert)

    audit = AuditLog(
        tenant_id=bank.id,
        event_type="FRAUD_SCORE",
        entity_type="transaction",
        entity_id=txn.id,
        actor_type="api",
        event_data={
            "transaction_id": payload.transaction_id,
            "decision": decision,
            "ensemble_score": float(ensemble_score),
            "rule_reasons": rule_reasons,
        },
    )
    db.add(audit)
    await db.flush()
    processing_ms = int((time.perf_counter() - t0) * 1000)

    return FraudScoreOut(
        transaction_id=payload.transaction_id,
        decision=decision,
        fraud_score=float(ensemble_score),
        confidence=confidence,
        reasons=reason_codes + rule_reasons,
        recommended_action=recommended_action(decision),
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
    loc_country = _location_country(payload)
    txn = Transaction(
        tenant_id=bank.id,
        customer_id=customer.id,
        external_tx_id=payload.transaction_id,
        amount=Decimal(str(payload.amount)),
        currency=payload.currency,
        merchant_category=payload.merchant_category,
        device_id=payload.device_id,
        location_country=loc_country,
        channel=None,
        tx_timestamp=tx_ts,
        status="PENDING",
    )
    db.add(txn)
    await db.flush()
    fv = await build_feature_vector(
        db, str(bank.id), str(customer.id),
        payload.amount, payload.currency, payload.merchant_category,
        payload.device_id, None, tx_ts, float(customer.risk_score),
        location_country=loc_country,
    )
    lgbm_score, iso_score, rule_score_val, ensemble_score, decision, confidence, shap_values, reason_codes, rule_reasons = score_and_explain(
        fv, threshold_block=THRESHOLD_BLOCK, threshold_otp=THRESHOLD_OTP
    )
    score_row = FraudScore(
        tenant_id=bank.id,
        transaction_id=txn.id,
        lgbm_score=Decimal(str(lgbm_score)),
        isolation_score=Decimal(str(iso_score)) if iso_score is not None else None,
        rule_score=Decimal(str(rule_score_val)),
        ensemble_score=Decimal(str(ensemble_score)),
        decision=decision,
        confidence=confidence,
        shap_values=shap_values,
        reason_codes=reason_codes,
        feature_vector=fv,
        model_version=MODEL_VERSION,
        processing_ms=int((time.perf_counter() - t0) * 1000),
    )
    db.add(score_row)
    if decision in ("BLOCK", "REQUEST_OTP"):
        db.add(FraudAlert(tenant_id=bank.id, transaction_id=txn.id, customer_id=customer.id, alert_type="FRAUD_RISK", severity="HIGH" if decision == "BLOCK" else "MEDIUM", status="OPEN"))
    await db.flush()
    return ScoreDetailOut(
        transaction_id=payload.transaction_id,
        risk_score=float(ensemble_score),
        model_score=float(lgbm_score),
        anomaly_score=float(iso_score) if iso_score is not None else None,
        rule_score=float(rule_score_val),
        decision=decision,
        reasons=reason_codes,
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
