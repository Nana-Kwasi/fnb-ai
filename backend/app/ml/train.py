"""
Train LightGBM + Isolation Forest for fraud detection.
Outputs: models/fraud/lgb_fraud.txt (or sklearn_fraud.joblib if LightGBM unavailable), models/fraud/isolation_forest.joblib
Run from repo root: python -m app.ml.train
Optional: FRAUD_TRAIN_SAMPLES=200 (default) or set for more data.
"""
import json
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest, GradientBoostingClassifier

from app.services.feature_engine import FEATURE_NAMES

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


def make_synthetic(n_legit: int = 160, n_fraud: int = 40) -> tuple[np.ndarray, np.ndarray]:
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


def main():
    model_path_env = os.getenv("MODEL_PATH", "")
    if model_path_env and model_path_env != "/models":
        out_dir = Path(model_path_env).parent / "fraud"
    else:
        out_dir = Path(__file__).resolve().parents[3] / "models" / "fraud"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_total = int(os.getenv("FRAUD_TRAIN_SAMPLES", "200"))
    n_fraud = max(10, n_total // 5)
    n_legit = n_total - n_fraud
    X, y = make_synthetic(n_legit=n_legit, n_fraud=n_fraud)
    if _HAS_SMOTE and len(np.unique(y)) == 2:
        try:
            smote = SMOTE(sampling_strategy=0.25, random_state=42)
            X_res, y_res = smote.fit_resample(X, y)
        except Exception:
            X_res, y_res = X, y
    else:
        X_res, y_res = X, y

    idx = np.random.RandomState(42).permutation(len(X_res))
    X_res, y_res = X_res[idx], y_res[idx]
    train_size = int(0.8 * len(X_res))
    X_train, X_val = X_res[:train_size], X_res[train_size:]
    y_train, y_val = y_res[:train_size], y_res[train_size:]

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
        n_rounds = 150 if len(X_res) < 500 else 300
        model = lgb.train(
            params,
            lgb_data,
            num_boost_round=n_rounds,
            valid_sets=[lgb_val],
            callbacks=[lgb.early_stopping(20)],
        )
        model.save_model(str(out_dir / "lgb_fraud.txt"))
    else:
        print("LightGBM not available (e.g. libomp missing), using sklearn GradientBoostingClassifier")
        model = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
        model.fit(X_train, y_train)
        joblib.dump(model, out_dir / "sklearn_fraud.joblib")

    X_legit = X[y == 0]
    iso = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    iso.fit(X_legit)
    joblib.dump(iso, out_dir / "isolation_forest.joblib")

    with open(out_dir / "feature_names.json", "w") as f:
        json.dump(FEATURE_NAMES, f)
    print("Models saved to", out_dir)


if __name__ == "__main__":
    main()
