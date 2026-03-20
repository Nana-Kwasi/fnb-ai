from datetime import datetime, timedelta
from typing import Any, Dict
import time

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession


def _count(*args: Any, **kwargs: Any) -> Any:
    # Pylint mis-detects `func.count` as not callable.
    return func.count(*args, **kwargs)  # pylint: disable=not-callable

from app.models import Transaction, Customer, FraudOutcome
from app.services.fraud_ring import get_network_risk_features
from app.services.fraud_graph_engine import get_graph_features_for_scoring
from app.services.transaction_fingerprint import (
    compute_transaction_fingerprint,
    get_fingerprint_features,
)

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
    # Network / entity risk
    "devices_seen_last_30d_for_customer",
    "customers_seen_last_7d_for_device",
    "ips_seen_last_30d_for_customer",
    "device_reuse_ratio",
    "email_reuse_ratio",
    "device_fraud_ratio_90d",
    "ip_fraud_ratio_90d",
    "card_fraud_ratio_90d",
    # Merchant risk
    "merchant_fraud_rate_90d",
    "merchant_volume_7d",
    "merchant_country_mismatch",
    # Fraud ring / network
    "accounts_seen_for_device_7d",
    "accounts_seen_for_device_30d",
    "device_risk_score",
    "accounts_seen_for_ip_7d",
    "accounts_seen_for_ip_30d",
    "ip_risk_score",
    "merchant_fraud_rate_30d",
    "merchant_transaction_volume_7d",
    "merchant_risk_score",
    "device_shared_account_count",
    "ip_shared_account_count",
    "shared_email_accounts",
    "shared_phone_accounts",
    "fraud_cluster_size",
    # Transaction fingerprint (repeat/bot/card-test detection)
    "fingerprint_repeat_count",
    "fingerprint_repeat_count_30d",
    "fingerprint_fraud_rate",
    "fingerprint_velocity_1h",
    "shortest_path_to_known_fraud",
    "graph_risk_score",
]

CACHE_TTL_SECONDS = 300

# Cache maps: key -> (value, expires_at_epoch_seconds)
_DEVICE_CACHE: Dict[tuple, tuple[Dict[str, float], float]] = {}
_MERCHANT_CACHE: Dict[tuple, tuple[Dict[str, float], float]] = {}

NETWORK_FEATURE_KEYS = {
    "devices_seen_last_30d_for_customer",
    "customers_seen_last_7d_for_device",
    "ips_seen_last_30d_for_customer",
    "device_reuse_ratio",
    "email_reuse_ratio",
    "device_fraud_ratio_90d",
    "ip_fraud_ratio_90d",
    "card_fraud_ratio_90d",
    "accounts_seen_for_device_7d",
    "accounts_seen_for_device_30d",
    "device_risk_score",
    "accounts_seen_for_ip_7d",
    "accounts_seen_for_ip_30d",
    "ip_risk_score",
    "merchant_fraud_rate_30d",
    "merchant_transaction_volume_7d",
    "merchant_risk_score",
    "device_shared_account_count",
    "ip_shared_account_count",
    "shared_email_accounts",
    "shared_phone_accounts",
    "fraud_cluster_size",
    "graph_risk_score",
    "shortest_path_to_known_fraud",
}


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
        select(_count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= one_h)
        )
    )
    txn_1h_challenged = await db.execute(
        select(_count(Transaction.id)).where(
            and_(
                base,
                Transaction.tx_timestamp >= one_h,
                Transaction.status.in_(["DECLINED", "PENDING_REVIEW"]),
            )
        )
    )
    txn_24h = await db.execute(
        select(_count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= one_d)
        )
    )
    txn_7d = await db.execute(
        select(_count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(base, Transaction.tx_timestamp >= seven_d)
        )
    )

    r1 = txn_1h.one()
    r1_challenged = txn_1h_challenged.scalar() or 0
    r24 = txn_24h.one()
    r7 = txn_7d.one()
    txn_count_1h = float(r1[0] or 0)
    txn_count_1h_challenged = float(r1_challenged or 0)
    txn_count_1h_non_challenged = max(0.0, txn_count_1h - txn_count_1h_challenged)
    # Poisson-style baseline using recent 24h activity.
    expected_1h_from_24h = max(float(r24[0] or 0) / 24.0, 0.05)
    variance_1h = max(expected_1h_from_24h, 0.25)
    txn_velocity_zscore_1h = (txn_count_1h - expected_1h_from_24h) / (variance_1h ** 0.5)
    txn_velocity_ratio_1h = txn_count_1h / max(expected_1h_from_24h, 0.05)

    return {
        "txn_count_1h": txn_count_1h,
        "txn_count_1h_challenged": txn_count_1h_challenged,
        "txn_count_1h_non_challenged": txn_count_1h_non_challenged,
        "txn_velocity_zscore_1h": max(-5.0, min(10.0, float(txn_velocity_zscore_1h))),
        "txn_velocity_ratio_1h": max(0.0, float(txn_velocity_ratio_1h)),
        "txn_expected_1h_from_24h": expected_1h_from_24h,
        "total_amount_1h": float(r1[1] or 0),
        "txn_count_24h": float(r24[0] or 0),
        "total_amount_24h": float(r24[1] or 0),
        "txn_count_7d": float(r7[0] or 0),
        "total_amount_7d": float(r7[1] or 0),
    }

