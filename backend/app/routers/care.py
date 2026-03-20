from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from jose import jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantBank
from app.database import get_db
from app.middleware.auth import resolve_tenant
from app.middleware.end_user_auth import resolve_end_user
from app.config import settings
from app.services import handle_chat
from app.services.care_transactions import (
    customer_transaction_stats,
    list_customer_transactions,
    parse_time_range,
    resolve_customer_or_404,
)
from app.services.care_pdf import StatementRow, render_statement_pdf

router = APIRouter()


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
    result = await handle_chat(
        db=db,
        bank=bank,
        session_id=payload.session_id,
        customer_id=customer_external_id,
        message=payload.message,
        channel=payload.channel,
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
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )
