"""
Reject Inference for fraud model training.

Problem: when the fraud model blocks a transaction, we never observe whether
it was truly fraudulent or a false positive. Over time, training data becomes
biased toward approved transactions, causing the model to underestimate risk
on patterns it previously blocked (survivorship bias).

Solution — Parceling method:
    For each BLOCKED transaction without a FraudOutcome label, assign a
    pseudo-label based on the model's score at the time of blocking:

        ensemble_score >= fraud_threshold  →  pseudo-fraud  (weight = score)
        ensemble_score <= legit_threshold  →  pseudo-legit   (weight = 1-score)
        in between                         →  include with fractional weight

These pseudo-labeled rows are included in the next training run at reduced
sample weight, so they improve the model without overwhelming confirmed labels.

Reference: Hand (2001) "Reject inference, augmentation, and sample selection
bias in credit scoring" — European Journal of Operational Research 119(3).
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


async def load_reject_inference_samples(
    db,
    tenant_id: str | None,
    feature_names: List[str],
    fraud_threshold: float = 0.80,
    legit_threshold: float = 0.40,
    limit: int = 5_000,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Load BLOCKED transactions without confirmed labels and assign pseudo-labels.

    Returns:
        X       – feature matrix  (n_samples, n_features)
        y       – pseudo-labels   (n_samples,) int  0 or 1
        weights – sample weights  (n_samples,) float  0.0–1.0
                  reduced vs confirmed labels to avoid dominating the training set
    """
    from sqlalchemy import select, and_, not_, exists
    from app.models import Transaction, FraudScore, FraudOutcome

    subquery = select(FraudOutcome.transaction_id)

    filters = [
        Transaction.status.in_(["BLOCKED", "DECLINED"]),
        not_(Transaction.id.in_(subquery)),
        FraudScore.decision.in_(["BLOCK", "DECLINE"]),
    ]
    if tenant_id:
        filters.append(Transaction.tenant_id == tenant_id)

    stmt = (
        select(FraudScore.feature_vector, FraudScore.ensemble_score)
        .join(Transaction, Transaction.id == FraudScore.transaction_id)
        .where(and_(*filters))
        .order_by(FraudScore.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        empty = np.zeros((0, len(feature_names)), dtype=np.float32)
        return empty, np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)

    X_list: List[List[float]] = []
    y_list: List[int] = []
    w_list: List[float] = []

    # Reduced weight multiplier so pseudo-labels don't overwhelm confirmed data
    PSEUDO_WEIGHT_SCALE = 0.3

    for fv_dict, ensemble_score in rows:
        if not fv_dict:
            continue
        score = float(ensemble_score)
        row = [float(fv_dict.get(name, 0.0)) for name in feature_names]

        if score >= fraud_threshold:
            # Highly likely fraud — assign pseudo-label 1
            pseudo_label = 1
            weight = score * PSEUDO_WEIGHT_SCALE
        elif score <= legit_threshold:
            # Model thought it was borderline but blocked anyway — assign pseudo-legit
            pseudo_label = 0
            weight = (1.0 - score) * PSEUDO_WEIGHT_SCALE
        else:
            # Uncertain zone: use score as fractional weight for both classes
            # Parceling: contribute to both via duplicate rows with complementary weights
            row_fraud = row[:]
            row_legit = row[:]
            X_list.append(row_fraud)
            y_list.append(1)
            w_list.append(score * PSEUDO_WEIGHT_SCALE)
            X_list.append(row_legit)
            y_list.append(0)
            w_list.append((1.0 - score) * PSEUDO_WEIGHT_SCALE)
            continue

        X_list.append(row)
        y_list.append(pseudo_label)
        w_list.append(weight)

    if not X_list:
        empty = np.zeros((0, len(feature_names)), dtype=np.float32)
        return empty, np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)

    X = np.asarray(X_list, dtype=np.float32)
    y = np.asarray(y_list, dtype=np.int32)
    w = np.asarray(w_list, dtype=np.float32)

    return X, y, w
