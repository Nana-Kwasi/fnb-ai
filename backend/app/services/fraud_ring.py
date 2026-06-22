"""
Fraud ring detection and network-based risk.
Uses DeviceAccountMap, IPAccountMap, MerchantRisk, AccountConnection + optional NetworkX.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
import time

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Transaction,
    Customer,
    FraudOutcome,
    FraudAlert,
    DeviceAccountMap,
    IPAccountMap,
    MerchantRisk,
    AccountConnection,
    TransactionFingerprint,
    FingerprintStats,
)

# Pylint sometimes mis-detects `func.count` as not callable. Use a wrapper.
def _count(*args, **kwargs):
    return func.count(*args, **kwargs)  # type: ignore[misc]

# Cache for graph-derived metrics (entity -> metrics).
CACHE_TTL_SECONDS = 300
_RING_CACHE: Dict[Tuple[str, str, str], tuple[Dict[str, float], float]] = {}
_CACHE_MAX = 3000

DEVICE_RING_ACCOUNT_THRESHOLD = 3
IP_RING_ACCOUNT_THRESHOLD = 3
MERCHANT_FRAUD_HUB_MIN_RATE = 0.2


async def get_network_risk_features(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
    ip_address: str | None,
    merchant_id: str | None,
    tx_timestamp: datetime,
) -> Dict[str, float]:
    """
    Compute device_risk_score, ip_risk_score, merchant_risk_score and ring-style counts
    for real-time scoring. Uses map tables + Transaction/FraudOutcome; no full graph build.
    """
    cache_key = (tenant_id, customer_id, device_id or "", ip_address or "", merchant_id or "")
    cached = _RING_CACHE.get(cache_key)
    if cached:
        val, expires_at = cached
        if time.time() < expires_at:
            return val
        _RING_CACHE.pop(cache_key, None)
    if len(_RING_CACHE) > _CACHE_MAX:
        _RING_CACHE.clear()

    seven_days_ago = tx_timestamp - timedelta(days=7)
    thirty_days_ago = tx_timestamp - timedelta(days=30)
    ninety_days_ago = tx_timestamp - timedelta(days=90)

    base_t = and_(
        Transaction.tenant_id == tenant_id,
        Transaction.tx_timestamp < tx_timestamp,
    )

    # ---- Device risk ----
    accounts_seen_for_device_7d = 0.0
    accounts_seen_for_device_30d = 0.0
    device_fraud_ratio_90d = 0.0
    device_risk_score = 0.0

    if device_id:
        acc_7 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(base_t, Transaction.device_id == device_id, Transaction.tx_timestamp >= seven_days_ago)
            )
        )
        acc_30 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(base_t, Transaction.device_id == device_id, Transaction.tx_timestamp >= thirty_days_ago)
            )
        )
        accounts_seen_for_device_7d = float(acc_7.scalar() or 0)
        accounts_seen_for_device_30d = float(acc_30.scalar() or 0)

        tot = await db.execute(
            select(_count()).where(
                and_(
                    base_t,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= ninety_days_ago,
                )
            )
        )
        fraud = await db.execute(
            select(_count()).select_from(Transaction).join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id).where(
                and_(
                    base_t,
                    Transaction.device_id == device_id,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    FraudOutcome.classification == "CONFIRMED_FRAUD",
                )
            )
        )
        t, f = float(tot.scalar() or 0), float(fraud.scalar() or 0)
        device_fraud_ratio_90d = f / t if t > 0 else 0.0

        if accounts_seen_for_device_7d >= DEVICE_RING_ACCOUNT_THRESHOLD or accounts_seen_for_device_30d >= DEVICE_RING_ACCOUNT_THRESHOLD:
            device_risk_score = min(1.0, 0.3 + 0.2 * (accounts_seen_for_device_7d - 1) + 0.3 * device_fraud_ratio_90d)
        else:
            device_risk_score = 0.2 * device_fraud_ratio_90d

    # ---- IP risk ----
    accounts_seen_for_ip_7d = 0.0
    accounts_seen_for_ip_30d = 0.0
    ip_fraud_ratio_90d = 0.0
    ip_risk_score = 0.0

    if ip_address:
        acc_7 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(base_t, Transaction.ip_address_hash == ip_address, Transaction.tx_timestamp >= seven_days_ago)
            )
        )
        acc_30 = await db.execute(
            select(_count(func.distinct(Transaction.customer_id))).where(
                and_(base_t, Transaction.ip_address_hash == ip_address, Transaction.tx_timestamp >= thirty_days_ago)
            )
        )
        accounts_seen_for_ip_7d = float(acc_7.scalar() or 0)
        accounts_seen_for_ip_30d = float(acc_30.scalar() or 0)

        tot = await db.execute(
            select(_count()).where(
                and_(base_t, Transaction.ip_address_hash == ip_address, Transaction.tx_timestamp >= ninety_days_ago)
            )
        )
        fraud = await db.execute(
            select(_count()).select_from(Transaction).join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id).where(
                and_(
                    base_t,
                    Transaction.ip_address_hash == ip_address,
                    Transaction.tx_timestamp >= ninety_days_ago,
                    FraudOutcome.classification == "CONFIRMED_FRAUD",
                )
            )
        )
        t, f = float(tot.scalar() or 0), float(fraud.scalar() or 0)
        ip_fraud_ratio_90d = f / t if t > 0 else 0.0

        if accounts_seen_for_ip_7d >= IP_RING_ACCOUNT_THRESHOLD or accounts_seen_for_ip_30d >= IP_RING_ACCOUNT_THRESHOLD:
            ip_risk_score = min(1.0, 0.3 + 0.2 * (accounts_seen_for_ip_7d - 1) + 0.3 * ip_fraud_ratio_90d)
        else:
            ip_risk_score = 0.2 * ip_fraud_ratio_90d

    # ---- Merchant risk ----
    merchant_fraud_rate_30d = 0.0
    merchant_transaction_volume_7d = 0.0
    merchant_risk_score = 0.0

    if merchant_id:
        merchant_filter = [
            base_t,
            func.coalesce(Transaction.merchant_id, Transaction.merchant_category) == merchant_id,
            Transaction.tx_timestamp >= thirty_days_ago,
        ]
        tot_30 = await db.execute(select(_count()).where(and_(*merchant_filter)))
        fraud_30 = await db.execute(
            select(_count()).select_from(Transaction).join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id).where(
                and_(*merchant_filter, FraudOutcome.classification == "CONFIRMED_FRAUD")
            )
        )
        t30, f30 = float(tot_30.scalar() or 0), float(fraud_30.scalar() or 0)
        merchant_fraud_rate_30d = f30 / t30 if t30 > 0 else 0.0

        vol = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                and_(
                    base_t,
                    func.coalesce(Transaction.merchant_id, Transaction.merchant_category) == merchant_id,
                    Transaction.tx_timestamp >= seven_days_ago,
                )
            )
        )
        merchant_transaction_volume_7d = float(vol.scalar() or 0)

        if merchant_fraud_rate_30d >= MERCHANT_FRAUD_HUB_MIN_RATE:
            merchant_risk_score = min(1.0, 0.2 + 0.6 * merchant_fraud_rate_30d)
        else:
            merchant_risk_score = 0.2 * merchant_fraud_rate_30d

    # Shared entity counts (for feature vector)
    device_shared_account_count = max(accounts_seen_for_device_7d, accounts_seen_for_device_30d)
    ip_shared_account_count = max(accounts_seen_for_ip_7d, accounts_seen_for_ip_30d)

    cust = (await db.execute(select(Customer).where(Customer.id == customer_id))).scalar_one_or_none()
    shared_email_accounts = 0.0
    shared_phone_accounts = 0.0
    if cust and cust.phone_hash:
        same_phone = await db.execute(
            select(_count()).where(and_(Customer.tenant_id == tenant_id, Customer.phone_hash == cust.phone_hash))
        )
        shared_phone_accounts = float(same_phone.scalar() or 0)
        shared_email_accounts = shared_phone_accounts  # proxy

    # network_risk_score = 0.4 * device + 0.3 * ip + 0.3 * merchant (computed in fraud_engine)
    out = {
        "accounts_seen_for_device_7d": accounts_seen_for_device_7d,
        "accounts_seen_for_device_30d": accounts_seen_for_device_30d,
        "device_fraud_ratio_90d": device_fraud_ratio_90d,
        "device_risk_score": device_risk_score,
        "accounts_seen_for_ip_7d": accounts_seen_for_ip_7d,
        "accounts_seen_for_ip_30d": accounts_seen_for_ip_30d,
        "ip_fraud_ratio_90d": ip_fraud_ratio_90d,
        "ip_risk_score": ip_risk_score,
        "merchant_fraud_rate_30d": merchant_fraud_rate_30d,
        "merchant_transaction_volume_7d": merchant_transaction_volume_7d,
        "merchant_risk_score": merchant_risk_score,
        "device_shared_account_count": device_shared_account_count,
        "ip_shared_account_count": ip_shared_account_count,
        "shared_email_accounts": shared_email_accounts,
        "shared_phone_accounts": shared_phone_accounts,
        "fraud_cluster_size": max(device_shared_account_count, ip_shared_account_count, 1.0),
    }
    _RING_CACHE[cache_key] = (out, time.time() + CACHE_TTL_SECONDS)
    return out


def compute_network_risk_score(ring_features: Dict[str, float]) -> float:
    """network_risk_score = 0.4 * device_risk + 0.3 * ip_risk + 0.3 * merchant_risk."""
    d = ring_features.get("device_risk_score", 0.0) or 0.0
    i = ring_features.get("ip_risk_score", 0.0) or 0.0
    m = ring_features.get("merchant_risk_score", 0.0) or 0.0
    return min(1.0, 0.4 * d + 0.3 * i + 0.3 * m)


async def update_entity_maps(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
    ip_address: str | None,
    merchant_id: str | None,
    tx_ts: datetime,
) -> None:
    """Upsert DeviceAccountMap, IPAccountMap; update MerchantRisk. Call after each scored transaction."""
    if device_id:
        existing = (await db.execute(
            select(DeviceAccountMap).where(
                and_(
                    DeviceAccountMap.tenant_id == tenant_id,
                    DeviceAccountMap.device_id == device_id,
                    DeviceAccountMap.customer_id == customer_id,
                )
            )
        )).scalar_one_or_none()
        if existing:
            existing.last_seen = tx_ts
        else:
            db.add(DeviceAccountMap(tenant_id=tenant_id, device_id=device_id, customer_id=customer_id, first_seen=tx_ts, last_seen=tx_ts))
    if ip_address:
        existing = (await db.execute(
            select(IPAccountMap).where(
                and_(
                    IPAccountMap.tenant_id == tenant_id,
                    IPAccountMap.ip_address == ip_address,
                    IPAccountMap.customer_id == customer_id,
                )
            )
        )).scalar_one_or_none()
        if existing:
            existing.last_seen = tx_ts
        else:
            db.add(IPAccountMap(tenant_id=tenant_id, ip_address=ip_address, customer_id=customer_id, first_seen=tx_ts, last_seen=tx_ts))
    if merchant_id:
        existing = (await db.execute(
            select(MerchantRisk).where(
                and_(MerchantRisk.tenant_id == tenant_id, MerchantRisk.merchant_id == merchant_id)
            )
        )).scalar_one_or_none()
        if existing:
            existing.total_transactions += 1
            existing.last_updated = tx_ts
        else:
            db.add(MerchantRisk(tenant_id=tenant_id, merchant_id=merchant_id, total_transactions=1, last_updated=tx_ts))
    await db.flush()


def build_graph_and_rings(
    device_accounts: List[Tuple[str, str]],
    ip_accounts: List[Tuple[str, str]],
    merchant_accounts: List[Tuple[str, str]],
    account_connections: List[Tuple[str, str]],
) -> Tuple[Any, List[Dict[str, Any]]]:
    """
    Build NetworkX graph and detect rings. Returns (graph, list of ring alerts).
    node id: 'acc:{id}' | 'dev:{id}' | 'ip:{id}' | 'merchant:{id}'
    """
    try:
        import networkx as nx
    except ImportError:
        return None, []

    G = nx.Graph()

    for dev, acc in device_accounts:
        G.add_node(f"dev:{dev}", type="device")
        G.add_node(f"acc:{acc}", type="account")
        G.add_edge(f"dev:{dev}", f"acc:{acc}", rel="used_device")
    for ip, acc in ip_accounts:
        G.add_node(f"ip:{ip}", type="ip")
        G.add_node(f"acc:{acc}", type="account")
        G.add_edge(f"ip:{ip}", f"acc:{acc}", rel="used_ip")
    for mer, acc in merchant_accounts:
        G.add_node(f"merchant:{mer}", type="merchant")
        G.add_node(f"acc:{acc}", type="account")
        G.add_edge(f"merchant:{mer}", f"acc:{acc}", rel="paid")
    for src, dst in account_connections:
        G.add_node(f"acc:{src}", type="account")
        G.add_node(f"acc:{dst}", type="account")
        G.add_edge(f"acc:{src}", f"acc:{dst}", rel="transferred_to")

    rings: List[Dict[str, Any]] = []

    # Device rings: device with degree (account count) >= threshold
    for n in G.nodes():
        if G.nodes[n].get("type") == "device" and G.degree(n) >= DEVICE_RING_ACCOUNT_THRESHOLD:
            rings.append({"type": "device_ring", "entity_id": n.replace("dev:", ""), "account_count": G.degree(n)})
    # IP rings
    for n in G.nodes():
        if G.nodes[n].get("type") == "ip" and G.degree(n) >= IP_RING_ACCOUNT_THRESHOLD:
            rings.append({"type": "ip_ring", "entity_id": n.replace("ip:", ""), "account_count": G.degree(n)})
    # Cycles in account graph (simplified: 3+ node cycles)
    try:
        acc_subgraph = G.subgraph([n for n in G.nodes() if G.nodes[n].get("type") == "account"])
        for c in nx.simple_cycles(nx.DiGraph(acc_subgraph)) if hasattr(nx, "simple_cycles") else []:
            if len(c) >= 3:
                rings.append({"type": "circular_flow", "nodes": c, "size": len(c)})
    except Exception:
        pass

    return G, rings


async def apply_fraud_outcome(
    db: AsyncSession,
    tenant_id: str,
    transaction_id: str,
    classification: str,
    source: str | None = None,
    notes: str | None = None,
) -> None:
    """
    Upsert FraudOutcome for a transaction and update MerchantRisk / FingerprintStats fraud aggregates.
    """
    tx = (await db.execute(
        select(Transaction).where(
            and_(Transaction.id == transaction_id, Transaction.tenant_id == tenant_id)
        )
    )).scalar_one_or_none()
    if not tx:
        return

    prev_is_fraud = False
    outcome = (await db.execute(
        select(FraudOutcome).where(
            and_(
                FraudOutcome.tenant_id == tenant_id,
                FraudOutcome.transaction_id == transaction_id,
            )
        )
    )).scalar_one_or_none()
    if outcome:
        prev_is_fraud = outcome.classification == "CONFIRMED_FRAUD"
        outcome.classification = classification
        if source is not None:
            outcome.source = source
        if notes is not None:
            outcome.notes = notes
    else:
        db.add(
            FraudOutcome(
                tenant_id=tenant_id,
                transaction_id=transaction_id,
                classification=classification,
                source=source,
                notes=notes,
            )
        )
    new_is_fraud = classification == "CONFIRMED_FRAUD"

    # Close any related OPEN alerts once an ops label is provided.
    # This keeps the review queue actionable and prevents re-labeling churn.
    alert_q = await db.execute(
        select(FraudAlert).where(
            and_(
                FraudAlert.tenant_id == tenant_id,
                FraudAlert.transaction_id == transaction_id,
                FraudAlert.status == "OPEN",
            )
        )
    )
    open_alerts = alert_q.scalars().all()
    for a in open_alerts:
        a.status = "CLOSED"
    await db.flush()

    # Invalidate caches affected by outcome labels so next scores use up-to-date risk.
    _RING_CACHE.clear()
    try:
        from app.services import feature_engine as _feature_engine  # local import to avoid cycles
        if hasattr(_feature_engine, "clear_feature_caches"):
            _feature_engine.clear_feature_caches()
    except Exception:
        pass

    delta = (1 if new_is_fraud else 0) - (1 if prev_is_fraud else 0)
    if delta == 0:
        await db.flush()
        return

    # Update MerchantRisk fraud aggregates for this transaction's merchant (if present).
    merchant_entity_id = tx.merchant_id or tx.merchant_category
    if merchant_entity_id:
        mr = (await db.execute(
            select(MerchantRisk).where(
                and_(
                    MerchantRisk.tenant_id == tenant_id,
                    MerchantRisk.merchant_id == merchant_entity_id,
                )
            )
        )).scalar_one_or_none()
        if mr:
            mr.fraud_transactions = max(0, int(mr.fraud_transactions or 0) + delta)
            total = float(mr.total_transactions or 0)
            mr.fraud_rate = float(mr.fraud_transactions) / total if total > 0 else 0.0
            mr.last_updated = tx.tx_timestamp

    # Update FingerprintStats: all fingerprints linked to this transaction.
    fps = (await db.execute(
        select(TransactionFingerprint.fingerprint_id).where(
            and_(
                TransactionFingerprint.tenant_id == tenant_id,
                TransactionFingerprint.transaction_id == transaction_id,
            )
        )
    )).scalars().all()
    for fp in fps:
        row = (await db.execute(
            select(FingerprintStats).where(
                and_(
                    FingerprintStats.tenant_id == tenant_id,
                    FingerprintStats.fingerprint_id == fp,
                )
            )
        )).scalar_one_or_none()
        if row:
            row.fraud_transactions = max(0, int(row.fraud_transactions or 0) + delta)
            total = float(row.total_transactions or 0)
            row.fraud_rate = float(row.fraud_transactions) / total if total > 0 else 0.0
            row.last_seen = tx.tx_timestamp
    await db.flush()


async def get_tenant_graph_data(
    db: AsyncSession,
    tenant_id: str,
    since_days: int = 30,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Load device–account, ip–account, merchant–account, and account–account links for a tenant."""
    since = datetime.utcnow() - timedelta(days=since_days)
    dev_rows = (await db.execute(
        select(DeviceAccountMap.device_id, DeviceAccountMap.customer_id).where(
            and_(DeviceAccountMap.tenant_id == tenant_id, DeviceAccountMap.last_seen >= since)
        )
    )).all()
    device_accounts = [(str(d), str(c)) for d, c in dev_rows]
    ip_rows = (await db.execute(
        select(IPAccountMap.ip_address, IPAccountMap.customer_id).where(
            and_(IPAccountMap.tenant_id == tenant_id, IPAccountMap.last_seen >= since)
        )
    )).all()
    ip_accounts = [(str(i), str(c)) for i, c in ip_rows]
    mer_rows = (await db.execute(
        select(func.coalesce(Transaction.merchant_id, Transaction.merchant_category), Transaction.customer_id).where(
            and_(
                Transaction.tenant_id == tenant_id,
                Transaction.tx_timestamp >= since,
                func.coalesce(Transaction.merchant_id, Transaction.merchant_category).isnot(None),
            )
        )
    )).all()
    merchant_accounts = [(str(m), str(c)) for m, c in mer_rows if m]
    conn_rows = (await db.execute(
        select(AccountConnection.source_customer_id, AccountConnection.destination_customer_id).where(
            AccountConnection.tenant_id == tenant_id
        )
    )).all()
    account_connections = [(str(s), str(d)) for s, d in conn_rows]
    return device_accounts, ip_accounts, merchant_accounts, account_connections
