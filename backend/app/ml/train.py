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
import time
from pathlib import Path
from typing import Tuple, List

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.metrics import roc_auc_score, brier_score_loss, precision_recall_curve, roc_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Transaction, Customer, FraudOutcome
from app.services.feature_engine import FEATURE_NAMES, build_feature_vector
from app.ml.model_card import generate_model_card
from app.ml.bias_audit import run_bias_audit
from app.model_paths import packaged_fraud_models_dir

from datetime import datetime, timezone

try:
    import lightgbm as lgb
    _HAS_LGB = True
except Exception:
    _HAS_LGB = False


def make_synthetic(n_legit: int = 160, n_fraud: int = 40) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic training data covering all features in FEATURE_NAMES.
    New features are populated with realistic distributions that preserve
    the fraud/legit signal direction.
    """
    import math as _math
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

    # New features
    impossible_travel = np.concatenate([
        np.random.binomial(1, 0.005, n_legit),
        np.random.binomial(1, 0.12, n_fraud),
    ]).astype(float)
    travel_speed_kmh = np.where(impossible_travel == 1,
                                np.random.uniform(1000, 8000, n),
                                np.random.uniform(0, 400, n))
    velocity_ewma_1h = np.concatenate([
        np.random.exponential(0.3, n_legit),
        np.random.exponential(2.0, n_fraud),
    ])
    velocity_ewma_24h = np.concatenate([
        np.random.exponential(2.0, n_legit),
        np.random.exponential(8.0, n_fraud),
    ])
    amount_log_scaled = np.clip(
        np.log1p(amount) / _math.log1p(100_000.0), 0.0, 1.0
    )
    biometric_confidence = np.concatenate([
        np.random.beta(8, 2, n_legit),   # legit: usually high confidence
        np.random.beta(2, 5, n_fraud),   # fraud: usually low confidence
    ])
    typing_speed_dev = np.concatenate([
        np.random.exponential(0.1, n_legit),
        np.random.exponential(0.6, n_fraud),
    ])
    touch_pressure_dev = np.concatenate([
        np.random.exponential(0.08, n_legit),
        np.random.exponential(0.5, n_fraud),
    ])
    session_age = np.concatenate([
        np.random.exponential(300, n_legit),
        np.random.exponential(30, n_fraud),   # fraud: very short sessions
    ])
    biometric_signals_present = np.random.binomial(1, 0.7, n).astype(float)
    gnn_account_risk = np.concatenate([
        np.random.beta(1, 8, n_legit),
        np.random.beta(4, 3, n_fraud),
    ])

    # Build base feature matrix matching FEATURE_NAMES order
    base_features = np.column_stack([
        amount, txn_1h, total_1h, txn_24h, total_24h, txn_7d, total_7d,
        amount_vs_avg, is_new_device, hour, is_weekend, days_since,
        customer_risk, merchant_cat_risk,
    ])
    n_base = base_features.shape[1]  # 14 base features

    # Pad network/ring/fingerprint features with zeros for synthetic data
    n_network = len(FEATURE_NAMES) - n_base - 10  # 10 new features at end
    if n_network < 0:
        n_network = 0
    network_zeros = np.zeros((n, max(0, n_network)))

    new_features = np.column_stack([
        impossible_travel, travel_speed_kmh,
        velocity_ewma_1h, velocity_ewma_24h,
        amount_log_scaled,
        biometric_confidence, typing_speed_dev, touch_pressure_dev,
        session_age, biometric_signals_present,
        gnn_account_risk,
    ])

    X = np.column_stack([base_features, network_zeros, new_features])

    # Truncate or pad to exactly len(FEATURE_NAMES) columns
    target_cols = len(FEATURE_NAMES)
    if X.shape[1] > target_cols:
        X = X[:, :target_cols]
    elif X.shape[1] < target_cols:
        pad = np.zeros((n, target_cols - X.shape[1]))
        X = np.column_stack([X, pad])

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


def _focal_loss_objective(y_pred: np.ndarray, dtrain, gamma: float = 2.0, alpha: float = 0.25):
    """
    Focal loss custom objective for LightGBM.

    Focal loss down-weights easy negatives so the model focuses on hard cases.
    Reference: Lin et al. (2017) "Focal Loss for Dense Object Detection".
    """
    y_true = dtrain.get_label()
    p = 1.0 / (1.0 + np.exp(-y_pred))
    p = np.clip(p, 1e-7, 1 - 1e-7)

    # Gradient
    grad = np.where(
        y_true == 1,
        -alpha * (1 - p) ** gamma * (gamma * p * np.log(p) + p - 1),
        (1 - alpha) * p ** gamma * (gamma * (1 - p) * np.log(1 - p) + p),
    )
    # Hessian (approximation for stability)
    hess = np.where(
        y_true == 1,
        alpha * (1 - p) ** gamma * (1 + gamma * p) * p * (1 - p),
        (1 - alpha) * p ** gamma * (1 + gamma * (1 - p)) * p * (1 - p),
    )
    hess = np.maximum(hess, 1e-6)
    return grad, hess


def _train_supervised(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    out_dir: Path,
    sample_weights: np.ndarray | None = None,
) -> List[dict]:
    """
    Train primary fraud model.

    Uses dynamic class weights instead of SMOTE — more statistically sound for
    extreme imbalance. Optionally applies focal loss (set FRAUD_USE_FOCAL_LOSS=1).

    Returns feature importances list.
    """
    # Dynamic scale_pos_weight: ratio of negatives to positives
    n_pos = max(int(y_train.sum()), 1)
    n_neg = max(len(y_train) - n_pos, 1)
    scale_pos_weight = n_neg / n_pos
    print(f"Class imbalance — negatives: {n_neg}, positives: {n_pos}, scale_pos_weight: {scale_pos_weight:.1f}")

    use_focal = os.getenv("FRAUD_USE_FOCAL_LOSS", "0").strip().lower() in ("1", "true", "yes")

    if _HAS_LGB:
        lgb_data = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
        lgb_val = lgb.Dataset(X_val, label=y_val, reference=lgb_data)

        if use_focal:
            print("Using focal loss objective")
            params = {
                "objective": "binary",  # ignored when custom fobj provided, but needed for eval
                "metric": "auc",
                "num_leaves": 63,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "min_child_samples": 10,
                "verbosity": -1,
            }
            fobj = lambda y_pred, dtrain: _focal_loss_objective(y_pred, dtrain, gamma=2.0, alpha=0.25)
            n_rounds = 200 if len(X_train) < 500 else 400
            model = lgb.train(
                params,
                lgb_data,
                num_boost_round=n_rounds,
                fobj=fobj,
                valid_sets=[lgb_val],
                callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(50)],
            )
        else:
            params = {
                "objective": "binary",
                "metric": "auc",
                "scale_pos_weight": scale_pos_weight,
                "num_leaves": 63,
                "learning_rate": 0.05,
                "feature_fraction": 0.8,
                "bagging_fraction": 0.8,
                "bagging_freq": 5,
                "min_child_samples": 10,
                "lambda_l1": 0.1,
                "lambda_l2": 0.1,
                "verbosity": -1,
            }
            n_rounds = 150 if len(X_train) < 500 else 400
            model = lgb.train(
                params,
                lgb_data,
                num_boost_round=n_rounds,
                valid_sets=[lgb_val],
                callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(50)],
            )

        model.save_model(str(out_dir / "lgb_fraud.txt"))

        feature_importances = []
        try:
            importances = model.feature_importance(importance_type="gain")
            # Pad importances if model was trained on fewer features than current FEATURE_NAMES
            if len(importances) < len(FEATURE_NAMES):
                importances = list(importances) + [0.0] * (len(FEATURE_NAMES) - len(importances))
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
            feature_importances = fi
        except Exception as exc:
            print("Warning: could not compute feature importances:", exc)

        return feature_importances
    else:
        print("LightGBM not available, using sklearn GradientBoostingClassifier")
        sw = sample_weights if sample_weights is not None else None
        model = GradientBoostingClassifier(n_estimators=100, max_depth=5, random_state=42)
        model.fit(X_train, y_train, sample_weight=sw)
        joblib.dump(model, out_dir / "sklearn_fraud.joblib")
        return []


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
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    train_size = int(0.8 * len(X))
    return X[:train_size], y[:train_size], X[train_size:], y[train_size:]


def _evaluate(y_true: np.ndarray, y_proba: np.ndarray) -> None:
    try:
        auc = roc_auc_score(y_true, y_proba)
        print(f"AUC: {auc:.4f}")
    except Exception:
        pass


def _fit_calibrators(
    out_dir: Path,
    raw_val_proba: np.ndarray,
    y_val: np.ndarray,
) -> None:
    try:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_val_proba, y_val)
        joblib.dump(iso, out_dir / "isotonic_calibrator.joblib")
    except Exception as exc:
        print("Warning: isotonic calibrator failed:", exc)
    try:
        platt = LogisticRegression(solver="lbfgs")
        platt.fit(raw_val_proba.reshape(-1, 1), y_val)
        joblib.dump(platt, out_dir / "platt_calibrator.joblib")
    except Exception as exc:
        print("Warning: platt calibrator failed:", exc)
    try:
        report = {
            "raw_brier": float(brier_score_loss(y_val, raw_val_proba)),
        }
        if (out_dir / "isotonic_calibrator.joblib").exists():
            iso = joblib.load(out_dir / "isotonic_calibrator.joblib")
            report["isotonic_brier"] = float(brier_score_loss(y_val, iso.predict(raw_val_proba)))
        if (out_dir / "platt_calibrator.joblib").exists():
            platt = joblib.load(out_dir / "platt_calibrator.joblib")
            report["platt_brier"] = float(brier_score_loss(y_val, platt.predict_proba(raw_val_proba.reshape(-1, 1))[:, 1]))
        with open(out_dir / "calibration_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception as exc:
        print("Warning: calibration report failed:", exc)


def _compute_extended_metrics(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    block_threshold: float = 0.80,
) -> dict:
    """Compute AUC, Brier, precision@recall80, recall@fpr1pct."""
    metrics: dict = {}
    try:
        metrics["auc"] = float(roc_auc_score(y_true, y_proba))
    except Exception:
        metrics["auc"] = None
    try:
        metrics["brier_score"] = float(brier_score_loss(y_true, y_proba))
    except Exception:
        metrics["brier_score"] = None

    # Precision at 80% recall
    try:
        prec, rec, _ = precision_recall_curve(y_true, y_proba)
        idx = np.searchsorted(-rec, -0.80)
        metrics["precision_at_recall80"] = float(prec[min(idx, len(prec) - 1)])
    except Exception:
        metrics["precision_at_recall80"] = None

    # Recall at 1% FPR
    try:
        fpr_arr, tpr_arr, _ = roc_curve(y_true, y_proba)
        idx = np.searchsorted(fpr_arr, 0.01)
        metrics["recall_at_fpr1pct"] = float(tpr_arr[min(idx, len(tpr_arr) - 1)])
    except Exception:
        metrics["recall_at_fpr1pct"] = None

    return metrics


async def _load_reject_inference_samples_if_enabled(limit: int = 5000) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load pseudo-labeled rejected transactions when reject inference is enabled."""
    reject_enabled = os.getenv("REJECT_INFERENCE_ENABLED", "true").lower() in ("1", "true", "yes")
    if not reject_enabled:
        empty = np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32)
        return empty, np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)

    fraud_threshold = float(os.getenv("REJECT_INFERENCE_FRAUD_THRESHOLD", "0.80"))
    legit_threshold = float(os.getenv("REJECT_INFERENCE_LEGIT_THRESHOLD", "0.40"))

    try:
        from app.services.reject_inference import load_reject_inference_samples
        async with AsyncSessionLocal() as db:
            X_ri, y_ri, w_ri = await load_reject_inference_samples(
                db=db,
                tenant_id=None,  # pool across all tenants for global model
                feature_names=FEATURE_NAMES,
                fraud_threshold=fraud_threshold,
                legit_threshold=legit_threshold,
                limit=limit,
            )
        if len(X_ri) > 0:
            print(f"Reject inference: loaded {len(X_ri)} pseudo-labeled samples "
                  f"({int(y_ri.sum())} pseudo-fraud, {int((y_ri == 0).sum())} pseudo-legit)")
        return X_ri, y_ri, w_ri
    except Exception as exc:
        print(f"Warning: reject inference skipped: {exc}")
        empty = np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32)
        return empty, np.zeros(0, dtype=np.int32), np.zeros(0, dtype=np.float32)


