"""
Transaction fingerprinting: unique signature per transaction pattern.
Detects duplicate fraud, bots, card testing, repeated attack patterns.
"""
import hashlib
from typing import Optional


def _amount_bucket(amount: float) -> str:
    if amount < 10:
        return "0_10"
    if amount < 50:
        return "10_50"
    if amount < 100:
        return "50_100"
    if amount < 500:
        return "100_500"
    if amount < 1000:
        return "500_1k"
    if amount < 5000:
        return "1k_5k"
    if amount < 20000:
        return "5k_20k"
    return "20k_plus"


def compute_transaction_fingerprint(
    account_id: str,
    device_id: Optional[str],
    ip_address: Optional[str],
    merchant_id: Optional[str],
    amount: float,
    hour_of_day: int,
) -> str:
    """
    Deterministic fingerprint for a transaction pattern.
    Same pattern (same device, IP, merchant, amount bucket, hour) yields same ID.
    """
    parts = [
        str(account_id or ""),
        str(device_id or ""),
        str(ip_address or ""),
        str(merchant_id or ""),
        _amount_bucket(amount),
        str(hour_of_day),
    ]
    payload = "|".join(parts)
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return h[:16]


async def get_fingerprint_features(
    db,
    tenant_id: str,
    fingerprint_id: str,
    tx_timestamp,
) -> dict:
    """
    Returns fingerprint_repeat_count (7d), fingerprint_repeat_count_30d,
    fingerprint_fraud_rate, fingerprint_velocity_1h for the feature vector.
    """
    from datetime import timedelta
    from sqlalchemy import and_, func, select
    from app.models import TransactionFingerprint, FingerprintStats, FraudOutcome

    seven_days_ago = tx_timestamp - timedelta(days=7)
    thirty_days_ago = tx_timestamp - timedelta(days=30)
    one_hour_ago = tx_timestamp - timedelta(hours=1)

    base = and_(
        TransactionFingerprint.tenant_id == tenant_id,
        TransactionFingerprint.fingerprint_id == fingerprint_id,
        TransactionFingerprint.created_at < tx_timestamp,
    )

    repeat_7 = (await db.execute(
        select(func.count()).select_from(TransactionFingerprint).where(
            and_(base, TransactionFingerprint.created_at >= seven_days_ago)
        )
    )).scalar() or 0
    repeat_30 = (await db.execute(
        select(func.count()).select_from(TransactionFingerprint).where(
            and_(base, TransactionFingerprint.created_at >= thirty_days_ago)
        )
    )).scalar() or 0
    velocity_1h = (await db.execute(
        select(func.count()).select_from(TransactionFingerprint).where(
            and_(base, TransactionFingerprint.created_at >= one_hour_ago)
        )
    )).scalar() or 0

    stats = (await db.execute(
        select(FingerprintStats.fraud_rate, FingerprintStats.total_transactions).where(
            and_(
                FingerprintStats.tenant_id == tenant_id,
                FingerprintStats.fingerprint_id == fingerprint_id,
            )
        )
    )).first()
    fraud_rate = float(stats[0]) if stats and stats[1] and stats[1] > 0 else 0.0

    return {
        "fingerprint_repeat_count": float(repeat_7),
        "fingerprint_repeat_count_30d": float(repeat_30),
        "fingerprint_fraud_rate": fraud_rate,
        "fingerprint_velocity_1h": float(velocity_1h),
    }


async def store_fingerprint(
    db,
    tenant_id,
    transaction_id,
    fingerprint_id: str,
    device_id: Optional[str],
    ip_address_hash: Optional[str],
    merchant_id: Optional[str],
):
    """Record transaction fingerprint and bump FingerprintStats. Call after scoring."""
    from sqlalchemy import select, and_
    from app.models import TransactionFingerprint, FingerprintStats
    from datetime import datetime

    db.add(TransactionFingerprint(
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        fingerprint_id=fingerprint_id,
        device_id=device_id,
        ip_address_hash=ip_address_hash,
        merchant_id=merchant_id,
    ))
    await db.flush()

    now = datetime.utcnow()
    row = (await db.execute(
        select(FingerprintStats).where(
            and_(
                FingerprintStats.tenant_id == tenant_id,
                FingerprintStats.fingerprint_id == fingerprint_id,
            )
        )
    )).scalar_one_or_none()
    if row:
        row.total_transactions += 1
        row.last_seen = now
    else:
        db.add(FingerprintStats(
            tenant_id=tenant_id,
            fingerprint_id=fingerprint_id,
            total_transactions=1,
            last_seen=now,
        ))
    await db.flush()
