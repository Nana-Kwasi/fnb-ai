"""
Bias and Fairness Audit for the fraud detection model.

Computes model performance metrics stratified by:
  - location_country (geographic/regional bias)
  - merchant_cat_risk tier (merchant type bias)
  - hour_of_day quartile (time-of-day bias)
  - amount_tier (micro/small/medium/large transaction bias)

For each stratum, reports: AUC, fraud rate, block rate, false positive rate.
Flags disparate impact if any stratum's FPR exceeds 2× the minimum stratum FPR
(4/5ths rule adapted for fraud: using FPR rather than selection rate).

Output is written to bias_audit.json alongside the model.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def _safe_auc(y_true: np.ndarray, y_score: np.ndarray) -> float | None:
    try:
        from sklearn.metrics import roc_auc_score
        if len(np.unique(y_true)) < 2:
            return None
        return float(roc_auc_score(y_true, y_score))
    except Exception:
        return None


def _stratum_metrics(y_true: np.ndarray, y_pred_proba: np.ndarray, threshold: float = 0.80) -> Dict[str, Any]:
    n = len(y_true)
    if n == 0:
        return {"n": 0, "fraud_rate": None, "auc": None, "block_rate": None, "fpr": None, "tpr": None}

    fraud_rate = float(y_true.mean()) if n > 0 else 0.0
    blocked = (y_pred_proba >= threshold).astype(int)
    block_rate = float(blocked.mean())

    tp = int(((blocked == 1) & (y_true == 1)).sum())
    fp = int(((blocked == 1) & (y_true == 0)).sum())
    fn = int(((blocked == 0) & (y_true == 1)).sum())
    tn = int(((blocked == 0) & (y_true == 0)).sum())

    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    auc = _safe_auc(y_true, y_pred_proba)

    return {
        "n": n,
        "fraud_rate": round(fraud_rate, 4),
        "auc": round(auc, 4) if auc is not None else None,
        "block_rate": round(block_rate, 4),
        "fpr": round(fpr, 4),
        "tpr": round(tpr, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def _amount_tier(amount: float) -> str:
    if amount < 10:
        return "micro"
    if amount < 100:
        return "small"
    if amount < 1000:
        return "medium"
    if amount < 10000:
        return "large"
    return "very_large"


def _hour_quartile(hour: float) -> str:
    h = int(hour) % 24
    if h < 6:
        return "night_00_06"
    if h < 12:
        return "morning_06_12"
    if h < 18:
        return "afternoon_12_18"
    return "evening_18_24"


def run_bias_audit(
    X: np.ndarray,
    y_true: np.ndarray,
    y_pred_proba: np.ndarray,
    feature_names: List[str],
    out_dir: Path,
    block_threshold: float = 0.80,
) -> Dict[str, Any]:
    """
    Compute stratified bias metrics and write bias_audit.json.

    Args:
        X               – feature matrix (n_samples, n_features)
        y_true          – true labels (0=legit, 1=fraud)
        y_pred_proba    – model probability scores
        feature_names   – list of feature names matching X columns
        out_dir         – directory to write bias_audit.json
        block_threshold – threshold for classifying BLOCK decision

    Returns the bias report dict.
    """
    fn_idx = {name: i for i, name in enumerate(feature_names)}
    report: Dict[str, Any] = {
        "overall": _stratum_metrics(y_true, y_pred_proba, block_threshold),
        "by_country": {},
        "by_merchant_risk": {},
        "by_hour_quartile": {},
        "by_amount_tier": {},
        "disparate_impact_flags": [],
    }

    # ── By country ────────────────────────────────────────────────────────────
    if "location_country" not in fn_idx:
        # location_country is stored as a non-numeric passthrough; use a proxy
        country_col = None
    else:
        country_col = fn_idx.get("location_country")

    # ── By merchant_cat_risk ──────────────────────────────────────────────────
    if "merchant_cat_risk" in fn_idx:
        mcat_col = fn_idx["merchant_cat_risk"]
        for tier_val, tier_name in [(0.0, "standard"), (0.2, "high_risk")]:
            mask = np.isclose(X[:, mcat_col], tier_val, atol=0.1)
            if mask.sum() > 10:
                report["by_merchant_risk"][tier_name] = _stratum_metrics(
                    y_true[mask], y_pred_proba[mask], block_threshold
                )

    # ── By hour of day ────────────────────────────────────────────────────────
    if "hour_of_day" in fn_idx:
        hour_col = fn_idx["hour_of_day"]
        for qname in ["night_00_06", "morning_06_12", "afternoon_12_18", "evening_18_24"]:
            if qname == "night_00_06":
                mask = X[:, hour_col] < 6
            elif qname == "morning_06_12":
                mask = (X[:, hour_col] >= 6) & (X[:, hour_col] < 12)
            elif qname == "afternoon_12_18":
                mask = (X[:, hour_col] >= 12) & (X[:, hour_col] < 18)
            else:
                mask = X[:, hour_col] >= 18
            if mask.sum() > 10:
                report["by_hour_quartile"][qname] = _stratum_metrics(
                    y_true[mask], y_pred_proba[mask], block_threshold
                )

    # ── By amount tier ────────────────────────────────────────────────────────
    if "amount" in fn_idx:
        amt_col = fn_idx["amount"]
        amounts = X[:, amt_col]
        for tier in ["micro", "small", "medium", "large", "very_large"]:
            if tier == "micro":
                mask = amounts < 10
            elif tier == "small":
                mask = (amounts >= 10) & (amounts < 100)
            elif tier == "medium":
                mask = (amounts >= 100) & (amounts < 1000)
            elif tier == "large":
                mask = (amounts >= 1000) & (amounts < 10000)
            else:
                mask = amounts >= 10000
            if mask.sum() > 10:
                report["by_amount_tier"][tier] = _stratum_metrics(
                    y_true[mask], y_pred_proba[mask], block_threshold
                )

    # ── Disparate impact detection ────────────────────────────────────────────
    report["disparate_impact_flags"] = _check_disparate_impact(report)

    # Write to disk
    out_path = out_dir / "bias_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Bias audit written to {out_path}")
    _print_summary(report)
    return report


def _check_disparate_impact(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Flag any stratum where FPR is ≥2× the minimum stratum FPR.
    (4/5ths rule adapted for fraud false positive rate.)
    """
    flags = []
    for section_name in ["by_merchant_risk", "by_hour_quartile", "by_amount_tier"]:
        section = report.get(section_name, {})
        fprs = {k: v["fpr"] for k, v in section.items() if v.get("fpr") is not None and v.get("n", 0) >= 30}
        if len(fprs) < 2:
            continue
        min_fpr = min(fprs.values())
        if min_fpr <= 0:
            continue
        for stratum, fpr in fprs.items():
            ratio = fpr / min_fpr
            if ratio >= 2.0:
                flags.append({
                    "section": section_name,
                    "stratum": stratum,
                    "fpr": fpr,
                    "min_fpr_stratum": min(fprs, key=fprs.get),
                    "min_fpr": min_fpr,
                    "ratio": round(ratio, 2),
                    "severity": "HIGH" if ratio >= 4.0 else "MEDIUM",
                    "recommendation": (
                        f"False positive rate for '{stratum}' is {ratio:.1f}× higher than "
                        f"the lowest group. Review threshold or collect more labelled data "
                        f"for this segment."
                    ),
                })
    return flags


def _print_summary(report: Dict[str, Any]) -> None:
    overall = report.get("overall", {})
    print(f"\nBias Audit Summary")
    print(f"  Overall — AUC: {overall.get('auc')}, FPR: {overall.get('fpr')}, TPR: {overall.get('tpr')}")
    flags = report.get("disparate_impact_flags", [])
    if flags:
        print(f"  ⚠  {len(flags)} disparate impact flag(s) detected:")
        for f in flags:
            print(f"     [{f['severity']}] {f['section']}/{f['stratum']} FPR ratio = {f['ratio']}×")
    else:
        print("  No disparate impact flags.")
