"""
Core banking ledger + simple auth and account management, now backed by Postgres.

The app does NOT call this directly for payments. Flow: App → Gateway → Fraud → Ledger.
Run ledger:  uvicorn main:app --reload --port 8001
Run gateway: uvicorn gateway:app --reload --port 8002
"""
import asyncio
import os
import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx

_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import (
    String,
    Float,
    DateTime,
    Integer,
    ForeignKey,
    Numeric,
    select,
    func,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

security = HTTPBasic()


class Base(DeclarativeBase):
    pass


class CBUser(Base):
    __tablename__ = "cb_users"

    username: Mapped[str] = mapped_column(String, primary_key=True)
    password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")


class Account(Base):
    __tablename__ = "cb_accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, ForeignKey("cb_users.username"), index=True)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=10_000.0)
    currency: Mapped[str] = mapped_column(String, default="USD")
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    daily_limit: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    user: Mapped[CBUser] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "cb_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(String, ForeignKey("cb_accounts.account_id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String, default="USD")
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    fraud_label: Mapped[str | None] = mapped_column(String, nullable=True)
    counterparty_account_id: Mapped[str | None] = mapped_column(String, nullable=True)

    account: Mapped[Account] = relationship(back_populates="transactions")


DATABASE_URL = os.getenv(
    "CORE_BANKING_DATABASE_URL",
    os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://bankaiuser:bankaidev@localhost:5432/bankaidb",
    ),
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


app = FastAPI(title="Core Banking Ledger")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5175",
        "http://127.0.0.1:5175",
        "http://localhost:5176",
        "http://127.0.0.1:5176",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE cb_transactions ADD COLUMN IF NOT EXISTS counterparty_account_id VARCHAR(255) NULL"))


EXTERNAL_USERNAME = "__external__"

