"""
Scheduled job: retrain fraud models (LightGBM + Isolation Forest) from labelled data.

Intended usage:

  # what the scheduler runs (real-data mode, limited rows)
  python -m app.tasks.fraud_train_scheduled
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from app.ml import train as fraud_train


def run_fraud_training(limit: int = 5000, mode: str = "real") -> Dict[str, Any]:
    """
    Retrain fraud models from historical transactions + FraudOutcome labels.

    Thin wrapper around app.ml.train.main with timing + observability.
    """
    env = os.environ
    env.setdefault("FRAUD_TRAIN_MODE", mode)
    if mode.lower() == "real":
        env.setdefault("FRAUD_TRAIN_LIMIT", str(limit))

    t0 = time.time()
    success = True
    try:
        fraud_train.main()
    except Exception as exc:
        success = False
        try:
            from app.observability import record_training_run
            record_training_run("fraud", success=False, duration_s=time.time() - t0)
        except Exception:
            pass
        raise exc

    duration = time.time() - t0
    try:
        from app.observability import record_training_run, update_model_status
        from app.services.fraud_engine import ensure_fraud_models_loaded
        status = ensure_fraud_models_loaded()
        update_model_status(status.get("mode") == "model")
        record_training_run("fraud", success=True, duration_s=duration)
    except Exception:
        pass

    return {
        "mode": env.get("FRAUD_TRAIN_MODE"),
        "limit": int(env.get("FRAUD_TRAIN_LIMIT", str(limit))),
        "duration_seconds": round(duration, 1),
    }


if __name__ == "__main__":
    # Allow manual invocation for ops / experimentation.
    out = run_fraud_training()
    print("Fraud training job completed:", out)

