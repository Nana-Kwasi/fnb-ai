import hashlib
import hmac
import asyncio
import secrets
import uuid
import csv
import io
import json
import os
import subprocess
import sys
import time
import random
import re
import unicodedata
import math
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.legacy_admin import ADMIN_RBAC_JSON, admin_token_hash, load_admin_rbac, save_admin_rbac
from app.auth.platform_deps import (
    AdminContext,
    ensure_tenant_access,
    require_platform_roles,
    visible_tenant_ids_for_list,
)
from app.config import settings
from app.services.tenant_registry_gate import tenant_has_registered_model
from app.database import get_db, get_read_db
from app.models import TenantBank
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.fraud import FraudScore
from app.models.fraud_extra import FraudAlert, FraudOutcome
from app.models.calibration import CalibrationArtifact
from app.models.model_registry import InferenceTrace, ModelRegistry, TenantMapper
from app.models.model_kpi import ModelKpiSnapshot
from app.models.job_run import JobRun
from app.models.idempotency_key import IdempotencyKey
from app.models.reporting import ReportJob
from app.models.training_data import TrainingUpload, TrainingUploadRow
from app.models.transaction import Transaction
from app.services.care_upload_eval import (
    evaluate_care_external_rows,
    evaluate_care_upload,
    summarize_care_label_mapping,
)
from app.services.care_engine import summarise_care_events
from app.services.fraud_drift import compute_tenant_drift
from app.services.fraud_upload_eval import evaluate_fraud_external_rows, evaluate_fraud_upload
from app.services.mapper_validation import get_contract_schema, validate_and_dry_run, validate_mapper_shape
from app.services.artifact_store import fetch_artifact_uri_to_local_path
from app.tasks.model_challenger_evaluator import run_challenger_evaluator
from app.tasks.model_cutover_executor import run_model_cutover_executor
from app.tasks.model_guardrails import run_model_guardrails
from app.tasks.model_kpi_snapshots import run_model_kpi_snapshot
from app.tasks.warehouse_isolation_verify import run_warehouse_isolation_verification
from app.services.model_kpis import compute_care_kpis, compute_fraud_kpis
from app.services.production_hardening import collect_production_violations
from app.services.training_governance import assert_global_pooled_uploads, assert_training_upload_allowed
from app.services.job_runs import run_tracked_job
from app.services.report_jobs import run_tenant_export_job
from app.observability import get_request_id

router = APIRouter()
BACKEND_ROOT = Path(__file__).resolve().parents[2]
CARE_DEFAULT_HOLDOUT_JSONL = BACKEND_ROOT / "app" / "ml" / "data" / "care_external_holdout_default.jsonl"
CARE_RETRAIN_RECO_CONFIG_JSON = BACKEND_ROOT / "app" / "ml" / "data" / "care_retrain_reco_config.json"
FRAUD_DEFAULT_HOLDOUT_CSV = BACKEND_ROOT / "app" / "ml" / "data" / "fraud_external_holdout_default.csv"
FRAUD_MODEL_REGISTRY_JSON = BACKEND_ROOT / "models" / "fraud" / "model_registry.json"
TENANT_LOGOS_DIR = BACKEND_ROOT / "app" / "ml" / "data" / "tenant_logos"
SYSTEM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
TRAINING_UPLOADS_DIR = BACKEND_ROOT / "app" / "ml" / "data" / "training_uploads"


def _validate_artifact_uri_or_raise(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("artifact_uri is required.")
    blocked = ("javascript:", "data:", "ftp://")
    if raw.lower().startswith(blocked):
        raise ValueError("artifact_uri scheme is not allowed.")
    if ".." in raw.replace("\\", "/"):
        raise ValueError("artifact_uri cannot contain path traversal ('..').")
    env = (settings.environment or "").strip().lower()
    if env == "production" and bool(settings.enforce_production_hardening):
        # In hardened production, allow local/file and s3 only by default.
        if raw.startswith(("http://", "https://", "gs://")):
            raise ValueError("artifact_uri http(s)/gs schemes are not allowed in hardened production.")
    return raw


def _verify_registry_artifact_integrity_or_raise(row: ModelRegistry) -> None:
    meta = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    lineage = meta.get("lineage") if isinstance(meta.get("lineage"), dict) else {}
    expected = str(lineage.get("artifact_sha256") or "").strip()
    if not expected:
        return
    actual = _artifact_sha256(row.artifact_uri)
    if not actual:
        raise HTTPException(
            status_code=400,
            detail=f"Artifact integrity check failed: cannot compute sha256 for URI '{row.artifact_uri}'.",
        )
    if expected.lower() != actual.lower():
        raise HTTPException(
            status_code=400,
            detail=(
                "Artifact integrity mismatch for model activation. "
                f"expected_sha256={expected}, actual_sha256={actual}"
            ),
        )


def _request_fingerprint_for_registry_action(row: ModelRegistry, action: str) -> str:
    raw = f"{action}|{row.id}|{row.tenant_id}|{row.model_type}|{row.version}|{row.status}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _acquire_registry_lock(db: AsyncSession, row: ModelRegistry, action: str) -> None:
    if db.bind and db.bind.dialect.name == "postgresql":
        lock_key = f"registry:{action}:{row.model_type}:{row.tenant_id or 'global'}"
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})


async def _idempotency_replay_or_none(
    db: AsyncSession,
    *,
    scope: str,
    idempotency_key: str | None,
    request_fingerprint: str,
) -> dict | None:
    key = (idempotency_key or "").strip()
    if not key:
        return None
    row = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == scope,
                IdempotencyKey.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.request_fingerprint != request_fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency key reused with different request payload.")
    return row.response_json if isinstance(row.response_json, dict) else {}


