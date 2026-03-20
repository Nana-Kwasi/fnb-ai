"""
Payment gateway (BFF): App → Gateway → Fraud (first) → Core banking (only on approve).
App talks only to this; fraud sits in between app and core banking.
Run: uvicorn gateway:app --reload --port 8002
"""
import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Payment Gateway (App → Fraud → Core banking)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175", "http://127.0.0.1:5175", "http://localhost:5176", "http://127.0.0.1:5176"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BANKAI_URL = os.environ.get("BANKAI_API_URL", "http://127.0.0.1:8000/api/v1")
BANKAI_API_KEY = os.environ.get("BANKAI_API_KEY", "")
CORE_BANKING_URL = os.environ.get("CORE_BANKING_URL", "http://127.0.0.1:8001")


class PayIn(BaseModel):
    account_id: str
    amount: float
    currency: str = "USD"
    merchant_name: str | None = None
    merchant_category: str | None = None
    device_id: str | None = None
    ip_address: str | None = None
    location: str | None = None


class PayOut(BaseModel):
    success: bool
    transaction_id: str | None = None
    decision: str | None = None
    fraud_score: float | None = None
    reasons: list[str] | None = None
    message: str
    balance_after: float | None = None


class TransferIn(BaseModel):
    from_account_id: str
    to_account_id: str
    amount: float
    currency: str = "USD"
    comment: str | None = None
    device_id: str | None = None
    ip_address: str | None = None
    location: str | None = None
    channel: str | None = None


class TransferOut(BaseModel):
    success: bool
    transaction_id: str | None = None
    decision: str | None = None
    fraud_score: float | None = None
    reasons: list[str] | None = None
    message: str


@app.get("/api/balance")
async def get_balance(account_id: str):
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{CORE_BANKING_URL}/api/balance", params={"account_id": account_id})
        r.raise_for_status()
        return r.json()


@app.get("/api/transactions")
async def list_transactions(account_id: str, limit: int = 50):
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(f"{CORE_BANKING_URL}/api/transactions", params={"account_id": account_id, "limit": limit})
        r.raise_for_status()
        return r.json()


@app.post("/api/pay", response_model=PayOut)
async def pay(payload: PayIn):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    tx_id = f"cb-{uuid.uuid4().hex[:12]}"
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if not BANKAI_API_KEY:
        return PayOut(
            success=False,
            transaction_id=tx_id,
            message="BANKAI_API_KEY not set; set env and restart.",
        )

    body = {
        "transaction_id": tx_id,
        "account_id": payload.account_id,
        "amount": payload.amount,
        "currency": payload.currency,
        "merchant_category": payload.merchant_category,
        "location": payload.location,
        "device_id": payload.device_id,
        "ip_address": payload.ip_address,
        "timestamp": ts,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{BANKAI_URL}/fraud/score",
                json=body,
                headers={"X-API-Key": BANKAI_API_KEY, "Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return PayOut(
            success=False,
            transaction_id=tx_id,
            message=f"Fraud API error: {e.response.status_code}",
        )
    except Exception as e:
        return PayOut(
            success=False,
            transaction_id=tx_id,
            message=f"Fraud API unreachable: {e!s}",
        )

    decision = data.get("decision", "")
    reasons = data.get("reasons") or []
    fraud_score = data.get("fraud_score")

    # Map decisions to gateway behaviour:
    # - BLOCK / DECLINE: hard stop.
    # - REQUEST_OTP / SOFT_DECLINE: require extra auth (app shows OTP/challenge screen).
    # - LIMITED_APPROVAL / APPROVE / others: allowed but app can display \"approved with limits\".
    if decision in ("BLOCK", "DECLINE"):
        return PayOut(
            success=False,
            transaction_id=tx_id,
            decision=decision,
            fraud_score=fraud_score,
            reasons=reasons,
            message="Transaction blocked by fraud check. Payment did not reach core banking.",
        )
    if decision in ("REQUEST_OTP", "SOFT_DECLINE"):
        return PayOut(
            success=False,
            transaction_id=tx_id,
            decision=decision,
            fraud_score=fraud_score,
            reasons=reasons,
            message="Additional authentication required. Payment did not reach core banking.",
        )

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            f"{CORE_BANKING_URL}/api/pay/complete",
            json={
                "transaction_id": tx_id,
                "account_id": payload.account_id,
                "amount": payload.amount,
                "currency": payload.currency,
                "merchant_name": payload.merchant_name,
                "merchant_category": payload.merchant_category,
            },
        )
        if r.status_code != 200:
            return PayOut(
                success=False,
                transaction_id=tx_id,
                message=f"Core banking error: {r.status_code}",
            )
        out = r.json()

    msg = "Payment approved by fraud check and completed in core banking."
    if decision == "LIMITED_APPROVAL":
        msg = "Payment approved with limits by fraud policy and completed in core banking."

    return PayOut(
        success=True,
        transaction_id=tx_id,
        decision=decision,
        fraud_score=fraud_score,
        reasons=reasons,
        message=msg,
        balance_after=out.get("balance_after"),
    )


