from __future__ import annotations

import asyncio
import io
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, cast, func, select, Text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import AdminContext, ensure_tenant_access, require_platform_roles
from app.config import settings
from app.database import get_db
from app.models.audit import AuditLog
from app.models.tenant import TenantBank
from app.models.reporting import ReportJob, ReportPreset
from app.services.report_jobs import run_report_job

router = APIRouter()


class ReportJobCreateIn(BaseModel):
    tenant_id: uuid.UUID
    from_date: str
    to_date: str
    decision_filter: str = "ALL"


class ReportJobOut(BaseModel):
    job_id: str
    tenant_id: str
    status: str
    filters: dict
    summary: dict | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class ReportJobListOut(BaseModel):
    items: list[ReportJobOut]
    total: int
    page: int
    page_size: int


class ReportPresetIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    decision_filter: str = "ALL"
    from_date: str
    to_date: str
    sort_by: str = "created_at"
    sort_dir: str = "desc"


class ReportPresetOut(BaseModel):
    preset_id: str
    tenant_id: str
    name: str
    decision_filter: str
    from_date: str
    to_date: str
    sort_by: str
    sort_dir: str
    created_at: str


class ReportAuditOut(BaseModel):
    id: int
    event_type: str
    actor_id: str | None = None
    entity_id: str | None = None
    event_data: dict
    created_at: str