async def _store_idempotency_result(
    db: AsyncSession,
    *,
    scope: str,
    idempotency_key: str | None,
    request_fingerprint: str,
    response_json: dict,
) -> None:
    key = (idempotency_key or "").strip()
    if not key:
        return
    existing = (
        await db.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == scope,
                IdempotencyKey.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return
    db.add(
        IdempotencyKey(
            scope=scope,
            idempotency_key=key,
            request_fingerprint=request_fingerprint,
            status_code=200,
            response_json=response_json,
        )
    )


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


class TrainingUploadOut(BaseModel):
    id: str
    model_type: str
    filename: str
    row_count: int
    status: str
    created_at: str
    retrain_locked: bool = False
    eval_summary: dict | None = None
    last_error: str | None = None
    last_retrained_at: str | None = None
    last_training_duration_s: float | None = None


def _normalize_training_row_for_contract(model_type: str, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row or {})
    if model_type == "fraud":
        if "tx_timestamp" not in out and "timestamp" in out:
            out["tx_timestamp"] = out.get("timestamp")
        if "merchant_id" not in out and "merchant_category" in out:
            out["merchant_id"] = out.get("merchant_category")
        if "location_country" not in out and "location" in out:
            loc = str(out.get("location") or "")
            out["location_country"] = loc[:2].upper() if len(loc) >= 2 else None
        if "channel" not in out:
            out["channel"] = "api"
        if "velocity_1h" not in out:
            out["velocity_1h"] = None
    elif model_type == "care":
        if "message_text" not in out and "text" in out:
            out["message_text"] = out.get("text")
        if "message_text" not in out and "message" in out:
            out["message_text"] = out.get("message")
        if "customer_id" not in out and "customer_external_id" in out:
            out["customer_id"] = out.get("customer_external_id")
        if "session_id" not in out and "session" in out:
            out["session_id"] = out.get("session")
        if "channel" not in out:
            out["channel"] = "mobile_app"
    return out


def _validate_training_rows_against_contract(
    *,
    model_type: str,
    contract_version: str,
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    schema = get_contract_schema(model_type, contract_version)
    allowed_fields = set(schema.model_fields.keys())
    normalized_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for idx, raw_row in enumerate(rows, start=1):
        normalized = _normalize_training_row_for_contract(model_type, raw_row)
        # Allow extra training labels/metadata, but validate canonical subset strictly.
        canonical_subset = {k: normalized.get(k) for k in allowed_fields if k in normalized}
        try:
            parsed = schema.model_validate(canonical_subset)
            normalized_rows.append({**raw_row, **parsed.model_dump()})
        except Exception as exc:
            errors.append(f"row {idx}: {str(exc)}")
            if len(errors) >= 25:
                break
    return errors, normalized_rows


def _training_upload_meta_fields(
    meta: dict | None,
) -> tuple[bool, dict | None, str | None, str | None, float | None]:
    if not meta:
        return False, None, None, None, None
    locked = bool(meta.get("retrain_locked"))
    last_error = (meta.get("last_error") or None) if isinstance(meta, dict) else None
    last_retrained_at = (meta.get("last_retrained_at") or None) if isinstance(meta, dict) else None
    duration = None
    if isinstance(meta, dict) and meta.get("last_training_duration_s") is not None:
        try:
            duration = float(meta.get("last_training_duration_s"))
        except (TypeError, ValueError):
            duration = None
    ev = meta.get("last_eval")
    if isinstance(ev, dict):
        summary = {
            "n_scored": ev.get("n_scored"),
            "n_skipped": ev.get("n_skipped"),
            "accuracy": ev.get("accuracy"),
            "auc": ev.get("auc"),
        }
        return locked, summary, last_error, last_retrained_at, duration
    return locked, None, last_error, last_retrained_at, duration


def _extract_care_text_intent(payload: dict) -> tuple[str, str]:
    lower = {str(k).strip().lower(): v for k, v in (payload or {}).items()}
    text = (
        lower.get("text")
        or lower.get("prompt")
        or lower.get("message")
        or lower.get("utterance")
        or lower.get("query")
        or ""
    )
    intent = (
        lower.get("intent")
        or lower.get("label")
        or lower.get("intent_name")
        or lower.get("category")
        or ""
    )
    return str(text).strip(), str(intent).strip()


def _parse_rows_from_text(name: str, text: str) -> list[dict]:
    rows: list[dict] = []
    if name.endswith(".jsonl"):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    else:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if row:
                rows.append(dict(row))
    return rows


def _norm_text_key(text: str) -> str:
    t = unicodedata.normalize("NFKC", (text or "").lower())
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return " ".join(t.split())[:160]


def _normalize_and_validate_fraud_holdout_rows(
    rows: list[dict],
    schema_version: str = "fraud_holdout_v1",
) -> tuple[list[dict], str]:
    if schema_version != "fraud_holdout_v1":
        raise ValueError("Unsupported schema_version. Supported: fraud_holdout_v1")
    cleaned: list[dict] = []
    for i, r in enumerate(rows, start=1):
        row = {str(k).strip().lower(): v for k, v in (r or {}).items()}
        try:
            m = FraudHoldoutRowV1(**row)
        except Exception as exc:
            raise ValueError(f"Row {i} invalid for {schema_version}: {exc}") from exc
        cls = str(m.classification or "").strip().upper()
        if cls not in {"CONFIRMED_FRAUD", "FALSE_POSITIVE", "CONFIRMED_LEGIT"}:
            raise ValueError(f"Row {i} classification must be CONFIRMED_FRAUD|FALSE_POSITIVE|CONFIRMED_LEGIT")
        obj = m.model_dump()
        obj["classification"] = cls
        cleaned.append(obj)
    return cleaned, schema_version


class TrainingTriggerOut(BaseModel):
    status: str
    message: str
    upload_id: str


class GlobalPooledTrainingTriggerOut(BaseModel):
    status: str
    message: str
    upload_ids: list[str]


@router.post("/onboard", response_model=OnboardOut)
async def onboard_bank(
    payload: OnboardIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
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
    await _audit_admin_change(
        db,
        "TENANT_ONBOARDED",
        {"tenant_id": str(bank.id), "name": payload.name, "country_code": payload.country_code},
        actor=admin_ctx.actor_id,
    )
    return OnboardOut(bank_id=str(bank.id), api_key=raw_key)


@router.get("/care/metrics", response_model=CareMetricsOut)
async def get_care_metrics(
    window_hours: int = Query(24, ge=1, le=168),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
) -> CareMetricsOut:
    data = summarise_care_events(window_hours=window_hours)
    return CareMetricsOut(**data)


@router.get("/training/uploads", response_model=List[TrainingUploadOut])
async def list_training_uploads(
    model_type: str = Query(..., pattern="^(fraud|care)$"),
    tenant_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=200),
    admin_ctx: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(TrainingUpload)
            .where(TrainingUpload.model_type == model_type)
            .order_by(TrainingUpload.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    tenant_uuid = uuid.UUID(tenant_id) if tenant_id else None
    if tenant_uuid:
        await ensure_tenant_access(db, admin_ctx, tenant_uuid)
    out: list[TrainingUploadOut] = []
    for r in rows:
        meta = r.meta if isinstance(r.meta, dict) else {}
        if tenant_uuid and str(meta.get("tenant_id")) != str(tenant_uuid):
            continue
        lk, sm, er, rt, dur = _training_upload_meta_fields(r.meta)
        out.append(
            TrainingUploadOut(
                id=str(r.id),
                model_type=r.model_type,
                filename=r.filename,
                row_count=int(r.row_count or 0),
                status=r.status,
                created_at=r.created_at.isoformat() if r.created_at else "",
                retrain_locked=lk,
                eval_summary=sm,
                last_error=er,
                last_retrained_at=rt,
                last_training_duration_s=dur,
            )
        )
    return out


@router.post("/training/upload", response_model=TrainingUploadOut)
async def upload_training_file(
    model_type: str = Form(..., pattern="^(fraud|care)$"),
    contract_version: str = Form("v1"),
    tenant_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 text.") from exc

    content_sha256 = hashlib.sha256(raw).hexdigest()
    tenant_uuid = uuid.UUID(tenant_id) if tenant_id else None
    if tenant_uuid:
        await ensure_tenant_access(db, admin_ctx, tenant_uuid)
        if not await tenant_has_registered_model(db, tenant_id=tenant_uuid, model_type=model_type):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Register a {model_type} model for this tenant in Model registry "
                    "before uploading training data."
                ),
            )
    existing_rows = (
        await db.execute(select(TrainingUpload).where(TrainingUpload.model_type == model_type).limit(1000))
    ).scalars().all()
    for e in existing_rows:
        e_meta = e.meta if isinstance(e.meta, dict) else {}
        same_tenant = (str(e_meta.get("tenant_id")) if e_meta.get("tenant_id") else None) == (str(tenant_uuid) if tenant_uuid else None)
        if same_tenant and e_meta.get("upload_sha256") == content_sha256:
            raise HTTPException(
                status_code=400,
                detail=f"This exact file has already been uploaded ({e.filename}). Reuse it or upload a different dataset.",
            )

    parsed_rows: list[dict] = []
    name = (file.filename or "upload").lower()
    if model_type == "fraud":
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if row:
                parsed_rows.append(dict(row))
    else:
        if name.endswith(".jsonl"):
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    parsed_rows.append(obj)
        else:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                if row:
                    parsed_rows.append(dict(row))

    if not parsed_rows:
        raise HTTPException(status_code=400, detail="No parseable rows found.")
    try:
        validation_errors, normalized_rows = _validate_training_rows_against_contract(
            model_type=model_type,
            contract_version=contract_version,
            rows=parsed_rows,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "upload_contract_validation_failed",
                "contract_version": contract_version,
                "errors": validation_errors,
            },
        )

    dataset_version = f"{model_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{content_sha256[:10]}"
    tenant_scope = str(tenant_uuid) if tenant_uuid else "global"
    target_dir = TRAINING_UPLOADS_DIR / tenant_scope / model_type
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = (file.filename or "upload.csv").replace("/", "_")
    stored_path = target_dir / f"{dataset_version}__{safe_name}"
    stored_path.write_bytes(raw)

    upload = TrainingUpload(
        model_type=model_type,
        filename=file.filename or "upload",
        content_type=file.content_type,
        row_count=len(normalized_rows),
        status="UPLOADED",
        meta={
            "upload_sha256": content_sha256,
            "contract_version": contract_version,
            "tenant_id": str(tenant_uuid) if tenant_uuid else None,
            "training_scope": "tenant" if tenant_uuid else "global",
            "dataset_version": dataset_version,
            "storage_path": str(stored_path),
            "mapper_version": None,
        },
    )
    db.add(upload)
    await db.flush()

    for idx, payload in enumerate(normalized_rows, start=1):
        db.add(TrainingUploadRow(upload_id=upload.id, row_index=idx, payload=payload))

    await db.flush()
    await _audit_admin_change(
        db,
        "TRAINING_UPLOAD_CREATED",
        {
            "upload_id": str(upload.id),
            "model_type": model_type,
            "tenant_id": str(tenant_uuid) if tenant_uuid else None,
            "training_scope": "tenant" if tenant_uuid else "global",
            "row_count": len(normalized_rows),
            "dataset_version": dataset_version,
        },
        actor=admin_ctx.actor_id,
    )
    lk, sm, er, rt, dur = _training_upload_meta_fields(upload.meta)
    return TrainingUploadOut(
        id=str(upload.id),
        model_type=upload.model_type,
        filename=upload.filename,
        row_count=int(upload.row_count or 0),
        status=upload.status,
        created_at=upload.created_at.isoformat() if upload.created_at else "",
        retrain_locked=lk,
        eval_summary=sm,
        last_error=er,
        last_retrained_at=rt,
        last_training_duration_s=dur,
    )


class FraudUploadTestOut(BaseModel):
    upload_id: str
    n_scored: int
    n_skipped: int
    accuracy: float
    auc: float | None
    retrain_locked: bool
    samples: List[Dict[str, Any]]
    per_intent: List[Dict[str, Any]] | None = None
    confusion: Dict[str, Any] | None = None
    threshold_metrics: List[Dict[str, Any]] | None = None
    segments: Dict[str, Any] | None = None


class FraudDataQualityOut(BaseModel):
    upload_id: str
    total_rows: int
    duplicate_external_tx_rate: float
    class_balance_entropy_norm: float
    missing_critical_fields_rate: float
    channel_counts: List[Dict[str, Any]]
    trustworthiness_score: float
    recommendation: str
    summary: str


class FraudDriftOut(BaseModel):
    feature: str
    psi: float
    ks: float
    alert: bool


class FraudModelLifecycleOut(BaseModel):
    active: str
    champion: dict
    challenger: dict | None = None
    last_backup: str | None = None


class AdminAuditOut(BaseModel):
    event_type: str
    actor_id: str | None
    created_at: str
    event_data: dict


class FraudHoldoutRowV1(BaseModel):
    tenant_id: str
    external_tx_id: str
    classification: str
    amount: float
    tx_timestamp: str
    currency: str | None = None
    merchant_category: str | None = None
    device_id: str | None = None
    ip_address_hash: str | None = None
    location_country: str | None = None
    channel: str | None = None
    customer_risk_score: float | None = None


class HoldoutSchemaOut(BaseModel):
    schema_version: str
    required_fields: list[str]
    optional_fields: list[str]


class AdminTokenMetaOut(BaseModel):
    token_id: str
    name: str
    role: str
    active: bool
    created_at: str
    rotated_at: str | None = None


class AdminTokenCreateOut(BaseModel):
    token: str
    meta: AdminTokenMetaOut


class CareLabelMapRowOut(BaseModel):
    raw_label: str
    mapped_intent: str
    count: int


class CareLabelMapOut(BaseModel):
    upload_id: str
    total_rows: int
    ignored_rows: int
    rows: List[CareLabelMapRowOut]


class CareSplitOut(BaseModel):
    upload_id: str
    train_file: str
    test_file: str
    total_rows: int
    train_rows: int
    test_rows: int


class CareDataQualityIntentOut(BaseModel):
    intent: str
    count: int
    pct: float


class CareDataQualityOut(BaseModel):
    upload_id: str
    total_valid_rows: int
    unique_normalized_texts: int
    duplicate_rate: float
    ambiguous_text_rate: float
    intent_balance_entropy_norm: float
    intent_counts: List[CareDataQualityIntentOut]
    trustworthiness_score: float
    difficulty_estimate: str
    retrain_recommendation: str
    retrain_recommendation_note: str
    summary: str


class CareRetrainRecoConfigOut(BaseModel):
    trust_green_min: float
    dup_green_max: float
    trust_amber_min: float


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _sign_payload(payload: str) -> str:
    key = (settings.secret_key or "dev-secret").encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _resolve_local_artifact_path(artifact_uri: str | None) -> Path | None:
    if not artifact_uri:
        return None
    raw = str(artifact_uri).strip()
    if not raw:
        return None
    return fetch_artifact_uri_to_local_path(raw)


def _artifact_sha256(artifact_uri: str | None) -> str | None:
    p = _resolve_local_artifact_path(artifact_uri)
    if p is None or not p.exists():
        return None
    h = hashlib.sha256()
    if p.is_file():
        with open(p, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    files = sorted([x for x in p.rglob("*") if x.is_file()])
    if not files:
        return None
    for fp in files:
        rel = str(fp.relative_to(p)).replace("\\", "/").encode("utf-8")
        h.update(rel)
        with open(fp, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    return h.hexdigest()


async def _audit_admin_change(
    db: AsyncSession,
    event_type: str,
    event_data: dict,
    actor: str = "admin_api",
) -> None:
    data = dict(event_data or {})
    req_id = get_request_id()
    if req_id and "request_id" not in data:
        data["request_id"] = req_id
    db.add(
        AuditLog(
            tenant_id=SYSTEM_TENANT_ID,
            event_type=event_type,
            entity_type="admin_config",
            actor_type="api",
            actor_id=actor,
            event_data=data,
        )
    )
    await db.flush()


def _fraud_model_registry_defaults() -> dict:
    return {
        "active": "champion",
        "champion": {"lgb_path": "lgb_fraud.txt", "sklearn_path": "sklearn_fraud.joblib"},
        "challenger": None,
        "last_backup": None,
    }


def _load_fraud_model_registry() -> dict:
    reg = _fraud_model_registry_defaults()
    if not FRAUD_MODEL_REGISTRY_JSON.exists():
        return reg
    try:
        raw = json.loads(FRAUD_MODEL_REGISTRY_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            reg.update(raw)
    except Exception:
        pass
    return reg


def _save_fraud_model_registry(reg: dict) -> None:
    FRAUD_MODEL_REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    FRAUD_MODEL_REGISTRY_JSON.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _care_retrain_reco_defaults() -> dict[str, float]:
    return {
        "trust_green_min": _env_float("CARE_RETRAIN_RECO_TRUST_GREEN_MIN", 0.72),
        "dup_green_max": _env_float("CARE_RETRAIN_RECO_DUP_GREEN_MAX", 0.45),
        "trust_amber_min": _env_float("CARE_RETRAIN_RECO_TRUST_AMBER_MIN", 0.52),
    }


def _load_care_retrain_reco_config() -> dict[str, float]:
    cfg = _care_retrain_reco_defaults()
    if not CARE_RETRAIN_RECO_CONFIG_JSON.exists():
        return cfg
    try:
        raw = json.loads(CARE_RETRAIN_RECO_CONFIG_JSON.read_text(encoding="utf-8"))
    except Exception:
        return cfg
    for k in list(cfg.keys()):
        v = raw.get(k)
        if v is None:
            continue
        try:
            cfg[k] = float(v)
        except (TypeError, ValueError):
            continue
    return cfg


def _save_care_retrain_reco_config(cfg: dict[str, float]) -> None:
    CARE_RETRAIN_RECO_CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CARE_RETRAIN_RECO_CONFIG_JSON.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


@router.post("/training/fraud/test-upload", response_model=FraudUploadTestOut)
async def test_fraud_training_upload(
    upload_id: str = Form(...),
    sample_max: int = Form(120),
    _admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    meta = upload.meta if isinstance(upload.meta, dict) else {}
    tid = meta.get("tenant_id")
    if tid:
        t_uuid = uuid.UUID(str(tid))
        await ensure_tenant_access(db, _admin, t_uuid)
        if not await tenant_has_registered_model(db, tenant_id=t_uuid, model_type="fraud"):
            raise HTTPException(
                status_code=403,
                detail="Register a fraud model for this tenant in Model registry before evaluating uploads.",
            )
    if sample_max < 50 or sample_max > 5000:
        raise HTTPException(status_code=400, detail="sample_max must be between 50 and 5000.")
    try:
        out = await evaluate_fraud_upload(db, uid, sample_max=sample_max)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    return FraudUploadTestOut(**out)


@router.post("/training/care/test-upload", response_model=FraudUploadTestOut)
async def test_care_training_upload(
    upload_id: str = Form(...),
    sample_max: int = Form(300),
    _admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    meta = upload.meta if isinstance(upload.meta, dict) else {}
    tid = meta.get("tenant_id")
    if tid:
        t_uuid = uuid.UUID(str(tid))
        await ensure_tenant_access(db, _admin, t_uuid)
        if not await tenant_has_registered_model(db, tenant_id=t_uuid, model_type="care"):
            raise HTTPException(
                status_code=403,
                detail="Register a care model for this tenant in Model registry before evaluating uploads.",
            )
    if sample_max < 20 or sample_max > 2000:
        raise HTTPException(status_code=400, detail="sample_max must be between 20 and 2000.")
    try:
        out = await evaluate_care_upload(db, uid, sample_max=sample_max)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await db.commit()
    return FraudUploadTestOut(**out)


@router.post("/training/care/test-external", response_model=FraudUploadTestOut)
async def test_care_external_file(
    file: UploadFile | None = File(None),
    sample_max: int = Form(1000),
    use_default: bool = Form(False),
    save_as_default: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    if sample_max < 20 or sample_max > 5000:
        raise HTTPException(status_code=400, detail="sample_max must be between 20 and 5000.")
    rows: list[dict]
    if file is not None:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty test file.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Test file must be UTF-8 text.") from exc
        rows = _parse_rows_from_text((file.filename or "").lower(), text)
        if save_as_default:
            CARE_DEFAULT_HOLDOUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
            with open(CARE_DEFAULT_HOLDOUT_JSONL, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif use_default:
        if CARE_DEFAULT_HOLDOUT_JSONL.exists():
            txt = CARE_DEFAULT_HOLDOUT_JSONL.read_text(encoding="utf-8")
            rows = _parse_rows_from_text("default.jsonl", txt)
        else:
            # Fallback: use latest auto-split test file for most recent care upload.
            latest = (
                await db.execute(
                    select(TrainingUpload)
                    .where(TrainingUpload.model_type == "care")
                    .order_by(TrainingUpload.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest is None:
                raise HTTPException(status_code=400, detail="No care upload found to derive default holdout.")
            fallback = BACKEND_ROOT / "app" / "ml" / "data" / f"care_split_test_{latest.id}.csv"
            if not fallback.exists():
                raise HTTPException(
                    status_code=400,
                    detail="No default external holdout file saved yet. Click Auto split once or upload a holdout file.",
                )
            txt = fallback.read_text(encoding="utf-8")
            rows = _parse_rows_from_text(fallback.name.lower(), txt)
            # Cache fallback as default for next runs.
            CARE_DEFAULT_HOLDOUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
            with open(CARE_DEFAULT_HOLDOUT_JSONL, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    else:
        raise HTTPException(status_code=400, detail="Provide file or set use_default=true.")
    try:
        out = await evaluate_care_external_rows(rows, sample_max=sample_max)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return FraudUploadTestOut(**out)


@router.post("/training/fraud/test-external", response_model=FraudUploadTestOut)
async def test_fraud_external_file(
    file: UploadFile | None = File(None),
    sample_max: int = Form(1200),
    use_default: bool = Form(False),
    save_as_default: bool = Form(False),
    schema_version: str = Form("fraud_holdout_v1"),
    _admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if sample_max < 50 or sample_max > 6000:
        raise HTTPException(status_code=400, detail="sample_max must be between 50 and 6000.")
    rows: list[dict]
    if file is not None:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="Empty test file.")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Test file must be UTF-8 text.") from exc
        rows = _parse_rows_from_text((file.filename or "").lower(), text)
        try:
            rows, _ = _normalize_and_validate_fraud_holdout_rows(rows, schema_version=schema_version)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Schema validation failed: {e}") from e
        if save_as_default:
            FRAUD_DEFAULT_HOLDOUT_CSV.parent.mkdir(parents=True, exist_ok=True)
            with open(FRAUD_DEFAULT_HOLDOUT_CSV, "w", encoding="utf-8", newline="") as f:
                if rows:
                    fieldnames = sorted({k for r in rows for k in (r or {}).keys()})
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    for r in rows:
                        w.writerow(r)
    elif use_default:
        if not FRAUD_DEFAULT_HOLDOUT_CSV.exists():
            raise HTTPException(
                status_code=400,
                detail="No default fraud external holdout file saved yet. Upload one and tick save-as-default.",
            )
        txt = FRAUD_DEFAULT_HOLDOUT_CSV.read_text(encoding="utf-8")
        rows = _parse_rows_from_text("default.csv", txt)
        try:
            rows, _ = _normalize_and_validate_fraud_holdout_rows(rows, schema_version=schema_version)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Schema validation failed: {e}") from e
    else:
        raise HTTPException(status_code=400, detail="Provide file or set use_default=true.")
    try:
        out = await evaluate_fraud_external_rows(db, rows, sample_max=sample_max)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    out["schema_version"] = schema_version
    return FraudUploadTestOut(**out)


@router.get("/training/fraud/holdout-schemas", response_model=List[HoldoutSchemaOut])
async def fraud_holdout_schemas(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    return [
        HoldoutSchemaOut(
            schema_version="fraud_holdout_v1",
            required_fields=["tenant_id", "external_tx_id", "classification", "amount", "tx_timestamp"],
            optional_fields=[
                "currency",
                "merchant_category",
                "device_id",
                "ip_address_hash",
                "location_country",
                "channel",
                "customer_risk_score",
            ],
        )
    ]


@router.post("/training/care/split-upload", response_model=CareSplitOut)
async def split_care_upload(
    upload_id: str = Form(...),
    test_ratio: float = Form(0.2),
    db: AsyncSession = Depends(get_db),
):
    if test_ratio <= 0.05 or test_ratio >= 0.5:
        raise HTTPException(status_code=400, detail="test_ratio must be between 0.05 and 0.5.")
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload or upload.model_type != "care":
        raise HTTPException(status_code=400, detail="Upload not found or not a care upload.")
    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == uid).order_by(TrainingUploadRow.row_index.asc())
    )
    rows = rows_q.scalars().all()
    parsed: list[tuple[str, str]] = []
    for r in rows:
        text, intent = _extract_care_text_intent(r.payload or {})
        if text and intent:
            parsed.append((text, intent))
    if len(parsed) < 20:
        raise HTTPException(status_code=400, detail="Need at least 20 valid rows to split.")

    groups: dict[str, list[tuple[str, str]]] = {}
    for text, intent in parsed:
        groups.setdefault(_norm_text_key(text), []).append((text, intent))
    keys = list(groups.keys())
    rng = random.Random(uid.int & 0xFFFFFFFF)
    rng.shuffle(keys)
    target = max(1, int(len(parsed) * test_ratio))
    test: list[tuple[str, str]] = []
    test_count = 0
    test_keys: set[str] = set()
    for k in keys:
        if test_count >= target:
            break
        chunk = groups[k]
        test.extend(chunk)
        test_count += len(chunk)
        test_keys.add(k)
    train = [(t, i) for (t, i) in parsed if _norm_text_key(t) not in test_keys]
    if not train or not test:
        raise HTTPException(status_code=400, detail="Could not create non-empty train/test split from this upload.")

    data_dir = BACKEND_ROOT / "app" / "ml" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    train_file = data_dir / f"care_split_train_{uid}.csv"
    test_file = data_dir / f"care_split_test_{uid}.csv"
    with open(train_file, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "intent"])
        w.writeheader()
        for text, intent in train:
            w.writerow({"text": text, "intent": intent})
    with open(test_file, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "intent"])
        w.writeheader()
        for text, intent in test:
            w.writerow({"text": text, "intent": intent})

    # Make auto-split test file immediately available as default holdout.
    CARE_DEFAULT_HOLDOUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(CARE_DEFAULT_HOLDOUT_JSONL, "w", encoding="utf-8") as f:
        for text, intent in test:
            f.write(json.dumps({"text": text, "intent": intent}, ensure_ascii=False) + "\n")

    return CareSplitOut(
        upload_id=str(uid),
        train_file=str(train_file),
        test_file=str(test_file),
        total_rows=len(parsed),
        train_rows=len(train),
        test_rows=len(test),
    )


@router.get("/training/fraud/data-quality", response_model=FraudDataQualityOut)
async def fraud_data_quality(
    upload_id: str = Query(...),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload or upload.model_type != "fraud":
        raise HTTPException(status_code=400, detail="Upload not found or not a fraud upload.")
    meta_u = upload.meta if isinstance(upload.meta, dict) else {}
    tid_u = meta_u.get("tenant_id")
    if tid_u:
        t_uuid = uuid.UUID(str(tid_u))
        await ensure_tenant_access(db, _admin, t_uuid)
        if not await tenant_has_registered_model(db, tenant_id=t_uuid, model_type="fraud"):
            raise HTTPException(
                status_code=403,
                detail="Register a fraud model for this tenant in Model registry before analyzing upload quality.",
            )
    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == uid).order_by(TrainingUploadRow.row_index.asc())
    )
    rows = rows_q.scalars().all()
    payloads = [r.payload or {} for r in rows]
    total = len(payloads)
    if total == 0:
        raise HTTPException(status_code=400, detail="No rows in upload.")

    seen_ext: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    missing = 0
    for p in payloads:
        ext = str(p.get("external_tx_id") or "").strip()
        cls = str(p.get("classification") or "").strip().upper()
        ch = str(p.get("channel") or "UNKNOWN").strip().upper() or "UNKNOWN"
        tenant = str(p.get("tenant_id") or "").strip()
        if not ext or not tenant or cls not in {"CONFIRMED_FRAUD", "FALSE_POSITIVE", "CONFIRMED_LEGIT"}:
            missing += 1
        if ext:
            seen_ext[ext] = seen_ext.get(ext, 0) + 1
        if cls:
            class_counts[cls] = class_counts.get(cls, 0) + 1
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    dup_n = sum(max(0, c - 1) for c in seen_ext.values())
    duplicate_rate = dup_n / max(1, total)
    probs = [c / total for c in class_counts.values() if c > 0]
    entropy = -sum(p * math.log(p, 2) for p in probs) if probs else 0.0
    max_entropy = math.log(max(2, len(class_counts) or 2), 2)
    balance = max(0.0, min(1.0, entropy / max_entropy))
    missing_rate = missing / max(1, total)

    trust = 0.45 * (1.0 - duplicate_rate) + 0.35 * balance + 0.20 * (1.0 - missing_rate)
    trust = max(0.0, min(1.0, trust))
    if trust >= 0.75:
        reco = "strong_for_retrain"
        summary = "Dataset is clean and balanced; eval score is likely trustworthy."
    elif trust >= 0.55:
        reco = "usable_with_caution"
        summary = "Dataset is usable, but duplication/missing fields can skew scores."
    else:
        reco = "fix_data_first"
        summary = "Dataset quality is weak; test score may be misleading."

    channels = [
        {"channel": k, "count": v, "pct": round((v / total) * 100.0, 2)}
        for k, v in sorted(channel_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return FraudDataQualityOut(
        upload_id=str(uid),
        total_rows=total,
        duplicate_external_tx_rate=round(duplicate_rate, 4),
        class_balance_entropy_norm=round(balance, 4),
        missing_critical_fields_rate=round(missing_rate, 4),
        channel_counts=channels,
        trustworthiness_score=round(trust, 4),
        recommendation=reco,
        summary=summary,
    )


@router.get("/training/care/data-quality", response_model=CareDataQualityOut)
async def care_data_quality(
    upload_id: str = Query(...),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload or upload.model_type != "care":
        raise HTTPException(status_code=400, detail="Upload not found or not a care upload.")
    meta_u = upload.meta if isinstance(upload.meta, dict) else {}
    tid_u = meta_u.get("tenant_id")
    if tid_u:
        t_uuid = uuid.UUID(str(tid_u))
        await ensure_tenant_access(db, _admin, t_uuid)
        if not await tenant_has_registered_model(db, tenant_id=t_uuid, model_type="care"):
            raise HTTPException(
                status_code=403,
                detail="Register a care model for this tenant in Model registry before analyzing upload quality.",
            )

    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == uid).order_by(TrainingUploadRow.row_index.asc())
    )
    rows = rows_q.scalars().all()
    parsed: list[tuple[str, str]] = []
    for r in rows:
        text, intent = _extract_care_text_intent(r.payload or {})
        if text and intent:
            parsed.append((text, intent))
    if not parsed:
        raise HTTPException(status_code=400, detail="No valid text+intent rows in this upload.")

    total = len(parsed)
    norm_groups: dict[str, list[str]] = {}
    intent_counts: dict[str, int] = {}
    for text, intent in parsed:
        k = _norm_text_key(text)
        norm_groups.setdefault(k, []).append(intent)
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    unique_norm = len(norm_groups)
    duplicate_rate = max(0.0, 1.0 - (unique_norm / max(1, total)))

    ambiguous_groups = 0
    for intents in norm_groups.values():
        if len(set(intents)) > 1:
            ambiguous_groups += 1
    ambiguous_text_rate = ambiguous_groups / max(1, unique_norm)

    probs = [c / total for c in intent_counts.values()]
    entropy = -sum(p * math.log(p, 2) for p in probs if p > 0)
    max_entropy = math.log(max(2, len(intent_counts)), 2)
    entropy_norm = max(0.0, min(1.0, entropy / max_entropy))

    # Heuristic trust score (0..1): lower duplicates, better balance, moderate ambiguity.
    trust = 0.45 * (1.0 - duplicate_rate) + 0.45 * entropy_norm + 0.10 * (1.0 - ambiguous_text_rate)
    trust = max(0.0, min(1.0, trust))

    if trust >= 0.75:
        difficulty = "mostly_easy"
    elif trust >= 0.55:
        difficulty = "moderate"
    else:
        difficulty = "hard_or_unreliable"

    reco_cfg = _load_care_retrain_reco_config()
    retrain_now_min_trust = reco_cfg["trust_green_min"]
    retrain_now_max_dup = reco_cfg["dup_green_max"]
    retrain_optional_min_trust = reco_cfg["trust_amber_min"]

    if trust >= retrain_now_min_trust and duplicate_rate <= retrain_now_max_dup:
        recommendation = "retrain_now"
        recommendation_note = "Data quality looks strong."
    elif trust >= retrain_optional_min_trust:
        recommendation = "retrain_optional"
        recommendation_note = "Data quality is mixed but usable."
    else:
        recommendation = "fix_data_first"
        recommendation_note = "Data quality is weak; score may be misleading."

    if difficulty == "mostly_easy":
        summary = "Dataset is clean and balanced but likely easy; test scores may look very high."
    elif difficulty == "moderate":
        summary = "Dataset is reasonably balanced with some duplication/overlap; scores are fairly trustworthy."
    else:
        summary = "Dataset has heavy duplication or imbalance; test scores may be unstable or misleading."

    intents_out = [
        CareDataQualityIntentOut(intent=k, count=v, pct=round((v / total) * 100.0, 2))
        for k, v in sorted(intent_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return CareDataQualityOut(
        upload_id=str(uid),
        total_valid_rows=total,
        unique_normalized_texts=unique_norm,
        duplicate_rate=round(duplicate_rate, 4),
        ambiguous_text_rate=round(ambiguous_text_rate, 4),
        intent_balance_entropy_norm=round(entropy_norm, 4),
        intent_counts=intents_out,
        trustworthiness_score=round(trust, 4),
        difficulty_estimate=difficulty,
        retrain_recommendation=recommendation,
        retrain_recommendation_note=recommendation_note,
        summary=summary,
    )


@router.get("/training/care/retrain-reco-config", response_model=CareRetrainRecoConfigOut)
async def get_care_retrain_reco_config(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    cfg = _load_care_retrain_reco_config()
    return CareRetrainRecoConfigOut(
        trust_green_min=cfg["trust_green_min"],
        dup_green_max=cfg["dup_green_max"],
        trust_amber_min=cfg["trust_amber_min"],
    )


@router.patch("/training/care/retrain-reco-config", response_model=CareRetrainRecoConfigOut)
async def update_care_retrain_reco_config(
    trust_green_min: float = Form(...),
    dup_green_max: float = Form(...),
    trust_amber_min: float = Form(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if not (0.0 <= trust_green_min <= 1.0):
        raise HTTPException(status_code=400, detail="trust_green_min must be between 0 and 1.")
    if not (0.0 <= dup_green_max <= 1.0):
        raise HTTPException(status_code=400, detail="dup_green_max must be between 0 and 1.")
    if not (0.0 <= trust_amber_min <= 1.0):
        raise HTTPException(status_code=400, detail="trust_amber_min must be between 0 and 1.")
    if trust_amber_min > trust_green_min:
        raise HTTPException(status_code=400, detail="trust_amber_min cannot be greater than trust_green_min.")

    cfg = {
        "trust_green_min": float(trust_green_min),
        "dup_green_max": float(dup_green_max),
        "trust_amber_min": float(trust_amber_min),
    }
    prev = _load_care_retrain_reco_config()
    _save_care_retrain_reco_config(cfg)
    await _audit_admin_change(db, "CARE_RETRAIN_RECO_CONFIG_UPDATE", {"prev": prev, "next": cfg}, actor=admin_ctx.actor_id)
    return CareRetrainRecoConfigOut(**cfg)


@router.post("/training/care/retrain-reco-config/reset", response_model=CareRetrainRecoConfigOut)
async def reset_care_retrain_reco_config(
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    prev = _load_care_retrain_reco_config()
    if CARE_RETRAIN_RECO_CONFIG_JSON.exists():
        CARE_RETRAIN_RECO_CONFIG_JSON.unlink()
    cfg = _care_retrain_reco_defaults()
    await _audit_admin_change(db, "CARE_RETRAIN_RECO_CONFIG_RESET", {"prev": prev, "next": cfg}, actor=admin_ctx.actor_id)
    return CareRetrainRecoConfigOut(
        trust_green_min=cfg["trust_green_min"],
        dup_green_max=cfg["dup_green_max"],
        trust_amber_min=cfg["trust_amber_min"],
    )


@router.get("/training/care/label-mapping", response_model=CareLabelMapOut)
async def care_upload_label_mapping(
    upload_id: str = Query(...),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    uid = uuid.UUID(upload_id)
    try:
        out = await summarize_care_label_mapping(db, uid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return CareLabelMapOut(**out)


@router.post("/training/{model_type}/trigger", response_model=TrainingTriggerOut)
async def trigger_training_from_upload(
    model_type: str,
    upload_id: str = Form(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if model_type not in {"fraud", "care"}:
        raise HTTPException(status_code=400, detail="Invalid model_type.")
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.model_type != model_type:
        raise HTTPException(status_code=400, detail="Upload model_type mismatch.")
    meta = upload.meta if isinstance(upload.meta, dict) else {}
    tid = meta.get("tenant_id")
    if tid:
        t_uuid = uuid.UUID(str(tid))
        await ensure_tenant_access(db, admin_ctx, t_uuid)
        if not await tenant_has_registered_model(db, tenant_id=t_uuid, model_type=model_type):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Register a {model_type} model for this tenant in Model registry "
                    "before starting training from tenant uploads."
                ),
            )
    await assert_training_upload_allowed(db, upload=upload, model_type=model_type)
    if upload.status == "TRAINING":
        raise HTTPException(status_code=400, detail="Training already in progress for this upload.")
    if model_type == "fraud" and upload.meta and upload.meta.get("retrain_locked"):
        raise HTTPException(
            status_code=400,
            detail="Retrain locked: last evaluation met quality thresholds on this upload. Upload a new dataset to train again.",
        )
    # Flip status immediately so UI reflects that retrain started right away.
    upload.status = "TRAINING"
    await db.flush()
    await _audit_admin_change(
        db,
        "TRAINING_TRIGGERED",
        {"model_type": model_type, "upload_id": str(uid), "mode": "single"},
        actor=admin_ctx.actor_id,
    )

    env = os.environ.copy()
    subprocess.Popen(
        [
            sys.executable,
            "scripts/train_from_uploaded_data.py",
            "--model",
            model_type,
            "--upload-id",
            str(uid),
        ],
        env=env,
        cwd=str(BACKEND_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return TrainingTriggerOut(
        status="started",
        message=f"{model_type} training started from uploaded dataset.",
        upload_id=str(uid),
    )


@router.post("/training/{model_type}/global-pooled/trigger", response_model=GlobalPooledTrainingTriggerOut)
async def trigger_global_pooled_training(
    model_type: str,
    upload_ids: str = Form(..., description="Comma-separated upload UUIDs (all global scope)"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if model_type not in {"fraud", "care"}:
        raise HTTPException(status_code=400, detail="Invalid model_type.")
    raw_ids = [x.strip() for x in str(upload_ids).split(",") if x.strip()]
    if len(raw_ids) < 2:
        raise HTTPException(status_code=400, detail="global_pooled requires at least two upload UUIDs.")
    uuids: list[uuid.UUID] = []
    for s in raw_ids:
        try:
            uuids.append(uuid.UUID(s))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {s}") from e
    uploads: list[TrainingUpload] = []
    for u in uuids:
        row = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == u))).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail=f"Upload not found: {u}")
        uploads.append(row)
    await assert_global_pooled_uploads(db, uploads=uploads, model_type=model_type)
    for row in uploads:
        if row.status == "TRAINING":
            raise HTTPException(status_code=400, detail=f"Training already in progress for upload {row.id}.")
    for row in uploads:
        row.status = "TRAINING"
    await db.flush()
    merge_arg = ",".join(str(x) for x in uuids)
    await _audit_admin_change(
        db,
        "TRAINING_TRIGGERED",
        {"model_type": model_type, "upload_ids": [str(x) for x in uuids], "mode": "global_pooled"},
        actor=admin_ctx.actor_id,
    )
    env = os.environ.copy()
    subprocess.Popen(
        [
            sys.executable,
            "scripts/train_from_uploaded_data.py",
            "--model",
            model_type,
            "--merge-upload-ids",
            merge_arg,
        ],
        env=env,
        cwd=str(BACKEND_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return GlobalPooledTrainingTriggerOut(
        status="started",
        message=f"{model_type} global pooled training started ({len(uuids)} uploads).",
        upload_ids=[str(x) for x in uuids],
    )


class TenantSummary(BaseModel):
    id: str
    name: str
    country_code: str
    logo_url: str | None = None


@router.get("/tenants", response_model=List[TenantSummary])
async def list_tenants(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TenantBank.id, TenantBank.name, TenantBank.country_code, TenantBank.logo_path).order_by(TenantBank.created_at.desc())
    allowed = await visible_tenant_ids_for_list(db, _admin)
    if allowed is not None:
        if not allowed:
            return []
        stmt = stmt.where(TenantBank.id.in_(allowed))
    result = await db.execute(stmt)
    return [
        TenantSummary(
            id=str(r.id),
            name=r.name,
            country_code=r.country_code,
            logo_url=(f"/api/v1/admin/tenants/{r.id}/logo" if r.logo_path else None),
        )
        for r in result.all()
    ]


@router.post("/tenants/{tenant_id}/logo")
async def upload_tenant_logo(
    tenant_id: uuid.UUID,
    file: UploadFile = File(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    filename = str(file.filename or "").lower()
    ext = ".png"
    if filename.endswith(".jpg") or filename.endswith(".jpeg"):
        ext = ".jpg"
    elif filename.endswith(".webp"):
        ext = ".webp"
    elif filename.endswith(".png"):
        ext = ".png"
    else:
        raise HTTPException(status_code=400, detail="Logo must be png, jpg, or webp")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(payload) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo too large (max 2MB)")
    TENANT_LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    path = TENANT_LOGOS_DIR / f"{tenant_id}{ext}"
    path.write_bytes(payload)
    bank.logo_path = str(path)
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_LOGO_UPDATED",
        {"tenant_id": str(tenant_id)},
        actor=admin_ctx.actor_id,
    )
    return {"status": "ok", "logo_url": f"/api/v1/admin/tenants/{tenant_id}/logo"}


@router.get("/tenants/{tenant_id}/logo")
async def get_tenant_logo(
    tenant_id: uuid.UUID,
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank or not bank.logo_path:
        raise HTTPException(status_code=404, detail="Logo not found")
    path = Path(str(bank.logo_path))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    suffix = path.suffix.lower()
    media = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif suffix == ".webp":
        media = "image/webp"
    return FileResponse(path=str(path), media_type=media)


@router.delete("/tenants/{tenant_id}/logo")
async def delete_tenant_logo(
    tenant_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if bank.logo_path:
        p = Path(str(bank.logo_path))
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    bank.logo_path = None
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_LOGO_REMOVED",
        {"tenant_id": str(tenant_id)},
        actor=admin_ctx.actor_id,
    )
    return {"status": "ok"}


@router.post("/tenants/{tenant_id}/api-key", response_model=ApiKeyRotateOut)
async def rotate_tenant_api_key(
    tenant_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a fresh API key for an existing tenant bank.
    Old key stops working immediately after rotation.
    """
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    raw_key, key_hash, key_prefix = generate_api_key()
    bank.api_key_hash = key_hash
    bank.api_key_prefix = key_prefix
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_API_KEY_ROTATED",
        {"tenant_id": str(tenant_id), "key_prefix": key_prefix},
        actor=admin_ctx.actor_id,
    )
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


class ModelRegistryIn(BaseModel):
    model_type: str = Field(pattern="^(fraud|care)$")
    tenant_id: str | None = None
    version: str
    artifact_uri: str
    feature_contract_version: str = "v1"
    mapper_version: str = "v1"
    status: str = Field(default="shadow", pattern="^(shadow|active|rollback|disabled)$")
    metadata_json: dict = Field(default_factory=dict)

    @field_validator("artifact_uri")
    @classmethod
    def _validate_artifact_uri(cls, v: str) -> str:
        return _validate_artifact_uri_or_raise(v)


class ModelRegistryOut(BaseModel):
    id: str
    model_type: str
    tenant_id: str | None
    version: str
    artifact_uri: str
    feature_contract_version: str
    mapper_version: str
    status: str
    activated_at: str | None
    created_at: str


class TenantMapperIn(BaseModel):
    tenant_id: str
    model_type: str = Field(pattern="^(fraud|care)$")
    mapper_version: str
    contract_version: str = "v1"
    mapping_json: dict = Field(default_factory=dict)
    is_active: bool = False


class TenantMapperOut(BaseModel):
    id: str
    tenant_id: str
    model_type: str
    mapper_version: str
    contract_version: str
    is_active: bool
    created_at: str


class InferenceTraceOut(BaseModel):
    id: str
    tenant_id: str
    model_type: str
    model_version: str
    mapper_version: str
    contract_version: str
    decision: str | None
    processing_ms: int | None
    trace_json: dict
    created_at: str


class MapperValidateIn(BaseModel):
    model_type: str = Field(pattern="^(fraud|care)$")
    contract_version: str = "v1"
    mapping_json: dict = Field(default_factory=dict)


class MapperDryRunIn(MapperValidateIn):
    raw_payload: dict = Field(default_factory=dict)


class MapperValidationOut(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class MapperDryRunOut(MapperValidationOut):
    canonical_payload: dict | None = None


class CalibrationArtifactIn(BaseModel):
    tenant_id: str
    model_type: str = Field(pattern="^(fraud|care)$")
    model_version: str
    calibration_version: str
    method: str = Field(pattern="^(none|platt|isotonic)$")
    params_json: dict = Field(default_factory=dict)
    status: str = Field(default="shadow", pattern="^(shadow|active|disabled)$")


class CalibrationArtifactOut(BaseModel):
    id: str
    tenant_id: str
    model_type: str
    model_version: str
    calibration_version: str
    method: str
    params_json: dict
    status: str
    activated_at: str | None
    created_at: str


class ModelKpiOut(BaseModel):
    tenant_id: str
    model_type: str
    days: int
    total_scored: int
    block_rate: float
    otp_rate: float
    alert_rate: float
    precision_proxy: float | None = None
    recall_proxy: float | None = None
    fpr_proxy: float | None = None
    labeled_count: int | None = None
    auc_proxy: float | None = None
    decision_mix: dict
    avg_latency_ms: float | None = None
    p90_latency_ms: float | None = None
    shadow_disagree_rate: float | None = None
    avg_confidence: float | None = None


class GuardrailRunOut(BaseModel):
    triggered: bool
    enabled: bool


class ChallengerEvaluatorRunOut(BaseModel):
    triggered: bool
    enabled: bool
    scanned_tenants: int = 0
    promoted_count: int = 0
    window_hours: int = 0
    min_compared: int = 0


class ChallengerPolicyOut(BaseModel):
    enabled: bool
    window_hours: int
    min_compared: int
    max_block_rate_delta: float
    max_otp_rate_delta: float
    max_disagree_rate: float
    cooldown_hours: int
    candidate_min_age_hours: int
    tenant_override: bool = False


class ChallengerPolicyUpdateIn(BaseModel):
    min_compared: int | None = Field(default=None, ge=10, le=50000)
    max_block_rate_delta: float | None = Field(default=None, ge=0.0, le=1.0)
    max_otp_rate_delta: float | None = Field(default=None, ge=0.0, le=1.0)
    max_disagree_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    cooldown_hours: int | None = Field(default=None, ge=1, le=720)
    candidate_min_age_hours: int | None = Field(default=None, ge=1, le=720)


class ChampionChallengerKpiOut(BaseModel):
    tenant_id: str
    model_type: str
    window_hours: int
    total_traces: int
    compared_traces: int
    champion_block_rate: float
    challenger_block_rate: float | None = None
    champion_otp_rate: float
    challenger_otp_rate: float | None = None
    champion_approve_rate: float
    challenger_approve_rate: float | None = None
    disagree_rate: float | None = None
    champion_model_version: str | None = None
    challenger_model_version: str | None = None


class IsolationReadinessOut(BaseModel):
    tenant_id: str
    model_type: str
    strict_mapper_enforcement: bool
    allow_model_fallback: bool
    has_active_model: bool
    has_active_mapper: bool
    active_model_version: str | None = None
    active_mapper_version: str | None = None
    active_artifact_uri: str | None = None
    artifact_exists: bool | None = None
    artifact_check: str = "unknown"
    ready_for_strict_cutover: bool


class PolicyProfileOut(BaseModel):
    profile: str
    environment: str
    enforce_production_hardening: bool
    violations: list[str] = Field(default_factory=list)
    ok: bool


class CutoverGateOut(BaseModel):
    tenant_id: str
    model_type: str
    pass_gate: bool
    checked_at: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_trace_count_24h: int = 0
    latest_labeled_count_30d: int = 0
    latest_precision_30d: float | None = None
    latest_snapshot_at: str | None = None
    last_executed_at: str | None = None
    last_executed_by: str | None = None


class CutoverExecuteOut(BaseModel):
    executed: bool
    tenant_id: str
    model_type: str
    checked_at: str
    message: str
    blockers: list[str] = Field(default_factory=list)


class CutoverAutoRunOut(BaseModel):
    triggered: bool
    enabled: bool
    dry_run: bool
    scanned: int
    eligible: int
    executed: int
    model_types: list[str] = Field(default_factory=list)
    require_no_prior_execution: bool = True


class WarehouseIsolationVerifyOut(BaseModel):
    triggered: bool
    enabled: bool
    passed: bool
    errors: list[str] = Field(default_factory=list)
    checked_tables: list[str] = Field(default_factory=list)


class JobRunOut(BaseModel):
    id: str
    job_name: str
    trigger_source: str
    actor_id: str | None = None
    request_id: str | None = None
    status: str
    started_at: str
    finished_at: str | None = None
    duration_ms: int | None = None
    error_summary: str | None = None
    result_json: dict | None = None


class TenantRetentionPreviewOut(BaseModel):
    tenant_id: str
    retention_days: int
    before: str
    inference_trace_rows: int
    training_upload_rows: int
    fraud_score_rows: int
    fraud_alert_rows: int


class CanaryPercentIn(BaseModel):
    canary_percent: float = Field(ge=0.0, le=100.0)


class TenantExportOut(BaseModel):
    tenant_id: str
    generated_at: str
    artifact_path: str
    summary: dict = Field(default_factory=dict)


class TenantAnonymizeOut(BaseModel):
    tenant_id: str
    anonymized_at: str
    customers_updated: int
    transactions_updated: int


class TenantExportJobOut(BaseModel):
    job_id: str
    tenant_id: str
    status: str
    created_at: str
    finished_at: str | None = None
    artifact_path: str | None = None
    summary: dict | None = None
    error: str | None = None


class BatchCutoverGateItemOut(BaseModel):
    tenant_id: str
    tenant_name: str
    model_type: str
    pass_gate: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_trace_count_24h: int = 0
    latest_labeled_count_30d: int = 0
    latest_precision_30d: float | None = None
    checked_at: str


class BatchCutoverGateOut(BaseModel):
    checked_at: str
    scanned: int
    pass_count: int
    fail_count: int
    items: list[BatchCutoverGateItemOut] = Field(default_factory=list)


def _sign_payload(payload: str) -> str:
    key = (settings.secret_key or "dev-secret").encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _serialize_export_job(job: ReportJob) -> TenantExportJobOut:
    return TenantExportJobOut(
        job_id=str(job.id),
        tenant_id=str(job.tenant_id),
        status=job.status,
        created_at=job.created_at.isoformat() if job.created_at else "",
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        artifact_path=job.artifact_pdf_path,
        summary=(dict(job.summary) if isinstance(job.summary, dict) else None),
        error=job.error,
    )


class ModelKpiSnapshotOut(BaseModel):
    created_at: str
    window_days: int
    total_scored: int
    labeled_count: int
    block_rate: float
    otp_rate: float
    alert_rate: float
    precision: float | None
    recall: float | None
    fpr: float | None
    auc: float | None


class ModelKpiSnapshotRunOut(BaseModel):
    triggered: bool
    created: int
    window_days: int
    stale_flagged: int = 0


class DeploymentReadinessOut(BaseModel):
    environment: str
    enforce_production_hardening: bool
    production_hardening_ok: bool
    production_hardening_issues: list[str] = Field(default_factory=list)
    strict_mapper_enforcement: bool
    strict_training_governance: bool
    allow_model_fallback: bool
    alert_webhook_configured: bool
    paging_webhook_configured: bool
    warehouse_verification_enabled: bool
    warehouse_require_local_training_layout: bool
    read_replica_configured: bool
    analytics_warehouse_configured: bool
    s3_data_plane_configured: bool
    calibration_activation_requires_validation: bool
    auto_cutover_enabled: bool
    auto_cutover_dry_run: bool


class CalibrationHoldoutOut(BaseModel):
    upload_id: str
    accuracy: float
    auc: float | None = None
    n_scored: int = 0
    validated_at: str


class TraceHumanFeedbackIn(BaseModel):
    true_intent: str = Field(min_length=1, max_length=80)


class FineTuneEligibilityOut(BaseModel):
    tenant_id: str
    model_type: str
    min_rows_required: int
    rows_available: int
    quality_score: float | None = None
    eligible: bool
    reasons: list[str] = Field(default_factory=list)


class FineTuneStartOut(BaseModel):
    status: str
    message: str
    upload_id: str
    tenant_id: str
    model_type: str
    model_registry_id: str


def _model_registry_out(row: ModelRegistry) -> ModelRegistryOut:
    return ModelRegistryOut(
        id=str(row.id),
        model_type=row.model_type,
        tenant_id=str(row.tenant_id) if row.tenant_id else None,
        version=row.version,
        artifact_uri=row.artifact_uri,
        feature_contract_version=row.feature_contract_version,
        mapper_version=row.mapper_version,
        status=row.status,
        activated_at=row.activated_at.isoformat() if row.activated_at else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _tenant_mapper_out(row: TenantMapper) -> TenantMapperOut:
    return TenantMapperOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        model_type=row.model_type,
        mapper_version=row.mapper_version,
        contract_version=row.contract_version,
        is_active=bool(row.is_active),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _calibration_out(row: CalibrationArtifact) -> CalibrationArtifactOut:
    return CalibrationArtifactOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        model_type=row.model_type,
        model_version=row.model_version,
        calibration_version=row.calibration_version,
        method=row.method,
        params_json=dict(row.params_json or {}),
        status=row.status,
        activated_at=row.activated_at.isoformat() if row.activated_at else None,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


class TenantModelRegistrationStatusOut(BaseModel):
    fraud_registered: bool
    care_registered: bool


async def _ensure_tenant_model_registered_or_403(
    db: AsyncSession, *, tenant_id: uuid.UUID, model_type: str
) -> None:
    if not await tenant_has_registered_model(db, tenant_id=tenant_id, model_type=model_type):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Register a {model_type} model for this tenant in Model registry "
                "before using this resource."
            ),
        )


@router.get("/tenants/{tenant_id}/model-registration-status", response_model=TenantModelRegistrationStatusOut)
async def tenant_model_registration_status(
    tenant_id: uuid.UUID,
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    fraud_registered = await tenant_has_registered_model(db, tenant_id=tenant_id, model_type="fraud")
    care_registered = await tenant_has_registered_model(db, tenant_id=tenant_id, model_type="care")
    return TenantModelRegistrationStatusOut(fraud_registered=fraud_registered, care_registered=care_registered)


@router.get("/tenants/{tenant_id}/fraud-policy", response_model=FraudPolicyOut)
async def get_fraud_policy(
    tenant_id: uuid.UUID,
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not await tenant_has_registered_model(db, tenant_id=tenant_id, model_type="fraud"):
        raise HTTPException(
            status_code=403,
            detail="Register a fraud model for this tenant in Model registry before viewing fraud policy.",
        )
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
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not await tenant_has_registered_model(db, tenant_id=tenant_id, model_type="fraud"):
        raise HTTPException(
            status_code=403,
            detail="Register a fraud model for this tenant in Model registry before updating fraud policy.",
        )
    if bank.tone_config is None:
        bank.tone_config = {}
    policy = dict(bank.tone_config.get("fraud_policy") or {})
    prev_policy = dict(policy)
    update = payload.model_dump(exclude_unset=True)
    for k, v in update.items():
        if v is not None:
            policy[k] = v
    bank.tone_config = {**(bank.tone_config or {}), "fraud_policy": policy}
    await db.flush()
    if policy != prev_policy:
        await _audit_admin_change(
            db,
            "FRAUD_POLICY_UPDATE",
            {"tenant_id": str(tenant_id), "prev": prev_policy, "next": policy},
            actor=admin_ctx.actor_id,
        )
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


@router.post("/model-registry", response_model=ModelRegistryOut)
async def create_model_registry_entry(
    payload: ModelRegistryIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = uuid.UUID(payload.tenant_id) if payload.tenant_id else None
    if tenant_uuid:
        await ensure_tenant_access(db, admin_ctx, tenant_uuid)
    artifact_uri = _validate_artifact_uri_or_raise(payload.artifact_uri)
    artifact_sha = _artifact_sha256(artifact_uri)
    lineage = {
        "dataset_version": (payload.metadata_json or {}).get("dataset_version"),
        "contract_version": payload.feature_contract_version,
        "mapper_version": payload.mapper_version,
        "artifact_sha256": artifact_sha,
        "artifact_uri": artifact_uri,
    }
    metadata_json = {
        **(payload.metadata_json or {}),
        "lineage": {k: v for k, v in lineage.items() if v is not None},
    }
    row = ModelRegistry(
        model_type=payload.model_type,
        tenant_id=tenant_uuid,
        version=payload.version,
        artifact_uri=artifact_uri,
        feature_contract_version=payload.feature_contract_version,
        mapper_version=payload.mapper_version,
        status=payload.status,
        metadata_json=metadata_json,
        activated_at=datetime.now(timezone.utc) if payload.status == "active" else None,
    )
    db.add(row)
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_REGISTRY_CREATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "model_type": row.model_type,
            "version": row.version,
            "status": row.status,
            "artifact_uri": row.artifact_uri,
            "feature_contract_version": row.feature_contract_version,
            "mapper_version": row.mapper_version,
        },
        actor=admin_ctx.actor_id,
    )
    return _model_registry_out(row)


@router.get("/model-registry", response_model=List[ModelRegistryOut])
async def list_model_registry_entries(
    tenant_id: uuid.UUID | None = Query(default=None),
    model_type: str | None = Query(default=None, pattern="^(fraud|care)$"),
    status: str | None = Query(default=None, pattern="^(shadow|active|rollback|disabled)$"),
    limit: int = Query(100, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_read_db),
    write_db: AsyncSession = Depends(get_db),
):
    stmt = select(ModelRegistry).order_by(ModelRegistry.created_at.desc()).limit(limit)
    if tenant_id is not None:
        await ensure_tenant_access(write_db, _admin, tenant_id)
        stmt = stmt.where(ModelRegistry.tenant_id == tenant_id)
    elif _admin.role != "owner":
        visible = await visible_tenant_ids_for_list(write_db, _admin)
        if not visible:
            return []
        stmt = stmt.where(ModelRegistry.tenant_id.in_(visible))
    if model_type:
        stmt = stmt.where(ModelRegistry.model_type == model_type)
    if status:
        stmt = stmt.where(ModelRegistry.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [_model_registry_out(r) for r in rows]


@router.post("/model-registry/{entry_id}/activate", response_model=ModelRegistryOut)
async def activate_model_registry_entry(
    entry_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ModelRegistry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model registry entry not found")
    if row.tenant_id:
        await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    await _acquire_registry_lock(db, row, "activate")
    fp = _request_fingerprint_for_registry_action(row, "activate")
    replay = await _idempotency_replay_or_none(
        db, scope=f"model_registry:{entry_id}:activate", idempotency_key=idempotency_key, request_fingerprint=fp
    )
    if replay is not None:
        return ModelRegistryOut(**replay)
    _verify_registry_artifact_integrity_or_raise(row)
    prior = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == row.model_type,
                ModelRegistry.tenant_id == row.tenant_id,
                ModelRegistry.status == "active",
            )
        )
    ).scalars().all()
    for p in prior:
        p.status = "shadow"
    row.status = "active"
    row.activated_at = datetime.now(timezone.utc)
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_REGISTRY_ACTIVATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "model_type": row.model_type,
            "version": row.version,
            "prior_active_ids": [str(p.id) for p in prior if p.id != row.id],
        },
        actor=admin_ctx.actor_id,
    )
    out = _model_registry_out(row)
    await _store_idempotency_result(
        db,
        scope=f"model_registry:{entry_id}:activate",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        response_json=out.model_dump(),
    )
    return out


@router.post("/model-registry/{entry_id}/rollback", response_model=ModelRegistryOut)
async def rollback_model_registry_entry(
    entry_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    current = await db.get(ModelRegistry, entry_id)
    if not current:
        raise HTTPException(status_code=404, detail="Model registry entry not found")
    if current.tenant_id:
        await ensure_tenant_access(db, admin_ctx, current.tenant_id)
    await _acquire_registry_lock(db, current, "rollback")
    fp = _request_fingerprint_for_registry_action(current, "rollback")
    replay = await _idempotency_replay_or_none(
        db, scope=f"model_registry:{entry_id}:rollback", idempotency_key=idempotency_key, request_fingerprint=fp
    )
    if replay is not None:
        return ModelRegistryOut(**replay)
    if current.status != "active":
        raise HTTPException(status_code=400, detail="Rollback requires the current active model entry.")

    prev = (
        await db.execute(
            select(ModelRegistry)
            .where(
                ModelRegistry.model_type == current.model_type,
                ModelRegistry.tenant_id == current.tenant_id,
                ModelRegistry.id != current.id,
                ModelRegistry.status.in_(("shadow", "rollback")),
            )
            .order_by(ModelRegistry.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not prev:
        raise HTTPException(status_code=404, detail="No previous model found to rollback to.")
    _verify_registry_artifact_integrity_or_raise(prev)

    current.status = "rollback"
    prev.status = "active"
    prev.activated_at = datetime.now(timezone.utc)
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_REGISTRY_ROLLBACK",
        {
            "tenant_id": str(current.tenant_id) if current.tenant_id else None,
            "model_type": current.model_type,
            "from_id": str(current.id),
            "from_version": current.version,
            "to_id": str(prev.id),
            "to_version": prev.version,
        },
        actor=admin_ctx.actor_id,
    )
    out = _model_registry_out(prev)
    await _store_idempotency_result(
        db,
        scope=f"model_registry:{entry_id}:rollback",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        response_json=out.model_dump(),
    )
    return out


@router.post("/model-registry/{entry_id}/promote", response_model=ModelRegistryOut)
async def promote_challenger_model_registry_entry(
    entry_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ModelRegistry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model registry entry not found")
    if row.tenant_id:
        await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    await _acquire_registry_lock(db, row, "promote")
    fp = _request_fingerprint_for_registry_action(row, "promote")
    replay = await _idempotency_replay_or_none(
        db, scope=f"model_registry:{entry_id}:promote", idempotency_key=idempotency_key, request_fingerprint=fp
    )
    if replay is not None:
        return ModelRegistryOut(**replay)
    if row.status == "active":
        return _model_registry_out(row)
    if row.status not in {"shadow", "rollback"}:
        raise HTTPException(status_code=400, detail="Only shadow/rollback entries can be promoted.")
    _verify_registry_artifact_integrity_or_raise(row)

    prior = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == row.model_type,
                ModelRegistry.tenant_id == row.tenant_id,
                ModelRegistry.status == "active",
            )
        )
    ).scalars().all()
    for p in prior:
        p.status = "rollback"
    row.status = "active"
    row.activated_at = datetime.now(timezone.utc)
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_CHALLENGER_PROMOTED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "model_type": row.model_type,
            "version": row.version,
            "prior_active_ids": [str(p.id) for p in prior if p.id != row.id],
        },
        actor=admin_ctx.actor_id,
    )
    out = _model_registry_out(row)
    await _store_idempotency_result(
        db,
        scope=f"model_registry:{entry_id}:promote",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        response_json=out.model_dump(),
    )
    return out


@router.post("/model-registry/{entry_id}/pause", response_model=ModelRegistryOut)
async def pause_model_registry_entry(
    entry_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ModelRegistry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model registry entry not found")
    if row.tenant_id:
        await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    await _acquire_registry_lock(db, row, "pause")
    fp = _request_fingerprint_for_registry_action(row, "pause")
    replay = await _idempotency_replay_or_none(
        db, scope=f"model_registry:{entry_id}:pause", idempotency_key=idempotency_key, request_fingerprint=fp
    )
    if replay is not None:
        return ModelRegistryOut(**replay)
    if row.status == "active":
        raise HTTPException(status_code=400, detail="Cannot pause an active model. Roll back or promote another model first.")
    prev_status = row.status
    row.status = "disabled"
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_CHALLENGER_PAUSED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "model_type": row.model_type,
            "version": row.version,
            "previous_status": prev_status,
            "new_status": row.status,
        },
        actor=admin_ctx.actor_id,
    )
    out = _model_registry_out(row)
    await _store_idempotency_result(
        db,
        scope=f"model_registry:{entry_id}:pause",
        idempotency_key=idempotency_key,
        request_fingerprint=fp,
        response_json=out.model_dump(),
    )
    return out


@router.post("/model-registry/{entry_id}/canary", response_model=ModelRegistryOut)
async def set_model_registry_canary_percent(
    entry_id: uuid.UUID,
    payload: CanaryPercentIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ModelRegistry, entry_id)
    if not row:
        raise HTTPException(status_code=404, detail="Model registry entry not found")
    if row.tenant_id:
        await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    meta = dict(row.metadata_json or {})
    meta["canary_percent"] = float(payload.canary_percent)
    row.metadata_json = meta
    await db.flush()
    await _audit_admin_change(
        db,
        "MODEL_CANARY_PERCENT_UPDATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
            "model_type": row.model_type,
            "version": row.version,
            "canary_percent": float(payload.canary_percent),
        },
        actor=admin_ctx.actor_id,
    )
    return _model_registry_out(row)


@router.post("/tenant-mappers", response_model=TenantMapperOut)
async def create_tenant_mapper(
    payload: TenantMapperIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = uuid.UUID(payload.tenant_id)
    await ensure_tenant_access(db, admin_ctx, tenant_uuid)
    mapper_errors = validate_mapper_shape(
        model_type=payload.model_type,
        contract_version=payload.contract_version,
        mapping_json=payload.mapping_json or {},
    )
    if mapper_errors:
        raise HTTPException(status_code=422, detail={"code": "mapper_validation_failed", "errors": mapper_errors})
    if payload.is_active:
        prev = (
            await db.execute(
                select(TenantMapper).where(
                    TenantMapper.tenant_id == tenant_uuid,
                    TenantMapper.model_type == payload.model_type,
                    TenantMapper.is_active.is_(True),
                )
            )
        ).scalars().all()
        for p in prev:
            p.is_active = False
    row = TenantMapper(
        tenant_id=tenant_uuid,
        model_type=payload.model_type,
        mapper_version=payload.mapper_version,
        contract_version=payload.contract_version,
        mapping_json=payload.mapping_json or {},
        is_active=payload.is_active,
    )
    db.add(row)
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_MAPPER_CREATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "model_type": row.model_type,
            "mapper_version": row.mapper_version,
            "contract_version": row.contract_version,
            "is_active": bool(row.is_active),
        },
        actor=admin_ctx.actor_id,
    )
    return _tenant_mapper_out(row)


@router.post("/tenant-mappers/validate", response_model=MapperValidationOut)
async def validate_tenant_mapper_payload(
    payload: MapperValidateIn,
    _admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
):
    errors = validate_mapper_shape(
        model_type=payload.model_type,
        contract_version=payload.contract_version,
        mapping_json=payload.mapping_json or {},
    )
    return MapperValidationOut(valid=(len(errors) == 0), errors=errors)


@router.post("/tenant-mappers/dry-run", response_model=MapperDryRunOut)
async def dry_run_tenant_mapper_payload(
    payload: MapperDryRunIn,
    _admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
):
    canonical, errors = validate_and_dry_run(
        model_type=payload.model_type,
        contract_version=payload.contract_version,
        mapping_json=payload.mapping_json or {},
        raw_payload=payload.raw_payload or {},
    )
    return MapperDryRunOut(valid=(len(errors) == 0), errors=errors, canonical_payload=canonical)


@router.get("/tenant-mappers", response_model=List[TenantMapperOut])
async def list_tenant_mappers(
    tenant_id: uuid.UUID,
    model_type: str | None = Query(default=None, pattern="^(fraud|care)$"),
    only_active: bool = Query(False),
    limit: int = Query(100, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    stmt = (
        select(TenantMapper)
        .where(TenantMapper.tenant_id == tenant_id)
        .order_by(TenantMapper.created_at.desc())
        .limit(limit)
    )
    if model_type:
        stmt = stmt.where(TenantMapper.model_type == model_type)
    if only_active:
        stmt = stmt.where(TenantMapper.is_active.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return [_tenant_mapper_out(r) for r in rows]


@router.post("/tenant-mappers/{mapper_id}/activate", response_model=TenantMapperOut)
async def activate_tenant_mapper(
    mapper_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(TenantMapper, mapper_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tenant mapper not found")
    await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    mapper_errors = validate_mapper_shape(
        model_type=row.model_type,
        contract_version=row.contract_version,
        mapping_json=row.mapping_json or {},
    )
    if mapper_errors:
        raise HTTPException(status_code=422, detail={"code": "mapper_validation_failed", "errors": mapper_errors})

    prev = (
        await db.execute(
            select(TenantMapper).where(
                TenantMapper.tenant_id == row.tenant_id,
                TenantMapper.model_type == row.model_type,
                TenantMapper.is_active.is_(True),
                TenantMapper.id != row.id,
            )
        )
    ).scalars().all()
    for p in prev:
        p.is_active = False
    row.is_active = True
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_MAPPER_ACTIVATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "model_type": row.model_type,
            "mapper_version": row.mapper_version,
            "deactivated_ids": [str(p.id) for p in prev],
        },
        actor=admin_ctx.actor_id,
    )
    return _tenant_mapper_out(row)


@router.post("/calibration", response_model=CalibrationArtifactOut)
async def create_calibration_artifact(
    payload: CalibrationArtifactIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    tenant_uuid = uuid.UUID(payload.tenant_id)
    await ensure_tenant_access(db, admin_ctx, tenant_uuid)
    row = CalibrationArtifact(
        tenant_id=tenant_uuid,
        model_type=payload.model_type,
        model_version=payload.model_version,
        calibration_version=payload.calibration_version,
        method=payload.method,
        params_json=payload.params_json or {},
        status=payload.status,
        activated_at=datetime.now(timezone.utc) if payload.status == "active" else None,
    )
    if payload.status == "active":
        prev = (
            await db.execute(
                select(CalibrationArtifact).where(
                    CalibrationArtifact.tenant_id == tenant_uuid,
                    CalibrationArtifact.model_type == payload.model_type,
                    CalibrationArtifact.model_version == payload.model_version,
                    CalibrationArtifact.status == "active",
                )
            )
        ).scalars().all()
        for p in prev:
            p.status = "shadow"
    db.add(row)
    await db.flush()
    await _audit_admin_change(
        db,
        "CALIBRATION_CREATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "model_type": row.model_type,
            "model_version": row.model_version,
            "calibration_version": row.calibration_version,
            "method": row.method,
            "status": row.status,
        },
        actor=admin_ctx.actor_id,
    )
    return _calibration_out(row)


@router.get("/calibration", response_model=List[CalibrationArtifactOut])
async def list_calibration_artifacts(
    tenant_id: uuid.UUID,
    model_type: str | None = Query(default=None, pattern="^(fraud|care)$"),
    model_version: str | None = Query(default=None),
    limit: int = Query(100, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    stmt = (
        select(CalibrationArtifact)
        .where(CalibrationArtifact.tenant_id == tenant_id)
        .order_by(CalibrationArtifact.created_at.desc())
        .limit(limit)
    )
    if model_type:
        stmt = stmt.where(CalibrationArtifact.model_type == model_type)
    if model_version:
        stmt = stmt.where(CalibrationArtifact.model_version == model_version)
    rows = (await db.execute(stmt)).scalars().all()
    return [_calibration_out(r) for r in rows]


@router.post("/calibration/{artifact_id}/holdout-validate", response_model=CalibrationHoldoutOut)
async def validate_calibration_holdout(
    artifact_id: uuid.UUID,
    upload_id: str = Form(...),
    sample_max: int = Form(400),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(CalibrationArtifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Calibration artifact not found")
    await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    uid = uuid.UUID(upload_id.strip())
    try:
        if row.model_type == "fraud":
            out = await evaluate_fraud_upload(db, uid, sample_max=max(50, min(5000, int(sample_max))))
        else:
            out = await evaluate_care_upload(db, uid, sample_max=max(20, min(2000, int(sample_max))))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    pj = dict(row.params_json or {})
    hv = {
        "upload_id": str(uid),
        "accuracy": float(out.get("accuracy") or 0.0),
        "auc": out.get("auc"),
        "n_scored": int(out.get("n_scored") or 0),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    pj["holdout_validation"] = hv
    row.params_json = pj
    await db.flush()
    await _audit_admin_change(
        db,
        "CALIBRATION_HOLDOUT_VALIDATED",
        {
            "calibration_id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "model_type": row.model_type,
            "holdout": hv,
        },
        actor=admin_ctx.actor_id,
    )
    return CalibrationHoldoutOut(
        upload_id=hv["upload_id"],
        accuracy=hv["accuracy"],
        auc=(float(hv["auc"]) if hv.get("auc") is not None else None),
        n_scored=hv["n_scored"],
        validated_at=hv["validated_at"],
    )


@router.post("/calibration/{artifact_id}/activate", response_model=CalibrationArtifactOut)
async def activate_calibration_artifact(
    artifact_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(CalibrationArtifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Calibration artifact not found")
    await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    if settings.calibration_activation_requires_validation:
        hv = (row.params_json or {}).get("holdout_validation") or {}
        if not hv.get("validated_at"):
            raise HTTPException(
                status_code=422,
                detail="holdout_validation_required: POST /calibration/{id}/holdout-validate with a TRAINED upload_id first.",
            )
        acc = float(hv.get("accuracy") or 0.0)
        if acc < float(settings.calibration_activation_min_accuracy):
            raise HTTPException(
                status_code=422,
                detail=f"holdout accuracy {acc} below minimum {settings.calibration_activation_min_accuracy}",
            )
        if row.model_type == "fraud" and settings.calibration_activation_min_auc is not None:
            aucv = hv.get("auc")
            if aucv is None or float(aucv) < float(settings.calibration_activation_min_auc):
                raise HTTPException(
                    status_code=422,
                    detail=f"holdout AUC insufficient (min {settings.calibration_activation_min_auc})",
                )
    prev = (
        await db.execute(
            select(CalibrationArtifact).where(
                CalibrationArtifact.tenant_id == row.tenant_id,
                CalibrationArtifact.model_type == row.model_type,
                CalibrationArtifact.model_version == row.model_version,
                CalibrationArtifact.status == "active",
            )
        )
    ).scalars().all()
    for p in prev:
        if p.id != row.id:
            p.status = "shadow"
    row.status = "active"
    row.activated_at = datetime.now(timezone.utc)
    await db.flush()
    await _audit_admin_change(
        db,
        "CALIBRATION_ACTIVATED",
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "model_type": row.model_type,
            "model_version": row.model_version,
            "calibration_version": row.calibration_version,
        },
        actor=admin_ctx.actor_id,
    )
    return _calibration_out(row)


@router.get("/inference-trace", response_model=List[InferenceTraceOut])
async def list_inference_traces(
    tenant_id: uuid.UUID,
    model_type: str | None = Query(default=None, pattern="^(fraud|care)$"),
    limit: int = Query(50, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    stmt = select(InferenceTrace).where(InferenceTrace.tenant_id == tenant_id).order_by(InferenceTrace.created_at.desc()).limit(limit)
    if model_type:
        stmt = stmt.where(InferenceTrace.model_type == model_type)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        InferenceTraceOut(
            id=str(r.id),
            tenant_id=str(r.tenant_id),
            model_type=r.model_type,
            model_version=r.model_version,
            mapper_version=r.mapper_version,
            contract_version=r.contract_version,
            decision=r.decision,
            processing_ms=r.processing_ms,
            trace_json=dict(r.trace_json or {}),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.patch("/inference-trace/{trace_id}/human-feedback", response_model=InferenceTraceOut)
async def patch_inference_trace_human_feedback(
    trace_id: uuid.UUID,
    payload: TraceHumanFeedbackIn,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(InferenceTrace, trace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Inference trace not found")
    await ensure_tenant_access(db, admin_ctx, row.tenant_id)
    tj = dict(row.trace_json or {})
    hf = dict(tj.get("human_feedback") or {}) if isinstance(tj.get("human_feedback"), dict) else {}
    hf["true_intent"] = payload.true_intent.strip()
    hf["updated_at"] = datetime.now(timezone.utc).isoformat()
    tj["human_feedback"] = hf
    row.trace_json = tj
    await db.flush()
    await _audit_admin_change(
        db,
        "INFERENCE_TRACE_HUMAN_FEEDBACK",
        {"trace_id": str(trace_id), "tenant_id": str(row.tenant_id), "model_type": row.model_type},
        actor=admin_ctx.actor_id,
    )
    return InferenceTraceOut(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        model_type=row.model_type,
        model_version=row.model_version,
        mapper_version=row.mapper_version,
        contract_version=row.contract_version,
        decision=row.decision,
        processing_ms=row.processing_ms,
        trace_json=dict(row.trace_json or {}),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@router.get("/monitoring/fraud-drift", response_model=List[FraudDriftOut])
async def fraud_drift_monitor(
    tenant_id: uuid.UUID = Query(...),
    recent_limit: int = Query(600, ge=100, le=5000),
    baseline_limit: int = Query(3000, ge=500, le=10000),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type="fraud")
    drift = await compute_tenant_drift(db, tenant_id, recent_limit=recent_limit, baseline_limit=baseline_limit)
    if drift.get("status") == "insufficient_data":
        raise HTTPException(status_code=400, detail="Not enough fraud scores for drift monitoring.")
    return [
        FraudDriftOut(
            feature=str(x.get("feature")),
            psi=float(x.get("psi", 0.0)),
            ks=float(x.get("ks", 0.0)),
            alert=bool(str(x.get("severity")) in {"yellow", "red"}),
        )
        for x in drift.get("features", [])
    ]


@router.get("/monitoring/deployment-readiness", response_model=DeploymentReadinessOut)
async def deployment_readiness(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    issues = collect_production_violations(settings)
    return DeploymentReadinessOut(
        environment=str(settings.environment or "development"),
        enforce_production_hardening=bool(settings.enforce_production_hardening),
        production_hardening_ok=len(issues) == 0,
        production_hardening_issues=issues,
        strict_mapper_enforcement=bool(settings.strict_mapper_enforcement),
        strict_training_governance=bool(settings.strict_training_governance),
        allow_model_fallback=bool(settings.allow_model_fallback),
        alert_webhook_configured=bool(str(settings.alert_webhook_url or "").strip()),
        paging_webhook_configured=bool(str(settings.paging_webhook_url or "").strip()),
        warehouse_verification_enabled=bool(settings.warehouse_isolation_verification_enabled),
        warehouse_require_local_training_layout=bool(settings.warehouse_isolation_require_local_training_layout),
        read_replica_configured=bool(str(settings.read_replica_database_url or "").strip()),
        analytics_warehouse_configured=bool(str(settings.analytics_warehouse_url or "").strip()),
        s3_data_plane_configured=bool(str(settings.data_plane_s3_bucket or "").strip()),
        calibration_activation_requires_validation=bool(settings.calibration_activation_requires_validation),
        auto_cutover_enabled=bool(settings.auto_cutover_enabled),
        auto_cutover_dry_run=bool(settings.auto_cutover_dry_run),
    )


@router.get("/monitoring/model-kpis", response_model=ModelKpiOut)
async def model_kpis(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    days: int = Query(30, ge=1, le=180),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type=model_type)
    if model_type == "care":
        k = await compute_care_kpis(db, tenant_id=tenant_id, days=days)
    else:
        k = await compute_fraud_kpis(db, tenant_id=tenant_id, days=days)
    return ModelKpiOut(
        tenant_id=str(tenant_id),
        model_type=model_type,
        days=days,
        total_scored=k.total_scored,
        block_rate=k.block_rate,
        otp_rate=k.otp_rate,
        alert_rate=k.alert_rate,
        precision_proxy=k.precision,
        recall_proxy=k.recall,
        fpr_proxy=k.fpr,
        labeled_count=k.labeled_count,
        auc_proxy=k.auc,
        decision_mix=k.decision_mix,
        avg_latency_ms=k.avg_latency_ms,
        p90_latency_ms=k.p90_latency_ms,
        shadow_disagree_rate=k.shadow_disagree_rate,
        avg_confidence=k.avg_confidence,
    )


@router.get("/monitoring/model-kpis/history", response_model=List[ModelKpiSnapshotOut])
async def model_kpis_history(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    window_days: int = Query(30, ge=1, le=180),
    limit: int = Query(60, ge=1, le=500),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type=model_type)
    rows = (
        await db.execute(
            select(ModelKpiSnapshot)
            .where(
                ModelKpiSnapshot.tenant_id == tenant_id,
                ModelKpiSnapshot.model_type == model_type,
                ModelKpiSnapshot.window_days == window_days,
            )
            .order_by(ModelKpiSnapshot.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        ModelKpiSnapshotOut(
            created_at=r.created_at.isoformat() if r.created_at else "",
            window_days=int(r.window_days),
            total_scored=int(r.total_scored),
            labeled_count=int(r.labeled_count),
            block_rate=float(r.block_rate),
            otp_rate=float(r.otp_rate),
            alert_rate=float(r.alert_rate),
            precision=(float(r.precision) if r.precision is not None else None),
            recall=(float(r.recall) if r.recall is not None else None),
            fpr=(float(r.fpr) if r.fpr is not None else None),
            auc=(float(r.auc) if r.auc is not None else None),
        )
        for r in rows
    ]


@router.post("/monitoring/model-kpis/snapshot/run", response_model=ModelKpiSnapshotRunOut)
async def run_model_kpi_snapshot_now(
    window_days: int = Query(30, ge=1, le=180),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
):
    result = await run_tracked_job(
        job_name="model_kpi_snapshot_manual",
        trigger_source="api_manual",
        actor_id=admin_ctx.actor_id,
        runner=lambda: run_model_kpi_snapshot(window_days),
    )
    return ModelKpiSnapshotRunOut(
        triggered=True,
        created=int(result.get("created", 0)),
        window_days=int(result.get("window_days", window_days)),
        stale_flagged=int(result.get("stale_flagged", 0)),
    )


@router.post("/monitoring/model-guardrails/run", response_model=GuardrailRunOut)
async def run_model_guardrails_now(
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
):
    await run_tracked_job(
        job_name="model_guardrails_manual",
        trigger_source="api_manual",
        actor_id=admin_ctx.actor_id,
        runner=run_model_guardrails,
    )
    return GuardrailRunOut(triggered=True, enabled=bool(settings.auto_rollback_enabled))


@router.get("/monitoring/challenger-policy", response_model=ChallengerPolicyOut)
async def challenger_policy(
    tenant_id: uuid.UUID | None = Query(default=None),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    tenant_override = False
    overrides: dict = {}
    if tenant_id is not None:
        await ensure_tenant_access(db, _admin, tenant_id)
        await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type="fraud")
        bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
        if not bank:
            raise HTTPException(status_code=404, detail="Tenant not found")
        cfg = bank.tone_config or {}
        overrides = cfg.get("challenger_policy") if isinstance(cfg.get("challenger_policy"), dict) else {}
        tenant_override = bool(overrides)
    return ChallengerPolicyOut(
        enabled=bool(settings.auto_promotion_enabled),
        window_hours=int(settings.auto_promotion_window_hours),
        min_compared=int(overrides.get("min_compared") or settings.auto_promotion_min_compared),
        max_block_rate_delta=float(overrides.get("max_block_rate_delta") or settings.auto_promotion_max_block_rate_delta),
        max_otp_rate_delta=float(overrides.get("max_otp_rate_delta") or settings.auto_promotion_max_otp_rate_delta),
        max_disagree_rate=float(overrides.get("max_disagree_rate") or settings.auto_promotion_max_disagree_rate),
        cooldown_hours=int(overrides.get("cooldown_hours") or settings.auto_promotion_cooldown_hours),
        candidate_min_age_hours=int(overrides.get("candidate_min_age_hours") or settings.auto_promotion_candidate_min_age_hours),
        tenant_override=tenant_override,
    )


@router.patch("/monitoring/challenger-policy", response_model=ChallengerPolicyOut)
async def update_challenger_policy(
    tenant_id: uuid.UUID = Query(...),
    payload: ChallengerPolicyUpdateIn = ...,
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type="fraud")
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cfg = dict(bank.tone_config or {})
    pol = dict(cfg.get("challenger_policy") or {})
    prev = dict(pol)
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            pol[k] = v
    cfg["challenger_policy"] = pol
    bank.tone_config = cfg
    await db.flush()
    if pol != prev:
        await _audit_admin_change(
            db,
            "CHALLENGER_POLICY_UPDATED",
            {"tenant_id": str(tenant_id), "prev": prev, "next": pol},
            actor=admin_ctx.actor_id,
        )
    return ChallengerPolicyOut(
        enabled=bool(settings.auto_promotion_enabled),
        window_hours=int(settings.auto_promotion_window_hours),
        min_compared=int(pol.get("min_compared") or settings.auto_promotion_min_compared),
        max_block_rate_delta=float(pol.get("max_block_rate_delta") or settings.auto_promotion_max_block_rate_delta),
        max_otp_rate_delta=float(pol.get("max_otp_rate_delta") or settings.auto_promotion_max_otp_rate_delta),
        max_disagree_rate=float(pol.get("max_disagree_rate") or settings.auto_promotion_max_disagree_rate),
        cooldown_hours=int(pol.get("cooldown_hours") or settings.auto_promotion_cooldown_hours),
        candidate_min_age_hours=int(pol.get("candidate_min_age_hours") or settings.auto_promotion_candidate_min_age_hours),
        tenant_override=True,
    )


@router.delete("/monitoring/challenger-policy", response_model=ChallengerPolicyOut)
async def reset_challenger_policy(
    tenant_id: uuid.UUID = Query(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type="fraud")
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cfg = dict(bank.tone_config or {})
    prev = dict(cfg.get("challenger_policy") or {})
    cfg.pop("challenger_policy", None)
    bank.tone_config = cfg
    await db.flush()
    await _audit_admin_change(
        db,
        "CHALLENGER_POLICY_RESET",
        {"tenant_id": str(tenant_id), "prev": prev, "next": {}},
        actor=admin_ctx.actor_id,
    )
    return ChallengerPolicyOut(
        enabled=bool(settings.auto_promotion_enabled),
        window_hours=int(settings.auto_promotion_window_hours),
        min_compared=int(settings.auto_promotion_min_compared),
        max_block_rate_delta=float(settings.auto_promotion_max_block_rate_delta),
        max_otp_rate_delta=float(settings.auto_promotion_max_otp_rate_delta),
        max_disagree_rate=float(settings.auto_promotion_max_disagree_rate),
        cooldown_hours=int(settings.auto_promotion_cooldown_hours),
        candidate_min_age_hours=int(settings.auto_promotion_candidate_min_age_hours),
        tenant_override=False,
    )


@router.post("/monitoring/challenger-evaluator/run", response_model=ChallengerEvaluatorRunOut)
async def run_challenger_evaluator_now(
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
):
    result = await run_tracked_job(
        job_name="challenger_evaluator_manual",
        trigger_source="api_manual",
        actor_id=admin_ctx.actor_id,
        runner=run_challenger_evaluator,
    )
    return ChallengerEvaluatorRunOut(
        triggered=True,
        enabled=bool(result.get("enabled", False)),
        scanned_tenants=int(result.get("scanned_tenants", 0)),
        promoted_count=int(result.get("promoted_count", 0)),
        window_hours=int(result.get("window_hours", 0)),
        min_compared=int(result.get("min_compared", 0)),
    )


@router.post("/monitoring/cutover-auto/run", response_model=CutoverAutoRunOut)
async def run_cutover_auto_now(
    force_execute: bool = Query(False),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
):
    result = await run_tracked_job(
        job_name="cutover_auto_manual",
        trigger_source="api_manual",
        actor_id=admin_ctx.actor_id,
        runner=lambda: run_model_cutover_executor(force_execute=bool(force_execute)),
    )
    return CutoverAutoRunOut(
        triggered=True,
        enabled=bool(result.get("enabled", False)),
        dry_run=bool(result.get("dry_run", True)),
        scanned=int(result.get("scanned", 0)),
        eligible=int(result.get("eligible", 0)),
        executed=int(result.get("executed", 0)),
        model_types=[str(x) for x in (result.get("model_types") or [])],
        require_no_prior_execution=bool(result.get("require_no_prior_execution", True)),
    )


@router.post("/monitoring/warehouse-isolation/verify", response_model=WarehouseIsolationVerifyOut)
async def run_warehouse_isolation_verify_now(
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
):
    result = await run_tracked_job(
        job_name="warehouse_isolation_verify_manual",
        trigger_source="api_manual",
        actor_id=admin_ctx.actor_id,
        runner=run_warehouse_isolation_verification,
    )
    return WarehouseIsolationVerifyOut(
        triggered=True,
        enabled=bool(result.get("enabled", False)),
        passed=bool(result.get("passed", True)),
        errors=[str(x) for x in (result.get("errors") or [])],
        checked_tables=[str(x) for x in (result.get("checked_tables") or [])],
    )


async def _retention_preview(db: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime) -> TenantRetentionPreviewOut:
    upload_ids = select(TrainingUpload.id).where(TrainingUpload.tenant_id == tenant_id, TrainingUpload.created_at < cutoff)
    inf = await db.scalar(
        select(func.count())
        .select_from(InferenceTrace)
        .where(InferenceTrace.tenant_id == tenant_id, InferenceTrace.created_at < cutoff)
    )
    up = await db.scalar(
        select(func.count())
        .select_from(TrainingUploadRow)
        .where(TrainingUploadRow.upload_id.in_(upload_ids), TrainingUploadRow.created_at < cutoff)
    )
    sc = await db.scalar(
        select(func.count()).select_from(FraudScore).where(FraudScore.tenant_id == tenant_id, FraudScore.created_at < cutoff)
    )
    al = await db.scalar(
        select(func.count()).select_from(FraudAlert).where(FraudAlert.tenant_id == tenant_id, FraudAlert.created_at < cutoff)
    )
    return TenantRetentionPreviewOut(
        tenant_id=str(tenant_id),
        retention_days=int(getattr(settings, "tenant_data_retention_days", 365) or 365),
        before=cutoff.isoformat(),
        inference_trace_rows=int(inf or 0),
        training_upload_rows=int(up or 0),
        fraud_score_rows=int(sc or 0),
        fraud_alert_rows=int(al or 0),
    )


@router.get("/compliance/tenant-retention/preview", response_model=TenantRetentionPreviewOut)
async def tenant_retention_preview(
    tenant_id: uuid.UUID = Query(...),
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    days = int(retention_days or getattr(settings, "tenant_data_retention_days", 365) or 365)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return await _retention_preview(db, tenant_id, cutoff)


@router.post("/compliance/tenant-retention/apply", response_model=TenantRetentionPreviewOut)
async def tenant_retention_apply(
    tenant_id: uuid.UUID = Query(...),
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    dry_run: bool = Query(default=True),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    days = int(retention_days or getattr(settings, "tenant_data_retention_days", 365) or 365)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    preview = await _retention_preview(db, tenant_id, cutoff)
    if dry_run:
        return preview
    await db.execute(delete(InferenceTrace).where(InferenceTrace.tenant_id == tenant_id, InferenceTrace.created_at < cutoff))
    upload_ids = select(TrainingUpload.id).where(TrainingUpload.tenant_id == tenant_id, TrainingUpload.created_at < cutoff)
    await db.execute(delete(TrainingUploadRow).where(TrainingUploadRow.upload_id.in_(upload_ids), TrainingUploadRow.created_at < cutoff))
    await db.execute(delete(TrainingUpload).where(TrainingUpload.tenant_id == tenant_id, TrainingUpload.created_at < cutoff))
    await db.execute(delete(FraudScore).where(FraudScore.tenant_id == tenant_id, FraudScore.created_at < cutoff))
    await db.execute(delete(FraudAlert).where(FraudAlert.tenant_id == tenant_id, FraudAlert.created_at < cutoff))
    await _audit_admin_change(
        db,
        "TENANT_RETENTION_APPLIED",
        {
            "tenant_id": str(tenant_id),
            "retention_days": days,
            "before": cutoff.isoformat(),
            "deleted": preview.model_dump(),
            "dry_run": False,
        },
        actor=admin_ctx.actor_id,
    )
    return preview


@router.post("/compliance/tenant-export", response_model=TenantExportOut)
async def tenant_export_snapshot(
    tenant_id: uuid.UUID = Query(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    out_dir = BACKEND_ROOT / "app" / "ml" / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    row = await _retention_preview(db, tenant_id, now + timedelta(days=36500))
    summary = row.model_dump()
    payload = {
        "tenant_id": str(tenant_id),
        "generated_at": now.isoformat(),
        "summary": summary,
    }
    artifact = out_dir / f"tenant_export_{tenant_id}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    artifact.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    await _audit_admin_change(
        db,
        "TENANT_EXPORT_GENERATED",
        {"tenant_id": str(tenant_id), "artifact_path": str(artifact), "summary": summary},
        actor=admin_ctx.actor_id,
    )
    return TenantExportOut(
        tenant_id=str(tenant_id),
        generated_at=now.isoformat(),
        artifact_path=str(artifact),
        summary=summary,
    )


@router.post("/compliance/tenant-export/jobs", response_model=TenantExportJobOut)
async def tenant_export_job_create(
    tenant_id: uuid.UUID = Query(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    job = ReportJob(
        tenant_id=tenant_id,
        requested_by=admin_ctx.actor_id,
        status="queued",
        filters={"kind": "tenant_export"},
    )
    db.add(job)
    await db.flush()
    await db.commit()
    await db.refresh(job)
    asyncio.create_task(run_tenant_export_job(job.id))
    return _serialize_export_job(job)


@router.get("/compliance/tenant-export/jobs/{job_id}", response_model=TenantExportJobOut)
async def tenant_export_job_get(
    job_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    await ensure_tenant_access(db, admin_ctx, job.tenant_id)
    if str((job.filters or {}).get("kind") or "") != "tenant_export":
        raise HTTPException(status_code=404, detail="Export job not found")
    return _serialize_export_job(job)


@router.post("/compliance/tenant-export/jobs/{job_id}/sign-download")
async def tenant_export_job_sign_download(
    job_id: uuid.UUID,
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    await ensure_tenant_access(db, admin_ctx, job.tenant_id)
    if str((job.filters or {}).get("kind") or "") != "tenant_export":
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Export job is not ready")
    exp = int(time.time()) + 600
    payload = f"tenant_export:{job_id}:{job.tenant_id}:{exp}"
    sig = _sign_payload(payload)
    return {
        "url": f"/api/v1/admin/compliance/tenant-export/download/{job_id}?exp={exp}&sig={sig}",
        "expires_at": exp,
    }


@router.get("/compliance/tenant-export/download/{job_id}")
async def tenant_export_job_download(
    job_id: uuid.UUID,
    exp: int,
    sig: str,
    db: AsyncSession = Depends(get_db),
):
    if int(time.time()) > int(exp):
        raise HTTPException(status_code=403, detail="Signed URL expired")
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    if str((job.filters or {}).get("kind") or "") != "tenant_export":
        raise HTTPException(status_code=404, detail="Export job not found")
    expected = _sign_payload(f"tenant_export:{job_id}:{job.tenant_id}:{exp}")
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")
    path = Path(job.artifact_pdf_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export artifact missing")
    return FileResponse(path=str(path), media_type="application/json", filename=f"tenant-export-{str(job.tenant_id)[:8]}.json")


@router.post("/compliance/tenant-anonymize", response_model=TenantAnonymizeOut)
async def tenant_anonymize(
    tenant_id: uuid.UUID = Query(...),
    dry_run: bool = Query(default=True),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    now = datetime.now(timezone.utc)
    customers_count = int(
        await db.scalar(select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id)) or 0
    )
    tx_count = int(await db.scalar(select(func.count()).select_from(Transaction).where(Transaction.tenant_id == tenant_id)) or 0)
    if not dry_run and bool(getattr(settings, "tenant_anonymization_enabled", False)):
        anon_external = f"anon-{now.strftime('%Y%m%d')}"
        await db.execute(
            update(Customer)
            .where(Customer.tenant_id == tenant_id)
            .values(name_encrypted=None, phone_hash=None, external_id=anon_external, updated_at=now)
        )
        await db.execute(
            update(Transaction)
            .where(Transaction.tenant_id == tenant_id)
            .values(external_tx_id=anon_external, device_id=None, ip_address_hash=None)
        )
    await _audit_admin_change(
        db,
        "TENANT_ANONYMIZATION",
        {
            "tenant_id": str(tenant_id),
            "dry_run": bool(dry_run),
            "enabled": bool(getattr(settings, "tenant_anonymization_enabled", False)),
            "customers_updated": customers_count,
            "transactions_updated": tx_count,
        },
        actor=admin_ctx.actor_id,
    )
    return TenantAnonymizeOut(
        tenant_id=str(tenant_id),
        anonymized_at=now.isoformat(),
        customers_updated=customers_count,
        transactions_updated=tx_count,
    )


@router.get("/monitoring/job-runs", response_model=list[JobRunOut])
async def list_job_runs(
    job_name: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(started|success|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_read_db),
):
    stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    if job_name:
        stmt = stmt.where(JobRun.job_name == job_name)
    if status:
        stmt = stmt.where(JobRun.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        JobRunOut(
            id=str(r.id),
            job_name=r.job_name,
            trigger_source=r.trigger_source,
            actor_id=r.actor_id,
            request_id=r.request_id,
            status=r.status,
            started_at=r.started_at.isoformat() if r.started_at else "",
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
            duration_ms=r.duration_ms,
            error_summary=r.error_summary,
            result_json=(dict(r.result_json) if isinstance(r.result_json, dict) else None),
        )
        for r in rows
    ]


@router.get("/monitoring/champion-challenger", response_model=ChampionChallengerKpiOut)
async def champion_challenger_kpis(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    window_hours: int = Query(24, ge=1, le=168),
    limit: int = Query(2000, ge=100, le=10000),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_read_db),
    write_db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(write_db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(write_db, tenant_id=tenant_id, model_type=model_type)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = (
        await db.execute(
            select(InferenceTrace)
            .where(
                InferenceTrace.tenant_id == tenant_id,
                InferenceTrace.model_type == model_type,
                InferenceTrace.created_at >= cutoff,
            )
            .order_by(InferenceTrace.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    total = len(rows)
    if total == 0:
        return ChampionChallengerKpiOut(
            tenant_id=str(tenant_id),
            model_type=model_type,
            window_hours=window_hours,
            total_traces=0,
            compared_traces=0,
            champion_block_rate=0.0,
            champion_otp_rate=0.0,
            champion_approve_rate=0.0,
        )

    champ_decisions: list[str] = []
    challenger_decisions: list[str] = []
    champion_model_version = None
    challenger_model_version = None
    for r in rows:
        cdec = str(r.decision or "").upper()
        if cdec:
            champ_decisions.append(cdec)
        tv = r.trace_json if isinstance(r.trace_json, dict) else {}
        mv = tv.get("mapper_validation") if isinstance(tv.get("mapper_validation"), dict) else {}
        shadow = mv.get("shadow") if isinstance(mv.get("shadow"), dict) else {}
        sdec = str(shadow.get("candidate_decision") or "").upper()
        if sdec:
            challenger_decisions.append(sdec)
            if challenger_model_version is None:
                challenger_model_version = shadow.get("candidate_model_version")
        if champion_model_version is None:
            champion_model_version = r.model_version

    comp_n = min(len(champ_decisions), len(challenger_decisions))
    if comp_n == 0:
        return ChampionChallengerKpiOut(
            tenant_id=str(tenant_id),
            model_type=model_type,
            window_hours=window_hours,
            total_traces=total,
            compared_traces=0,
            champion_block_rate=round(sum(1 for d in champ_decisions if d == "BLOCK") / max(1, len(champ_decisions)), 6),
            champion_otp_rate=round(sum(1 for d in champ_decisions if d == "REQUEST_OTP") / max(1, len(champ_decisions)), 6),
            champion_approve_rate=round(sum(1 for d in champ_decisions if d == "APPROVE") / max(1, len(champ_decisions)), 6),
            champion_model_version=str(champion_model_version) if champion_model_version else None,
        )

    disagreements = 0
    for i in range(comp_n):
        if champ_decisions[i] != challenger_decisions[i]:
            disagreements += 1
    return ChampionChallengerKpiOut(
        tenant_id=str(tenant_id),
        model_type=model_type,
        window_hours=window_hours,
        total_traces=total,
        compared_traces=comp_n,
        champion_block_rate=round(sum(1 for d in champ_decisions if d == "BLOCK") / max(1, len(champ_decisions)), 6),
        challenger_block_rate=round(sum(1 for d in challenger_decisions if d == "BLOCK") / max(1, len(challenger_decisions)), 6),
        champion_otp_rate=round(sum(1 for d in champ_decisions if d == "REQUEST_OTP") / max(1, len(champ_decisions)), 6),
        challenger_otp_rate=round(sum(1 for d in challenger_decisions if d == "REQUEST_OTP") / max(1, len(challenger_decisions)), 6),
        champion_approve_rate=round(sum(1 for d in champ_decisions if d == "APPROVE") / max(1, len(champ_decisions)), 6),
        challenger_approve_rate=round(sum(1 for d in challenger_decisions if d == "APPROVE") / max(1, len(challenger_decisions)), 6),
        disagree_rate=round(disagreements / float(comp_n), 6),
        champion_model_version=str(champion_model_version) if champion_model_version else None,
        challenger_model_version=str(challenger_model_version) if challenger_model_version else None,
    )


@router.get("/monitoring/isolation-readiness", response_model=IsolationReadinessOut)
async def isolation_readiness(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type=model_type)
    mapper = (
        await db.execute(
            select(TenantMapper).where(
                TenantMapper.tenant_id == tenant_id,
                TenantMapper.model_type == model_type,
                TenantMapper.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    model = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == model_type,
                ModelRegistry.tenant_id == tenant_id,
                ModelRegistry.status == "active",
            )
        )
    ).scalar_one_or_none()
    artifact_exists: bool | None = None
    artifact_check = "unknown"
    artifact_uri = (model.artifact_uri if model else None)
    if artifact_uri:
        uri = str(artifact_uri).strip()
        if uri.startswith("s3://") or uri.startswith("gs://") or uri.startswith("http://") or uri.startswith("https://"):
            artifact_check = "remote_uri_not_checked"
        else:
            p_raw = uri[7:] if uri.startswith("file://") else uri
            p = Path(p_raw)
            if not p.is_absolute():
                p = (BACKEND_ROOT / p).resolve()
            artifact_exists = p.exists()
            artifact_check = "local_path_checked"
    ready = bool(model and mapper and (artifact_exists is not False) and settings.strict_mapper_enforcement and (not settings.allow_model_fallback))
    return IsolationReadinessOut(
        tenant_id=str(tenant_id),
        model_type=model_type,
        strict_mapper_enforcement=bool(settings.strict_mapper_enforcement),
        allow_model_fallback=bool(settings.allow_model_fallback),
        has_active_model=bool(model),
        has_active_mapper=bool(mapper),
        active_model_version=(str(model.version) if model else None),
        active_mapper_version=(str(mapper.mapper_version) if mapper else None),
        active_artifact_uri=(str(artifact_uri) if artifact_uri else None),
        artifact_exists=artifact_exists,
        artifact_check=artifact_check,
        ready_for_strict_cutover=ready,
    )


@router.get("/monitoring/policy-profile", response_model=PolicyProfileOut)
async def monitoring_policy_profile(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    violations = collect_production_violations(settings)
    return PolicyProfileOut(
        profile=(settings.production_policy_profile or "baseline"),
        environment=(settings.environment or "development"),
        enforce_production_hardening=bool(settings.enforce_production_hardening),
        violations=violations,
        ok=(len(violations) == 0),
    )


@router.get("/monitoring/cutover-gate", response_model=CutoverGateOut)
async def cutover_gate(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, _admin, tenant_id)
    await _ensure_tenant_model_registered_or_403(db, tenant_id=tenant_id, model_type=model_type)
    blockers: list[str] = []
    warnings: list[str] = []

    mapper = (
        await db.execute(
            select(TenantMapper).where(
                TenantMapper.tenant_id == tenant_id,
                TenantMapper.model_type == model_type,
                TenantMapper.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    model = (
        await db.execute(
            select(ModelRegistry).where(
                ModelRegistry.model_type == model_type,
                ModelRegistry.tenant_id == tenant_id,
                ModelRegistry.status == "active",
            )
        )
    ).scalar_one_or_none()
    if not settings.strict_mapper_enforcement:
        blockers.append("STRICT_MAPPER_ENFORCEMENT is disabled.")
    if settings.allow_model_fallback:
        blockers.append("ALLOW_MODEL_FALLBACK must be false for strict cutover.")
    if not model:
        blockers.append("No active tenant model in registry.")
    if not mapper:
        blockers.append("No active tenant mapper.")

    if model:
        lineage = {}
        if isinstance(model.metadata_json, dict):
            raw = model.metadata_json.get("lineage")
            if isinstance(raw, dict):
                lineage = raw
        required = ("dataset_version", "contract_version", "mapper_version", "artifact_uri")
        missing = [k for k in required if not lineage.get(k)]
        if missing:
            blockers.append(f"Model lineage missing required fields: {', '.join(missing)}")
        if not lineage.get("artifact_sha256"):
            warnings.append("artifact_sha256 missing (remote artifact or unstamped local artifact).")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    trace_rows = (
        await db.execute(
            select(InferenceTrace.trace_json).where(
                InferenceTrace.tenant_id == tenant_id,
                InferenceTrace.model_type == model_type,
                InferenceTrace.created_at >= cutoff,
            )
        )
    ).all()
    fallback_24h = 0
    for (tjson,) in trace_rows:
        src = ""
        if isinstance(tjson, dict):
            src = str(tjson.get("route_source") or "").lower()
        if src == "fallback":
            fallback_24h += 1
    if fallback_24h > 0:
        blockers.append(f"{fallback_24h} fallback-routed traces in last 24h.")

    latest_snapshot = (
        await db.execute(
            select(ModelKpiSnapshot)
            .where(
                ModelKpiSnapshot.tenant_id == tenant_id,
                ModelKpiSnapshot.model_type == model_type,
                ModelKpiSnapshot.window_days == 30,
            )
            .order_by(ModelKpiSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    labeled_count = int(latest_snapshot.labeled_count) if latest_snapshot else 0
    latest_precision = (float(latest_snapshot.precision) if (latest_snapshot and latest_snapshot.precision is not None) else None)
    latest_snapshot_at = latest_snapshot.created_at.isoformat() if (latest_snapshot and latest_snapshot.created_at) else None
    if latest_snapshot is None:
        blockers.append("No KPI snapshot found (run model KPI snapshot job).")
    if labeled_count < int(settings.auto_promotion_min_labeled):
        warnings.append(
            f"Labeled sample count below recommended minimum ({labeled_count}/{int(settings.auto_promotion_min_labeled)})."
        )

    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    cutover_status = {}
    if bank and isinstance(bank.tone_config, dict):
        raw_status = bank.tone_config.get("cutover_status")
        if isinstance(raw_status, dict):
            cutover_status = raw_status
    this_model_status = cutover_status.get(model_type) if isinstance(cutover_status.get(model_type), dict) else {}
    last_executed_at = this_model_status.get("executed_at")
    last_executed_by = this_model_status.get("executed_by")

    return CutoverGateOut(
        tenant_id=str(tenant_id),
        model_type=model_type,
        pass_gate=(len(blockers) == 0),
        checked_at=datetime.now(timezone.utc).isoformat(),
        blockers=blockers,
        warnings=warnings,
        fallback_trace_count_24h=fallback_24h,
        latest_labeled_count_30d=labeled_count,
        latest_precision_30d=latest_precision,
        latest_snapshot_at=latest_snapshot_at,
        last_executed_at=(str(last_executed_at) if last_executed_at else None),
        last_executed_by=(str(last_executed_by) if last_executed_by else None),
    )


@router.get("/monitoring/cutover-gate/batch", response_model=BatchCutoverGateOut)
async def cutover_gate_batch(
    model_types: str = Query("fraud,care"),
    include_passed: bool = Query(True),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    mt = [m.strip().lower() for m in str(model_types or "").split(",") if m.strip()]
    mt = [m for m in mt if m in {"fraud", "care"}] or ["fraud", "care"]
    visible = await visible_tenant_ids_for_list(db, _admin)
    _tenant_stmt = select(TenantBank).where(TenantBank.is_active.is_(True))
    if visible is not None:
        if not visible:
            return []
        _tenant_stmt = _tenant_stmt.where(TenantBank.id.in_(visible))
    tenants = (await db.execute(_tenant_stmt)).scalars().all()
    items: list[BatchCutoverGateItemOut] = []
    pass_count = 0
    fail_count = 0
    for t in tenants:
        for m in mt:
            g = await cutover_gate(tenant_id=t.id, model_type=m, _admin=_admin, db=db)
            if g.pass_gate:
                pass_count += 1
                if not include_passed:
                    continue
            else:
                fail_count += 1
            items.append(
                BatchCutoverGateItemOut(
                    tenant_id=str(t.id),
                    tenant_name=str(t.name or ""),
                    model_type=m,
                    pass_gate=bool(g.pass_gate),
                    blockers=list(g.blockers or []),
                    warnings=list(g.warnings or []),
                    fallback_trace_count_24h=int(g.fallback_trace_count_24h or 0),
                    latest_labeled_count_30d=int(g.latest_labeled_count_30d or 0),
                    latest_precision_30d=(float(g.latest_precision_30d) if g.latest_precision_30d is not None else None),
                    checked_at=str(g.checked_at),
                )
            )
    return BatchCutoverGateOut(
        checked_at=datetime.now(timezone.utc).isoformat(),
        scanned=len(tenants) * len(mt),
        pass_count=pass_count,
        fail_count=fail_count,
        items=items,
    )


@router.post("/monitoring/cutover-execute", response_model=CutoverExecuteOut)
async def cutover_execute(
    tenant_id: uuid.UUID = Query(...),
    model_type: str = Query("fraud", pattern="^(fraud|care)$"),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    gate = await cutover_gate(tenant_id=tenant_id, model_type=model_type, _admin=admin_ctx, db=db)
    if not gate.pass_gate:
        return CutoverExecuteOut(
            executed=False,
            tenant_id=str(tenant_id),
            model_type=model_type,
            checked_at=datetime.now(timezone.utc).isoformat(),
            message="Cutover blocked by gate.",
            blockers=list(gate.blockers or []),
        )
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    cfg = dict(bank.tone_config or {})
    cut = dict(cfg.get("cutover_status") or {})
    cut[model_type] = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "executed_by": admin_ctx.actor_id,
        "strict_mapper_enforcement": bool(settings.strict_mapper_enforcement),
        "allow_model_fallback": bool(settings.allow_model_fallback),
    }
    cfg["cutover_status"] = cut
    bank.tone_config = cfg
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_CUTOVER_EXECUTED",
        {
            "tenant_id": str(tenant_id),
            "model_type": model_type,
            "executed_by": admin_ctx.actor_id,
            "strict_mapper_enforcement": bool(settings.strict_mapper_enforcement),
            "allow_model_fallback": bool(settings.allow_model_fallback),
        },
        actor=admin_ctx.actor_id,
    )
    return CutoverExecuteOut(
        executed=True,
        tenant_id=str(tenant_id),
        model_type=model_type,
        checked_at=datetime.now(timezone.utc).isoformat(),
        message="Cutover executed and recorded.",
        blockers=[],
    )


@router.get("/audit/events", response_model=List[AdminAuditOut])
async def list_admin_audit_events(
    event_type: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    limit: int = Query(80, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit * 8)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    rows = (await db.execute(stmt)).scalars().all()
    out: list[AdminAuditOut] = []
    for r in rows:
        data = dict(r.event_data or {})
        if tenant_id:
            ev_tid = data.get("tenant_id")
            if str(ev_tid) != str(tenant_id):
                continue
        out.append(
            AdminAuditOut(
                event_type=r.event_type,
                actor_id=r.actor_id,
                created_at=r.created_at.isoformat() if r.created_at else "",
                event_data=data,
            )
        )
        if len(out) >= limit:
            break
    return out


@router.get("/training/{model_type}/tenant-eligibility", response_model=FineTuneEligibilityOut)
async def tenant_finetune_eligibility(
    model_type: str,
    tenant_id: uuid.UUID = Query(...),
    min_rows_required: int = Query(500, ge=100, le=100000),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if model_type not in {"fraud", "care"}:
        raise HTTPException(status_code=400, detail="Invalid model_type.")
    await ensure_tenant_access(db, _admin, tenant_id)

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
                except Exception:
                    quality_score = None

    reasons: list[str] = []
    if rows_available < min_rows_required:
        reasons.append("insufficient_labeled_volume")
    if quality_score is not None and quality_score < 0.65:
        reasons.append("quality_below_threshold")
    eligible = len(reasons) == 0
    return FineTuneEligibilityOut(
        tenant_id=str(tenant_id),
        model_type=model_type,
        min_rows_required=min_rows_required,
        rows_available=rows_available,
        quality_score=quality_score,
        eligible=eligible,
        reasons=reasons,
    )


@router.post("/training/{model_type}/tenant-finetune/start", response_model=FineTuneStartOut)
async def start_tenant_finetune(
    model_type: str,
    tenant_id: uuid.UUID = Form(...),
    upload_id: str = Form(...),
    candidate_version: str = Form(...),
    artifact_uri: str = Form(...),
    auto_activate: bool = Form(False),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if model_type not in {"fraud", "care"}:
        raise HTTPException(status_code=400, detail="Invalid model_type.")
    await ensure_tenant_access(db, admin_ctx, tenant_id)
    if not await tenant_has_registered_model(db, tenant_id=tenant_id, model_type=model_type):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Register a {model_type} model for this tenant in Model registry "
                "before starting tenant fine-tune."
            ),
        )
    uid = uuid.UUID(upload_id)
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == uid))).scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if upload.model_type != model_type:
        raise HTTPException(status_code=400, detail="Upload model_type mismatch.")
    meta = upload.meta if isinstance(upload.meta, dict) else {}
    if str(meta.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=400, detail="Upload tenant mismatch.")
    dataset_version = meta.get("dataset_version")
    contract_version = meta.get("contract_version")
    if not dataset_version or not contract_version:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "lineage_missing",
                "errors": ["Upload meta must include dataset_version and contract_version before model publish."],
            },
        )

    elig = await tenant_finetune_eligibility(
        model_type=model_type,
        tenant_id=tenant_id,
        min_rows_required=500,
        _admin=admin_ctx,
        db=db,
    )
    if not elig.eligible:
        raise HTTPException(status_code=400, detail={"code": "tenant_not_eligible", "reasons": elig.reasons})

    await assert_training_upload_allowed(db, upload=upload, model_type=model_type)

    if upload.status == "TRAINING":
        raise HTTPException(status_code=400, detail="Training already in progress for this upload.")
    upload.status = "TRAINING"
    await db.flush()

    env = os.environ.copy()
    subprocess.Popen(
        [
            sys.executable,
            "scripts/train_from_uploaded_data.py",
            "--model",
            model_type,
            "--upload-id",
            str(uid),
        ],
        env=env,
        cwd=str(BACKEND_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if auto_activate:
        prior = (
            await db.execute(
                select(ModelRegistry).where(
                    ModelRegistry.model_type == model_type,
                    ModelRegistry.tenant_id == tenant_id,
                    ModelRegistry.status == "active",
                )
            )
        ).scalars().all()
        for p in prior:
            p.status = "shadow"

    artifact_uri_clean = _validate_artifact_uri_or_raise(artifact_uri)
    artifact_sha = _artifact_sha256(artifact_uri_clean)
    row = ModelRegistry(
        model_type=model_type,
        tenant_id=tenant_id,
        version=candidate_version.strip(),
        artifact_uri=artifact_uri_clean,
        feature_contract_version=str(contract_version or "v1"),
        mapper_version="mapper-v0",
        status="active" if auto_activate else "shadow",
        metadata_json={
            "source": "tenant_finetune",
            "upload_id": str(uid),
            "dataset_version": dataset_version,
            "tenant_id": str(tenant_id),
            "eligibility": elig.model_dump(),
            "lineage": {
                "upload_id": str(uid),
                "dataset_version": dataset_version,
                "contract_version": str(contract_version),
                "mapper_version": "mapper-v0",
                "artifact_sha256": artifact_sha,
                "artifact_uri": artifact_uri_clean,
                "training_storage_path": meta.get("storage_path"),
                "training_data_sha256": meta.get("content_sha256"),
            },
        },
        activated_at=(datetime.now(timezone.utc) if auto_activate else None),
    )
    db.add(row)
    await db.flush()
    await _audit_admin_change(
        db,
        "TENANT_FINETUNE_STARTED",
        {
            "tenant_id": str(tenant_id),
            "model_type": model_type,
            "upload_id": str(uid),
            "candidate_version": candidate_version.strip(),
            "artifact_uri": artifact_uri.strip(),
            "auto_activate": bool(auto_activate),
            "model_registry_id": str(row.id),
        },
        actor=admin_ctx.actor_id,
    )
    return FineTuneStartOut(
        status="started",
        message=f"Tenant {model_type} fine-tune started from uploaded dataset.",
        upload_id=str(uid),
        tenant_id=str(tenant_id),
        model_type=model_type,
        model_registry_id=str(row.id),
    )


@router.get("/training/fraud/model-lifecycle", response_model=FraudModelLifecycleOut)
async def get_fraud_model_lifecycle(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    reg = _load_fraud_model_registry()
    return FraudModelLifecycleOut(**reg)


@router.post("/training/fraud/model-lifecycle/register-challenger", response_model=FraudModelLifecycleOut)
async def register_fraud_challenger(
    lgb_path: str | None = Form(None),
    sklearn_path: str | None = Form(None),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    reg = _load_fraud_model_registry()
    if not lgb_path and not sklearn_path:
        raise HTTPException(status_code=400, detail="Provide lgb_path or sklearn_path.")
    model_dir = BACKEND_ROOT / "models" / "fraud"
    chal_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    chal_dir = model_dir / "challengers" / chal_id
    chal_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    staged: dict[str, str] = {}
    if lgb_path:
        src = Path(str(lgb_path))
        if not src.exists():
            raise HTTPException(status_code=404, detail=f"lgb_path not found: {src}")
        dst = chal_dir / "lgb_fraud.txt"
        shutil.copy2(src, dst)
        hashes["lgb_fraud.txt"] = hashlib.sha256(dst.read_bytes()).hexdigest()
        staged["lgb_path"] = str(dst)
    if sklearn_path:
        src = Path(str(sklearn_path))
        if not src.exists():
            raise HTTPException(status_code=404, detail=f"sklearn_path not found: {src}")
        dst = chal_dir / "sklearn_fraud.joblib"
        shutil.copy2(src, dst)
        hashes["sklearn_fraud.joblib"] = hashlib.sha256(dst.read_bytes()).hexdigest()
        staged["sklearn_path"] = str(dst)
    payload = json.dumps({"challenger_id": chal_id, "hashes": hashes}, sort_keys=True)
    signature = _sign_payload(payload)
    reg["challenger"] = {
        **staged,
        "challenger_id": chal_id,
        "hashes": hashes,
        "signature": signature,
        "signed_payload": payload,
    }
    _save_fraud_model_registry(reg)
    await _audit_admin_change(
        db,
        "FRAUD_MODEL_REGISTER_CHALLENGER",
        {"challenger": reg["challenger"]},
        actor=admin_ctx.actor_id,
    )
    return FraudModelLifecycleOut(**reg)


@router.post("/training/fraud/model-lifecycle/promote-challenger", response_model=FraudModelLifecycleOut)
async def promote_fraud_challenger(
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    reg = _load_fraud_model_registry()
    challenger = reg.get("challenger")
    if not isinstance(challenger, dict):
        raise HTTPException(status_code=400, detail="No challenger registered.")
    try:
        payload = str(challenger.get("signed_payload") or "")
        sig = str(challenger.get("signature") or "")
        if not payload or not sig or _sign_payload(payload) != sig:
            raise HTTPException(status_code=400, detail="Challenger signature verification failed.")
        hashes = dict(challenger.get("hashes") or {})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid challenger manifest.") from exc
    model_dir = BACKEND_ROOT / "models" / "fraud"
    backup_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_dir = model_dir / "backups" / backup_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("lgb_fraud.txt", "sklearn_fraud.joblib", "isolation_forest.joblib", "isotonic_calibrator.joblib", "platt_calibrator.joblib"):
        src = model_dir / fname
        if src.exists():
            shutil.copy2(src, backup_dir / fname)
    if challenger.get("lgb_path"):
        src = Path(str(challenger["lgb_path"]))
        if not src.exists():
            raise HTTPException(status_code=404, detail="Challenger lgb artifact missing.")
        got = hashlib.sha256(src.read_bytes()).hexdigest()
        if hashes.get("lgb_fraud.txt") and got != hashes.get("lgb_fraud.txt"):
            raise HTTPException(status_code=400, detail="Challenger lgb artifact hash mismatch.")
        shutil.copy2(src, model_dir / "lgb_fraud.txt")
    if challenger.get("sklearn_path"):
        src = Path(str(challenger["sklearn_path"]))
        if not src.exists():
            raise HTTPException(status_code=404, detail="Challenger sklearn artifact missing.")
        got = hashlib.sha256(src.read_bytes()).hexdigest()
        if hashes.get("sklearn_fraud.joblib") and got != hashes.get("sklearn_fraud.joblib"):
            raise HTTPException(status_code=400, detail="Challenger sklearn artifact hash mismatch.")
        shutil.copy2(src, model_dir / "sklearn_fraud.joblib")
    reg["active"] = "champion"
    reg["champion"] = {"lgb_path": "lgb_fraud.txt", "sklearn_path": "sklearn_fraud.joblib"}
    reg["last_backup"] = backup_id
    reg["challenger"] = None
    _save_fraud_model_registry(reg)
    await _audit_admin_change(
        db,
        "FRAUD_MODEL_PROMOTE_CHALLENGER",
        {"backup_id": backup_id},
        actor=admin_ctx.actor_id,
    )
    return FraudModelLifecycleOut(**reg)


@router.post("/training/fraud/model-lifecycle/rollback", response_model=FraudModelLifecycleOut)
async def rollback_fraud_model(
    backup_id: str | None = Form(None),
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    reg = _load_fraud_model_registry()
    model_dir = BACKEND_ROOT / "models" / "fraud"
    bid = backup_id or reg.get("last_backup")
    if not bid:
        raise HTTPException(status_code=400, detail="No backup id provided and no last_backup in registry.")
    backup_dir = model_dir / "backups" / str(bid)
    if not backup_dir.exists():
        raise HTTPException(status_code=404, detail="Backup not found.")
    for fname in ("lgb_fraud.txt", "sklearn_fraud.joblib", "isolation_forest.joblib", "isotonic_calibrator.joblib", "platt_calibrator.joblib"):
        src = backup_dir / fname
        if src.exists():
            shutil.copy2(src, model_dir / fname)
    reg["active"] = "champion"
    reg["champion"] = {"lgb_path": "lgb_fraud.txt", "sklearn_path": "sklearn_fraud.joblib"}
    reg["last_backup"] = str(bid)
    _save_fraud_model_registry(reg)
    await _audit_admin_change(
        db,
        "FRAUD_MODEL_ROLLBACK",
        {"backup_id": str(bid)},
        actor=admin_ctx.actor_id,
    )
    return FraudModelLifecycleOut(**reg)


@router.get("/audit/config-changes", response_model=List[AdminAuditOut])
async def list_admin_config_audit(
    limit: int = Query(50, ge=1, le=300),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "admin_config")
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        AdminAuditOut(
            event_type=r.event_type,
            actor_id=r.actor_id,
            created_at=r.created_at.isoformat() if r.created_at else "",
            event_data=dict(r.event_data or {}),
        )
        for r in rows
    ]


@router.get("/monitoring/fraud-drift-status")
async def fraud_drift_status(
    tenant_id: str | None = Query(None),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if tenant_id:
        try:
            tid = uuid.UUID(str(tenant_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid tenant_id.") from exc
        await ensure_tenant_access(db, _admin, tid)
        await _ensure_tenant_model_registered_or_403(db, tenant_id=tid, model_type="fraud")
    stmt = (
        select(AuditLog)
        .where(AuditLog.event_type == "FRAUD_DRIFT_STATUS", AuditLog.entity_type == "monitoring")
        .order_by(AuditLog.created_at.desc())
    )
    if tenant_id:
        stmt = stmt.limit(200)
        rows = (await db.execute(stmt)).scalars().all()
        row = next((r for r in rows if str((r.event_data or {}).get("tenant_id")) == str(tenant_id)), None)
        if not row:
            return {"status": "unknown", "checked_at": None, "tenant_id": tenant_id}
    else:
        row = (await db.execute(stmt.limit(1))).scalars().first()
        if not row:
            return {"status": "unknown", "checked_at": None}
    data = dict(row.event_data or {})
    return {
        "status": data.get("status") or "unknown",
        "checked_at": data.get("checked_at"),
        "tenant_id": data.get("tenant_id"),
        "alerts_count": len(data.get("alerts") or []),
    }


@router.get("/monitoring/fraud-drift-alerts")
async def fraud_drift_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    tenant_id: str | None = Query(None),
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    if tenant_id:
        try:
            tid = uuid.UUID(str(tenant_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid tenant_id.") from exc
        await ensure_tenant_access(db, _admin, tid)
        await _ensure_tenant_model_registered_or_403(db, tenant_id=tid, model_type="fraud")
    stmt = (
        select(AuditLog)
        .where(AuditLog.event_type == "FRAUD_DRIFT_STATUS", AuditLog.entity_type == "monitoring")
        .order_by(AuditLog.created_at.desc())
    )
    rows = (await db.execute(stmt.limit(5000))).scalars().all()
    if tenant_id:
        rows = [r for r in rows if str((r.event_data or {}).get("tenant_id")) == str(tenant_id)]
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [
            {
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "status": (r.event_data or {}).get("status"),
                "tenant_id": (r.event_data or {}).get("tenant_id"),
                "alerts": (r.event_data or {}).get("alerts", []),
                "features": (r.event_data or {}).get("features", []),
            }
            for r in page_rows
        ],
    }


@router.get("/rbac/tokens", response_model=List[AdminTokenMetaOut])
async def list_admin_tokens(
    _admin: AdminContext = Depends(require_platform_roles({"owner"})),
):
    data = load_admin_rbac()
    out = []
    for t in data.get("tokens", []):
        out.append(
            AdminTokenMetaOut(
                token_id=str(t.get("token_id")),
                name=str(t.get("name") or ""),
                role=str(t.get("role") or "viewer"),
                active=bool(t.get("active")),
                created_at=str(t.get("created_at") or ""),
                rotated_at=t.get("rotated_at"),
            )
        )
    return out


@router.post("/rbac/tokens/create", response_model=AdminTokenCreateOut)
async def create_admin_token(
    name: str = Form(...),
    role: str = Form(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    role = role.strip().lower()
    if role not in {"viewer", "editor", "owner"}:
        raise HTTPException(status_code=400, detail="role must be viewer|editor|owner")
    token_id = secrets.token_hex(8)
    raw_token = f"adm_{token_id}_{secrets.token_urlsafe(24)}"
    rec = {
        "token_id": token_id,
        "name": name.strip()[:80],
        "role": role,
        "active": True,
        "token_hash": admin_token_hash(raw_token),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rotated_at": None,
    }
    data = load_admin_rbac()
    data.setdefault("tokens", []).append(rec)
    save_admin_rbac(data)
    await _audit_admin_change(
        db,
        "ADMIN_RBAC_TOKEN_CREATE",
        {"token_id": token_id, "name": rec["name"], "role": role},
        actor=admin_ctx.actor_id,
    )
    return AdminTokenCreateOut(
        token=raw_token,
        meta=AdminTokenMetaOut(
            token_id=token_id,
            name=rec["name"],
            role=role,
            active=True,
            created_at=rec["created_at"],
            rotated_at=None,
        ),
    )


@router.post("/rbac/tokens/rotate", response_model=AdminTokenCreateOut)
async def rotate_admin_token(
    token_id: str = Form(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    data = load_admin_rbac()
    rec = next((t for t in data.get("tokens", []) if str(t.get("token_id")) == str(token_id)), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Token not found")
    raw_token = f"adm_{token_id}_{secrets.token_urlsafe(24)}"
    rec["token_hash"] = admin_token_hash(raw_token)
    rec["active"] = True
    rec["rotated_at"] = datetime.now(timezone.utc).isoformat()
    save_admin_rbac(data)
    await _audit_admin_change(
        db,
        "ADMIN_RBAC_TOKEN_ROTATE",
        {"token_id": token_id},
        actor=admin_ctx.actor_id,
    )
    return AdminTokenCreateOut(
        token=raw_token,
        meta=AdminTokenMetaOut(
            token_id=str(rec.get("token_id")),
            name=str(rec.get("name") or ""),
            role=str(rec.get("role") or "viewer"),
            active=bool(rec.get("active")),
            created_at=str(rec.get("created_at") or ""),
            rotated_at=rec.get("rotated_at"),
        ),
    )


@router.post("/rbac/tokens/revoke")
async def revoke_admin_token(
    token_id: str = Form(...),
    admin_ctx: AdminContext = Depends(require_platform_roles({"owner"})),
    db: AsyncSession = Depends(get_db),
):
    data = load_admin_rbac()
    rec = next((t for t in data.get("tokens", []) if str(t.get("token_id")) == str(token_id)), None)
    if not rec:
        raise HTTPException(status_code=404, detail="Token not found")
    rec["active"] = False
    save_admin_rbac(data)
    await _audit_admin_change(
        db,
        "ADMIN_RBAC_TOKEN_REVOKE",
        {"token_id": token_id},
        actor=admin_ctx.actor_id,
    )
    return {"status": "ok", "token_id": token_id}


@router.post("/trigger-fraud-train")
async def trigger_fraud_train(
    admin_ctx: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    """
    Start fraud model retrain in the background (from labelled data).

    Implementation detail:
      - Spawns a separate Python process running `python -m app.ml.train`
      - Uses FRAUD_TRAIN_MODE=real so it trains from historical data + labels
      - This avoids mixing FastAPI's event loop with the async training loop.
    """
    if settings.strict_training_governance or settings.strict_mapper_enforcement:
        raise HTTPException(
            status_code=403,
            detail="Legacy path disabled when STRICT_TRAINING_GOVERNANCE or STRICT_MAPPER_ENFORCEMENT is on. "
            "Use POST /api/v1/admin/training/fraud/trigger with a governed upload_id.",
        )
    await _audit_admin_change(
        db,
        "LEGACY_FRAUD_TRAIN_TRIGGERED",
        {"path": "app.ml.train"},
        actor=admin_ctx.actor_id,
    )
    env = os.environ.copy()
    env.setdefault("FRAUD_TRAIN_MODE", "real")
    env.setdefault("FRAUD_TRAIN_LIMIT", "5000")
    # Fire-and-forget subprocess; errors are logged to its own stderr.
    subprocess.Popen(
        [sys.executable, "-m", "app.ml.train"],
        env=env,
        cwd=str(BACKEND_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "started", "message": "Fraud training job started in background process."}


@router.get("/fraud-train-status", response_model=FraudTrainStatusOut)
async def fraud_train_status(
    _admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
) -> FraudTrainStatusOut:
    """
    Lightweight status endpoint for fraud model training.

    Reads models/fraud/train_status.json if present; otherwise reports idle.
    """
    model_path_env = os.getenv("MODEL_PATH", "")
    if model_path_env and model_path_env != "/models":
        out_dir = Path(model_path_env).parent / "fraud"
    else:
        out_dir = Path(__file__).resolve().parents[3] / "models" / "fraud"
    status_path = out_dir / "train_status.json"
    if not status_path.exists():
        return FraudTrainStatusOut(state="idle")
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return FraudTrainStatusOut(
            state=str(data.get("state") or "unknown"),
            mode=data.get("mode"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )
    except (ValueError, OSError):
        return FraudTrainStatusOut(state="unknown")
