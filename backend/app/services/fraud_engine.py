import os
import time
from pathlib import Path
from typing import Dict, Any

import numpy as np

import logging

from datetime import datetime, timedelta
from sqlalchemy import select

from app.config import settings
from app.services.feature_engine import FEATURE_NAMES
from app.services.fraud_ring import compute_network_risk_score
from app.services.adaptive_risk_engine import get_adaptive_state_and_modifier
from app.services.rule_engine import (
    rule_score as rule_engine_score,
    DEFAULT_SUSPICIOUS_COUNTRIES,
    DEFAULT_AMOUNT_THRESHOLD,
    DEFAULT_VELOCITY_1H_THRESHOLD,
)
from app.models.fraud import FraudScore

MODEL_VERSION = "1.0.0"
logger = logging.getLogger(__name__)
REASON_MAP = {
    "amount": {"high": "Unusual transaction amount", "low": "Transaction amount in normal range"},
    "amount_vs_avg_ratio": {
        "high": "Transaction amount significantly above your normal spending",
        "low": "Transaction amount consistent with your typical spending",
    },
    "is_new_device": {
        "high": "Transaction from an unrecognized device",
        "low": "Transaction from a known device",
    },
    "txn_count_1h": {"high": "Higher-than-usual transaction frequency in the last hour", "low": "Normal transaction frequency"},
    "txn_count_24h": {"high": "Elevated transaction count in last 24 hours", "low": "Typical daily activity"},
    "customer_risk_score": {"high": "Account has elevated risk history", "low": "Account risk within normal range"},
    "merchant_cat_risk": {"high": "Higher-risk merchant category", "low": "Standard merchant category"},
    "days_since_last_txn": {"high": "First transaction after a long period", "low": "Consistent with recent activity"},
}

_lgb_model = None
_sklearn_model = None
_iso_model = None
_shap_explainer = None
_models_loaded = False
_model_load_mode: str = "unknown"
_model_load_errors: list[str] = []
_DYN_THRESH_CACHE: dict[tuple, tuple[float, float, float]] = {}  # key -> (block_th, otp_th, expires_at)
_DYN_THRESH_CACHE_TTL_SECONDS = 60


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _get_models_path() -> Path:
    env_path = os.getenv("MODEL_PATH", "").strip()
    if env_path and env_path != "/models":
        return Path(env_path).parent / "fraud"
    return Path(__file__).resolve().parents[3] / "models" / "fraud"


def _ensure_models():
    global _lgb_model, _sklearn_model, _iso_model, _shap_explainer, _models_loaded
    global _model_load_mode, _model_load_errors
    if _models_loaded:
        return
    _model_load_errors = []
    base = _get_models_path()
    lgb_path = base / "lgb_fraud.txt"
    sklearn_path = base / "sklearn_fraud.joblib"
    iso_path = base / "isolation_forest.joblib"
    import joblib
    strict_loading = _env_bool("STRICT_MODEL_LOADING", bool(settings.strict_model_loading))
    heuristic_allowed = _env_bool("ALLOW_HEURISTIC_FALLBACK", bool(settings.allow_heuristic_fallback))
    try:
        import lightgbm as lgb
        if lgb_path.exists():
            _lgb_model = lgb.Booster(model_file=str(lgb_path))
            import shap
            _shap_explainer = shap.TreeExplainer(_lgb_model)
    except Exception:
        if strict_loading:
            raise RuntimeError(f"Failed to load LightGBM fraud model from {lgb_path}.")
        _model_load_errors.append(f"LightGBM load failed (strict off): {lgb_path}")
    if _lgb_model is None and sklearn_path.exists():
        try:
            _sklearn_model = joblib.load(sklearn_path)
        except Exception:
            if strict_loading:
                raise RuntimeError(f"Failed to load sklearn fraud model from {sklearn_path}.")
            _model_load_errors.append(f"Sklearn load failed (strict off): {sklearn_path}")
    if iso_path.exists():
        try:
            _iso_model = joblib.load(iso_path)
        except Exception:
            if strict_loading:
                raise RuntimeError(f"Failed to load isolation forest model from {iso_path}.")
            _model_load_errors.append(f"Isolation forest load failed (strict off): {iso_path}")
    if _lgb_model is None and _sklearn_model is None:
        msg = (
            "No primary fraud model loaded. "
            f"Checked {lgb_path} and {sklearn_path}. "
            "Set STRICT_MODEL_LOADING=false only if you intentionally want fallback mode."
        )
        if strict_loading:
            raise RuntimeError(msg)
        if heuristic_allowed:
            _model_load_mode = "heuristic"
            logger.warning("Fraud scoring using heuristic fallback (models not loaded).")
        else:
            _model_load_mode = "none"
            logger.error(
                "Fraud models not loaded and heuristic fallback disabled. "
                "Set ALLOW_HEURISTIC_FALLBACK=true or restore model files."
            )
    else:
        _model_load_mode = "model"
    _models_loaded = True