def clear_feature_caches() -> None:
    """Clear all in-memory caches used for network/merchant features."""
    _DEVICE_CACHE.clear()
    _MERCHANT_CACHE.clear()


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


async def _network_features(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
    ip_hash: str | None,
    tx_timestamp: datetime,
    customer_phone_hash: str | None,
) -> Dict[str, float]:
    cache_key = (tenant_id, customer_id, device_id or "", ip_hash or "", tx_timestamp.date())
    cached = _DEVICE_CACHE.get(cache_key)
    if cached:
        val, expires_at = cached
        if time.time() < expires_at:
            return val
        _DEVICE_CACHE.pop(cache_key, None)
    if len(_DEVICE_CACHE) > 5000:
        _DEVICE_CACHE.clear()

    base = and_(
        Transaction.tenant_id == tenant_id,
        Transaction.tx_timestamp < tx_timestamp,
    )
    thirty_days_ago = tx_timestamp - timedelta(days=30)
    seven_days_ago = tx_timestamp - timedelta(days=7)
    ninety_days_ago = tx_timestamp - timedelta(days=90)

    # Devices seen for this customer in last 30 days
    dev_q = await db.execute(
        select(_count(func.distinct(Transaction.device_id))).where(
            and_(
                base,
                Transaction.customer_id == customer_id,
                Transaction.device_id.isnot(None),
                Transaction.tx_timestamp >= thirty_days_ago,
            )
        )
    )
    devices_seen_last_30d_for_customer = float(dev_q.scalar() or 0)

    # Customers seen on this device in last 7/90 days
    customers_seen_last_7d_for_device = 0.0
    customers_seen_last_90d_for_device = 0.0
    if device_id:
        dev_cust_7 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(
                    base,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= seven_days_ago,
                )
            )
        )
        customers_seen_last_7d_for_device = float(dev_cust_7.scalar() or 0)
        dev_cust_90 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(
                    base,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= ninety_days_ago,
                )
            )
        )
        customers_seen_last_90d_for_device = float(dev_cust_90.scalar() or 0)

    # IPs seen for this customer in last 30 days
    ips_q = await db.execute(
        select(_count(func.distinct(Transaction.ip_address_hash))).where(
            and_(
                base,
                Transaction.customer_id == customer_id,
                Transaction.ip_address_hash.isnot(None),
                Transaction.tx_timestamp >= thirty_days_ago,
            )
        )
    )
    ips_seen_last_30d_for_customer = float(ips_q.scalar() or 0)

    # Device reuse ratio: how many different customers used this device in last 90 days
    if customers_seen_last_90d_for_device <= 1:
        device_reuse_ratio = 0.0
    else:
        # Normalise: 0 when 1 customer, approach 1 when >=5 customers
        device_reuse_ratio = min(1.0, (customers_seen_last_90d_for_device - 1.0) / 4.0)

    # Email reuse ratio: approximate using phone_hash as a stable contact proxy
    email_reuse_ratio = 0.0
    if customer_phone_hash:
        contact_q = await db.execute(
            select(_count(func.distinct(Customer.id))).where(
                and_(
                    Customer.tenant_id == tenant_id,
                    Customer.phone_hash == customer_phone_hash,
                )
            )
        )
        contact_count = float(contact_q.scalar() or 0)
        if contact_count > 1:
            email_reuse_ratio = min(1.0, (contact_count - 1.0) / 4.0)

    # Fraud adjacency: device / IP / card (card approximated as 0.0 until card IDs are modelled)
    device_fraud_ratio_90d = 0.0
    ip_fraud_ratio_90d = 0.0

    # Device fraud ratio
    if device_id:
        dev_tot = await db.execute(
            select(_count()).select_from(Transaction)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .where(
                and_(
                    Transaction.tenant_id == tenant_id,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    Transaction.tx_timestamp < tx_timestamp,
                )
            )
        )
        dev_fraud = await db.execute(
            select(_count()).select_from(Transaction)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .where(
                and_(
                    Transaction.tenant_id == tenant_id,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    Transaction.tx_timestamp < tx_timestamp,
                    FraudOutcome.classification == "CONFIRMED_FRAUD",
                )
            )
        )
        tot = float(dev_tot.scalar() or 0)
        frd = float(dev_fraud.scalar() or 0)
        device_fraud_ratio_90d = frd / tot if tot > 0 else 0.0

    # IP fraud ratio
    if ip_hash:
        ip_tot = await db.execute(
            select(_count()).select_from(Transaction)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .where(
                and_(
                    Transaction.tenant_id == tenant_id,
                    Transaction.ip_address_hash == ip_hash,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    Transaction.tx_timestamp < tx_timestamp,
                )
            )
        )
        ip_fraud = await db.execute(
            select(_count()).select_from(Transaction)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .where(
                and_(
                    Transaction.tenant_id == tenant_id,
                    Transaction.ip_address_hash == ip_hash,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    Transaction.tx_timestamp < tx_timestamp,
                    FraudOutcome.classification == "CONFIRMED_FRAUD",
                )
            )
        )
        tot_ip = float(ip_tot.scalar() or 0)
        frd_ip = float(ip_fraud.scalar() or 0)
        ip_fraud_ratio_90d = frd_ip / tot_ip if tot_ip > 0 else 0.0

    # Card fraud ratio is a placeholder until card identifiers are modelled explicitly
    card_fraud_ratio_90d = 0.0

    out = {
        "devices_seen_last_30d_for_customer": devices_seen_last_30d_for_customer,
        "customers_seen_last_7d_for_device": customers_seen_last_7d_for_device,
        "ips_seen_last_30d_for_customer": ips_seen_last_30d_for_customer,
        "device_reuse_ratio": device_reuse_ratio,
        "email_reuse_ratio": email_reuse_ratio,
        "device_fraud_ratio_90d": device_fraud_ratio_90d,
        "ip_fraud_ratio_90d": ip_fraud_ratio_90d,
        "card_fraud_ratio_90d": card_fraud_ratio_90d,
    }
    _DEVICE_CACHE[cache_key] = (out, time.time() + CACHE_TTL_SECONDS)
    return out


