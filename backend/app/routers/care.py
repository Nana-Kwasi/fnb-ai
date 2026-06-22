from datetime import datetime, timezone

import hashlib
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from jose import jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantBank
from app.models.calibration import CalibrationArtifact
from app.models.model_registry import InferenceTrace, TenantMapper
from app.database import get_db
from app.middleware.auth import resolve_tenant
from app.middleware.end_user_auth import resolve_end_user
from app.config import settings
from app.services import handle_chat
from app.services.care_engine import predict_intent_shadow
from app.observability import record_care_request, get_logger as _obs_logger

_logger = _obs_logger(__name__)
from app.services.calibration import apply_calibration
from app.services.mapper_validation import validate_and_dry_run
from app.services.model_routing import resolve_model_route, resolve_shadow_candidate
from app.services.care_transactions import (
    customer_transaction_stats,
    list_customer_transactions,
    parse_time_range,
    resolve_customer_or_404,
)
from app.services.care_pdf import StatementRow, render_statement_pdf
from app.services.cloudinary_store import upload_bytes, signed_download_url

router = APIRouter()


def _care_trace_payload(route, mapper_validation: dict) -> dict:
    return {
        "route_source": route.source,
        "model_registry_id": route.model_registry_id,
        "mapper_id": route.mapper_id,
        "mapper_validation": mapper_validation,
    }