def get_fraud_model_status() -> Dict[str, Any]:
    """Expose model load mode/errors for health checks and debugging."""
    return {
        "models_loaded": bool(_models_loaded),
        "mode": _model_load_mode,
        "has_lgb": _lgb_model is not None,
        "has_sklearn": _sklearn_model is not None,
        "has_iso": _iso_model is not None,
        "errors": list(_model_load_errors),
    }


def ensure_fraud_models_loaded() -> Dict[str, Any]:
    """Fail-fast (when strict) by loading fraud models during app startup."""
    _ensure_models()
    return get_fraud_model_status()


def _fraud_policy_from_tenant(tone_config: dict | None) -> Dict[str, Any]:
    """
    Extract per-tenant fraud policy weights/thresholds from TenantBank.tone_config.

    Falls back to sensible defaults if not set:
        model_weight=0.5, iso_weight=0.2, rule_weight=0.2, network_weight=0.1,
        block_threshold=0.80, otp_threshold=0.55, shadow_mode=False.
    """
    cfg = tone_config or {}
    pw = cfg.get("fraud_policy") or {}
    model_w = float(pw.get("model_weight", 0.5))
    iso_w = float(pw.get("iso_weight", 0.2))
    rule_w = float(pw.get("rule_weight", 0.2))
    network_w = float(pw.get("network_weight", 0.1))
    graph_w = float(pw.get("graph_weight", 0.15))
    adaptive_w = float(pw.get("adaptive_weight", 0.05))
    total = model_w + iso_w + rule_w + network_w
    if total <= 0:
        model_w, iso_w, rule_w, network_w = 0.5, 0.2, 0.2, 0.1
    else:
        model_w = model_w / total
        iso_w = iso_w / total
        rule_w = rule_w / total
        network_w = network_w / total
    # graph/adaptive stay explicit components; clamp to sane ranges.
    graph_w = min(max(graph_w, 0.0), 0.30)
    adaptive_w = min(max(adaptive_w, 0.0), 0.20)

    block_th = float(pw.get("fraud_block_threshold", cfg.get("fraud_block_threshold", 0.80)))
    otp_th = float(pw.get("fraud_otp_threshold", cfg.get("fraud_otp_threshold", 0.55)))

    shadow_mode = bool(pw.get("shadow_mode", cfg.get("fraud_shadow_mode", False)))

    return {
        "model_weight": model_w,
        "iso_weight": iso_w,
        "rule_weight": rule_w,
        "network_weight": network_w,
        "graph_weight": graph_w,
        "adaptive_weight": adaptive_w,
        "block_threshold": block_th,
        "otp_threshold": otp_th,
        "shadow_mode": shadow_mode,
    }


