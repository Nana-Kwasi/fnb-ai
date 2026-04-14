from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import TenantBank
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.fraud import FraudScore
from app.models.fraud_extra import FraudAlert
from app.models.reporting import ReportJob
from app.models.transaction import Transaction

REPORTS_DIR = Path(__file__).resolve().parents[1] / "ml" / "data" / "reports"
EXPORTS_DIR = Path(__file__).resolve().parents[1] / "ml" / "data" / "exports"


def _coerce_iso(s: str) -> datetime:
    # Expecting "YYYY-MM-DD"
    return datetime.fromisoformat(f"{s}T00:00:00+00:00")


def _coerce_iso_end(s: str) -> datetime:
    return datetime.fromisoformat(f"{s}T23:59:59+00:00")


def _decision_norm(decision: str | None) -> str:
    d = str(decision or "").upper()
    mapping = {
        "REQUEST_OT": "REQUEST_OTP",
        "LIMITED_AP": "LIMITED_APPROVAL",
        "MANUAL_REV": "MANUAL_REVIEW",
        "SOFT_DECLI": "SOFT_DECLINE",
    }
    return mapping.get(d, d or "PENDING")


def _render_pdf(path: Path, title: str, summary: dict[str, Any], tx_rows: list[dict[str, Any]], logo_path: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>{title}</b>", styles["Title"]),
        Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()}", styles["Normal"]),
        Spacer(1, 8),
        Paragraph(f"<b>Total transactions:</b> {summary.get('total_transactions', 0)}", styles["Normal"]),
        Paragraph(f"<b>Total amount:</b> {summary.get('total_amount', 0)}", styles["Normal"]),
        Paragraph(f"<b>Open alerts:</b> {summary.get('open_alerts', 0)}", styles["Normal"]),
        Paragraph(f"<b>Avg fraud score:</b> {summary.get('avg_fraud_score', 0)}", styles["Normal"]),
        Spacer(1, 10),
    ]
    if logo_path:
        p = Path(str(logo_path))
        if p.exists():
            try:
                story.insert(0, Image(str(p), width=28 * mm, height=12 * mm))
                story.insert(1, Spacer(1, 4))
            except Exception:
                pass
    table_data = [["Time", "Tx ID", "Account", "Amount", "Decision", "Score"]]
    for r in tx_rows[:200]:
        table_data.append(
            [
                str(r.get("created_at") or ""),
                str(r.get("transaction_id") or ""),
                str(r.get("account_id") or ""),
                f"{r.get('currency') or ''} {r.get('amount') or ''}",
                str(r.get("decision") or ""),
                str(r.get("fraud_score") if r.get("fraud_score") is not None else ""),
            ]
        )
    table = Table(table_data, colWidths=[30 * mm, 35 * mm, 28 * mm, 30 * mm, 28 * mm, 18 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#334155")),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
            ]
        )
    )
    story.append(table)
    doc.build(story)


def _render_xlsx(path: Path, tx_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["transaction_id", "account_id", "amount", "currency", "decision", "fraud_score", "created_at"])
    for r in tx_rows:
        ws.append(
            [
                r.get("transaction_id"),
                r.get("account_id"),
                r.get("amount"),
                r.get("currency"),
                r.get("decision"),
                r.get("fraud_score"),
                r.get("created_at"),
            ]
        )
    wb.save(str(path))


