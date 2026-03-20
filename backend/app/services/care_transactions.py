from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, FraudScore, TenantBank, Transaction


Decision = Literal["APPROVE", "LIMITED_APPROVAL", "REQUEST_OTP", "BLOCK"]


DECISION_NORM: dict[str, Decision] = {
    "REQUEST_OT": "REQUEST_OTP",
    "LIMITED_AP": "LIMITED_APPROVAL",
    # Fraud engine may emit SOFT_DECLINE; stored truncated to 10 chars.
    # Treat it as OTP-required for customer-facing analytics.
    "SOFT_DECLI": "REQUEST_OTP",
}


def normalize_decision(value: str | None) -> Decision | None:
    if not value:
        return None
    v = str(value).strip().upper()
    if not v:
        return None
    return DECISION_NORM.get(v, v)  # type: ignore[return-value]


@dataclass(frozen=True)
class TimeRange:
    start: datetime | None = None
    end: datetime | None = None


def parse_time_range(
    *,
    time_range_key: str | None,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> TimeRange:
    tz = ZoneInfo(tz_name or "Africa/Accra")
    n = (now or datetime.now(timezone.utc)).astimezone(tz)
    r = (time_range_key or "").strip().lower()
    if r in ("today", "todays", "day"):
        start_local = datetime(n.year, n.month, n.day, tzinfo=tz)
        return TimeRange(start=start_local.astimezone(timezone.utc), end=n.astimezone(timezone.utc))
    if r in ("yesterday",):
        start_local = datetime(n.year, n.month, n.day, tzinfo=tz) - timedelta(days=1)
        end_local = datetime(n.year, n.month, n.day, tzinfo=tz)
        return TimeRange(start=start_local.astimezone(timezone.utc), end=end_local.astimezone(timezone.utc))
    if r in ("this_week", "week", "last_7d", "7d"):
        return TimeRange(start=(n - timedelta(days=7)).astimezone(timezone.utc), end=n.astimezone(timezone.utc))
    if r.startswith("last_") and r.endswith("d"):
        # last_3d, last_14d, etc
        try:
            days = int(r.removeprefix("last_").removesuffix("d"))
            days = max(1, min(days, 365))
            return TimeRange(start=(n - timedelta(days=days)).astimezone(timezone.utc), end=n.astimezone(timezone.utc))
        except ValueError:
            return TimeRange(start=(n - timedelta(days=7)).astimezone(timezone.utc), end=n.astimezone(timezone.utc))
    if r in ("since_monday", "since monday"):
        # Start at most recent Monday 00:00 in bank timezone
        start_local = datetime(n.year, n.month, n.day, tzinfo=tz)
        start_local = start_local - timedelta(days=start_local.weekday())
        return TimeRange(start=start_local.astimezone(timezone.utc), end=n.astimezone(timezone.utc))
    if r in ("this_month", "month", "last_30d", "30d"):
        return TimeRange(start=(n - timedelta(days=30)).astimezone(timezone.utc), end=n.astimezone(timezone.utc))
    if r in ("all", "", "lifetime"):
        return TimeRange(start=None, end=n.astimezone(timezone.utc))
    if r in ("recent",):
        return TimeRange(start=None, end=n.astimezone(timezone.utc))
    # Unknown → treat as last 7 days to avoid huge scans.
    return TimeRange(start=(n - timedelta(days=7)).astimezone(timezone.utc), end=n.astimezone(timezone.utc))


async def resolve_customer_or_404(
    db: AsyncSession,
    bank: TenantBank,
    external_customer_id: str,
) -> Customer:
    result = await db.execute(
        select(Customer).where(
            Customer.tenant_id == bank.id,
            Customer.external_id == external_customer_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


async def list_customer_transactions(
    *,
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer,
    time_range: TimeRange,
    limit: int = 50,
    offset: int = 0,
    decision_in: list[Decision] | None = None,
) -> list[dict]:
    stmt = (
        select(
            Transaction.external_tx_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.merchant_name,
            Transaction.merchant_category,
            Transaction.channel,
            Transaction.status,
            Transaction.tx_timestamp,
            FraudScore.decision,
            FraudScore.ensemble_score,
        )
        .outerjoin(FraudScore, FraudScore.transaction_id == Transaction.id)
        .where(
            Transaction.tenant_id == bank.id,
            Transaction.customer_id == customer.id,
        )
        .order_by(Transaction.tx_timestamp.desc())
        .limit(max(1, min(int(limit), 200)))
    )
    if offset:
        stmt = stmt.offset(max(0, int(offset)))
    if time_range.start is not None:
        stmt = stmt.where(Transaction.tx_timestamp >= time_range.start)
    if time_range.end is not None:
        stmt = stmt.where(Transaction.tx_timestamp <= time_range.end)

    rows = (await db.execute(stmt)).all()
    out: list[dict] = []
    for ext_tx_id, amount, currency, merchant_name, merchant_category, channel, status, ts, decision, ensemble_score in rows:
        dec = normalize_decision(decision)
        if decision_in and dec not in decision_in:
            continue
        out.append(
            {
                "transaction_id": ext_tx_id,
                "amount": float(amount),
                "currency": currency,
                "merchant": merchant_name,
                "merchant_category": merchant_category,
                "channel": channel,
                "status": status,
                "timestamp": ts.isoformat() if ts else None,
                "model_decision": dec,
                "fraud_score": float(ensemble_score) if ensemble_score is not None else None,
            }
        )
    return out


async def customer_transaction_stats(
    *,
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer,
    time_range: TimeRange,
) -> dict:
    # Total transactions (scored or not)
    base = select(func.count(1)).select_from(Transaction).where(  # pylint: disable=not-callable
        Transaction.tenant_id == bank.id,
        Transaction.customer_id == customer.id,
    )
    if time_range.start is not None:
        base = base.where(Transaction.tx_timestamp >= time_range.start)
    if time_range.end is not None:
        base = base.where(Transaction.tx_timestamp <= time_range.end)
    total = int((await db.execute(base)).scalar() or 0)

    # Scored decisions only
    stmt = (
        select(FraudScore.decision, func.count(1))  # pylint: disable=not-callable
        .select_from(Transaction)
        .join(FraudScore, FraudScore.transaction_id == Transaction.id)
        .where(
            Transaction.tenant_id == bank.id,
            Transaction.customer_id == customer.id,
        )
        .group_by(FraudScore.decision)
    )
    if time_range.start is not None:
        stmt = stmt.where(Transaction.tx_timestamp >= time_range.start)
    if time_range.end is not None:
        stmt = stmt.where(Transaction.tx_timestamp <= time_range.end)

    rows = (await db.execute(stmt)).all()
    by_decision: dict[str, int] = {}
    scored_total = 0
    for decision, cnt in rows:
        dec = normalize_decision(decision) or "UNKNOWN"
        c = int(cnt or 0)
        scored_total += c
        by_decision[str(dec)] = by_decision.get(str(dec), 0) + c

    fraud_like = by_decision.get("BLOCK", 0) + by_decision.get("REQUEST_OTP", 0)

    return {
        "total_transactions": total,
        "scored_transactions": scored_total,
        "by_decision": by_decision,
        "fraud_like_transactions": fraud_like,
    }

