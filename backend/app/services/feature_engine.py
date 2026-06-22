from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import math
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
    # ── Impossible travel / geospatial velocity ───────────────────────────────
    "impossible_travel",       # 1.0 if physically impossible speed between transactions
    "travel_speed_kmh",        # km/h between last and current location (capped at 10000)
    # ── Recency-weighted velocity (EWMA) ─────────────────────────────────────
    "velocity_ewma_1h",        # exponentially weighted txn count, 30min half-life
    "velocity_ewma_24h",       # exponentially weighted txn count, 6h half-life
    # ── Amount cost weighting ─────────────────────────────────────────────────
    "amount_log_scaled",       # log(amount+1) normalised to [0,1] over 0–100k range
    # ── Behavioral biometrics (from mobile SDK) ───────────────────────────────
    "biometric_confidence",          # 0.0=suspicious, 1.0=matches baseline
    "typing_speed_deviation",        # normalised deviation from customer baseline
    "touch_pressure_deviation",      # normalised deviation from customer baseline
    "session_age_seconds",           # seconds since app session started (capped 3600)
    "biometric_signals_present",     # 1.0 if SDK sent biometrics, 0.0 if not
    # ── GNN graph embedding risk ──────────────────────────────────────────────
    "gnn_account_risk_score",  # graph-neural-network derived risk (0.0–1.0)
]

CACHE_TTL_SECONDS = 300

# Cache maps: key -> (value, expires_at_epoch_seconds)
_DEVICE_CACHE: Dict[tuple, tuple[Dict[str, float], float]] = {}
_MERCHANT_CACHE: Dict[tuple, tuple[Dict[str, float], float]] = {}

# ── Country centroids for impossible-travel detection ────────────────────────
# (latitude, longitude) for approximate haversine distance computation.
_COUNTRY_CENTROIDS: Dict[str, tuple] = {
    "GH": (7.9465, -1.0232),    "NG": (9.0820, 8.6753),
    "ZA": (-30.5595, 22.9375),  "KE": (-0.0236, 37.9062),
    "GB": (55.3781, -3.4360),   "US": (37.0902, -95.7129),
    "FR": (46.2276, 2.2137),    "DE": (51.1657, 10.4515),
    "CN": (35.8617, 104.1954),  "IN": (20.5937, 78.9629),
    "BR": (-14.2350, -51.9253), "AE": (23.4241, 53.8478),
    "SG": (1.3521, 103.8198),   "AU": (-25.2744, 133.7751),
    "CA": (56.1304, -106.3468), "JP": (36.2048, 138.2529),
    "RU": (61.5240, 105.3188),  "EG": (26.8206, 30.8025),
    "ET": (9.1450, 40.4897),    "TZ": (-6.3690, 34.8888),
    "UG": (1.3733, 32.2903),    "ZM": (-13.1339, 27.8493),
    "ZW": (-19.0154, 29.1549),  "RW": (-1.9403, 29.8739),
    "CI": (7.5400, -5.5471),    "SN": (14.4974, -14.4524),
    "CM": (3.8480, 11.5021),    "GH": (7.9465, -1.0232),
    "MX": (23.6345, -102.5528), "AR": (-38.4161, -63.6167),
    "IT": (41.8719, 12.5674),   "ES": (40.4637, -3.7492),
    "NL": (52.1326, 5.2913),    "BE": (50.5039, 4.4699),
    "CH": (46.8182, 8.2275),    "SE": (60.1282, 18.6435),
    "NO": (60.4720, 8.4689),    "DK": (56.2639, 9.5018),
    "PL": (51.9194, 19.1451),   "PT": (39.3999, -8.2245),
    "TR": (38.9637, 35.2433),   "SA": (23.8859, 45.0792),
    "QA": (25.3548, 51.1839),   "KW": (29.3117, 47.4818),
    "PK": (30.3753, 69.3451),   "BD": (23.6850, 90.3563),
    "PH": (12.8797, 121.7740),  "ID": (-0.7893, 113.9213),
    "MY": (4.2105, 101.9758),   "TH": (15.8700, 100.9925),
    "VN": (14.0583, 108.2772),  "KR": (35.9078, 127.7669),
    "HK": (22.3193, 114.1694),  "TW": (23.6978, 120.9605),
    "NZ": (-40.9006, 174.8860), "ZA": (-30.5595, 22.9375),
}