async def _validate_care_mapper_contract(
    db: AsyncSession,
    *,
    route,
    raw_payload: dict,
) -> tuple[dict | None, dict]:
    if not route.mapper_id:
        return None, {"validated": False, "reason": "no_active_mapper"}
    mapper = await db.get(TenantMapper, route.mapper_id)
    if not mapper:
        raise HTTPException(status_code=422, detail={"code": "mapper_not_configured", "errors": ["Active mapper not found."]})
    canonical, errors = validate_and_dry_run(
        model_type="care",
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


async def _resolve_active_care_calibration(
    db: AsyncSession,
    *,
    tenant_id,
    model_version: str,
) -> CalibrationArtifact | None:
    return (
        await db.execute(
            select(CalibrationArtifact).where(
                CalibrationArtifact.tenant_id == tenant_id,
                CalibrationArtifact.model_type == "care",
                CalibrationArtifact.model_version == model_version,
                CalibrationArtifact.status == "active",
            )
        )
    ).scalar_one_or_none()


class ChatIn(BaseModel):
    session_id: str
    customer_id: str
    message: str
    channel: str = "mobile_app"


class ChatOut(BaseModel):
    session_id: str
    intent: str
    response: str
    escalate_to_human: bool
    suggested_actions: list[str]
    processing_time_ms: int
    pdf_url: str | None = None


class CareUploadOut(BaseModel):
    download_url: str
    expires_in_seconds: int
    public_id: str
    resource_type: str
    filename: str
    size_bytes: int


@router.post("/chat", response_model=ChatOut)
async def chat(
    payload: ChatIn,
    bank: TenantBank = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
    customer_external_id: str = Depends(resolve_end_user),
):
    # Backward compatibility: client may still send customer_id, but it must match the token.
    if payload.customer_id != customer_external_id:
        raise HTTPException(status_code=403, detail="Customer mismatch")
    route = await resolve_model_route(
        db,
        tenant_id=bank.id,
        model_type="care",
        strict_mapper=bool(settings.strict_mapper_enforcement),
    )
    _canonical_payload, mapper_validation_meta = await _validate_care_mapper_contract(
        db,
        route=route,
        raw_payload={
            "session_id": payload.session_id,
            "customer_id": customer_external_id,
            "message_text": payload.message,
            "channel": payload.channel,
            "language": None,
            "intent_metadata": None,
            "message_ts": datetime.now(timezone.utc).isoformat(),
        },
    )
    result = await handle_chat(
        db=db,
        bank=bank,
        session_id=payload.session_id,
        customer_id=customer_external_id,
        message=payload.message,
        channel=payload.channel,
        model_artifact_uri=route.artifact_uri,
    )
    calibration = await _resolve_active_care_calibration(db, tenant_id=bank.id, model_version=route.model_version)
    # Care pipeline has no single raw risk score yet; use a stable intent-confidence proxy.
    base_confidence = 0.9 if str(result.get("intent")) not in {"GENERAL_SUPPORT", "UNKNOWN"} else 0.55
    calibrated_confidence = (
        apply_calibration(base_confidence, method=calibration.method, params=dict(calibration.params_json or {}))
        if calibration
        else base_confidence
    )
    shadow_meta = None
    if settings.shadow_scoring_enabled:
        shadow = await resolve_shadow_candidate(db, tenant_id=bank.id, model_type="care")
        if shadow:
            shadow_intent, shadow_conf = predict_intent_shadow(payload.message, model_artifact_uri=shadow.artifact_uri)
            shadow_cal = await _resolve_active_care_calibration(db, tenant_id=bank.id, model_version=shadow.version)
            shadow_conf_cal = (
                apply_calibration(
                    shadow_conf,
                    method=(shadow_cal.method if shadow_cal else "none"),
                    params=(dict(shadow_cal.params_json or {}) if shadow_cal else {}),
                )
                if shadow_conf is not None
                else None
            )
            shadow_meta = {
                "candidate_model_registry_id": str(shadow.id),
                "candidate_model_version": shadow.version,
                "candidate_intent": shadow_intent,
                "candidate_confidence": shadow_conf,
                "candidate_confidence_calibrated": shadow_conf_cal,
                "candidate_calibration_id": str(shadow_cal.id) if shadow_cal else None,
                "candidate_calibration_method": shadow_cal.method if shadow_cal else "none",
            }
    db.add(
        InferenceTrace(
            tenant_id=bank.id,
            model_type="care",
            model_version=route.model_version,
            mapper_version=route.mapper_version,
            contract_version=route.contract_version,
            decision=result.get("intent"),
            processing_ms=result.get("processing_time_ms"),
            trace_json={
                **_care_trace_payload(route, mapper_validation_meta),
                "confidence_proxy": {
                    "base": base_confidence,
                    "calibrated": calibrated_confidence,
                    "calibration_id": str(calibration.id) if calibration else None,
                    "calibration_method": calibration.method if calibration else "none",
                },
                "shadow": shadow_meta,
            },
        )
    )
    await db.flush()

    # Emit observability metrics
    latency_s = result.get("processing_time_ms", 0) / 1000.0
    escalated = bool(result.get("escalate_to_human", False))
    record_care_request(str(bank.id), result.get("intent", "UNKNOWN"), latency_s, escalated)
    _logger.info(
        "care_chat_processed",
        tenant_id=str(bank.id),
        intent=result.get("intent"),
        escalated=escalated,
        processing_ms=result.get("processing_time_ms"),
    )

    return ChatOut(**result)


class MyTxStatsOut(BaseModel):
    range: str
    total_transactions: int
    scored_transactions: int
    fraud_like_transactions: int
    by_decision: dict


@router.get("/my-transactions/stats", response_model=MyTxStatsOut)
async def my_transaction_stats(
    range: str | None = None,
    bank: TenantBank = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
    customer_external_id: str = Depends(resolve_end_user),
):
    customer = await resolve_customer_or_404(db, bank, customer_external_id)
    tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
    tr = parse_time_range(time_range_key=range, tz_name=tz_name)
    stats = await customer_transaction_stats(db=db, bank=bank, customer=customer, time_range=tr)
    return MyTxStatsOut(range=(range or "this_week"), **stats)


class MyTxOut(BaseModel):
    range: str
    transactions: list[dict]


@router.get("/my-transactions", response_model=MyTxOut)
async def my_transactions(
    range: str | None = None,
    limit: int = 50,
    decision: str | None = None,
    bank: TenantBank = Depends(resolve_tenant),
    db: AsyncSession = Depends(get_db),
    customer_external_id: str = Depends(resolve_end_user),
):
    customer = await resolve_customer_or_404(db, bank, customer_external_id)
    tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
    tr = parse_time_range(time_range_key=range, tz_name=tz_name)
    decisions = None
    if decision:
        ds = [d.strip().upper() for d in decision.split(",") if d.strip()]
        decisions = [d for d in ds if d in ("APPROVE", "LIMITED_APPROVAL", "REQUEST_OTP", "BLOCK")] or None
    txs = await list_customer_transactions(
        db=db,
        bank=bank,
        customer=customer,
        time_range=tr,
        limit=limit,
        decision_in=decisions,
    )
    return MyTxOut(range=(range or "this_week"), transactions=txs)


@router.get("/statement.pdf")
async def download_statement_pdf(
    token: str = Query(..., description="Signed download token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Download a PDF statement without headers (token-auth).

    We intentionally allow this endpoint to be opened in a browser/webview. The token is short-lived
    and encodes tenant_id + customer_external_id + range.
    """
    try:
        payload = jwt.decode(
            token,
            settings.care_jwt_secret,
            algorithms=["HS256"],
            audience="bankai-care-pdf",
            issuer="bankai",
            options={"verify_aud": True, "verify_iss": True},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    tenant_id = payload.get("tenant_id")
    customer_external_id = payload.get("customer_external_id")
    range_key = payload.get("range") or "this_week"
    if not tenant_id or not customer_external_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Resolve bank without API key (token is already bound to tenant_id)
    from sqlalchemy import select

    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
    if bank is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer = await resolve_customer_or_404(db, bank, str(customer_external_id))
    tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
    tr = parse_time_range(time_range_key=str(range_key), tz_name=tz_name)
    stats = await customer_transaction_stats(db=db, bank=bank, customer=customer, time_range=tr)
    txs = await list_customer_transactions(db=db, bank=bank, customer=customer, time_range=tr, limit=200)

    rows = [
        StatementRow(
            timestamp=datetime.fromisoformat((t.get("timestamp") or "").replace("Z", "+00:00")) if t.get("timestamp") else None,
            transaction_id=str(t.get("transaction_id") or ""),
            amount=float(t.get("amount") or 0.0),
            currency=str(t.get("currency") or ""),
            merchant=t.get("merchant"),
            merchant_category=t.get("merchant_category"),
            decision=t.get("model_decision"),
        )
        for t in txs
    ]
    bank_name = (bank.tone_config or {}).get("bank_name") or "BankAI"
    range_label = str(range_key).replace("_", " ")
    pdf_bytes = render_statement_pdf(
        bank_name=str(bank_name),
        customer_external_id=str(customer_external_id),
        range_label=range_label,
        tz_name=tz_name,
        rows=rows,
        stats=stats,
    )
    fn = f"statement-{customer_external_id}-{range_key}.pdf"

    # Optional: store statements in Cloudinary and redirect (better for serverless/webview downloads).
    if bool(getattr(settings, "cloudinary_store_statements", True)):
        res = upload_bytes(
            content=pdf_bytes,
            filename=fn,
            folder=f"statements/{tenant_id}/{customer_external_id}",
            resource_type="raw",
            delivery_type="private",
            tags=["statement", "care_pdf"],
            context={
                "tenant_id": str(tenant_id),
                "customer_external_id": str(customer_external_id),
                "range": str(range_key),
            },
        )
        if res is not None and res.url:
            # Use a short-lived signed URL to avoid public leakage of statements.
            ttl = int(getattr(settings, "care_upload_download_token_ttl_seconds", 300) or 300)
            su = signed_download_url(public_id=res.public_id, resource_type="raw", expires_in_seconds=ttl, filename=fn)
            if su:
                return Response(status_code=302, headers={"Location": su})

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )


@router.get("/uploads/download")
async def care_download_uploaded_file(
    token: str = Query(..., description="Signed download token"),
):
    """
    Redirect to a short-lived signed Cloudinary URL for an end-user upload.
    """
    try:
        payload = jwt.decode(
            token,
            settings.care_jwt_secret,
            algorithms=["HS256"],
            audience="bankai-care-upload",
            issuer="bankai",
            options={"verify_aud": True, "verify_iss": True},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    tenant_id = str(payload.get("tenant_id") or "").strip()
    customer_external_id = str(payload.get("customer_external_id") or "").strip()
    public_id = str(payload.get("public_id") or "").strip()
    resource_type = str(payload.get("resource_type") or "raw").strip()
    filename = str(payload.get("filename") or "download").strip()
    if not tenant_id or not customer_external_id or not public_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    ttl = int(getattr(settings, "care_upload_download_token_ttl_seconds", 300) or 300)
    url = signed_download_url(
        public_id=public_id,
        resource_type=resource_type,
        expires_in_seconds=ttl,
        filename=filename,
    )
    if not url:
        raise HTTPException(status_code=503, detail="Download unavailable")
    return Response(status_code=302, headers={"Location": url})


@router.post("/uploads", response_model=CareUploadOut)
async def care_upload_to_cloudinary(
    file: UploadFile = File(...),
    bank: TenantBank = Depends(resolve_tenant),
    customer_external_id: str = Depends(resolve_end_user),
):
    """
    End-user upload endpoint (Care).

    Security controls:
    - Requires end-user auth (resolve_end_user)
    - Enforces size cap and basic type restrictions
    - Stores under tenant/customer folder in Cloudinary
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    name = str(file.filename)
    lower = name.lower()

    # Keep tight allowlist for end users.
    allowed_ext = (".png", ".jpg", ".jpeg", ".webp", ".pdf")
    if not lower.endswith(allowed_ext):
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {', '.join(allowed_ext)}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    if not bool(getattr(settings, "care_uploads_enabled", True)):
        raise HTTPException(status_code=403, detail="Uploads disabled")

    max_bytes = int(getattr(settings, "care_upload_max_bytes", 8 * 1024 * 1024) or (8 * 1024 * 1024))
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {max_bytes} bytes)")

    # Basic magic-byte validation to reduce spoofing risk (best-effort).
    def _looks_like_pdf(b: bytes) -> bool:
        return b[:5] == b"%PDF-"

    def _looks_like_png(b: bytes) -> bool:
        return b[:8] == b"\x89PNG\r\n\x1a\n"

    def _looks_like_jpeg(b: bytes) -> bool:
        return b[:3] == b"\xff\xd8\xff"

    def _looks_like_webp(b: bytes) -> bool:
        return len(b) > 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"

    if lower.endswith(".pdf") and not _looks_like_pdf(content):
        raise HTTPException(status_code=400, detail="File content does not look like a PDF")
    if lower.endswith(".png") and not _looks_like_png(content):
        raise HTTPException(status_code=400, detail="File content does not look like a PNG")
    if lower.endswith((".jpg", ".jpeg")) and not _looks_like_jpeg(content):
        raise HTTPException(status_code=400, detail="File content does not look like a JPEG")
    if lower.endswith(".webp") and not _looks_like_webp(content):
        raise HTTPException(status_code=400, detail="File content does not look like a WEBP")

    # Redis-backed quotas (best-effort; if Redis is down we allow the upload).
    try:
        import redis  # type: ignore

        redis_url = str(getattr(settings, "redis_url", "") or os.getenv("REDIS_URL") or "").strip()
        if redis_url:
            r = redis.Redis.from_url(redis_url, decode_responses=True)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            base = f"care_upload:{str(bank.id)}:{customer_external_id}:{day}"
            files_key = base + ":files"
            bytes_key = base + ":bytes"
            ttl_s = 60 * 60 * 26  # keep a bit longer than 1 day to avoid edge cases

            pipe = r.pipeline()
            pipe.incr(files_key, 1)
            pipe.incrby(bytes_key, len(content))
            pipe.expire(files_key, ttl_s)
            pipe.expire(bytes_key, ttl_s)
            files_used, bytes_used, _t1, _t2 = pipe.execute()

            max_files = int(getattr(settings, "care_upload_max_files_per_day", 20) or 20)
            max_bytes_day = int(getattr(settings, "care_upload_max_bytes_per_day", 40 * 1024 * 1024) or (40 * 1024 * 1024))
            if int(files_used) > max_files or int(bytes_used) > max_bytes_day:
                raise HTTPException(status_code=429, detail="Daily upload quota exceeded")
    except HTTPException:
        raise
    except Exception:
        pass

    # Optional malware scan hook (best-effort). We send metadata + SHA256, not raw file.
    sha = hashlib.sha256(content).hexdigest()
    scan_url = str(getattr(settings, "malware_scan_webhook_url", "") or "").strip()
    if scan_url:
        require_clean = bool(getattr(settings, "malware_scan_require_clean", False))
        timeout_s = float(getattr(settings, "malware_scan_timeout_seconds", 6) or 6)
        try:
            import httpx
            resp = await httpx.AsyncClient(timeout=timeout_s).post(
                scan_url,
                json={
                    "tenant_id": str(bank.id),
                    "customer_external_id": customer_external_id,
                    "filename": name,
                    "size_bytes": len(content),
                    "sha256": sha,
                    "content_type": str(file.content_type or ""),
                },
                headers={"Content-Type": "application/json", "X-Webhook-Event": "MALWARE_SCAN_REQUEST"},
            )
            if require_clean and resp.status_code >= 400:
                raise HTTPException(status_code=503, detail="Malware scan unavailable")
        except HTTPException:
            raise
        except Exception:
            if require_clean:
                raise HTTPException(status_code=503, detail="Malware scan unavailable")

    resource_type = "image" if lower.endswith((".png", ".jpg", ".jpeg", ".webp")) else "raw"
    folder = f"care_uploads/{str(bank.id)}/{customer_external_id}"
    res = upload_bytes(
        content=content,
        filename=name,
        folder=folder,
        resource_type=resource_type,
        delivery_type="private",
        tags=["care_upload", "end_user"],
        context={"tenant_id": str(bank.id), "customer_external_id": customer_external_id, "sha256": sha},
    )
    if res is None:
        raise HTTPException(status_code=503, detail="Cloudinary not configured or upload failed")

    # Return a short-lived download token that redirects to a signed Cloudinary URL.
    ttl = int(getattr(settings, "care_upload_download_token_ttl_seconds", 300) or 300)
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "bankai",
            "aud": "bankai-care-upload",
            "tenant_id": str(bank.id),
            "customer_external_id": customer_external_id,
            "public_id": res.public_id,
            "resource_type": res.resource_type,
            "filename": name,
            "iat": now,
            "exp": now + ttl,
        },
        settings.care_jwt_secret,
        algorithm="HS256",
    )
    download_url = "/api/v1/care/uploads/download?token=" + token

    return CareUploadOut(
        download_url=download_url,
        expires_in_seconds=ttl,
        public_id=res.public_id,
        resource_type=res.resource_type,
        filename=name,
        size_bytes=len(content),
    )
