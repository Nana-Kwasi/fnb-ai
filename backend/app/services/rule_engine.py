"""
Rule-based fraud signals. Output 0.0–1.0 score for high-risk conditions.
Used in final risk: 0.6 * LGB + 0.3 * IF + 0.1 * rule_score.
"""
from typing import Any

# Default thresholds (can be overridden per tenant)
DEFAULT_AMOUNT_THRESHOLD = 50_000.0
DEFAULT_VELOCITY_1H_THRESHOLD = 10
DEFAULT_SUSPICIOUS_COUNTRIES = frozenset({"XX", "RU", "KP", "IR"})  # example; configure per bank


def rule_score(
    amount: float,
    is_new_device: float,
    is_new_location: float,
    txn_count_1h: float,
    location_country: str | None,
    amount_threshold: float = DEFAULT_AMOUNT_THRESHOLD,
    velocity_1h_threshold: int = DEFAULT_VELOCITY_1H_THRESHOLD,
    suspicious_countries: frozenset[str] | None = None,
) -> tuple[float, list[str]]:
    """
    Returns (rule_score 0.0–1.0, list of triggered reason strings).
    """
    reasons: list[str] = []
    score = 0.0

    if amount >= amount_threshold:
        reasons.append("Transaction amount above threshold")
        score = max(score, 0.4)

    if is_new_device and amount >= (amount_threshold * 0.2):
        reasons.append("New device + large transfer")
        score = max(score, 0.7)

    if location_country and (suspicious_countries or DEFAULT_SUSPICIOUS_COUNTRIES):
        if location_country.upper() in (suspicious_countries or DEFAULT_SUSPICIOUS_COUNTRIES):
            reasons.append("Transaction from high-risk country")
            score = max(score, 0.8)

    if txn_count_1h >= velocity_1h_threshold:
        reasons.append("Rapid transaction velocity")
        score = max(score, 0.5)

    if is_new_location and is_new_device:
        reasons.append("New device and new location")
        score = max(score, 0.6)

    return min(score, 1.0), reasons
