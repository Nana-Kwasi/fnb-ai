"""
Train LightGBM + Isolation Forest for fraud detection.

Outputs: models/fraud/lgb_fraud.txt (or sklearn_fraud.joblib if LightGBM unavailable),
         models/fraud/isolation_forest.joblib

Run from repo root:
    python -m app.ml.train              # synthetic fallback (default)
    FRAUD_TRAIN_MODE=real python -m app.ml.train  # train from historical data + FraudOutcome labels

Optional:
    FRAUD_TRAIN_SAMPLES=200  (synthetic sample size)
    FRAUD_TRAIN_LIMIT=5000   (max real labelled rows to use)
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.metrics import roc_auc_score

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Transaction, Customer, FraudOutcome
from app.services.feature_engine import FEATURE_NAMES, build_feature_vector

from datetime import datetime, timezone

try:
    import lightgbm as lgb
    _HAS_LGB = True
except Exception:
    _HAS_LGB = False

try:
    from imblearn.over_sampling import SMOTE
    _HAS_SMOTE = True
except Exception:
    _HAS_SMOTE = False


def make_synthetic(n_legit: int = 160, n_fraud: int = 40) -> Tuple[np.ndarray, np.ndarray]:
    np.random.seed(42)
    n = n_legit + n_fraud
    amount = np.concatenate([
        np.random.lognormal(5, 1.5, n_legit),
        np.random.lognormal(7, 2, n_fraud),
    ])
    txn_1h = np.concatenate([
        np.random.poisson(0.3, n_legit),
        np.random.poisson(2.5, n_fraud),
    ])
    txn_24h = np.concatenate([
        np.random.poisson(3, n_legit),
        np.random.poisson(12, n_fraud),
    ])
    txn_7d = txn_24h * 3 + np.random.poisson(5, n)
    total_1h = amount * 0.1 + np.random.exponential(50, n)
    total_24h = amount * 2 + np.random.exponential(200, n)
    total_7d = total_24h * 3 + np.random.exponential(500, n)
    avg_24h = np.maximum(total_24h / (txn_24h + 1), 1)
    amount_vs_avg = np.minimum(amount / avg_24h, 10)
    is_new_device = np.concatenate([
        np.random.binomial(1, 0.1, n_legit),
        np.random.binomial(1, 0.6, n_fraud),
    ])
    hour = np.random.randint(0, 24, n)
    is_weekend = np.random.binomial(1, 0.3, n)
    days_since = np.concatenate([
        np.random.exponential(5, n_legit),
        np.random.exponential(30, n_fraud),
    ])
    customer_risk = np.concatenate([
        np.random.beta(1, 10, n_legit),
        np.random.beta(3, 5, n_fraud),
    ])
    merchant_cat_risk = np.random.binomial(1, 0.1, n).astype(float)

    X = np.column_stack([
        amount, txn_1h, total_1h, txn_24h, total_24h, txn_7d, total_7d,
        amount_vs_avg, is_new_device, hour, is_weekend, days_since,
        customer_risk, merchant_cat_risk,
    ])
    y = np.array([0] * n_legit + [1] * n_fraud)
    return X, y


async def _load_real_samples(limit: int | None = None) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load labelled transactions from the database and build feature matrix + labels.

    Uses FraudOutcome.classification as the supervised label and build_feature_vector
    to generate the input features so train-time features match serving.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Transaction, FraudOutcome)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .limit(limit or 10_000)
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            raise RuntimeError("No labelled FraudOutcome rows found; cannot train in real-data mode.")

        total = len(rows)
        customer_ids = {row[0].customer_id for row in rows}
        cust_result = await db.execute(select(Customer).where(Customer.id.in_(customer_ids)))
        customer_map = {c.id: c for c in cust_result.scalars().unique().all()}
        print(f"Building features for {total} labelled transactions (this can take a while)...")

        X_list: list[list[float]] = []
        y_list: list[int] = []
        step = max(500, total // 20)

        for i, row in enumerate(rows):
            if (i + 1) % step == 0 or i == 0:
                print(f"  ... {i + 1}/{total}")
            tx: Transaction = row[0]
            outcome: FraudOutcome = row[1]

            cust = customer_map.get(tx.customer_id)
            if not cust:
                continue

            fv = await build_feature_vector(
                db,
                str(tx.tenant_id),
                str(tx.customer_id),
                float(tx.amount),
                tx.currency or "USD",
                tx.merchant_category,
                tx.merchant_id,
                tx.device_id,
                tx.channel,
                tx.tx_timestamp,
                float(cust.risk_score),
                location_country=tx.location_country,
                ip_address=tx.ip_address_hash,
            )
            X_list.append([fv.get(name, 0.0) for name in FEATURE_NAMES])

            if outcome.classification == "CONFIRMED_FRAUD":
                y_list.append(1)
            elif outcome.classification in ("FALSE_POSITIVE", "CONFIRMED_LEGIT"):
                y_list.append(0)
            else:
                # Unknown label – skip
                X_list.pop()

        if not X_list:
            raise RuntimeError("No usable labelled samples after feature generation.")

        X = np.asarray(X_list, dtype=np.float32)
        y = np.asarray(y_list, dtype=np.int32)
        return X, y


def _train_supervised(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    out_dir: Path,
) -> None:
    if _HAS_LGB:
        lgb_data = lgb.Dataset(X_train, label=y_train)
        lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_data)
        params = {
            "objective": "binary",
            "metric": "auc",
            "scale_pos_weight": 10,
            "num_leaves": 63,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "verbosity": -1,
        }
        n_rounds = 150 if len(X_train) < 500 else 300
        model = lgb.train(
            params,
            lgb_data,
            num_boost_round=n_rounds,
            valid_sets=[lgb_val],
            callbacks=[lgb.early_stopping(20)],
        )
        model.save_model(str(out_dir / "lgb_fraud.txt"))

        # Persist feature importances so we can verify that new signals are used.
        try:
            importances = model.feature_importance(importance_type="gain")
            fi = [
                {"feature": name, "importance_gain": float(imp)}
                for name, imp in zip(FEATURE_NAMES, importances)
            ]
            with open(out_dir / "feature_importances.json", "w", encoding="utf-8") as f:
                json.dump(fi, f, indent=2)
            top = sorted(fi, key=lambda x: x["importance_gain"], reverse=True)[:10]
            print("Top 10 features by gain:")
            for item in top:
                print(f"  {item['feature']}: {item['importance_gain']:.4f}")
        except Exception as exc:  # pragma: no cover - diagnostics only
            print("Warning: could not compute feature importances:", exc)
    else:
        print("LightGBM not available, using sklearn GradientBoostingClassifier")
        model = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
        model.fit(X_train, y_train)
        joblib.dump(model, out_dir / "sklearn_fraud.joblib")


def _train_iso(X: np.ndarray, y: np.ndarray, out_dir: Path) -> None:
    X_legit = X[y == 0]
    iso = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    iso.fit(X_legit)
    joblib.dump(iso, out_dir / "isolation_forest.joblib")


def _debug_scenarios(out_dir: Path, X_val: np.ndarray | None = None) -> None:
    """
    Simple sanity-check scenarios using the trained model.

    Builds synthetic feature vectors to simulate:
      - baseline transaction
      - card-testing (high fingerprint_repeat_count / velocity)
      - device ring (many accounts on one device)
      - high-risk merchant
    and prints model scores for each.
    """
    if not _HAS_LGB:
        return
    try:
        import lightgbm as lgb
        model = lgb.Booster(model_file=str(out_dir / "lgb_fraud.txt"))
    except Exception:
        return

    def make_vector(overrides: dict[str, float]) -> list[float]:
        base = {name: 0.0 for name in FEATURE_NAMES}
        base.update(overrides)
        return [base[name] for name in FEATURE_NAMES]

    scenarios = {
        "baseline": {},
        "card_testing": {
            "amount": 5.0,
            "fingerprint_repeat_count": 10.0,
            "fingerprint_velocity_1h": 5.0,
        },
        "device_ring": {
            "accounts_seen_for_device_7d": 10.0,
            "device_risk_score": 0.9,
        },
        "high_risk_merchant": {
            "merchant_risk_score": 0.9,
            "merchant_fraud_rate_30d": 0.8,
        },
    }

    X_debug = np.asarray([make_vector(v) for v in scenarios.values()], dtype=np.float32)
    preds = model.predict(X_debug)
    print("Sanity-check scenario scores (LightGBM):")
    for name, score in zip(scenarios.keys(), preds):
        print(f"  {name}: {float(score):.4f}")


def _split_train_val(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    idx = np.random.RandomState(42).permutation(len(X))
    X, y = X[idx], y[idx]
    train_size = int(0.8 * len(X))
    return X[:train_size], y[:train_size], X[train_size:], y[train_size:]


def _evaluate(y_true: np.ndarray, y_proba: np.ndarray) -> None:
    try:
        auc = roc_auc_score(y_true, y_proba)
        print(f"AUC: {auc:.4f}")
    except Exception:
        pass


def main():
    model_path_env = os.getenv("MODEL_PATH", "")
    if model_path_env and model_path_env != "/models":
        out_dir = Path(model_path_env).parent / "fraud"
    else:
        out_dir = Path(__file__).resolve().parents[3] / "models" / "fraud"
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "train_status.json"

    mode = os.getenv("FRAUD_TRAIN_MODE", "synthetic").lower()
    # Write initial status so UI can show progress.
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        with status_path.open("w", encoding="utf-8") as f:
            json.dump({"state": "running", "mode": mode, "started_at": started_at}, f)
    except Exception:
        pass
    if mode == "real":
        limit = int(os.getenv("FRAUD_TRAIN_LIMIT", "5000"))
        print(f"Training fraud model from real data (limit={limit})")
        X, y = asyncio.run(_load_real_samples(limit=limit))
    else:
        n_total = int(os.getenv("FRAUD_TRAIN_SAMPLES", "200"))
        n_fraud = max(10, n_total // 5)
        n_legit = n_total - n_fraud
        print(f"Training fraud model from synthetic data (n_legit={n_legit}, n_fraud={n_fraud})")
        X, y = make_synthetic(n_legit=n_legit, n_fraud=n_fraud)

        if _HAS_SMOTE and len(np.unique(y)) == 2:
            try:
                smote = SMOTE(sampling_strategy=0.25, random_state=42)
                X, y = smote.fit_resample(X, y)
            except Exception:
                pass

    X_train, y_train, X_val, y_val = _split_train_val(X, y)
    _train_supervised(X_train, y_train, X_val, y_val, out_dir)
    _train_iso(X, y, out_dir)

    # Simple evaluation on validation set if LightGBM/GBM is available.
    # For now, we only compute AUC using a trivial probability proxy (class balance),
    # detailed side-by-side model evaluation is added in a later step.
    try:
        base_proba = np.full_like(y_val, float(y_train.mean()), dtype=float)
        _evaluate(y_val, base_proba)
    except Exception:
        pass

    finished_at = datetime.now(timezone.utc).isoformat()
    try:
        with status_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "state": "done",
                    "mode": mode,
                    "started_at": started_at,
                    "finished_at": finished_at,
                },
                f,
                indent=2,
            )
    except Exception:
        pass

    # Persist feature names alongside the model for debugging / analysis.
    with open(out_dir / "feature_names.json", "w") as f:
        json.dump(FEATURE_NAMES, f)

    # Print simple scenario scores so we can see that network/fingerprint
    # signals are actually influencing the model.
    _debug_scenarios(out_dir, X_val)
    print("Models saved to", out_dir)


if __name__ == "__main__":
    main()
