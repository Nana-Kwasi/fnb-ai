"""
Model Card generator for the fraud detection model.

Produces a model_card.json alongside each trained model artifact.
Required by: EU AI Act (Article 13 transparency), South Africa FSCA,
             Basel Committee guidelines on ML in banking.

Card schema follows: Mitchell et al. (2019) "Model Cards for Model Reporting"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np


def generate_model_card(
    out_dir: Path,
    *,
    model_version: str,
    train_mode: str,
    n_train: int,
    n_val: int,
    fraud_rate_train: float,
    feature_names: List[str],
    auc: float | None,
    brier_score: float | None,
    precision_at_recall80: float | None,
    recall_at_fpr1pct: float | None,
    feature_importances: List[Dict[str, Any]] | None,
    bias_metrics: Dict[str, Any] | None,
    reject_inference_samples: int,
    training_duration_seconds: float,
    notes: str = "",
) -> None:
    """Write model_card.json to out_dir."""

    card = {
        "schema_version": "1.0",
        "model_details": {
            "name": "FNB-AI Fraud Detection Model",
            "version": model_version,
            "type": "LightGBM binary classifier with Isolation Forest ensemble",
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_mode": train_mode,
            "framework": "LightGBM 4.3 + scikit-learn 1.8",
            "intended_use": "Real-time fraud scoring for banking transactions",
            "out_of_scope_use": [
                "Credit scoring or lending decisions",
                "Customer identification or KYC",
                "Any use case not involving transaction fraud detection",
            ],
        },
        "training_data": {
            "n_train_samples": n_train,
            "n_val_samples": n_val,
            "fraud_rate_train": round(fraud_rate_train, 6),
            "fraud_rate_pct": f"{fraud_rate_train * 100:.3f}%",
            "reject_inference_pseudo_samples": reject_inference_samples,
            "features": feature_names,
            "n_features": len(feature_names),
            "labeling": "FraudOutcome.classification (CONFIRMED_FRAUD / FALSE_POSITIVE / CONFIRMED_LEGIT)",
            "data_period": "Last 90 days of transactions with analyst labels",
        },
        "performance_metrics": {
            "auc_roc": round(auc, 5) if auc is not None else None,
            "brier_score": round(brier_score, 5) if brier_score is not None else None,
            "precision_at_80pct_recall": round(precision_at_recall80, 4) if precision_at_recall80 is not None else None,
            "recall_at_1pct_fpr": round(recall_at_fpr1pct, 4) if recall_at_fpr1pct is not None else None,
            "calibration_method": "Isotonic regression + Platt scaling",
            "evaluation_set": "Stratified 20% holdout from training data",
        },
        "feature_importances": (feature_importances or [])[:20],
        "bias_and_fairness": bias_metrics or {
            "status": "not_evaluated",
            "note": "Run bias_audit.py after training to populate this section",
        },
        "known_limitations": [
            "Model trained primarily on digital channels; ATM / branch transactions underrepresented",
            "Behavioral biometrics features (biometric_confidence) are 0.5 when mobile SDK is not used",
            "Reject inference pseudo-labels introduce uncertainty; confirmed labels are authoritative",
            "Model may underperform on brand-new merchants with no transaction history",
            "GNN embeddings are graph-cache based (1h TTL); network changes lag slightly",
        ],
        "ethical_considerations": [
            "Decisions triggering BLOCK or REQUEST_OTP must include SHAP reason codes for explainability",
            "All decisions are logged with full feature vectors for audit purposes",
            "Customers can dispute decisions via the care channel",
            "Model performance must be monitored for demographic disparate impact quarterly",
        ],
        "regulatory_compliance": [
            "EU AI Act Article 13: Technical documentation provided in this model card",
            "POPIA (South Africa): Training data anonymised; no raw PII in features",
            "PCI-DSS: Card numbers not stored; card_fraud_ratio_90d derived from hashed identifiers",
            "Basel III: Explainability provided via SHAP values for every scored transaction",
        ],
        "training_infrastructure": {
            "training_duration_seconds": round(training_duration_seconds, 1),
            "notes": notes,
        },
    }

    card_path = out_dir / "model_card.json"
    with open(card_path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2)

    print(f"Model card written to {card_path}")