def _derive_customer_segment(fv: dict, fraud_policy_cfg: dict | None = None) -> str:
    """
    Lightweight segmentation based on current feature vector.

    Segments:
        - LOW_RISK_LONG_TENURE
        - NEW_CUSTOMER
        - HIGH_RISK_REGION
        - HIGH_VELOCITY_USER
    """
    risk = float(fv.get("customer_risk_score", 0.0) or 0.0)
    days_since = float(fv.get("days_since_last_txn", 999.0) or 999.0)
    txn_24h = float(fv.get("txn_count_24h", 0.0) or 0.0)
    country = (fv.get("location_country") or "").upper()

    cfg = fraud_policy_cfg or {}
    suspicious_countries = frozenset(cfg.get("heuristic_suspicious_countries") or DEFAULT_SUSPICIOUS_COUNTRIES)
    velocity_1h_threshold = int(cfg.get("heuristic_velocity_1h_threshold", DEFAULT_VELOCITY_1H_THRESHOLD))

    high_risk_country = country in suspicious_countries
    high_velocity = txn_24h >= float(velocity_1h_threshold) * 2

    # New or thin-file customer: very few recent transactions
    if days_since > 300 or (txn_24h == 0 and days_since > 60):
        return "NEW_CUSTOMER"
    # Long-tenure, consistently low-risk profile
    if risk < 0.2 and days_since < 120 and not high_velocity and not high_risk_country:
        return "LOW_RISK_LONG_TENURE"
    if high_risk_country:
        return "HIGH_RISK_REGION"
    if high_velocity:
        return "HIGH_VELOCITY_USER"
    # Fallback based on risk level
    if risk >= 0.7:
        return "HIGH_RISK_REGION"
    return "NEW_CUSTOMER" if risk > 0.4 else "LOW_RISK_LONG_TENURE"


def _feature_vector_to_array(fv: dict) -> np.ndarray:
    return np.array([[fv.get(name, 0.0) for name in FEATURE_NAMES]], dtype=np.float32)


def _score_lgb(fv: dict) -> float:
    X = _feature_vector_to_array(fv)
    if _lgb_model is not None:
        return float(_lgb_model.predict(X)[0])
    if _sklearn_model is not None:
        return float(_sklearn_model.predict_proba(X)[0][1])
    if not _env_bool("ALLOW_HEURISTIC_FALLBACK", bool(settings.allow_heuristic_fallback)):
        raise RuntimeError(
            "Fraud model unavailable and heuristic fallback is disabled. "
            "Set ALLOW_HEURISTIC_FALLBACK=true only for non-production recovery."
        )
    amount = fv.get("amount", 0)
    ratio = fv.get("amount_vs_avg_ratio", 1.0)
    new_dev = fv.get("is_new_device", 0)
    txn_1h = fv.get("txn_count_1h", 0)
    return min(0.95, 0.1 + (amount / 50000) * 0.2 + ratio * 0.15 + new_dev * 0.25 + min(txn_1h, 5) * 0.08)


async def _rule_score_from_fv(
    db,
    tenant_id: str | None,
    fv: dict,
    tenant_tone_config: dict | None = None,
) -> tuple[float, list[str]]:
    fraud_policy = ((tenant_tone_config or {}).get("fraud_policy") or {})
    amount_threshold = float(fraud_policy.get("heuristic_amount_threshold", DEFAULT_AMOUNT_THRESHOLD))
    velocity_1h_threshold = int(fraud_policy.get("heuristic_velocity_1h_threshold", DEFAULT_VELOCITY_1H_THRESHOLD))
    suspicious_countries = fraud_policy.get("heuristic_suspicious_countries")
    return await rule_engine_score(
        db=db,
        tenant_id=tenant_id,
        feature_vector=fv,
        amount_threshold=amount_threshold,
        velocity_1h_threshold=velocity_1h_threshold,
        suspicious_countries=suspicious_countries,
        policy=fraud_policy,
    )


async def _stub_score(
    db,
    tenant_id: str | None,
    fv: dict,
    model_weight: float,
    iso_weight: float,
    rule_weight: float,
    network_weight: float = 0.0,
    tenant_tone_config: dict | None = None,
) -> tuple[float, float | None, float, float, list[str]]:
    lgbm = _score_lgb(fv)
    iso_anomaly = None
    if _iso_model is not None:
        X = _feature_vector_to_array(fv)
        pred = _iso_model.predict(X)[0]
        iso_anomaly = 1.0 if pred == -1 else 0.0
    rule_sc, rule_reasons = await _rule_score_from_fv(db, tenant_id, fv, tenant_tone_config=tenant_tone_config)
    network_risk = compute_network_risk_score(fv)
    return (
        round(lgbm, 5),
        round(iso_anomaly, 5) if iso_anomaly is not None else None,
        round(rule_sc, 5),
        round(network_risk, 5),
        rule_reasons,
    )


