"""
Core banking ledger only: accounts, balance, complete payment (no fraud).
Fraud sits in front: Payment gateway calls Fraud first, then calls this to complete.
Run: uvicorn ledger:app --reload --port 8001
"""
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Core Banking Ledger")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5175", "http://127.0.0.1:5175", "http://localhost:5176", "http://127.0.0.1:5176"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

accounts: dict[str, dict] = {}
transactions: list[dict] = []


def _ensure_account(account_id: str) -> dict:
    if account_id not in accounts:
        accounts[account_id] = {
            "account_id": account_id,
            "balance": 10_000.0,
            "currency": "USD",
            "name": f"Account {account_id[:8]}",
        }
    return accounts[account_id]


class CompletePayIn(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    currency: str = "USD"
    merchant_name: str | None = None
    merchant_category: str | None = None


@app.get("/api/balance")
def get_balance(account_id: str):
    acc = _ensure_account(account_id)
    return {"account_id": account_id, "balance": acc["balance"], "currency": acc["currency"]}


@app.get("/api/transactions")
def list_transactions(account_id: str, limit: int = 50):
    _ensure_account(account_id)
    mine = [t for t in transactions if t.get("account_id") == account_id][-limit:][::-1]
    return {"account_id": account_id, "transactions": mine}


@app.post("/api/pay/complete")
def complete_payment(payload: CompletePayIn):
    """Ledger only: debit and record. Called by gateway after fraud approves."""
    acc = _ensure_account(payload.account_id)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if payload.amount > acc["balance"]:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    acc["balance"] = round(acc["balance"] - payload.amount, 2)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    transactions.append({
        "transaction_id": payload.transaction_id,
        "account_id": payload.account_id,
        "amount": -payload.amount,
        "currency": payload.currency,
        "merchant": payload.merchant_name or payload.merchant_category or "Merchant",
        "at": ts,
        "status": "completed",
    })
    return {"ok": True, "transaction_id": payload.transaction_id, "balance_after": acc["balance"]}


@app.get("/api/health")
def health():
    return {"ok": True}