async def _merchant_features(
    db: AsyncSession,
    tenant_id: str,
    merchant_entity_id: str | None,
    merchant_name: str | None,
    location_country: str | None,
    tx_timestamp: datetime,
) -> Dict[str, float]:
    if not merchant_entity_id and not merchant_name:
        # Avoid incorrectly treating the entire tenant as one "merchant".
        return {
            "merchant_fraud_rate_90d": 0.0,
            "merchant_volume_7d": 0.0,
            "merchant_country_mismatch": 0.0,
        }

    cache_key = (tenant_id, merchant_entity_id or "", merchant_name or "", location_country or "", tx_timestamp.date())
    cached = _MERCHANT_CACHE.get(cache_key)
    if cached:
        val, expires_at = cached
        if time.time() < expires_at:
            return val
        _MERCHANT_CACHE.pop(cache_key, None)
    if len(_MERCHANT_CACHE) > 5000:
        _MERCHANT_CACHE.clear()

    ninety_days_ago = tx_timestamp - timedelta(days=90)
    seven_days_ago = tx_timestamp - timedelta(days=7)

    merchant_filter = [Transaction.tenant_id == tenant_id]
    if merchant_entity_id:
        # Prefer stable MID when available; fall back to merchant_category stored on old rows.
        merchant_filter.append(func.coalesce(Transaction.merchant_id, Transaction.merchant_category) == merchant_entity_id)
    if merchant_name:
        merchant_filter.append(Transaction.merchant_name == merchant_name)

    # 90d fraud rate for this merchant
    base_q = select(_count()).select_from(Transaction).join(
        FraudOutcome, FraudOutcome.transaction_id == Transaction.id
    ).where(
        and_(
            *merchant_filter,
            Transaction.tx_timestamp >= ninety_days_ago,
            Transaction.tx_timestamp < tx_timestamp,
        )
    )
    tot_q = await db.execute(base_q)
    total_merchant = float(tot_q.scalar() or 0)

    fraud_q = await db.execute(
        base_q.where(FraudOutcome.classification == "CONFIRMED_FRAUD")
    )
    fraud_merchant = float(fraud_q.scalar() or 0)
    merchant_fraud_rate_90d = fraud_merchant / total_merchant if total_merchant > 0 else 0.0

    # 7d volume (sum of amount) for this merchant
    vol_q = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(
                *merchant_filter,
                Transaction.tx_timestamp >= seven_days_ago,
                Transaction.tx_timestamp < tx_timestamp,
            )
        )
    )
    merchant_volume_7d = float(vol_q.scalar() or 0) if vol_q is not None else 0.0

    # Merchant "usual" country: last non-null location_country
    usual_country_q = await db.execute(
        select(Transaction.location_country)
        .where(
            and_(
                *merchant_filter,
                Transaction.location_country.isnot(None),
            )
        )
        .order_by(Transaction.tx_timestamp.desc())
        .limit(1)
    )
    row = usual_country_q.one_or_none()
    usual_country = row[0] if row and row[0] else None
    merchant_country_mismatch = 0.0
    if usual_country and location_country:
        merchant_country_mismatch = 1.0 if usual_country.upper() != location_country.upper() else 0.0

    out = {
        "merchant_fraud_rate_90d": merchant_fraud_rate_90d,
        "merchant_volume_7d": merchant_volume_7d,
        "merchant_country_mismatch": merchant_country_mismatch,
    }
    _MERCHANT_CACHE[cache_key] = (out, time.time() + CACHE_TTL_SECONDS)
    return out