def _stub_explain(fv: dict) -> tuple[dict, list[str]]:
    farr = _feature_vector_to_array(fv)
    impacts = {
        "amount": float(fv.get("amount", 0)) / 10000.0,
        "amount_vs_avg_ratio": (float(fv.get("amount_vs_avg_ratio", 1)) - 1) * 0.1,
        "is_new_device": float(fv.get("is_new_device", 0)) * 0.2,
        "txn_count_1h": float(fv.get("txn_count_1h", 0)) * 0.05,
        "customer_risk_score": float(fv.get("customer_risk_score", 0)) * 0.15,
        "merchant_cat_risk": float(fv.get("merchant_cat_risk", 0)) * 0.2,
        "days_since_last_txn": 0.05 if fv.get("days_since_last_txn", 0) > 30 else -0.02,
    }
    shap_values = {name: impacts.get(name, 0.0) for name in FEATURE_NAMES}
    sorted_ = sorted(
        [(n, shap_values[n]) for n in FEATURE_NAMES],
        key=lambda x: abs(x[1]),
        reverse=True,
    )[:5]
    reason_codes = []
    for name, val in sorted_:
        if name not in REASON_MAP:
            continue
        if val > 0.05:
            reason_codes.append(REASON_MAP[name]["high"])
        elif val < -0.05:
            reason_codes.append(REASON_MAP[name]["low"])
    if not reason_codes:
        reason_codes.append("Transaction within normal patterns")
    return shap_values, reason_codes


async def _dynamic_thresholds_from_history(
    db,
    tenant_id: str | None,
    current_feature_vector: dict,
    fraud_policy_cfg: dict,
    segment: str,
    corridor: str | None,
    channel: str | None,
    base_block_threshold: float,
    base_otp_threshold: float,
) -> tuple[float, float, dict]:
    """
    Compute rolling percentile thresholds over recent historical FraudScore rows
    for the same (segment + corridor(country) + channel) bucket.
    """
    if not tenant_id:
        return base_block_threshold, base_otp_threshold, {"used": False}

    enabled = bool(fraud_policy_cfg.get("dynamic_threshold_enabled", True))
    if not enabled:
        return base_block_threshold, base_otp_threshold, {"used": False}

    lookback_days = int(fraud_policy_cfg.get("dynamic_threshold_lookback_days", 7))
    limit = int(fraud_policy_cfg.get("dynamic_threshold_limit", 5000))
    min_samples = int(fraud_policy_cfg.get("dynamic_threshold_min_samples", 300))
    block_q = float(fraud_policy_cfg.get("dynamic_threshold_block_percentile", 0.98))
    otp_q = float(fraud_policy_cfg.get("dynamic_threshold_otp_percentile", 0.90))
    max_block_delta = float(fraud_policy_cfg.get("dynamic_threshold_max_block_delta", 0.20))
    max_otp_delta = float(fraud_policy_cfg.get("dynamic_threshold_max_otp_delta", 0.20))

    # Defensive bounds (percentiles and ordering).
    block_q = min(max(block_q, 0.7), 0.999)
    otp_q = min(max(otp_q, 0.5), 0.999)
    if otp_q >= block_q:
        otp_q = max(0.01, block_q - 0.05)

    corridor_norm = (corridor or "").upper() or None
    channel_norm = channel or None
    cache_key = (
        tenant_id,
        segment,
        corridor_norm,
        channel_norm,
        lookback_days,
        limit,
        min_samples,
        block_q,
        otp_q,
        max_block_delta,
        max_otp_delta,
    )
    cached = _DYN_THRESH_CACHE.get(cache_key)
    if cached:
        block_cached, otp_cached, expires_at = cached
        if time.time() < expires_at:
            return block_cached, otp_cached, {
                "used": True,
                "cached": True,
                "segment": segment,
                "corridor": corridor_norm,
                "channel": channel_norm,
            }
        _DYN_THRESH_CACHE.pop(cache_key, None)

    now = datetime.utcnow()
    since = now - timedelta(days=lookback_days)

    rows = await db.execute(
        select(FraudScore.ensemble_score, FraudScore.feature_vector).where(
            FraudScore.tenant_id == tenant_id,
            FraudScore.created_at >= since,
        ).order_by(FraudScore.created_at.desc()).limit(limit)
    )
    hist_rows = rows.all()
    matched_scores: list[float] = []

    for ens, hist_fv in hist_rows:
        if not hist_fv:
            continue
        hist_corridor = (hist_fv.get("location_country") or "").upper() or None
        hist_channel = hist_fv.get("channel") or None
        if corridor_norm is not None and hist_corridor != corridor_norm:
            continue
        if corridor_norm is None and hist_corridor:
            continue
        if channel_norm is not None and hist_channel != channel_norm:
            continue
        if channel_norm is None and hist_channel:
            continue
        hist_segment = _derive_customer_segment(hist_fv, fraud_policy_cfg=fraud_policy_cfg)
        if hist_segment != segment:
            continue
        matched_scores.append(float(ens))

    if len(matched_scores) < min_samples:
        return base_block_threshold, base_otp_threshold, {
            "used": False,
            "matched_samples": len(matched_scores),
            "min_samples": min_samples,
        }

    arr = np.asarray(matched_scores, dtype=np.float32)
    dyn_block = float(np.quantile(arr, block_q))
    dyn_otp = float(np.quantile(arr, otp_q))

    # Ensure sensible ordering.
    dyn_otp = min(dyn_otp, dyn_block * 0.95)

    # Clamp to avoid huge drift vs tenant base thresholds.
    dyn_block = max(0.50, min(0.99, dyn_block))
    dyn_otp = max(0.25, min(0.90, dyn_otp))

    dyn_block = min(base_block_threshold + max_block_delta, max(base_block_threshold - max_block_delta, dyn_block))
    dyn_otp = min(base_otp_threshold + max_otp_delta, max(base_otp_threshold - max_otp_delta, dyn_otp))

    _DYN_THRESH_CACHE[cache_key] = (dyn_block, dyn_otp, time.time() + _DYN_THRESH_CACHE_TTL_SECONDS)
    return dyn_block, dyn_otp, {
        "used": True,
        "matched_samples": len(matched_scores),
        "lookback_days": lookback_days,
        "limit": limit,
        "block_percentile": block_q,
        "otp_percentile": otp_q,
    }