def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _get_account_or_404(session: AsyncSession, account_id: str) -> Account:
    acc = await session.get(Account, account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return acc


async def _ensure_account(session: AsyncSession, account_id: str, currency: str = "USD") -> Account:
    acc = await session.get(Account, account_id)
    if acc is not None:
        return acc
    user = await session.get(CBUser, EXTERNAL_USERNAME)
    if user is None:
        user = CBUser(
            username=EXTERNAL_USERNAME,
            password="",
            full_name="External",
            email="",
            phone="",
            country="",
        )
        session.add(user)
        await session.flush()
    acc = Account(
        account_id=account_id,
        username=EXTERNAL_USERNAME,
        balance=0.0,
        currency=currency,
        name=f"Account {account_id[:8]}",
    )
    session.add(acc)
    await session.flush()
    return acc


async def _get_current_username(
    session: AsyncSession = Depends(get_session),
    creds: HTTPBasicCredentials = Depends(security),
) -> str:
    result = await session.execute(select(CBUser).where(CBUser.username == creds.username))
    user = result.scalar_one_or_none()
    if not user or user.password != creds.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return creds.username


class CompletePayIn(BaseModel):
    transaction_id: str
    account_id: str
    amount: float
    currency: str = "USD"
    merchant_name: str | None = None
    merchant_category: str | None = None


class TransferIn(BaseModel):
    transaction_id: str
    from_account_id: str
    to_account_id: str
    amount: float
    currency: str = "USD"


class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str
    email: str
    phone: str
    country: str


class LimitUpdate(BaseModel):
    account_id: str
    daily_transfer_limit: float | None = None


class DepositIn(BaseModel):
    account_id: str
    amount: float
    currency: str = "USD"


class FraudLabelIn(BaseModel):
    fraud_label: str  # "fraud" | "not_fraud"


@app.get("/api/admin/customers")
async def admin_list_customers(session: AsyncSession = Depends(get_session)):
    """Dashboard: list all customers (users) with their accounts summary. No auth for internal dashboard."""
    result = await session.execute(
        select(CBUser).options(selectinload(CBUser.accounts))
    )
    users = result.scalars().all()
    out = []
    for user in users:
        if user.username == EXTERNAL_USERNAME:
            continue
        acc_list = user.accounts
        account_ids = [a.account_id for a in acc_list]
        total_balance = sum(float(a.balance or 0) for a in acc_list)
        last_transfer_to = None
        if account_ids:
            tx_res = await session.execute(
                select(Transaction.counterparty_account_id)
                .where(
                    Transaction.account_id.in_(account_ids),
                    Transaction.type == "transfer_debit",
                    Transaction.counterparty_account_id.isnot(None),
                )
                .order_by(Transaction.at.desc())
                .limit(1)
            )
            row = tx_res.scalars().first()
            if row is not None:
                last_transfer_to = row[0]
        out.append(
            {
                "username": user.username,
                "full_name": user.full_name or user.username,
                "email": user.email or "",
                "phone": user.phone or "",
                "country": user.country or "",
                "accounts": [
                    {
                        "account_id": a.account_id,
                        "balance": float(a.balance),
                        "currency": a.currency,
                        "name": a.name,
                        "daily_limit": float(a.daily_limit) if a.daily_limit is not None else None,
                    }
                    for a in acc_list
                ],
                "account_count": len(acc_list),
                "total_balance": round(total_balance, 2),
                "last_transfer_to": last_transfer_to,
            }
        )
    return {"customers": out}


@app.get("/api/admin/customers/{username}")
async def admin_get_customer(username: str, session: AsyncSession = Depends(get_session)):
    """Customer detail: user info, accounts, and all transactions across their accounts."""
    result = await session.execute(
        select(CBUser)
        .options(selectinload(CBUser.accounts))
        .where(CBUser.username == username)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    account_ids = [a.account_id for a in user.accounts]
    if account_ids:
        tx_result = await session.execute(
            select(Transaction)
            .where(Transaction.account_id.in_(account_ids))
            .order_by(Transaction.at.desc())
        )
        tx_list = tx_result.scalars().all()
    else:
        tx_list = []

    decisions: dict[str, dict] = {}
    if BANKAI_API_KEY and tx_list:
        ext_ids = list({t.transaction_id for t in tx_list})
        async with httpx.AsyncClient(timeout=10.0) as client:
            async def fetch_one(ext_id: str):
                try:
                    r = await client.get(
                        f"{BANKAI_API_URL}/fraud/transactions/detail-by-external-id/{ext_id}",
                        headers={"X-API-Key": BANKAI_API_KEY},
                    )
                    if r.status_code == 200:
                        d = r.json()
                        return ext_id, {"decision": d.get("decision"), "fraud_score": d.get("fraud_score")}
                except Exception:
                    pass
                return ext_id, {}

            results = await asyncio.gather(*[fetch_one(eid) for eid in ext_ids])
            for ext_id, info in results:
                if info:
                    decisions[ext_id] = info

    return {
        "username": user.username,
        "full_name": user.full_name or user.username,
        "email": user.email or "",
        "phone": user.phone or "",
        "country": user.country or "",
        "accounts": [
            {
                "account_id": a.account_id,
                "balance": float(a.balance),
                "currency": a.currency,
                "name": a.name,
                "daily_limit": float(a.daily_limit) if a.daily_limit is not None else None,
            }
            for a in user.accounts
        ],
        "transactions": [
            {
                "transaction_id": t.transaction_id,
                "account_id": t.account_id,
                "amount": float(t.amount),
                "currency": t.currency,
                "merchant": t.merchant,
                "at": t.at.isoformat().replace("+00:00", "Z") if t.at else None,
                "status": t.status,
                "type": t.type,
                "fraud_label": t.fraud_label,
                "decision": decisions.get(t.transaction_id, {}).get("decision"),
                "fraud_score": decisions.get(t.transaction_id, {}).get("fraud_score"),
            }
            for t in tx_list
        ],
    }


@app.patch("/api/admin/transactions/{transaction_id}/fraud-label")
async def admin_set_fraud_label(
    transaction_id: str,
    payload: FraudLabelIn,
    session: AsyncSession = Depends(get_session),
):
    """Mark transaction(s) as fraud or not_fraud; syncs to BankAI fraud/outcome for model retrain."""
    val = payload.fraud_label.strip().lower()
    if val not in ("fraud", "not_fraud"):
        raise HTTPException(status_code=400, detail="fraud_label must be 'fraud' or 'not_fraud'")

    result = await session.execute(
        select(Transaction).where(Transaction.transaction_id == transaction_id)
    )
    txs = result.scalars().all()
    if not txs:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for t in txs:
        t.fraud_label = val
    await session.commit()

    if BANKAI_API_KEY:
        classification = "CONFIRMED_FRAUD" if val == "fraud" else "CONFIRMED_LEGIT"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                r = await client.get(
                    f"{BANKAI_API_URL}/fraud/transactions/detail-by-external-id/{transaction_id}",
                    headers={"X-API-Key": BANKAI_API_KEY},
                )
                if r.status_code == 200:
                    data = r.json()
                    bankai_tx_id = data.get("transaction_id")
                    if bankai_tx_id:
                        await client.post(
                            f"{BANKAI_API_URL}/fraud/outcome",
                            json={
                                "transaction_id": bankai_tx_id,
                                "classification": classification,
                                "source": "CORE_BANKING",
                                "notes": None,
                            },
                            headers={"X-API-Key": BANKAI_API_KEY},
                        )
            except Exception:
                pass

    return {
        "ok": True,
        "transaction_id": transaction_id,
        "fraud_label": val,
        "updated_rows": len(txs),
    }


@app.post("/api/auth/register")
async def register(payload: RegisterIn, session: AsyncSession = Depends(get_session)):
    existing = await session.get(CBUser, payload.username)
    if existing is not None:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = CBUser(
        username=payload.username,
        password=payload.password,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        country=payload.country,
    )
    session.add(user)

    acc_id = f"acc-{uuid.uuid4().hex[:8]}"
    acc = Account(
        account_id=acc_id,
        username=payload.username,
        balance=10_000.0,
        currency="USD",
        name=f"{payload.full_name}'s account",
    )
    session.add(acc)
    await session.commit()

    return {"username": payload.username, "account_id": acc_id}


@app.post("/api/auth/login")
async def login(
    username: str = Depends(_get_current_username),
    session: AsyncSession = Depends(get_session),
):
    # For demo: HTTP Basic auth; client stores username/password.
    # Additionally, mint a signed token for BankAI Care so the care backend can
    # derive the user identity server-side (non-spoofable).
    result = await session.execute(select(Account).where(Account.username == username).order_by(Account.account_id.asc()))
    acc = result.scalars().first()
    account_id = acc.account_id if acc else None

    now = int(datetime.now(timezone.utc).timestamp())
    exp = now + 60 * 60 * 24  # 24h
    bank_key_hash = hashlib.sha256((BANKAI_API_KEY or "").encode("utf-8")).hexdigest()
    token = _jwt_hs256(
        {
            "iss": "core-banking",
            "aud": "bankai-care",
            "sub": username,
            "customer_external_id": account_id,
            "bank_key_hash": bank_key_hash,
            "iat": now,
            "exp": exp,
        },
        CARE_JWT_SECRET,
    )
    return {"username": username, "account_id": account_id, "care_token": token}


@app.get("/api/me/accounts")
async def me_accounts(
    username: str = Depends(_get_current_username),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Account).where(Account.username == username))
    accounts = result.scalars().all()
    return {
        "accounts": [
            {
                "account_id": a.account_id,
                "balance": float(a.balance),
                "currency": a.currency,
                "name": a.name,
                "daily_limit": float(a.daily_limit) if a.daily_limit is not None else None,
            }
            for a in accounts
        ]
    }


@app.get("/api/balance")
async def get_balance(account_id: str, session: AsyncSession = Depends(get_session)):
    acc = await _get_account_or_404(session, account_id)
    return {
        "account_id": acc.account_id,
        "balance": float(acc.balance),
        "currency": acc.currency,
    }


@app.get("/api/transactions")
async def list_transactions(
    account_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    await _get_account_or_404(session, account_id)
    result = await session.execute(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.at.desc())
        .limit(limit)
    )
    mine = result.scalars().all()
    return {
        "account_id": account_id,
        "transactions": [
            {
                "transaction_id": t.transaction_id,
                "account_id": t.account_id,
                "amount": float(t.amount),
                "currency": t.currency,
                "merchant": t.merchant,
                "at": t.at.isoformat().replace("+00:00", "Z") if t.at else None,
                "status": t.status,
                "type": t.type,
                "fraud_label": t.fraud_label,
            }
            for t in mine
        ],
    }


@app.post("/api/pay/complete")
async def complete_payment(
    payload: CompletePayIn,
    session: AsyncSession = Depends(get_session),
):
    """Ledger only: debit and record. Called by gateway after fraud approves."""
    acc = await _get_account_or_404(session, payload.account_id)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if float(acc.balance) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    acc.balance = float(acc.balance) - payload.amount
    ts = datetime.now(timezone.utc)
    tx = Transaction(
        transaction_id=payload.transaction_id,
        account_id=payload.account_id,
        amount=-payload.amount,
        currency=payload.currency,
        merchant=payload.merchant_name or payload.merchant_category or "Merchant",
        at=ts,
        status="completed",
        type="payment",
        fraud_label=None,
    )
    session.add(tx)
    await session.commit()
    return {
        "ok": True,
        "transaction_id": payload.transaction_id,
        "balance_after": float(acc.balance),
    }


@app.post("/api/transfers/complete")
async def complete_transfer(
    payload: TransferIn,
    session: AsyncSession = Depends(get_session),
):
    """
    Ledger-only transfer: debit from_account, credit to_account (if in DB), else debit-only.
    Called by gateway after fraud approves.
    """
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    from_acc = await _get_account_or_404(session, payload.from_account_id)
    to_acc = await session.get(Account, payload.to_account_id)
    if float(from_acc.balance) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    ts = datetime.now(timezone.utc)
    tx_id = payload.transaction_id
    from_acc.balance = float(from_acc.balance) - payload.amount

    debit = Transaction(
        transaction_id=tx_id,
        account_id=payload.from_account_id,
        amount=-payload.amount,
        currency=payload.currency,
        merchant=f"Transfer to {payload.to_account_id}",
        at=ts,
        status="completed",
        type="transfer_debit",
        fraud_label=None,
        counterparty_account_id=payload.to_account_id,
    )
    session.add(debit)

    if to_acc is not None:
        to_acc.balance = float(to_acc.balance) + payload.amount
        credit = Transaction(
            transaction_id=tx_id,
            account_id=payload.to_account_id,
            amount=payload.amount,
            currency=payload.currency,
            merchant=f"Transfer from {payload.from_account_id}",
            at=ts,
            status="completed",
            type="transfer_credit",
            fraud_label=None,
            counterparty_account_id=None,
        )
        session.add(credit)
        await session.commit()
        return {
            "ok": True,
            "transaction_id": tx_id,
            "from_balance_after": float(from_acc.balance),
            "to_balance_after": float(to_acc.balance),
        }

    await session.commit()
    return {
        "ok": True,
        "transaction_id": tx_id,
        "from_balance_after": float(from_acc.balance),
        "to_balance_after": None,
    }


@app.patch("/api/account-settings/limits")
async def update_limits(
    payload: LimitUpdate,
    username: str = Depends(_get_current_username),
    session: AsyncSession = Depends(get_session),
):
    acc = await session.get(Account, payload.account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc.username != username:
        raise HTTPException(status_code=403, detail="Not your account")
    acc.daily_limit = payload.daily_transfer_limit
    await session.commit()
    return {"account_id": acc.account_id, "daily_limit": float(acc.daily_limit) if acc.daily_limit is not None else None}


@app.post("/api/deposit")
async def deposit(
    payload: DepositIn,
    username: str = Depends(_get_current_username),
    session: AsyncSession = Depends(get_session),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    acc = await session.get(Account, payload.account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if acc.username != username:
        raise HTTPException(status_code=403, detail="Not your account")

    acc.balance = float(acc.balance) + payload.amount
    ts = datetime.now(timezone.utc)
    tx_id = f"dep-{uuid.uuid4().hex[:10]}"
    tx = Transaction(
        transaction_id=tx_id,
        account_id=payload.account_id,
        amount=payload.amount,
        currency=payload.currency,
        merchant="Deposit",
        at=ts,
        status="completed",
        type="deposit",
        fraud_label=None,
    )
    session.add(tx)
    await session.commit()
    return {
        "ok": True,
        "transaction_id": tx_id,
        "balance_after": float(acc.balance),
    }


@app.get("/api/health")
async def health():
    return {"ok": True}


BANKAI_API_URL = os.getenv("BANKAI_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
BANKAI_API_KEY = os.getenv("BANKAI_API_KEY", "")
CARE_JWT_SECRET = os.getenv("CARE_JWT_SECRET", "dev-care-secret-change-me")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _jwt_hs256(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    p = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    msg = f"{h}.{p}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    s = _b64url(sig)
    return f"{h}.{p}.{s}"


@app.get("/api/admin/fraud/transactions")
async def admin_fraud_transactions(limit: int = 200, account_id: str | None = None):
    """Proxy to BankAI: list scored transactions (transaction_id, account_id, amount, channel, status, created_at, decision)."""
    if not BANKAI_API_KEY:
        raise HTTPException(status_code=503, detail="BANKAI_API_KEY not set. Add it to core-banking/backend/.env or export it.")
    params = {"limit": limit}
    if account_id:
        params["account_id"] = account_id
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{BANKAI_API_URL}/fraud/transactions",
                params=params,
                headers={"X-API-Key": BANKAI_API_KEY},
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="BankAI backend unreachable. Start backend on port 8000.")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text or "Fraud API error")
    return r.json()


@app.get("/api/admin/fraud/transactions/{transaction_id}/detail")
async def admin_fraud_transaction_detail(transaction_id: str):
    """Proxy to BankAI: full detail for one transaction (decision, reasons, scores)."""
    if not BANKAI_API_KEY:
        raise HTTPException(status_code=503, detail="BANKAI_API_KEY not configured")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{BANKAI_API_URL}/fraud/transactions/{transaction_id}/detail",
                headers={"X-API-Key": BANKAI_API_KEY},
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="BankAI backend unreachable. Start backend on port 8000.")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text or "Fraud API error")
    return r.json()