def _sign_payload(payload: str) -> str:
    key = (settings.secret_key or "dev-secret").encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _serialize_job(job: ReportJob) -> ReportJobOut:
    return ReportJobOut(
        job_id=str(job.id),
        tenant_id=str(job.tenant_id),
        status=job.status,
        filters=dict(job.filters or {}),
        summary=dict(job.summary or {}) if isinstance(job.summary, dict) else None,
        error=job.error,
        created_at=job.created_at.isoformat() if job.created_at else "",
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


def _serialize_preset(p: ReportPreset) -> ReportPresetOut:
    return ReportPresetOut(
        preset_id=str(p.id),
        tenant_id=str(p.tenant_id),
        name=p.name,
        decision_filter=p.decision_filter,
        from_date=p.from_date,
        to_date=p.to_date,
        sort_by=p.sort_by,
        sort_dir=p.sort_dir,
        created_at=p.created_at.isoformat() if p.created_at else "",
    )


def _validate_preset_payload(payload: ReportPresetIn) -> tuple[str, str, str]:
    allowed_decisions = {"ALL", "APPROVE", "LIMITED_APPROVAL", "REQUEST_OTP", "SOFT_DECLINE", "BLOCK"}
    dec = (payload.decision_filter or "ALL").upper()
    if dec not in allowed_decisions:
        raise HTTPException(status_code=400, detail="Invalid decision_filter")
    allowed_sort = {"created_at", "status", "finished_at"}
    sort_by = (payload.sort_by or "created_at").lower()
    sort_dir = (payload.sort_dir or "desc").lower()
    if sort_by not in allowed_sort:
        raise HTTPException(status_code=400, detail="Invalid sort_by")
    if sort_dir not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sort_dir")
    return dec, sort_by, sort_dir


def _serialize_audit_row(row: AuditLog) -> ReportAuditOut:
    return ReportAuditOut(
        id=int(row.id),
        event_type=row.event_type,
        actor_id=row.actor_id,
        entity_id=str(row.entity_id) if row.entity_id else None,
        event_data=dict(row.event_data or {}),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _audit_preset_event(
    *,
    tenant_id: uuid.UUID,
    actor_id: str,
    event_type: str,
    preset_id: uuid.UUID | None = None,
    data: dict | None = None,
) -> AuditLog:
    return AuditLog(
        tenant_id=tenant_id,
        event_type=event_type,
        entity_type="report_preset",
        entity_id=preset_id,
        actor_type="api",
        actor_id=actor_id,
        event_data=data or {},
    )


def _kind_filter_clause(kind: str):
    # Portable filter over JSON column for sqlite/postgres.
    # report => rows not explicitly tagged tenant_export.
    ftxt = cast(ReportJob.filters, Text)
    if kind == "tenant_export":
        return ftxt.like('%"kind": "tenant_export"%')
    return ~ftxt.like('%"kind": "tenant_export"%')


@router.post("/jobs", response_model=ReportJobOut)
async def create_report_job(
    payload: ReportJobCreateIn,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, payload.tenant_id)
    filters = {
        "from_date": payload.from_date,
        "to_date": payload.to_date,
        "decision_filter": (payload.decision_filter or "ALL").upper(),
    }
    job = ReportJob(
        tenant_id=payload.tenant_id,
        requested_by=admin.actor_id,
        status="queued",
        filters=filters,
    )
    db.add(job)
    await db.flush()
    await db.commit()
    await db.refresh(job)
    job_id = job.id
    asyncio.create_task(run_report_job(job_id))
    return _serialize_job(job)


@router.get("/jobs/{job_id}", response_model=ReportJobOut)
async def get_report_job(
    job_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    await ensure_tenant_access(db, admin, job.tenant_id)
    return _serialize_job(job)


@router.get("/jobs", response_model=ReportJobListOut)
async def list_report_jobs(
    tenant_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    kind: str | None = Query(None, pattern="^(report|tenant_export)$"),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    filters = [ReportJob.tenant_id == tenant_id]
    if status:
        allowed = {"queued", "running", "done", "failed", "cancelled"}
        st = str(status).strip().lower()
        if st not in allowed:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        filters.append(ReportJob.status == st)
    if from_date:
        try:
            from_dt = datetime.fromisoformat(f"{from_date}T00:00:00+00:00")
            filters.append(ReportJob.created_at >= from_dt)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid from_date format; expected YYYY-MM-DD") from exc
    if to_date:
        try:
            to_dt = datetime.fromisoformat(f"{to_date}T23:59:59+00:00")
            filters.append(ReportJob.created_at <= to_dt)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid to_date format; expected YYYY-MM-DD") from exc
    if kind:
        filters.append(_kind_filter_clause(str(kind).strip().lower()))
    allowed_sort = {"created_at", "status", "finished_at"}
    sort_col = str(sort_by or "created_at").strip().lower()
    if sort_col not in allowed_sort:
        raise HTTPException(status_code=400, detail="Invalid sort_by; use created_at|status|finished_at")
    direction = str(sort_dir or "desc").strip().lower()
    if direction not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Invalid sort_dir; use asc|desc")
    col_map = {
        "created_at": ReportJob.created_at,
        "status": ReportJob.status,
        "finished_at": ReportJob.finished_at,
    }
    order_col = col_map[sort_col]
    order_expr = order_col.asc() if direction == "asc" else order_col.desc()
    where_clause = and_(*filters)
    rows = (
        await db.execute(
            select(ReportJob)
            .where(where_clause)
            .order_by(order_expr, ReportJob.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    total = int((await db.execute(select(func.count(ReportJob.id)).where(where_clause))).scalar_one() or 0)
    return ReportJobListOut(items=[_serialize_job(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/presets", response_model=list[ReportPresetOut])
async def list_report_presets(
    tenant_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    rows = (
        await db.execute(
            select(ReportPreset).where(ReportPreset.tenant_id == tenant_id).order_by(ReportPreset.created_at.desc())
        )
    ).scalars().all()
    return [_serialize_preset(r) for r in rows]


@router.get("/audit", response_model=list[ReportAuditOut])
async def list_report_audit(
    tenant_id: uuid.UUID,
    limit: int = Query(30, ge=1, le=200),
    event_type: str | None = Query(None),
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    stmt = select(AuditLog).where(
        AuditLog.tenant_id == tenant_id,
        AuditLog.entity_type.in_(["admin_report", "report_preset"]),
    )
    if event_type:
        stmt = stmt.where(AuditLog.event_type == str(event_type).strip().upper())
    rows = (await db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    return [_serialize_audit_row(r) for r in rows]


@router.get("/audit/{audit_id}/pdf")
async def download_report_audit_pdf(
    audit_id: int,
    tenant_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    row = await db.get(AuditLog, audit_id)
    if not row or row.tenant_id != tenant_id or row.entity_type not in {"admin_report", "report_preset"}:
        raise HTTPException(status_code=404, detail="Audit event not found")
    bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 16 * mm
    content_width = width - 2 * margin
    y = height - 16 * mm

    def ensure_page(min_y: float = 18 * mm):
        nonlocal y
        if y < min_y:
            c.showPage()
            y = height - 16 * mm

    def draw_header():
        nonlocal y
        c.setFillColor(colors.HexColor("#0f172a"))
        c.rect(0, height - 28 * mm, width, 28 * mm, stroke=0, fill=1)
        if bank and bank.logo_path:
            p = Path(str(bank.logo_path))
            if p.exists():
                try:
                    c.drawImage(str(p), margin, height - 24 * mm, width=24 * mm, height=10 * mm, preserveAspectRatio=True, mask="auto")
                except Exception:
                    pass
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(margin + 28 * mm, height - 14 * mm, "BankAI Audit Event")
        c.setFont("Helvetica", 9)
        c.drawRightString(width - margin, height - 14 * mm, datetime.now(timezone.utc).strftime("Generated %Y-%m-%d %H:%M UTC"))
        y = height - 36 * mm

    def draw_kv(label: str, value: str):
        nonlocal y
        ensure_page(22 * mm)
        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, label)
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawString(margin + 34 * mm, y, value[:120])
        y -= 6 * mm

    def draw_json_block(title: str, payload: dict):
        nonlocal y
        ensure_page(40 * mm)
        c.setFillColor(colors.HexColor("#0f172a"))
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, title)
        y -= 5 * mm
        text = json.dumps(payload or {}, indent=2, sort_keys=True, default=str)
        lines = text.splitlines() or ["{}"]
        block_pad = 3 * mm
        line_h = 4.5 * mm
        max_lines_per_page = int(max(1, (y - 20 * mm) // line_h))
        idx = 0
        while idx < len(lines):
            ensure_page(30 * mm)
            max_lines_per_page = int(max(1, (y - 20 * mm) // line_h))
            chunk = lines[idx : idx + max_lines_per_page]
            box_h = line_h * len(chunk) + 2 * block_pad
            c.setFillColor(colors.HexColor("#f8fafc"))
            c.setStrokeColor(colors.HexColor("#cbd5e1"))
            c.roundRect(margin, y - box_h, content_width, box_h, 3 * mm, stroke=1, fill=1)
            text_obj = c.beginText()
            text_obj.setTextOrigin(margin + block_pad, y - block_pad - 3.2 * mm)
            text_obj.setFont("Courier", 7.8)
            text_obj.setFillColor(colors.HexColor("#0f172a"))
            for ln in chunk:
                safe = ln
                if len(safe) > 150:
                    safe = f"{safe[:147]}..."
                text_obj.textLine(safe)
            c.drawText(text_obj)
            y -= box_h + 4 * mm
            idx += len(chunk)

    draw_header()
    draw_kv("Event ID", str(row.id))
    draw_kv("Tenant", str(row.tenant_id))
    draw_kv("Event Type", str(row.event_type or "-"))
    draw_kv("Entity Type", str(row.entity_type or "-"))
    draw_kv("Entity ID", str(row.entity_id or "-"))
    draw_kv("Actor", str(row.actor_id or "-"))
    draw_kv("Created At", row.created_at.isoformat() if row.created_at else "-")
    y -= 2 * mm
    draw_json_block("Event Data (JSON)", row.event_data or {})

    c.save()
    buf.seek(0)
    filename = f"audit-{row.id}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)


@router.post("/presets", response_model=ReportPresetOut)
async def create_report_preset(
    payload: ReportPresetIn,
    tenant_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    dec, sort_by, sort_dir = _validate_preset_payload(payload)
    existing = (
        await db.execute(
            select(ReportPreset).where(ReportPreset.tenant_id == tenant_id, ReportPreset.name == payload.name.strip())
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Preset with this name already exists")
    preset = ReportPreset(
        tenant_id=tenant_id,
        name=payload.name.strip(),
        decision_filter=dec,
        from_date=payload.from_date,
        to_date=payload.to_date,
        sort_by=sort_by,
        sort_dir=sort_dir,
        created_by=admin.actor_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(preset)
    db.add(
        _audit_preset_event(
            tenant_id=tenant_id,
            actor_id=admin.actor_id,
            event_type="REPORT_PRESET_CREATED",
            preset_id=preset.id,
            data={
                "name": preset.name,
                "decision_filter": preset.decision_filter,
                "from_date": preset.from_date,
                "to_date": preset.to_date,
                "sort_by": preset.sort_by,
                "sort_dir": preset.sort_dir,
            },
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(preset)
    return _serialize_preset(preset)


@router.put("/presets/{preset_id}", response_model=ReportPresetOut)
async def update_report_preset(
    preset_id: uuid.UUID,
    payload: ReportPresetIn,
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    preset = await db.get(ReportPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    await ensure_tenant_access(db, admin, preset.tenant_id)
    dec, sort_by, sort_dir = _validate_preset_payload(payload)
    new_name = payload.name.strip()
    if new_name != preset.name:
        existing = (
            await db.execute(
                select(ReportPreset).where(ReportPreset.tenant_id == preset.tenant_id, ReportPreset.name == new_name)
            )
        ).scalar_one_or_none()
        if existing and existing.id != preset.id:
            raise HTTPException(status_code=409, detail="Preset with this name already exists")
    preset.name = new_name
    preset.decision_filter = dec
    preset.from_date = payload.from_date
    preset.to_date = payload.to_date
    preset.sort_by = sort_by
    preset.sort_dir = sort_dir
    db.add(
        _audit_preset_event(
            tenant_id=preset.tenant_id,
            actor_id=admin.actor_id,
            event_type="REPORT_PRESET_UPDATED",
            preset_id=preset.id,
            data={
                "name": preset.name,
                "decision_filter": preset.decision_filter,
                "from_date": preset.from_date,
                "to_date": preset.to_date,
                "sort_by": preset.sort_by,
                "sort_dir": preset.sort_dir,
            },
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(preset)
    return _serialize_preset(preset)


@router.delete("/presets/{preset_id}")
async def delete_report_preset(
    preset_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    preset = await db.get(ReportPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    await ensure_tenant_access(db, admin, preset.tenant_id)
    db.add(
        _audit_preset_event(
            tenant_id=preset.tenant_id,
            actor_id=admin.actor_id,
            event_type="REPORT_PRESET_DELETED",
            preset_id=preset.id,
            data={"name": preset.name},
        )
    )
    await db.delete(preset)
    await db.commit()
    return {"status": "ok"}


@router.post("/presets/{preset_id}/duplicate", response_model=ReportPresetOut)
async def duplicate_report_preset(
    preset_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    preset = await db.get(ReportPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    await ensure_tenant_access(db, admin, preset.tenant_id)
    base_name = f"{preset.name} (copy)"
    name = base_name
    idx = 2
    while True:
        existing = (
            await db.execute(
                select(ReportPreset.id).where(ReportPreset.tenant_id == preset.tenant_id, ReportPreset.name == name)
            )
        ).scalar_one_or_none()
        if not existing:
            break
        name = f"{base_name} {idx}"
        idx += 1
    dup = ReportPreset(
        tenant_id=preset.tenant_id,
        name=name,
        decision_filter=preset.decision_filter,
        from_date=preset.from_date,
        to_date=preset.to_date,
        sort_by=preset.sort_by,
        sort_dir=preset.sort_dir,
        created_by=admin.actor_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(dup)
    db.add(
        _audit_preset_event(
            tenant_id=dup.tenant_id,
            actor_id=admin.actor_id,
            event_type="REPORT_PRESET_DUPLICATED",
            preset_id=dup.id,
            data={"source_preset_id": str(preset.id), "name": dup.name},
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(dup)
    return _serialize_preset(dup)


@router.post("/presets/{preset_id}/run", response_model=ReportJobOut)
async def run_report_preset(
    preset_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    preset = await db.get(ReportPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    await ensure_tenant_access(db, admin, preset.tenant_id)
    job = ReportJob(
        tenant_id=preset.tenant_id,
        requested_by=admin.actor_id,
        status="queued",
        filters={
            "from_date": preset.from_date,
            "to_date": preset.to_date,
            "decision_filter": preset.decision_filter,
        },
    )
    db.add(job)
    db.add(
        _audit_preset_event(
            tenant_id=preset.tenant_id,
            actor_id=admin.actor_id,
            event_type="REPORT_PRESET_RUN",
            preset_id=preset.id,
            data={"job_id": str(job.id), "name": preset.name},
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(job)
    asyncio.create_task(run_report_job(job.id))
    return _serialize_job(job)


@router.post("/jobs/{job_id}/cancel", response_model=ReportJobOut)
async def cancel_report_job(
    job_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    await ensure_tenant_access(db, admin, job.tenant_id)
    if job.status in {"done", "failed"}:
        raise HTTPException(status_code=400, detail="Cannot cancel completed job")
    job.status = "cancelled"
    if not job.finished_at:
        job.finished_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return _serialize_job(job)


@router.post("/jobs/{job_id}/retry", response_model=ReportJobOut)
async def retry_report_job(
    job_id: uuid.UUID,
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    prev = await db.get(ReportJob, job_id)
    if not prev:
        raise HTTPException(status_code=404, detail="Report job not found")
    await ensure_tenant_access(db, admin, prev.tenant_id)
    if prev.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Retry allowed only for failed/cancelled jobs")
    job = ReportJob(
        tenant_id=prev.tenant_id,
        requested_by=admin.actor_id,
        status="queued",
        filters=dict(prev.filters or {}),
    )
    db.add(job)
    await db.flush()
    await db.commit()
    await db.refresh(job)
    asyncio.create_task(run_report_job(job.id))
    return _serialize_job(job)


@router.post("/jobs/{job_id}/sign-download")
async def sign_download_url(
    job_id: uuid.UUID,
    format: str = Query(..., pattern="^(pdf|xlsx)$"),
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    await ensure_tenant_access(db, admin, job.tenant_id)
    if job.status != "done":
        raise HTTPException(status_code=400, detail="Report is not ready")
    exp = int(time.time()) + 10 * 60
    payload = f"{job_id}:{format}:{exp}:{job.tenant_id}"
    sig = _sign_payload(payload)
    return {
        "url": f"/api/v1/admin/reports/download/{job_id}/{format}?exp={exp}&sig={sig}",
        "expires_at": exp,
    }


@router.get("/download/{job_id}/{format}")
async def download_report_artifact(
    job_id: uuid.UUID,
    format: str,
    exp: int,
    sig: str,
    db: AsyncSession = Depends(get_db),
):
    fmt = (format or "").lower()
    if fmt not in {"pdf", "xlsx"}:
        raise HTTPException(status_code=400, detail="Invalid format")
    if int(time.time()) > int(exp):
        raise HTTPException(status_code=403, detail="Signed URL expired")
    job = await db.get(ReportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    payload = f"{job_id}:{fmt}:{exp}:{job.tenant_id}"
    expected = _sign_payload(payload)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")
    # Prefer Cloudinary URLs when configured (Render disks are ephemeral).
    url = (job.artifact_pdf_url if fmt == "pdf" else job.artifact_xlsx_url) or ""
    url = str(url).strip()
    if url:
        return RedirectResponse(url=url, status_code=302)

    path = Path(job.artifact_pdf_path if fmt == "pdf" else job.artifact_xlsx_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact missing")
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = f"tenant-report-{str(job.tenant_id)[:8]}-{str(job.id)[:8]}.{fmt}"
    return FileResponse(path=str(path), media_type=media, filename=filename)
