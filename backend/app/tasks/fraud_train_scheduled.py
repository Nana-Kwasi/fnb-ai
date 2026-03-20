"""
Scheduled job: retrain fraud models (LightGBM + Isolation Forest) from labelled data.

Intended usage:

  # what the scheduler runs (real-data mode, limited rows)
  python -m app.tasks.fraud_train_scheduled
"""
from __future__ import annotations

import os
from typing import Any, Dict

from app.ml import train as fraud_train


def run_fraud_training(limit: int = 5000, mode: str = "real") -> Dict[str, Any]:
    """
    Retrain fraud models from historical transactions + FraudOutcome labels.

    This is a thin wrapper around app.ml.train.main, setting sensible defaults:
      - FRAUD_TRAIN_MODE=real (unless already set)
      - FRAUD_TRAIN_LIMIT=<limit> (unless already set)
    """
    env = os.environ
    env.setdefault("FRAUD_TRAIN_MODE", mode)
    if mode.lower() == "real":
        env.setdefault("FRAUD_TRAIN_LIMIT", str(limit))
    fraud_train.main()
    return {
        "mode": env.get("FRAUD_TRAIN_MODE"),
        "limit": int(env.get("FRAUD_TRAIN_LIMIT", str(limit))),
    }


if __name__ == "__main__":
    # Allow manual invocation for ops / experimentation.
    out = run_fraud_training()
    print("Fraud training job completed:", out)