async def run_report_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(ReportJob, job_id)
        if not job:
            return
        if job.status == "cancelled":
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.flush()
        await db.commit()

    async with AsyncSessionLocal() as db:
        job = await db.get(ReportJob, job_id)
        if not job:
            return
        try:
            if job.status == "cancelled":
                return
            filters = dict(job.filters or {})
            tenant_id = job.tenant_id
            from_dt = _coerce_iso(str(filters.get("from_date")))
            to_dt = _coerce_iso_end(str(filters.get("to_date")))
            decision_filter = str(filters.get("decision_filter") or "ALL").upper()

            bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
            if not bank:
                raise ValueError("Tenant not found")

            tx_stmt = (
                select(
                    Transaction.id,
                    Customer.external_id,
                    Transaction.amount,
                    Transaction.currency,
                    Transaction.tx_timestamp,
                    FraudScore.decision,
                    FraudScore.ensemble_score,
                )
                .join(Customer, Customer.id == Transaction.customer_id)
                .outerjoin(FraudScore, FraudScore.transaction_id == Transaction.id)
                .where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.tx_timestamp >= from_dt,
                    Transaction.tx_timestamp <= to_dt,
                )
                .order_by(Transaction.tx_timestamp.desc())
            )
            tx_raw = (await db.execute(tx_stmt)).all()
            tx_rows: list[dict[str, Any]] = []
            decisions: dict[str, int] = {}
            total_amt = 0.0
            score_sum = 0.0
            score_n = 0
            for tx_id, external_id, amount, currency, tx_timestamp, decision, ensemble_score in tx_raw:
                norm_dec = _decision_norm(decision)
                if decision_filter != "ALL" and norm_dec != decision_filter:
                    continue
                amt = float(amount or 0)
                score = float(ensemble_score) if ensemble_score is not None else None
                tx_rows.append(
                    {
                        "transaction_id": str(tx_id),
                        "account_id": external_id,
                        "amount": amt,
                        "currency": currency,
                        "decision": norm_dec,
                        "fraud_score": score,
                        "created_at": tx_timestamp.isoformat() if tx_timestamp else "",
                    }
                )
                decisions[norm_dec] = decisions.get(norm_dec, 0) + 1
                total_amt += amt
                if score is not None:
                    score_sum += score
                    score_n += 1

            alerts_stmt = select(FraudAlert).where(
                FraudAlert.tenant_id == tenant_id,
                FraudAlert.created_at >= from_dt,
                FraudAlert.created_at <= to_dt,
            )
            alerts = (await db.execute(alerts_stmt)).scalars().all()
            open_alerts = len([a for a in alerts if str(a.status or "").upper() == "OPEN"])

            summary = {
                "total_transactions": len(tx_rows),
                "total_amount": round(total_amt, 2),
                "open_alerts": open_alerts,
                "avg_fraud_score": round(score_sum / max(1, score_n), 4),
                "decision_counts": decisions,
            }

            base = REPORTS_DIR / str(tenant_id) / str(job.id)
            pdf_path = base / "report.pdf"
            xlsx_path = base / "report.xlsx"
            _render_pdf(pdf_path, f"{bank.name} Report", summary, tx_rows, logo_path=bank.logo_path)
            if job.status == "cancelled":
                return
            _render_xlsx(xlsx_path, tx_rows)

            job.summary = summary
            job.status = "done"
            job.error = None
            job.artifact_pdf_path = str(pdf_path)
            job.artifact_xlsx_path = str(xlsx_path)
            job.finished_at = datetime.now(timezone.utc)
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    event_type="REPORT_JOB_COMPLETE",
                    entity_type="admin_report",
                    actor_type="api",
                    actor_id=job.requested_by,
                    event_data={"job_id": str(job.id), "filters": filters, "summary": summary},
                )
            )
            await db.flush()
            await db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.add(
                AuditLog(
                    tenant_id=job.tenant_id,
                    event_type="REPORT_JOB_FAILED",
                    entity_type="admin_report",
                    actor_type="api",
                    actor_id=job.requested_by,
                    event_data={"job_id": str(job.id), "error": str(exc)},
                )
            )
            await db.flush()
            await db.commit()


async def cleanup_old_report_artifacts(retention_days: int = 30) -> dict[str, int]:
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, int(retention_days)) * 24 * 60 * 60
    deleted_files = 0
    touched_jobs = 0
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(ReportJob).where(ReportJob.status.in_(["done", "failed", "cancelled"])))
        ).scalars().all()
        for job in rows:
            created_ts = (job.created_at or datetime.now(timezone.utc)).timestamp()
            if created_ts > cutoff:
                continue
            paths = [job.artifact_pdf_path, job.artifact_xlsx_path]
            changed = False
            for p in paths:
                if not p:
                    continue
                fp = Path(str(p))
                if fp.exists():
                    try:
                        fp.unlink()
                        deleted_files += 1
                    except Exception:
                        pass
                changed = True
            if changed:
                job.artifact_pdf_path = None
                job.artifact_xlsx_path = None
                touched_jobs += 1
        if touched_jobs:
            await db.flush()
            await db.commit()
    return {"deleted_files": deleted_files, "touched_jobs": touched_jobs}


async def run_tenant_export_job(job_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(ReportJob, job_id)
        if not job:
            return
        if job.status == "cancelled":
            return
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        await db.flush()
        await db.commit()

    async with AsyncSessionLocal() as db:
        job = await db.get(ReportJob, job_id)
        if not job:
            return
        try:
            tenant_id = job.tenant_id
            bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
            if not bank:
                raise ValueError("Tenant not found")
            customers = int(await db.scalar(select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id)) or 0)
            txs = int(await db.scalar(select(func.count()).select_from(Transaction).where(Transaction.tenant_id == tenant_id)) or 0)
            alerts = int(await db.scalar(select(func.count()).select_from(FraudAlert).where(FraudAlert.tenant_id == tenant_id)) or 0)
            scores = int(await db.scalar(select(func.count()).select_from(FraudScore).where(FraudScore.tenant_id == tenant_id)) or 0)
            summary = {
                "tenant_name": bank.name,
                "customer_count": customers,
                "transaction_count": txs,
                "alert_count": alerts,
                "score_count": scores,
            }
            out_dir = EXPORTS_DIR / str(tenant_id) / str(job.id)
            out_dir.mkdir(parents=True, exist_ok=True)
            export_json = out_dir / "tenant_export.json"
            export_json.write_text(
                json.dumps(
                    {
                        "tenant_id": str(tenant_id),
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "summary": summary,
                        "filters": dict(job.filters or {}),
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            job.summary = summary
            job.status = "done"
            job.error = None
            job.artifact_pdf_path = str(export_json)
            job.artifact_xlsx_path = None
            job.finished_at = datetime.now(timezone.utc)
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    event_type="TENANT_EXPORT_COMPLETE",
                    entity_type="tenant_export",
                    actor_type="api",
                    actor_id=job.requested_by,
                    event_data={"job_id": str(job.id), "summary": summary},
                )
            )
            await db.flush()
            await db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.add(
                AuditLog(
                    tenant_id=job.tenant_id,
                    event_type="TENANT_EXPORT_FAILED",
                    entity_type="tenant_export",
                    actor_type="api",
                    actor_id=job.requested_by,
                    event_data={"job_id": str(job.id), "error": str(exc)},
                )
            )
            await db.flush()
            await db.commit()
