"""
Tenant-configurable rule-based fraud signals.

Output 0.0–1.0 score for high-risk conditions plus human-readable reasons.
Used in final risk: model_weight * LGB + iso_weight * IF + rule_weight * rule_score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FraudRule

# Default thresholds (can be overridden per tenant / rule)
DEFAULT_AMOUNT_THRESHOLD = 50_000.0
DEFAULT_VELOCITY_1H_THRESHOLD = 10
DEFAULT_VELOCITY_ZSCORE_THRESHOLD = 2.0
DEFAULT_CHALLENGED_1H_THRESHOLD = 3
DEFAULT_SUSPICIOUS_COUNTRIES = frozenset({"XX", "RU", "KP", "IR"})  # example; configure per bank


@dataclass
class CompiledRule:
    rule_id: str
    weight: float
    reason_code: str
    func: Callable[[Dict[str, Any]], bool]


def _compile_expression(expr: str) -> Callable[[Dict[str, Any]], bool]:
    """
    Compile a simple Python expression into a predicate over the feature dict.

    Supported variables:
        amount, is_new_device, is_new_location, txn_count_1h, location_country,
        suspicious_countries, velocity_1h_threshold, amount_threshold, ...

    We deliberately restrict the eval namespace for safety.
    """
    code = compile(expr, "<fraud_rule>", "eval")

    def predicate(ctx: Dict[str, Any]) -> bool:
        safe_globals = {
            "__builtins__": {},
        }
        # Locals: all feature values plus helper sets / thresholds
        return bool(eval(code, safe_globals, ctx))

    return predicate


async def _load_rules(
    db: AsyncSession,
    tenant_id: str | None,
) -> List[CompiledRule]:
    """
    Load enabled rules for a tenant (and global rules where tenant_id is NULL),
    compile them into predicates.
    """
    conds = [FraudRule.enabled.is_(True)]
    if tenant_id is not None:
        conds.append(
            and_(
                (FraudRule.tenant_id == tenant_id) | (FraudRule.tenant_id.is_(None)),
            )
        )
    stmt = select(FraudRule).where(and_(*conds))
    res = await db.execute(stmt)
    rules: List[CompiledRule] = []
    for r in res.scalars():
        try:
            func = _compile_expression(r.condition_expression)
        except Exception:
            continue
        rules.append(
            CompiledRule(
                rule_id=r.rule_id,
                weight=float(r.weight or 0.5),
                reason_code=r.reason_code,
                func=func,
            )
        )
    return rules


async def rule_score(
    db: AsyncSession,
    tenant_id: str | None,
    feature_vector: Dict[str, Any],
    amount_threshold: float = DEFAULT_AMOUNT_THRESHOLD,
    velocity_1h_threshold: int = DEFAULT_VELOCITY_1H_THRESHOLD,
    suspicious_countries: Iterable[str] | None = None,
    policy: Dict[str, Any] | None = None,
) -> Tuple[float, List[str]]:
    """
    Evaluate all configured rules against the feature vector.

    Returns:
        (rule_score 0.0–1.0, list of triggered reason strings)
    """
    rules = await _load_rules(db, tenant_id)
    reasons: List[str] = []
    score = 0.0
    policy_cfg = policy or {}
    velocity_zscore_threshold = float(
        policy_cfg.get("velocity_zscore_threshold", DEFAULT_VELOCITY_ZSCORE_THRESHOLD)
    )
    challenged_1h_threshold = int(
        policy_cfg.get("challenged_txn_1h_threshold", DEFAULT_CHALLENGED_1H_THRESHOLD)
    )

    # Backwards-compatible defaults if no DB rules exist
    if not rules:
        loc = (feature_vector.get("location_country") or "").upper() or None
        amount = float(feature_vector.get("amount", 0) or 0.0)
        is_new_device = float(feature_vector.get("is_new_device", 0) or 0.0)
        is_new_location = float(feature_vector.get("is_new_location", 0) or 0.0)
        txn_count_1h = float(feature_vector.get("txn_count_1h", 0) or 0.0)
        txn_count_1h_challenged = float(feature_vector.get("txn_count_1h_challenged", 0) or 0.0)
        txn_velocity_zscore_1h = float(feature_vector.get("txn_velocity_zscore_1h", 0) or 0.0)
        sc = frozenset(suspicious_countries or DEFAULT_SUSPICIOUS_COUNTRIES)

        # Existing heuristic rules
        if amount >= amount_threshold:
            reasons.append("Transaction amount above threshold")
            score = max(score, 0.4)

        if is_new_device and amount >= (amount_threshold * 0.2):
            reasons.append("New device + large transfer")
            score = max(score, 0.7)

        if loc and loc in sc:
            reasons.append("Transaction from high-risk country")
            score = max(score, 0.8)

        # Pragmatic velocity signal:
        # require either a baseline spike or repeated challenged attempts
        # so we do not over-trigger on small normal bursts.
        if txn_count_1h >= velocity_1h_threshold and (
            txn_velocity_zscore_1h >= velocity_zscore_threshold
            or txn_count_1h_challenged >= challenged_1h_threshold
        ):
            reasons.append("Transaction frequency spike versus recent baseline")
            score = max(score, 0.5)
        elif txn_count_1h >= velocity_1h_threshold * 1.5:
            reasons.append("Rapid transaction velocity")
            score = max(score, 0.5)

        if txn_count_1h_challenged >= challenged_1h_threshold:
            reasons.append("Multiple challenged transactions in the last hour")
            score = max(score, 0.55)

        if is_new_location and is_new_device:
            reasons.append("New device and new location")
            score = max(score, 0.6)

        # New network / fingerprint hard rules
        fp_vel_1h = float(feature_vector.get("fingerprint_velocity_1h", 0) or 0.0)
        if fp_vel_1h >= 3:
            reasons.append("Repeated identical transaction pattern (fingerprint velocity)")
            score = max(score, 0.7)

        dev_accounts_7d = float(feature_vector.get("accounts_seen_for_device_7d", 0) or 0.0)
        if dev_accounts_7d >= 5:
            reasons.append("Device seen on many accounts in 7d")
            score = max(score, 0.7)

        merchant_risk = float(feature_vector.get("merchant_risk_score", 0) or 0.0)
        if merchant_risk >= 0.7:
            reasons.append("High-risk merchant based on historical fraud")
            score = max(score, 0.6)

        return min(score, 1.0), reasons

    ctx: Dict[str, Any] = dict(feature_vector)
    ctx.setdefault("amount_threshold", amount_threshold)
    ctx.setdefault("velocity_1h_threshold", velocity_1h_threshold)
    ctx.setdefault("velocity_zscore_threshold", velocity_zscore_threshold)
    ctx.setdefault("challenged_txn_1h_threshold", challenged_1h_threshold)
    ctx.setdefault("suspicious_countries", frozenset(suspicious_countries or DEFAULT_SUSPICIOUS_COUNTRIES))

    for r in rules:
        try:
            if r.func(ctx):
                reasons.append(r.reason_code)
                score = max(score, float(r.weight or 0.0))
        except Exception:
            continue

    return min(score, 1.0), reasons