# Maximum physically plausible travel speed (km/h) — supersonic aircraft
_MAX_PLAUSIBLE_SPEED_KMH = 2000.0
# Speed threshold above which we flag impossible travel
_IMPOSSIBLE_TRAVEL_KMH = 900.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points in kilometres."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _impossible_travel_features(
    current_country: str | None,
    current_ts: datetime,
    last_country: str | None,
    last_ts: datetime | None,
) -> Dict[str, float]:
    """
    Returns impossible_travel (0/1) and travel_speed_kmh.

    Logic:
      - If either country is unknown, return neutral (0, 0).
      - If same country, return (0, 0).
      - Compute great-circle distance between country centroids.
      - Divide by elapsed time in hours → speed in km/h.
      - If speed > 900 km/h (max commercial aircraft ≈ 920 km/h), flag as impossible.
    """
    if not current_country or not last_country or not last_ts:
        return {"impossible_travel": 0.0, "travel_speed_kmh": 0.0}

    c1 = current_country.upper()
    c2 = last_country.upper()

    if c1 == c2:
        return {"impossible_travel": 0.0, "travel_speed_kmh": 0.0}

    centroid1 = _COUNTRY_CENTROIDS.get(c1)
    centroid2 = _COUNTRY_CENTROIDS.get(c2)

    if not centroid1 or not centroid2:
        return {"impossible_travel": 0.0, "travel_speed_kmh": 0.0}

    dist_km = _haversine_km(centroid1[0], centroid1[1], centroid2[0], centroid2[1])
    elapsed_hours = max((current_ts - last_ts).total_seconds() / 3600.0, 1 / 3600.0)
    speed_kmh = dist_km / elapsed_hours
    capped_speed = min(speed_kmh, 10_000.0)
    impossible = 1.0 if speed_kmh > _IMPOSSIBLE_TRAVEL_KMH else 0.0

    return {
        "impossible_travel": impossible,
        "travel_speed_kmh": round(capped_speed, 1),
    }


def _ewma_velocity(
    timestamps: List[datetime],
    reference_ts: datetime,
    half_life_seconds: float,
) -> float:
    """
    Exponentially weighted count of transactions.

    Each transaction at age t seconds contributes exp(-λ·t) to the total,
    where λ = ln(2) / half_life_seconds. A transaction happening right now
    contributes 1.0; one from 30 minutes ago (with 30min half-life) contributes 0.5.
    """
    if not timestamps:
        return 0.0
    decay = math.log(2) / max(half_life_seconds, 1.0)
    total = 0.0
    for ts in timestamps:
        age = (reference_ts - ts).total_seconds()
        if 0 <= age:
            total += math.exp(-decay * age)
    return round(total, 4)

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
) -> tuple[datetime | None, float, List[datetime]]:
    """
    Returns (last_tx_timestamp, is_new_device, recent_timestamps_1h).

    recent_timestamps_1h is used for EWMA velocity computation.
    """
    base = and_(
        Transaction.tenant_id == tenant_id,
        Transaction.customer_id == customer_id,
    )
    last = await db.execute(
        select(Transaction.tx_timestamp, Transaction.device_id)
        .where(base)
        .order_by(Transaction.tx_timestamp.desc())
        .limit(100)
    )
    rows = last.all()
    if not rows:
        return None, 0.0, []
    last_ts = rows[0][0]
    devices = {r[1] for r in rows if r[1]}
    is_new_device = 1.0 if (device_id and device_id not in devices) else 0.0
    recent_timestamps = [r[0] for r in rows if r[0] is not None]
    return last_ts, is_new_device, recent_timestamps


