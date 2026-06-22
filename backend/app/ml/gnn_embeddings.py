"""
Graph Neural Network (GNN) embeddings for fraud detection.

Implements a lightweight graph-based account risk scoring system using
NetworkX. For each customer node, computes risk signals derived from
the transaction graph structure:

  - Degree centrality (how connected is this account?)
  - Weighted fraud adjacency (how many fraud-confirmed neighbours?)
  - PageRank-style propagation (guilt-by-association)
  - Connected component size (fraud ring membership)

These features approximate what a full GNN (GraphSAGE, GAT) would learn
and work without PyTorch Geometric. Upgrade path: replace
_compute_graph_features() with a GNN inference call.

Usage:
    from app.ml.gnn_embeddings import build_account_graph, get_gnn_risk_score
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

import networkx as nx

# In-memory graph cache: rebuilt periodically during training
# key: tenant_id → (graph, fraud_set, built_at)
_GRAPH_CACHE: Dict[str, Tuple[nx.Graph, set, float]] = {}
_GRAPH_TTL_SECONDS = 3600  # rebuild every hour


def build_transaction_graph(
    edges: List[Tuple[str, str, float]],  # (node_a, node_b, weight)
    fraud_nodes: set[str],
) -> nx.Graph:
    """
    Build a weighted undirected transaction graph.

    Nodes represent accounts/devices/IPs (prefixed: 'acct:X', 'dev:X', 'ip:X').
    Edges represent co-occurrence (shared device, shared IP, P2P transfer).
    """
    G = nx.Graph()
    for a, b, w in edges:
        if G.has_edge(a, b):
            G[a][b]["weight"] = G[a][b]["weight"] + w
        else:
            G.add_edge(a, b, weight=w)
    nx.set_node_attributes(G, {n: {"is_fraud": n in fraud_nodes} for n in G.nodes()})
    return G


def _fraud_neighbor_ratio(G: nx.Graph, node: str, fraud_set: set) -> float:
    """Fraction of direct neighbours that are confirmed fraud nodes."""
    if node not in G:
        return 0.0
    neighbors = list(G.neighbors(node))
    if not neighbors:
        return 0.0
    fraud_neighbors = sum(1 for n in neighbors if n in fraud_set)
    return fraud_neighbors / len(neighbors)


def _weighted_fraud_proximity(G: nx.Graph, node: str, fraud_set: set, max_hops: int = 3) -> float:
    """
    Guilt-by-association score: weighted sum of inverse-distance to fraud nodes.
    Score = sum(1 / hop_distance) for all fraud nodes reachable within max_hops.
    Capped at 1.0.
    """
    if node not in G or not fraud_set:
        return 0.0
    total = 0.0
    visited = {node}
    frontier = {node}
    for hop in range(1, max_hops + 1):
        next_frontier = set()
        for n in frontier:
            for nb in G.neighbors(n):
                if nb not in visited:
                    next_frontier.add(nb)
                    visited.add(nb)
                    if nb in fraud_set:
                        total += 1.0 / hop
        frontier = next_frontier
        if not frontier:
            break
    return min(1.0, total)


def _connected_component_fraud_density(G: nx.Graph, node: str, fraud_set: set) -> Tuple[int, float]:
    """Size of the connected component containing this node and fraction that are fraud."""
    if node not in G:
        return 1, 0.0
    component = nx.node_connected_component(G, node)
    size = len(component)
    fraud_in_component = sum(1 for n in component if n in fraud_set)
    density = fraud_in_component / size if size > 0 else 0.0
    return size, density


def compute_gnn_account_risk(
    G: nx.Graph,
    fraud_set: set,
    account_node: str,
) -> Dict[str, float]:
    """
    Compute GNN-style risk features for a single account node.

    Returns:
        gnn_account_risk_score  – composite 0.0–1.0 risk score
        gnn_fraud_neighbor_ratio
        gnn_fraud_proximity
        gnn_component_size      – log-scaled
        gnn_component_fraud_density
        gnn_degree_centrality
    """
    if account_node not in G:
        return {
            "gnn_account_risk_score": 0.0,
            "gnn_fraud_neighbor_ratio": 0.0,
            "gnn_fraud_proximity": 0.0,
            "gnn_component_size": 0.0,
            "gnn_component_fraud_density": 0.0,
            "gnn_degree_centrality": 0.0,
        }

    fraud_neighbor_ratio = _fraud_neighbor_ratio(G, account_node, fraud_set)
    fraud_proximity = _weighted_fraud_proximity(G, account_node, fraud_set)
    component_size, component_fraud_density = _connected_component_fraud_density(G, account_node, fraud_set)
    degree = G.degree(account_node)
    max_possible_degree = max(len(G) - 1, 1)
    degree_centrality = degree / max_possible_degree

    # Log-scale component size: 1 node → 0.0, 100 nodes → ~0.5, 10000 → ~1.0
    log_component = min(1.0, math.log1p(component_size) / math.log1p(10000))

    # Composite risk: heavily weight direct fraud neighbours and proximity
    composite = (
        0.40 * fraud_neighbor_ratio
        + 0.30 * fraud_proximity
        + 0.15 * component_fraud_density
        + 0.10 * log_component
        + 0.05 * degree_centrality
    )

    return {
        "gnn_account_risk_score": round(min(1.0, composite), 5),
        "gnn_fraud_neighbor_ratio": round(fraud_neighbor_ratio, 5),
        "gnn_fraud_proximity": round(fraud_proximity, 5),
        "gnn_component_size": round(log_component, 5),
        "gnn_component_fraud_density": round(component_fraud_density, 5),
        "gnn_degree_centrality": round(degree_centrality, 5),
    }


async def get_gnn_risk_score_from_db(
    db,
    tenant_id: str,
    customer_id: str,
    device_id: str | None = None,
) -> float:
    """
    Retrieve or compute the GNN-based risk score for a customer at score time.

    Uses a cached graph rebuilt hourly. Falls back to 0.0 (neutral) on any error.
    """
    try:
        from sqlalchemy import select, and_
        from app.models import Transaction, FraudOutcome
        from datetime import datetime, timedelta

        cache_entry = _GRAPH_CACHE.get(str(tenant_id))
        now = time.time()

        if cache_entry is None or (now - cache_entry[2]) > _GRAPH_TTL_SECONDS:
            # Rebuild graph for this tenant from last 30 days of transactions
            since = datetime.utcnow() - timedelta(days=30)
            txn_result = await db.execute(
                select(
                    Transaction.customer_id,
                    Transaction.device_id,
                    Transaction.ip_address_hash,
                    Transaction.id,
                ).where(
                    and_(
                        Transaction.tenant_id == tenant_id,
                        Transaction.tx_timestamp >= since,
                    )
                ).limit(50_000)
            )
            txn_rows = txn_result.all()

            fraud_result = await db.execute(
                select(Transaction.customer_id).join(
                    FraudOutcome, FraudOutcome.transaction_id == Transaction.id
                ).where(
                    and_(
                        Transaction.tenant_id == tenant_id,
                        FraudOutcome.classification == "CONFIRMED_FRAUD",
                        Transaction.tx_timestamp >= since,
                    )
                )
            )
            fraud_customers = {f"acct:{str(r[0])}" for r in fraud_result.all()}

            edges: List[Tuple[str, str, float]] = []
            for cust_id, dev_id, ip_hash, _tx_id in txn_rows:
                acct_node = f"acct:{str(cust_id)}"
                if dev_id:
                    edges.append((acct_node, f"dev:{dev_id}", 1.0))
                if ip_hash:
                    edges.append((acct_node, f"ip:{ip_hash}", 0.5))

            G = build_transaction_graph(edges, fraud_customers)
            _GRAPH_CACHE[str(tenant_id)] = (G, fraud_customers, now)
            # Evict other tenants if too many cached
            if len(_GRAPH_CACHE) > 50:
                oldest = min(_GRAPH_CACHE, key=lambda k: _GRAPH_CACHE[k][2])
                _GRAPH_CACHE.pop(oldest, None)
        else:
            G, fraud_customers, _ = cache_entry

        account_node = f"acct:{str(customer_id)}"
        result = compute_gnn_account_risk(G, fraud_customers, account_node)
        return result["gnn_account_risk_score"]

    except Exception:
        return 0.0


def build_training_graph_features(
    edges: List[Tuple[str, str, float]],
    fraud_nodes: set[str],
    target_nodes: List[str],
) -> Dict[str, Dict[str, float]]:
    """
    Batch-compute GNN features for a list of nodes during training.
    Returns: {node_id: {feature_name: value, ...}}
    """
    G = build_transaction_graph(edges, fraud_nodes)
    return {node: compute_gnn_account_risk(G, fraud_nodes, node) for node in target_nodes}


def invalidate_tenant_graph(tenant_id: str) -> None:
    _GRAPH_CACHE.pop(str(tenant_id), None)