def _client_ip(request: Request, payload_ip: str | None) -> str | None:
    if payload_ip:
        return payload_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@app.post("/api/transfers", response_model=TransferOut)
async def transfer(payload: TransferIn, request: Request):
    """
    Transfer between two accounts.
    Flow: Gateway → Fraud (score) → Ledger /api/transfers/complete on approve/limited.
    Sends device_id, location, ip_address to fraud model for real payment simulation.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(status_code=400, detail="Cannot transfer to the same account")

    tx_id = f"cb-tr-{uuid.uuid4().hex[:10]}"
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ip = _client_ip(request, payload.ip_address)

    if not BANKAI_API_KEY:
        return TransferOut(
            success=False,
            transaction_id=tx_id,
            message="BANKAI_API_KEY not set; set env and restart.",
        )

    body = {
        "transaction_id": tx_id,
        "account_id": payload.from_account_id,
        "amount": payload.amount,
        "currency": payload.currency,
        "merchant_category": "TRANSFER",
        "location": payload.location,
        "device_id": payload.device_id,
        "ip_address": ip,
        "channel": payload.channel or "MOBILE_APP",
        "timestamp": ts,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{BANKAI_URL}/fraud/score",
                json=body,
                headers={"X-API-Key": BANKAI_API_KEY, "Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        return TransferOut(
            success=False,
            transaction_id=tx_id,
            message=f"Fraud API error: {e.response.status_code}",
        )
    except Exception as e:
        return TransferOut(
            success=False,
            transaction_id=tx_id,
            message=f"Fraud API unreachable: {e!s}",
        )

    decision = data.get("decision", "")
    reasons = data.get("reasons") or []
    fraud_score = data.get("fraud_score")

    if decision in ("BLOCK", "DECLINE"):
        return TransferOut(
            success=False,
            transaction_id=tx_id,
            decision=decision,
            fraud_score=fraud_score,
            reasons=reasons,
            message="Transfer blocked by fraud check. Ledger was not updated.",
        )
    if decision in ("REQUEST_OTP", "SOFT_DECLINE"):
        return TransferOut(
            success=False,
            transaction_id=tx_id,
            decision=decision,
            fraud_score=fraud_score,
            reasons=reasons,
            message="Additional authentication required before transfer can proceed.",
        )

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            f"{CORE_BANKING_URL}/api/transfers/complete",
            json={
                "transaction_id": tx_id,
                "from_account_id": payload.from_account_id,
                "to_account_id": payload.to_account_id,
                "amount": payload.amount,
                "currency": payload.currency,
            },
        )
        if r.status_code != 200:
            return TransferOut(
                success=False,
                transaction_id=tx_id,
                message=f"Core banking error: {r.status_code}",
            )

    msg = "Transfer approved by fraud check and completed in core banking."
    if decision == "LIMITED_APPROVAL":
        msg = "Transfer approved with limits by fraud policy and completed in core banking."

    return TransferOut(
        success=True,
        transaction_id=tx_id,
        decision=decision,
        fraud_score=fraud_score,
        reasons=reasons,
        message=msg,
    )


@app.get("/api/health")
def health():
    return {"ok": True, "bankai_configured": bool(BANKAI_API_KEY), "core_banking": CORE_BANKING_URL}