async def get_last_location(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
) -> tuple[str | None, datetime | None]:
    """Returns (last_country_code, last_tx_timestamp_with_location)."""
    result = await db.execute(
        select(Transaction.location_country, Transaction.tx_timestamp)
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
    if row and row[0]:
        return row[0], row[1]
    return None, None


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
    biometrics: Dict[str, Any] | None = None,
) -> dict:
    merchant_entity_id = merchant_id or merchant_category
    velocity = await get_velocity(db, tenant_id, customer_id, tx_timestamp)
    last_ts, is_new_device, recent_timestamps = await get_last_txn_and_device(
        db, tenant_id, customer_id, device_id
    )
    last_country, last_country_ts = await get_last_location(db, tenant_id, customer_id)

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

    # ── Impossible travel ─────────────────────────────────────────────────────
    travel_feats = _impossible_travel_features(
        current_country=location_country,
        current_ts=tx_timestamp,
        last_country=last_country,
        last_ts=last_country_ts,
    )

    # ── EWMA velocity ─────────────────────────────────────────────────────────
    one_hour_ago = tx_timestamp - timedelta(hours=1)
    one_day_ago = tx_timestamp - timedelta(days=1)
    ts_1h = [t for t in recent_timestamps if t >= one_hour_ago]
    ts_24h = [t for t in recent_timestamps if t >= one_day_ago]
    velocity_ewma_1h = _ewma_velocity(ts_1h, tx_timestamp, half_life_seconds=1800.0)   # 30min
    velocity_ewma_24h = _ewma_velocity(ts_24h, tx_timestamp, half_life_seconds=21600.0) # 6h

    # ── Amount cost weight ────────────────────────────────────────────────────
    # log(amount+1) normalised over range 0–100,000
    amount_log_scaled = min(1.0, math.log1p(max(0.0, amount)) / math.log1p(100_000.0))

    # ── Behavioral biometrics ─────────────────────────────────────────────────
    from app.services.behavioral_biometrics import extract_biometric_features
    bio_feats = extract_biometric_features(biometrics, tenant_id, customer_id)

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
        "channel": channel,
        # ── New features ──────────────────────────────────────────────────────
        "impossible_travel": travel_feats["impossible_travel"],
        "travel_speed_kmh": travel_feats["travel_speed_kmh"],
        "velocity_ewma_1h": velocity_ewma_1h,
        "velocity_ewma_24h": velocity_ewma_24h,
        "amount_log_scaled": amount_log_scaled,
        # Biometrics (defaults populated by extract_biometric_features)
        "biometric_confidence": bio_feats["biometric_confidence"],
        "typing_speed_deviation": bio_feats["typing_speed_deviation"],
        "touch_pressure_deviation": bio_feats["touch_pressure_deviation"],
        "session_age_seconds": bio_feats["session_age_seconds"],
        "biometric_signals_present": bio_feats["biometric_signals_present"],
        # GNN score: computed async below
        "gnn_account_risk_score": 0.0,
    }
    fv.update(net_feats)
    fv.update(merch_feats)
    # Authoritative precedence: graph/ring signals override generic network placeholders.
    for k in FEATURE_NAMES:
        if k in ring_feats and (k in NETWORK_FEATURE_KEYS or k not in fv):
            fv[k] = ring_feats[k]
    # Fingerprint signals are authoritative for their namespace.
    for k in FEATURE_NAMES:
        if k in fp_feats:
            fv[k] = fp_feats[k]
    if "_fingerprint_id" in fp_feats:
        fv["_fingerprint_id"] = fp_feats["_fingerprint_id"]

    # ── GNN account risk score ────────────────────────────────────────────────
    try:
        from app.config import settings as _settings
        if getattr(_settings, "gnn_embeddings_enabled", True):
            from app.ml.gnn_embeddings import get_gnn_risk_score_from_db
            gnn_score = await get_gnn_risk_score_from_db(db, tenant_id, customer_id, device_id)
            fv["gnn_account_risk_score"] = gnn_score
    except Exception:
        pass  # GNN failure is non-fatal; defaults to 0.0

    return fv
