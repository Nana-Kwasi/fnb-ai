from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, Customer

FEATURE_NAMES = [
    "amount",
    "txn_count_1h",
    "total_amount_1h",
    "txn_count_24h",
    "total_amount_24h",
    "txn_count_7d",
    "total_amount_7d",
    "amount_vs_avg_ratio",
    "is_new_device",
    "hour_of_day",
    "is_weekend",
    "days_since_last_txn",
    "customer_risk_score",
    "merchant_cat_risk",
]


async def get_velocity(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    before_ts: datetime,
) -> dict:
    base = and_(
        Transaction.tenant_id == tenant_id,
        Transaction.customer_id == customer_id,
        Transaction.tx_timestamp < before_ts,
    )
    one_h = before_ts - timedelta(hours=1)
    one_d = before_ts - timedelta(days=1)
    seven_d = before_ts - timedelta(days=7)

    txn_1h = await db.execute(
        select(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= one_h)
        )
    )
    txn_24h = await db.execute(
        select(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= one_d)
        )
    )
    txn_7d = await db.execute(
        select(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= seven_d)
        )
    )

    r1 = txn_1h.one()
    r24 = txn_24h.one()
    r7 = txn_7d.one()

    return {
        "txn_count_1h": r1[0] or 0,
        "total_amount_1h": float(r1[1] or 0),
        "txn_count_24h": r24[0] or 0,
        "total_amount_24h": float(r24[1] or 0),
        "txn_count_7d": r7[0] or 0,
        "total_amount_7d": float(r7[1] or 0),
    }


async def get_last_txn_and_device(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
) -> tuple[datetime | None, int]:
    base = and_(
        Transaction.tenant_id == tenant_id,
        Transaction.customer_id == customer_id,
    )
    last = await db.execute(
        select(Transaction.tx_timestamp, Transaction.device_id).where(base).order_by(Transaction.tx_timestamp.desc()).limit(100)
    )
    rows = last.all()
    if not rows:
        return None, 0
    last_ts = rows[0][0]
    devices = {r[1] for r in rows if r[1]}
    is_new_device = 1.0 if (device_id and device_id not in devices) else 0.0
    return last_ts, is_new_device


async def get_last_location(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> str | None:
    result = await db.execute(
        select(Transaction.location_country)
        .where(
            and_(
                Transaction.tenant_id == tenant_id,
                Transaction.customer_id == customer_id,
                Transaction.location_country.isnot(None),
            )
        )
        .order_by(Transaction.tx_timestamp.desc())
        .limit(1)
    )
    row = result.one_or_none()
    return row[0] if row and row[0] else None


async def build_feature_vector(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    amount: float,
    currency: str,
    merchant_category: str | None,
    device_id: str | None,
    channel: str | None,
    tx_timestamp: datetime,
    customer_risk_score: float,
    location_country: str | None = None,
) -> dict:
    velocity = await get_velocity(db, tenant_id, customer_id, tx_timestamp)
    last_ts, is_new_device = await get_last_txn_and_device(db, tenant_id, customer_id, device_id)
    last_country = await get_last_location(db, tenant_id, customer_id)

    avg_24h = velocity["total_amount_24h"] / (velocity["txn_count_24h"] or 1)
    amount_vs_avg_ratio = amount / (avg_24h or 1.0)
    if amount_vs_avg_ratio > 10:
        amount_vs_avg_ratio = 10.0

    days_since = (tx_timestamp - last_ts).total_seconds() / 86400.0 if last_ts else 999.0
    if days_since > 365:
        days_since = 365.0

    hour = tx_timestamp.hour
    is_weekend = 1.0 if tx_timestamp.weekday() >= 5 else 0.0
    merchant_cat_risk = 0.2 if merchant_category in ("GAMBLING", "CRYPTO", "INTERNATIONAL") else 0.0

    is_new_location = 0.0
    if location_country and last_country:
        is_new_location = 1.0 if (location_country.upper() != last_country.upper()) else 0.0
    elif location_country and not last_country:
        is_new_location = 0.0
    elif not location_country and last_country:
        is_new_location = 0.5

    return {
        "amount": amount,
        "txn_count_1h": float(velocity["txn_count_1h"]),
        "total_amount_1h": velocity["total_amount_1h"],
        "txn_count_24h": float(velocity["txn_count_24h"]),
        "total_amount_24h": velocity["total_amount_24h"],
        "txn_count_7d": float(velocity["txn_count_7d"]),
        "total_amount_7d": velocity["total_amount_7d"],
        "amount_vs_avg_ratio": amount_vs_avg_ratio,
        "is_new_device": is_new_device,
        "is_new_location": is_new_location,
        "hour_of_day": float(hour),
        "is_weekend": is_weekend,
        "days_since_last_txn": days_since,
        "customer_risk_score": customer_risk_score,
        "merchant_cat_risk": merchant_cat_risk,
        "location_country": location_country,
    }