async def build_feature_vector(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    amount: float,
    currency: str,
    merchant_category: str | None,
    merchant_id: str | None,
    device_id: str | None,
    channel: str | None,
    tx_timestamp: datetime,
    customer_risk_score: float,
    location_country: str | None = None,
    ip_address: str | None = None,
) -> dict:
    merchant_entity_id = merchant_id or merchant_category
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

    # Network / entity features
    cust_row = await db.execute(
        select(Customer.phone_hash).where(
            and_(
                Customer.tenant_id == tenant_id,
                Customer.id == customer_id,
            )
        )
    )
    cust_phone_hash = cust_row.scalar_one_or_none()

    net_feats = await _network_features(
        db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        device_id=device_id,
        # Use real IP hash so entity-level IP risk features are not
        # silently under-estimated during scoring.
        ip_hash=ip_address,
        tx_timestamp=tx_timestamp,
        customer_phone_hash=cust_phone_hash,
    )

    merch_feats = await _merchant_features(
        db,
        tenant_id=tenant_id,
        merchant_entity_id=merchant_entity_id,
        merchant_name=None,
        location_country=location_country,
        tx_timestamp=tx_timestamp,
    )

    ring_feats = await get_network_risk_features(
        db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        device_id=device_id,
        ip_address=ip_address,
        merchant_id=merchant_entity_id,
        tx_timestamp=tx_timestamp,
    )
    graph_feats = await get_graph_features_for_scoring(
        db,
        tenant_id=tenant_id,
        customer_id=customer_id,
        device_id=device_id,
        ip_address=ip_address,
        tx_timestamp=tx_timestamp,
        ring_features=ring_feats,
        since_days=30,
    )
    ring_feats = {**(ring_feats or {}), **(graph_feats or {})}

    fingerprint_id = compute_transaction_fingerprint(
        str(customer_id),
        device_id,
        ip_address,
        merchant_entity_id,
        amount,
        tx_timestamp.hour,
    )
    fp_feats = await get_fingerprint_features(db, tenant_id, fingerprint_id, tx_timestamp)
    fp_feats["_fingerprint_id"] = fingerprint_id

    fv: Dict[str, Any] = {
        "amount": amount,
        "txn_count_1h": float(velocity["txn_count_1h"]),
        "txn_count_1h_challenged": float(velocity.get("txn_count_1h_challenged", 0.0) or 0.0),
        "txn_count_1h_non_challenged": float(velocity.get("txn_count_1h_non_challenged", 0.0) or 0.0),
        "txn_velocity_zscore_1h": float(velocity.get("txn_velocity_zscore_1h", 0.0) or 0.0),
        "txn_velocity_ratio_1h": float(velocity.get("txn_velocity_ratio_1h", 0.0) or 0.0),
        "txn_expected_1h_from_24h": float(velocity.get("txn_expected_1h_from_24h", 0.0) or 0.0),
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
        # Stored for dynamic thresholding (segment/corridor/channel bucketing).
        "channel": channel,
    }
    fv.update(net_feats)
    fv.update(merch_feats)
    # Authoritative precedence:
    # graph/ring network signals should override generic network placeholders.
    for k in FEATURE_NAMES:
        if k in ring_feats and (k in NETWORK_FEATURE_KEYS or k not in fv):
            fv[k] = ring_feats[k]
    # Fingerprint signals are authoritative for their namespace.
    for k in FEATURE_NAMES:
        if k in fp_feats:
            fv[k] = fp_feats[k]
    if "_fingerprint_id" in fp_feats:
        fv["_fingerprint_id"] = fp_feats["_fingerprint_id"]
    return fv
