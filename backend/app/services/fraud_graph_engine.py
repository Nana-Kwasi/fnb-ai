"""
Graph-based fraud detection: relationship graph, fraud clusters, mule chains.
Uses NetworkX; computes graph_risk_score and features for ensemble.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, FraudOutcome
from app.services.fraud_ring import get_tenant_graph_data

FRAUD_CLUSTER_SIZE_THRESHOLD = 5
MULE_CHAIN_DEPTH_THRESHOLD = 4
SHARED_ACCOUNT_SCORE_CAP = 10.0


def compute_graph_risk_score(features: Dict[str, float]) -> float:
    """
    graph_risk_score = 0.35*device_fraud_ratio + 0.25*ip_fraud_ratio
                     + 0.20*fraud_cluster_size_score + 0.20*shared_account_score
    Output 0.0 -> 1.0.
    """
    device_fraud = float(features.get("device_fraud_ratio_90d", 0) or features.get("device_fraud_ratio", 0) or 0)
    ip_fraud = float(features.get("ip_fraud_ratio_90d", 0) or features.get("ip_fraud_ratio", 0) or 0)
    cluster_size = float(features.get("fraud_cluster_size", 1) or 1)
    fraud_cluster_size_score = min(1.0, cluster_size / FRAUD_CLUSTER_SIZE_THRESHOLD)
    acc_dev = float(features.get("accounts_seen_for_device_7d", 0) or 0)
    acc_ip = float(features.get("accounts_seen_for_ip_7d", 0) or 0)
    shared_account_score = min(1.0, max(acc_dev, acc_ip) / SHARED_ACCOUNT_SCORE_CAP)
    path_to_fraud = float(features.get("shortest_path_to_known_fraud", 999) or 999)
    path_score = 0.0 if path_to_fraud >= 999 else max(0.0, 1.0 - path_to_fraud / 5.0)
    score = (
        0.35 * device_fraud
        + 0.25 * ip_fraud
        + 0.20 * fraud_cluster_size_score
        + 0.20 * shared_account_score
        + 0.15 * path_score
    )
    return min(1.0, max(0.0, score))


def _build_nx_graph(
    device_accounts: List[Tuple[str, str]],
    ip_accounts: List[Tuple[str, str]],
    merchant_accounts: List[Tuple[str, str]],
    account_connections: List[Tuple[str, str]],
):
    try:
        import networkx as nx
    except ImportError:
        return None
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
    return G


async def _get_known_fraud_accounts(
    db: AsyncSession,
    tenant_id: str,
    since_days: int = 90,
) -> set:
    since = datetime.utcnow() - timedelta(days=since_days)
    rows = (
        await db.execute(
            select(Transaction.customer_id)
            .select_from(Transaction)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .where(
                and_(
                    Transaction.tenant_id == tenant_id,
                    FraudOutcome.tenant_id == tenant_id,
                    FraudOutcome.classification == "CONFIRMED_FRAUD",
                    Transaction.tx_timestamp >= since,
                )
            )
        )
    ).scalars().all()
    return {str(r) for r in rows}


def _shortest_path_to_fraud(
    G,
    start_ids: List[str],
    fraud_accounts: set,
) -> float:
    if G is None or not start_ids or not fraud_accounts:
        return 999.0
    try:
        import networkx as nx
    except ImportError:
        return 999.0
    acc_fraud = {f"acc:{a}" for a in fraud_accounts}
    min_path = 999.0
    for n in start_ids:
        node_id = n if n.startswith("acc:") or n.startswith("dev:") or n.startswith("ip:") else f"acc:{n}"
        if node_id not in G:
            continue
        for fraud_node in acc_fraud:
            if fraud_node not in G:
                continue
            try:
                path_len = nx.shortest_path_length(G, node_id, fraud_node)
                min_path = min(min_path, float(path_len))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
    return min_path if min_path < 999 else 999.0


def _max_connected_component_size(G) -> int:
    if G is None:
        return 0
    try:
        import networkx as nx
    except ImportError:
        return 0
    comps = list(nx.connected_components(G))
    return max(len(c) for c in comps) if comps else 0


async def get_graph_features_for_scoring(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
    ip_address: str | None,
    tx_timestamp: datetime,
    ring_features: Dict[str, float],
    since_days: int = 30,
) -> Dict[str, float]:
    """
    Build tenant graph, compute fraud_cluster_size (max component size),
    shortest_path_to_known_fraud, and graph_risk_score. Merge with ring_features.
    """
    device_accounts, ip_accounts, merchant_accounts, account_connections = await get_tenant_graph_data(
        db, tenant_id, since_days=since_days
    )
    G = _build_nx_graph(device_accounts, ip_accounts, merchant_accounts, account_connections)
    fraud_accounts = await _get_known_fraud_accounts(db, tenant_id, since_days=min(90, since_days + 60))

    fraud_cluster_size = float(_max_connected_component_size(G))
    start_ids = [f"acc:{customer_id}"]
    if device_id:
        start_ids.append(f"dev:{device_id}")
    if ip_address:
        start_ids.append(f"ip:{ip_address}")
    shortest_path = _shortest_path_to_fraud(G, start_ids, fraud_accounts)

    out = dict(ring_features)
    out["fraud_cluster_size"] = max(ring_features.get("fraud_cluster_size", 1) or 1, fraud_cluster_size)
    out["shortest_path_to_known_fraud"] = shortest_path if shortest_path < 999 else 999.0
    out["graph_risk_score"] = compute_graph_risk_score(out)
    return out


async def update_graph_after_transaction(
    db: AsyncSession,
    tenant_id: str,
    customer_id: str,
    device_id: str | None,
    ip_address: str | None,
    tx_timestamp: datetime,
) -> None:
    """
    No-op here: entity maps are updated by fraud_ring.update_entity_maps.
    Optionally persist graph_risk_metrics snapshot for adaptive engine.
    """
    pass
