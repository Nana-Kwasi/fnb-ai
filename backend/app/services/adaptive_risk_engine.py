"""
Adaptive Risk AI: self-learning risk engine that adjusts fraud thresholds
based on current fraud patterns (fraud rate, cluster growth, etc.).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Tuple

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fraud_extra import FraudOutcome
from app.models.transaction import Transaction

SYSTEM_STATE_NORMAL = "NORMAL"
SYSTEM_STATE_ELEVATED = "ELEVATED_RISK"
SYSTEM_STATE_HIGH_ATTACK = "HIGH_ATTACK"

FRAUD_RATE_1H_HIGH = 0.05
FRAUD_RATE_1H_ELEVATED = 0.02
FRAUD_RATE_24H_HIGH = 0.04
FRAUD_RATE_24H_ELEVATED = 0.015
MIN_CONFIRMED_OUTCOME_SAMPLE_1H = 25
MIN_CONFIRMED_OUTCOME_SAMPLE_24H = 100


async def get_adaptive_metrics(
    db: AsyncSession,
    tenant_id: str,
) -> Dict[str, float]:
    """Compute adaptive metrics using confirmed outcomes, with safe fallback."""
    now = datetime.utcnow()
    one_h_ago = now - timedelta(hours=1)
    one_d_ago = now - timedelta(days=1)
    base_outcomes = and_(FraudOutcome.tenant_id == tenant_id)

    outcomes_1h = (
        await db.execute(
            select(
                func.count(FraudOutcome.id),
                func.coalesce(func.sum(case((FraudOutcome.classification == "CONFIRMED_FRAUD", 1), else_=0)), 0),
            ).where(base_outcomes, FraudOutcome.created_at >= one_h_ago)
        )
    ).one()
    outcomes_24h = (
        await db.execute(
            select(
                func.count(FraudOutcome.id),
                func.coalesce(func.sum(case((FraudOutcome.classification == "CONFIRMED_FRAUD", 1), else_=0)), 0),
            ).where(base_outcomes, FraudOutcome.created_at >= one_d_ago)
        )
    ).one()

    total_1h_outcomes = float(outcomes_1h[0] or 0)
    fraud_1h_outcomes = float(outcomes_1h[1] or 0)
    total_24h_outcomes = float(outcomes_24h[0] or 0)
    fraud_24h_outcomes = float(outcomes_24h[1] or 0)

    has_sufficient_1h = total_1h_outcomes >= MIN_CONFIRMED_OUTCOME_SAMPLE_1H
    has_sufficient_24h = total_24h_outcomes >= MIN_CONFIRMED_OUTCOME_SAMPLE_24H

    if has_sufficient_1h and has_sufficient_24h:
        fraud_rate_1h = fraud_1h_outcomes / max(total_1h_outcomes, 1.0)
        fraud_rate_24h = fraud_24h_outcomes / max(total_24h_outcomes, 1.0)
    else:
        # Confirmed-outcomes only: stay conservative when there isn't enough labelled truth.
        fraud_rate_1h = 0.0
        fraud_rate_24h = 0.0

    # Ops-facing fallback metric: transaction challenge/decline rate in 24h.
    tx_base = and_(Transaction.tenant_id == tenant_id, Transaction.tx_timestamp >= one_d_ago)
    tx_tot_24h = (await db.execute(select(func.count(Transaction.id)).where(tx_base))).scalar() or 0
    tx_failed_24h = (
        await db.execute(
            select(func.count(Transaction.id)).where(
                tx_base,
                Transaction.status.in_(["DECLINED", "PENDING_REVIEW"]),
            )
        )
    ).scalar() or 0
    failed_tx_rate = float(tx_failed_24h) / (float(tx_tot_24h) or 1.0)
    device_cluster_growth = 0.0
    suspicious_country_activity = 0.0
    graph_cluster_growth = 0.0

    return {
        "fraud_rate_1h": fraud_rate_1h,
        "fraud_rate_24h": fraud_rate_24h,
        "failed_transactions_rate": failed_tx_rate,
        "device_cluster_growth_rate": device_cluster_growth,
        "suspicious_country_activity": suspicious_country_activity,
        "graph_cluster_growth": graph_cluster_growth,
    }


def get_system_state(metrics: Dict[str, float]) -> str:
    """NORMAL | ELEVATED_RISK | HIGH_ATTACK."""
    fr1 = metrics.get("fraud_rate_1h", 0.0) or 0.0
    fr24 = metrics.get("fraud_rate_24h", 0.0) or 0.0
    if fr1 >= FRAUD_RATE_1H_HIGH or fr24 >= FRAUD_RATE_24H_HIGH:
        return SYSTEM_STATE_HIGH_ATTACK
    if fr1 >= FRAUD_RATE_1H_ELEVATED or fr24 >= FRAUD_RATE_24H_ELEVATED:
        return SYSTEM_STATE_ELEVATED
    return SYSTEM_STATE_NORMAL


def get_adjusted_thresholds(
    base_block: float,
    base_otp: float,
    system_state: str,
) -> Tuple[float, float]:
    """Tighten thresholds during attack; use base in NORMAL."""
    if system_state == SYSTEM_STATE_HIGH_ATTACK:
        return (max(0.5, base_block - 0.10), max(0.3, base_otp - 0.10))
    if system_state == SYSTEM_STATE_ELEVATED:
        return (max(0.55, base_block - 0.05), max(0.35, base_otp - 0.05))
    return (base_block, base_otp)


def get_adaptive_risk_modifier(system_state: str) -> float:
    """0.0–1.0 modifier for ensemble (e.g. 0.05 weight). Higher when attack."""
    if system_state == SYSTEM_STATE_HIGH_ATTACK:
        return 0.8
    if system_state == SYSTEM_STATE_ELEVATED:
        return 0.4
    return 0.0


def get_adaptive_weights(
    system_state: str,
    base_graph_weight: float = 0.15,
    base_rule_weight: float = 0.20,
) -> Tuple[float, float]:
    """Optionally increase graph/rule weight during attack."""
    if system_state == SYSTEM_STATE_HIGH_ATTACK:
        return (min(0.25, base_graph_weight + 0.05), min(0.25, base_rule_weight + 0.05))
    if system_state == SYSTEM_STATE_ELEVATED:
        return (min(0.20, base_graph_weight + 0.02), min(0.22, base_rule_weight + 0.02))
    return (base_graph_weight, base_rule_weight)


async def get_adaptive_state_and_modifier(
    db: AsyncSession,
    tenant_id: str,
    base_block: float,
    base_otp: float,
) -> Tuple[str, float, float, float, float]:
    """
    Returns: system_state, block_threshold, otp_threshold, adaptive_risk_modifier, graph_weight_override.
    graph_weight_override is 0 to use policy weight; else use this weight.
    """
    metrics = await get_adaptive_metrics(db, tenant_id)
    state = get_system_state(metrics)
    block_th, otp_th = get_adjusted_thresholds(base_block, base_otp, state)
    modifier = get_adaptive_risk_modifier(state)
    graph_w, _ = get_adaptive_weights(state)
    return (state, block_th, otp_th, modifier, graph_w)