def main():
    training_start = time.time()

    out_dir = packaged_fraud_models_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "train_status.json"

    mode = os.getenv("FRAUD_TRAIN_MODE", "synthetic").lower()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        with status_path.open("w", encoding="utf-8") as f:
            json.dump({"state": "running", "mode": mode, "started_at": started_at}, f)
    except Exception:
        pass

    # ── Load labelled training data ───────────────────────────────────────────
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

    # ── Reject inference: merge pseudo-labeled blocked transactions ───────────
    X_ri, y_ri, w_ri = asyncio.run(_load_reject_inference_samples_if_enabled())
    n_reject_inference_samples = len(X_ri)

    if n_reject_inference_samples > 0:
        # Confirmed labels get weight 1.0; pseudo-labels get lower weights (set in reject_inference)
        confirmed_weights = np.ones(len(X), dtype=np.float32)
        X = np.vstack([X, X_ri])
        y = np.concatenate([y, y_ri])
        confirmed_weights = np.concatenate([confirmed_weights, w_ri])
    else:
        confirmed_weights = None

    X_train, y_train, X_val, y_val = _split_train_val(X, y)

    # Split sample weights if we have them
    if confirmed_weights is not None:
        n_train_end = int(0.8 * len(X))
        w_train = confirmed_weights[:n_train_end]
        # w_val not needed for calibration (use unweighted val set)
    else:
        w_train = None

    # ── Train models ──────────────────────────────────────────────────────────
    feature_importances = _train_supervised(X_train, y_train, X_val, y_val, out_dir, sample_weights=w_train)
    _train_iso(X, y, out_dir)

    # ── Calibration ───────────────────────────────────────────────────────────
    raw_val = None
    try:
        if _HAS_LGB and (out_dir / "lgb_fraud.txt").exists():
            m = lgb.Booster(model_file=str(out_dir / "lgb_fraud.txt"))
            raw_val = m.predict(X_val).astype(float)
        elif (out_dir / "sklearn_fraud.joblib").exists():
            m = joblib.load(out_dir / "sklearn_fraud.joblib")
            raw_val = m.predict_proba(X_val)[:, 1].astype(float)
        if raw_val is not None and len(raw_val) == len(y_val):
            _fit_calibrators(out_dir, raw_val, y_val)
    except Exception as exc:
        print("Warning: calibration fit skipped:", exc)

    # ── Extended metrics ──────────────────────────────────────────────────────
    metrics = {}
    if raw_val is not None and len(raw_val) == len(y_val):
        metrics = _compute_extended_metrics(y_val, raw_val)
        print(f"Validation — AUC: {metrics.get('auc')}, Brier: {metrics.get('brier_score')}, "
              f"Precision@Recall80: {metrics.get('precision_at_recall80')}, "
              f"Recall@FPR1pct: {metrics.get('recall_at_fpr1pct')}")
    else:
        try:
            base_proba = np.full_like(y_val, float(y_train.mean()), dtype=float)
            _evaluate(y_val, base_proba)
        except Exception:
            pass

    # ── Bias audit ────────────────────────────────────────────────────────────
    bias_metrics = None
    if raw_val is not None and len(raw_val) == len(y_val) and len(y_val) >= 30:
        try:
            # Use calibrated scores if available
            cal_path = out_dir / "isotonic_calibrator.joblib"
            if cal_path.exists():
                cal = joblib.load(cal_path)
                cal_val = cal.predict(raw_val.astype(np.float32))
            else:
                cal_val = raw_val
            bias_report = run_bias_audit(
                X=X_val,
                y_true=y_val,
                y_pred_proba=cal_val,
                feature_names=FEATURE_NAMES,
                out_dir=out_dir,
            )
            bias_metrics = bias_report
        except Exception as exc:
            print(f"Warning: bias audit failed: {exc}")

    training_duration = time.time() - training_start

    # ── Model card ────────────────────────────────────────────────────────────
    fraud_rate_train = float(y_train.mean()) if len(y_train) > 0 else 0.0
    model_version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        generate_model_card(
            out_dir=out_dir,
            model_version=model_version,
            train_mode=mode,
            n_train=len(X_train),
            n_val=len(X_val),
            fraud_rate_train=fraud_rate_train,
            feature_names=FEATURE_NAMES,
            auc=metrics.get("auc"),
            brier_score=metrics.get("brier_score"),
            precision_at_recall80=metrics.get("precision_at_recall80"),
            recall_at_fpr1pct=metrics.get("recall_at_fpr1pct"),
            feature_importances=feature_importances,
            bias_metrics=bias_metrics,
            reject_inference_samples=n_reject_inference_samples,
            training_duration_seconds=training_duration,
        )
    except Exception as exc:
        print(f"Warning: model card generation failed: {exc}")

    # ── Status + feature names ────────────────────────────────────────────────
    finished_at = datetime.now(timezone.utc).isoformat()
    try:
        with status_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "state": "done",
                    "mode": mode,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "model_version": model_version,
                    "auc": metrics.get("auc"),
                    "n_train": len(X_train),
                    "n_val": len(X_val),
                    "reject_inference_samples": n_reject_inference_samples,
                    "training_duration_seconds": round(training_duration, 1),
                },
                f,
                indent=2,
            )
    except Exception:
        pass

    with open(out_dir / "feature_names.json", "w") as f:
        json.dump(FEATURE_NAMES, f)

    _debug_scenarios(out_dir, X_val)
    print(f"Models saved to {out_dir} (training took {training_duration:.1f}s)")

    # ── Emit observability metrics ────────────────────────────────────────────
    try:
        from app.observability import record_training_run
        record_training_run(
            model_type="fraud",
            success=True,
            duration_s=training_duration,
            auc=metrics.get("auc"),
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