async def score_and_explain(
    db,
    tenant_id: str | None,
    feature_vector: dict,
    tenant_tone_config: dict | None = None,
) -> tuple[
    float,
    float | None,
    float,
    float,
    float,
    str,
    str,
    dict,
    list[str],
    list[str],
    float,
    dict,
]:
    """
    Returns: lgbm_score, iso_score, rule_score, network_risk_score, ensemble_score, decision, confidence,
             shap_values, reason_codes, rule_reasons, graph_risk_score.
    Decision uses per-tenant thresholds:
        BLOCK if score >= block_threshold;
        REQUEST_OTP if score >= otp_threshold;
        else APPROVE.
    """
    _ensure_models()
    policy = _fraud_policy_from_tenant(tenant_tone_config)
    fraud_policy_cfg = ((tenant_tone_config or {}) or {}).get("fraud_policy") or {}
    lgbm_score, iso_score, rule_score_val, network_risk_score, rule_reasons = await _stub_score(
        db,
        tenant_id,
        feature_vector,
        model_weight=policy["model_weight"],
        iso_weight=policy["iso_weight"],
        rule_weight=policy["rule_weight"],
        network_weight=policy.get("network_weight", 0.1),
        tenant_tone_config=tenant_tone_config,
    )
    graph_risk_score = float(feature_vector.get("graph_risk_score", 0) or 0)
    graph_weight = float(policy.get("graph_weight", 0.15))
    if tenant_id:
        try:
            _state, block_th_adj, otp_th_adj, adaptive_modifier, graph_weight_override = await get_adaptive_state_and_modifier(
                db, tenant_id, policy["block_threshold"], policy["otp_threshold"]
            )
            if graph_weight_override and graph_weight_override > 0:
                graph_weight = float(graph_weight_override)
        except Exception:
            block_th_adj = policy["block_threshold"]
            otp_th_adj = policy["otp_threshold"]
            adaptive_modifier = 0.0
    else:
        block_th_adj = policy["block_threshold"]
        otp_th_adj = policy["otp_threshold"]
        adaptive_modifier = 0.0
    model_weight = float(policy["model_weight"])
    iso_weight = float(policy["iso_weight"])
    rule_weight = float(policy["rule_weight"])
    network_weight = float(policy["network_weight"])
    adaptive_weight = float(policy["adaptive_weight"])
    core_sum = model_weight + iso_weight + rule_weight + network_weight
    if core_sum <= 0:
        model_weight, iso_weight, rule_weight, network_weight = 0.5, 0.2, 0.2, 0.1
        core_sum = 1.0
    primary_budget = max(0.0, 1.0 - graph_weight - adaptive_weight)
    model_weight = (model_weight / core_sum) * primary_budget
    iso_weight = (iso_weight / core_sum) * primary_budget
    rule_weight = (rule_weight / core_sum) * primary_budget
    network_weight = (network_weight / core_sum) * primary_budget

    ensemble_score = round(
        min(
            0.99999,
            model_weight * lgbm_score
            + iso_weight * (iso_score if iso_score is not None else 0.0)
            + rule_weight * rule_score_val
            + network_weight * network_risk_score
            + graph_weight * graph_risk_score
            + adaptive_weight * adaptive_modifier,
        ),
        5,
    )
    if _lgb_model is not None and _shap_explainer is not None:
        X = _feature_vector_to_array(feature_vector)
        shap_vals = _shap_explainer.shap_values(X)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1]
        else:
            shap_vals = shap_vals
        shap_values = dict(zip(FEATURE_NAMES, map(float, shap_vals[0])))
        sorted_ = sorted(
            [(FEATURE_NAMES[i], shap_vals[0][i]) for i in range(len(FEATURE_NAMES))],
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:5]
        reason_codes = []
        for name, val in sorted_:
            if name in REASON_MAP and val > 0.05:
                reason_codes.append(REASON_MAP[name]["high"])
            elif name in REASON_MAP and val < -0.05:
                reason_codes.append(REASON_MAP[name]["low"])
        if not reason_codes:
            reason_codes.append("Transaction within normal patterns")
    else:
        shap_values, reason_codes = _stub_explain(feature_vector)

    # Add safer and more specific velocity narratives.
    txn_velocity_zscore_1h = float(feature_vector.get("txn_velocity_zscore_1h", 0.0) or 0.0)
    txn_count_1h_challenged = float(feature_vector.get("txn_count_1h_challenged", 0.0) or 0.0)
    if txn_velocity_zscore_1h >= 2.0 and not any("frequency" in r.lower() for r in reason_codes):
        reason_codes.append("Transaction frequency spike versus your recent baseline")
    challenged_threshold = int((((tenant_tone_config or {}).get("fraud_policy") or {}).get("challenged_txn_1h_threshold", 3)))
    if txn_count_1h_challenged >= challenged_threshold:
        reason_codes.append("Multiple challenged transactions were observed in the last hour")

    # Segment/corridor/channel dynamic thresholds via rolling percentiles
    # (keeps corridor bias down without hardcoding fixed thresholds).
    corridor = (feature_vector.get("location_country") or "").upper() or None
    channel = feature_vector.get("channel") or None
    segment = _derive_customer_segment(feature_vector, fraud_policy_cfg=fraud_policy_cfg)
    block_threshold, otp_threshold, dynamic_meta = await _dynamic_thresholds_from_history(
        db=db,
        tenant_id=tenant_id,
        current_feature_vector=feature_vector,
        fraud_policy_cfg=fraud_policy_cfg,
        segment=segment,
        corridor=corridor,
        channel=channel,
        base_block_threshold=block_th_adj,
        base_otp_threshold=otp_th_adj,
    )
    risk = float(feature_vector.get("customer_risk_score", 0.0) or 0.0)

    if segment == "LOW_RISK_LONG_TENURE" and risk < 0.2:
        # Be more tolerant: reduce false positives
        block_threshold = min(0.99, block_threshold + 0.05)
        otp_threshold = min(0.99, otp_threshold + 0.05)
    elif segment in ("NEW_CUSTOMER", "HIGH_RISK_REGION", "HIGH_VELOCITY_USER") or risk >= 0.7:
        # Be stricter: catch more fraud at the cost of more challenges
        block_threshold = max(0.5, block_threshold - 0.1)
        otp_threshold = max(0.3, otp_threshold - 0.1)

    # Adjust thresholds further based on network_risk_score:
    #   - For low-risk, down-weight small network anomalies so they don't cause OTPs.
    #   - For high-risk segments, treat strong network signals as an extra reason to challenge/block.
    if network_risk_score is not None:
        if segment == "LOW_RISK_LONG_TENURE" and network_risk_score < 0.3:
            block_threshold = min(0.99, block_threshold + 0.02)
            otp_threshold = min(0.99, otp_threshold + 0.02)
        elif segment in ("NEW_CUSTOMER", "HIGH_RISK_REGION", "HIGH_VELOCITY_USER") and network_risk_score >= 0.6:
            block_threshold = max(0.4, block_threshold - 0.05)
            otp_threshold = max(0.25, otp_threshold - 0.05)

    if ensemble_score >= block_threshold:
        decision = "BLOCK"
        confidence = "HIGH"
    elif ensemble_score >= otp_threshold:
        decision = "REQUEST_OTP"
        confidence = "MEDIUM"
    else:
        # Multi-stage decisions below full OTP threshold
        # High rule-driven risk -> manual review
        if rule_score_val >= 0.8:
            decision = "MANUAL_REVIEW"
            confidence = "MEDIUM"
        # Borderline high risk -> soft decline (ask customer to re-attempt/confirm)
        elif ensemble_score >= otp_threshold * 0.8:
            decision = "SOFT_DECLINE"
            confidence = "LOW"
        # Slightly elevated risk -> limited approval (e.g. smaller limits / extra checks)
        elif ensemble_score >= otp_threshold * 0.5:
            decision = "LIMITED_APPROVAL"
            confidence = "MEDIUM"
        else:
            decision = "APPROVE"
            confidence = "HIGH" if ensemble_score < 0.3 else "MEDIUM"

    effective_policy_snapshot = {
        "segment": segment,
        "dynamic_thresholds": dynamic_meta,
        "effective_weights": {
            "model_weight": float(model_weight),
            "iso_weight": float(iso_weight),
            "rule_weight": float(rule_weight),
            "network_weight": float(network_weight),
            "graph_weight": float(graph_weight),
            "adaptive_weight": float(adaptive_weight),
        },
        "thresholds": {
            "block_threshold": float(block_threshold),
            "otp_threshold": float(otp_threshold),
        },
        "model_mode": _model_load_mode,
    }

    return (
        lgbm_score,
        iso_score,
        rule_score_val,
        network_risk_score,
        ensemble_score,
        decision,
        confidence,
        shap_values,
        reason_codes,
        rule_reasons,
        graph_risk_score,
        effective_policy_snapshot,
    )


def recommended_action(decision: str) -> str:
    """
    Map high-level fraud decision to concrete policy action.

    Actions:
        - SMS_OTP
        - APP_PUSH_CHALLENGE
        - CALLBACK
        - MANUAL_REVIEW_QUEUE
        - CARD_TEMP_LOCK
        - PROCEED / PROCEED_WITH_LIMIT (backwards-compatible)
    """
    if decision == "APPROVE":
        return "PROCEED"
    if decision == "BLOCK":
        return "CARD_TEMP_LOCK"
    if decision == "REQUEST_OTP":
        return "SMS_OTP"
    if decision == "SOFT_DECLINE":
        return "APP_PUSH_CHALLENGE"
    if decision == "LIMITED_APPROVAL":
        return "PROCEED_WITH_LIMIT"
    if decision == "MANUAL_REVIEW":
        return "MANUAL_REVIEW_QUEUE,CALLBACK"
    if decision == "DECLINE":
        return "CARD_TEMP_LOCK"
    return "HOLD_AND_NOTIFY"
