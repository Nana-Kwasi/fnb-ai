import os
import time
from pathlib import Path

import numpy as np

from app.services.feature_engine import FEATURE_NAMES
from app.services.rule_engine import rule_score as rule_engine_score

MODEL_VERSION = "1.0.0"
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
    "txn_count_1h": {"high": "Unusually high number of transactions in the last hour", "low": "Normal transaction frequency"},
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


def _get_models_path() -> Path:
    env_path = os.getenv("MODEL_PATH", "").strip()
    if env_path and env_path != "/models":
        return Path(env_path).parent / "fraud"
    return Path(__file__).resolve().parents[3] / "models" / "fraud"


def _ensure_models():
    global _lgb_model, _sklearn_model, _iso_model, _shap_explainer, _models_loaded
    if _models_loaded:
        return
    base = _get_models_path()
    lgb_path = base / "lgb_fraud.txt"
    sklearn_path = base / "sklearn_fraud.joblib"
    iso_path = base / "isolation_forest.joblib"
    import joblib
    try:
        import lightgbm as lgb
        if lgb_path.exists():
            _lgb_model = lgb.Booster(model_file=str(lgb_path))
            import shap
            _shap_explainer = shap.TreeExplainer(_lgb_model)
    except Exception:
        pass
    if _lgb_model is None and sklearn_path.exists():
        try:
            _sklearn_model = joblib.load(sklearn_path)
        except Exception:
            pass
    if iso_path.exists():
        try:
            _iso_model = joblib.load(iso_path)
        except Exception:
            pass
    _models_loaded = True


def _feature_vector_to_array(fv: dict) -> np.ndarray:
    return np.array([[fv.get(name, 0.0) for name in FEATURE_NAMES]], dtype=np.float32)


def _score_lgb(fv: dict) -> float:
    X = _feature_vector_to_array(fv)
    if _lgb_model is not None:
        return float(_lgb_model.predict(X)[0])
    if _sklearn_model is not None:
        return float(_sklearn_model.predict_proba(X)[0][1])
    amount = fv.get("amount", 0)
    ratio = fv.get("amount_vs_avg_ratio", 1.0)
    new_dev = fv.get("is_new_device", 0)
    txn_1h = fv.get("txn_count_1h", 0)
    return min(0.95, 0.1 + (amount / 50000) * 0.2 + ratio * 0.15 + new_dev * 0.25 + min(txn_1h, 5) * 0.08)


def _rule_score_from_fv(fv: dict) -> tuple[float, list[str]]:
    return rule_engine_score(
        amount=float(fv.get("amount", 0)),
        is_new_device=float(fv.get("is_new_device", 0)),
        is_new_location=float(fv.get("is_new_location", 0)),
        txn_count_1h=float(fv.get("txn_count_1h", 0)),
        location_country=fv.get("location_country"),
    )


def _stub_score(fv: dict) -> tuple[float, float | None, float, float, list[str]]:
    lgbm = _score_lgb(fv)
    iso_anomaly = None
    if _iso_model is not None:
        X = _feature_vector_to_array(fv)
        pred = _iso_model.predict(X)[0]
        iso_anomaly = 1.0 if pred == -1 else 0.0
    rule_sc, rule_reasons = _rule_score_from_fv(fv)
    lgb_w, iso_w, rule_w = 0.6, 0.3, 0.1
    if iso_anomaly is not None:
        ensemble = lgb_w * lgbm + iso_w * iso_anomaly + rule_w * rule_sc
    else:
        ensemble = lgb_w * lgbm + (1.0 - lgb_w - rule_w) * 0.0 + rule_w * rule_sc
    return (
        round(lgbm, 5),
        round(iso_anomaly, 5) if iso_anomaly is not None else None,
        round(rule_sc, 5),
        round(min(ensemble, 0.99999), 5),
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


def score_and_explain(
    feature_vector: dict,
    threshold_block: float = 0.85,
    threshold_otp: float = 0.60,
) -> tuple[float, float | None, float, float, str, str, dict, list[str], list[str]]:
    """
    Returns: lgbm_score, iso_score, rule_score, ensemble_score, decision, confidence,
             shap_values, reason_codes, rule_reasons.
    Decision: BLOCK if score >= threshold_block; REQUEST_OTP if score >= threshold_otp; else APPROVE.
    """
    _ensure_models()
    lgbm_score, iso_score, rule_score_val, ensemble_score, rule_reasons = _stub_score(feature_vector)
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

    if ensemble_score >= threshold_block:
        decision = "BLOCK"
        confidence = "HIGH"
    elif ensemble_score >= threshold_otp:
        decision = "REQUEST_OTP"
        confidence = "MEDIUM"
    else:
        decision = "APPROVE"
        confidence = "HIGH" if ensemble_score < 0.3 else "MEDIUM"

    return lgbm_score, iso_score, rule_score_val, ensemble_score, decision, confidence, shap_values, reason_codes, rule_reasons


def recommended_action(decision: str) -> str:
    if decision == "APPROVE":
        return "PROCEED"
    if decision == "BLOCK":
        return "BLOCK_AND_NOTIFY"
    if decision == "REQUEST_OTP":
        return "HOLD_AND_NOTIFY"
    if decision == "DECLINE":
        return "BLOCK_AND_NOTIFY"
    return "HOLD_AND_NOTIFY"
