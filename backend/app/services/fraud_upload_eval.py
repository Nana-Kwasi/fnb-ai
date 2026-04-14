"""
Evaluate deployed fraud model against rows from a training upload (DB-backed txs).
"""
from __future__ import annotations

import os
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import accuracy_score, roc_auc_score, confusion_matrix, precision_recall_fscore_support
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, FraudOutcome, Transaction
from app.models.training_data import TrainingUpload, TrainingUploadRow
from app.services.feature_engine import FEATURE_NAMES, build_feature_vector


def _fraud_model_dir() -> Path:
    model_path_env = os.getenv("MODEL_PATH", "")
    if model_path_env and model_path_env != "/models":
        return Path(model_path_env).parent / "fraud"
    return Path(__file__).resolve().parents[3] / "models" / "fraud"


def _load_fraud_predictor():
    import joblib

    d = _fraud_model_dir()
    lgb_path = d / "lgb_fraud.txt"
    sk_path = d / "sklearn_fraud.joblib"
    try:
        import lightgbm as lgb

        if lgb_path.exists():
            model = lgb.Booster(model_file=str(lgb_path))

            def predict(X: np.ndarray) -> np.ndarray:
                return model.predict(X)

            return predict
    except Exception:
        pass
    if sk_path.exists():
        model = joblib.load(sk_path)

        def predict_sk(X: np.ndarray) -> np.ndarray:
            if hasattr(model, "predict_proba"):
                return model.predict_proba(X)[:, 1].astype(np.float64)
            return model.predict(X).astype(np.float64)

        return predict_sk
    raise RuntimeError("No fraud model found (lgb_fraud.txt or sklearn_fraud.joblib).")


def _label_from_classification(classification: str) -> int | None:
    c = (classification or "").strip().upper()
    if c == "CONFIRMED_FRAUD":
        return 1
    if c in ("FALSE_POSITIVE", "CONFIRMED_LEGIT"):
        return 0
    return None


def _parse_ts(s: str) -> datetime:
    s = (s or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.utcnow()


async def evaluate_fraud_upload(
    db: AsyncSession,
    upload_id: uuid.UUID,
    sample_max: int = 800,
    random_seed: int = 42,
) -> dict[str, Any]:
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == upload_id))).scalar_one_or_none()
    if not upload or upload.model_type != "fraud":
        raise ValueError("Upload not found or not a fraud upload.")
    if upload.status != "TRAINED":
        raise ValueError("Upload must be in TRAINED status (run manual train first).")

    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == upload_id).order_by(TrainingUploadRow.row_index.asc())
    )
    row_orms = rows_q.scalars().all()
    payloads = [(r.row_index, r.payload) for r in row_orms]
    if not payloads:
        raise ValueError("No rows in upload.")

    if len(payloads) > sample_max:
        rng = random.Random(random_seed)
        payloads = rng.sample(payloads, sample_max)

    predict_fn = _load_fraud_predictor()
    X_list: list[list[float]] = []
    y_list: list[int] = []
    skipped = 0
    meta_rows: list[dict[str, Any]] = []

    for row_index, p in payloads:
        ext = (p.get("external_tx_id") or "").strip()
        tid_s = (p.get("tenant_id") or "").strip()
        cls_raw = p.get("classification") or ""
        y = _label_from_classification(cls_raw)
        if not ext or not tid_s or y is None:
            skipped += 1
            continue
        try:
            tid = uuid.UUID(tid_s)
        except Exception:
            skipped += 1
            continue

        stmt = (
            select(Transaction, FraudOutcome, Customer)
            .join(FraudOutcome, FraudOutcome.transaction_id == Transaction.id)
            .join(Customer, Customer.id == Transaction.customer_id)
            .where(Transaction.tenant_id == tid, Transaction.external_tx_id == ext)
            .limit(1)
        )
        res = await db.execute(stmt)
        got = res.one_or_none()
        if not got:
            skipped += 1
            continue
        tx, _fo, cust = got
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
        X_list.append([float(fv.get(name, 0.0)) for name in FEATURE_NAMES])
        y_list.append(y)
        amt = float(tx.amount or 0.0)
        if amt < 100:
            amt_bucket = "lt_100"
        elif amt < 1000:
            amt_bucket = "100_to_999"
        else:
            amt_bucket = "ge_1000"
        meta_rows.append(
            {
                "row_index": row_index,
                "external_tx_id": ext,
                "y_true": y,
                "channel": (tx.channel or "UNKNOWN"),
                "amount_bucket": amt_bucket,
            }
        )

    n_scored = len(y_list)
    if n_scored < 10:
        raise ValueError(f"Too few rows scored ({n_scored}); import/training may not have loaded these txs into DB.")

    X = np.asarray(X_list, dtype=np.float32)
    y_true = np.asarray(y_list, dtype=np.int32)
    y_proba = predict_fn(X).astype(np.float64)
    y_hat = (y_proba >= 0.5).astype(np.int32)

    acc = float(accuracy_score(y_true, y_hat))
    auc_val: float | None
    try:
        auc_val = float(roc_auc_score(y_true, y_proba)) if len(np.unique(y_true)) > 1 else None
    except Exception:
        auc_val = None

    min_auc = float(os.getenv("FRAUD_UPLOAD_LOCK_MIN_AUC", "0.90"))
    min_acc = float(os.getenv("FRAUD_UPLOAD_LOCK_MIN_ACC", "0.93"))
    min_n = int(os.getenv("FRAUD_UPLOAD_LOCK_MIN_N", "200"))

    lock_ok = n_scored >= min_n and acc >= min_acc
    if auc_val is not None:
        lock_ok = lock_ok and auc_val >= min_auc
    else:
        lock_ok = False

    samples: list[dict[str, Any]] = []
    for i in range(min(15, len(meta_rows))):
        samples.append(
            {
                "external_tx_id": meta_rows[i]["external_tx_id"],
                "label": int(y_true[i]),
                "fraud_proba": float(y_proba[i]),
                "predicted_fraud": bool(y_hat[i] == 1),
            }
        )

    cm = confusion_matrix(y_true, y_hat, labels=[0, 1])
    confusion = {
        "labels": ["LEGIT", "FRAUD"],
        "matrix": [[int(cm[0][0]), int(cm[0][1])], [int(cm[1][0]), int(cm[1][1])]],
    }

    threshold_metrics: list[dict[str, Any]] = []
    for thr in (0.3, 0.5, 0.7):
        y_thr = (y_proba >= thr).astype(np.int32)
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, y_thr, labels=[1], average="binary", zero_division=0
        )
        threshold_metrics.append(
            {
                "threshold": float(thr),
                "accuracy": float(accuracy_score(y_true, y_thr)),
                "precision": float(p),
                "recall": float(r),
                "f1": float(f1),
            }
        )

    segments: dict[str, list[dict[str, Any]]] = {"channel": [], "amount_bucket": []}
    for key in ("channel", "amount_bucket"):
        buckets: dict[str, list[int]] = {}
        for i, mr in enumerate(meta_rows):
            b = str(mr.get(key) or "UNKNOWN")
            buckets.setdefault(b, []).append(i)
        for b, idxs in buckets.items():
            yt = y_true[idxs]
            yp = y_hat[idxs]
            if len(yt) < 5:
                continue
            p, r, f1, _ = precision_recall_fscore_support(
                yt, yp, labels=[1], average="binary", zero_division=0
            )
            segments[key].append(
                {
                    "segment": b,
                    "n": int(len(yt)),
                    "accuracy": float(accuracy_score(yt, yp)),
                    "precision": float(p),
                    "recall": float(r),
                    "f1": float(f1),
                }
            )
        segments[key].sort(key=lambda x: x["n"], reverse=True)

    last_eval = {
        "n_scored": n_scored,
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": auc_val,
        "lock_thresholds": {"min_auc": min_auc, "min_accuracy": min_acc, "min_n": min_n},
    }

    meta = dict(upload.meta or {})
    meta["last_eval"] = last_eval
    meta["retrain_locked"] = bool(lock_ok)
    upload.meta = meta
    await db.flush()

    return {
        "upload_id": str(upload_id),
        "n_scored": n_scored,
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": auc_val,
        "retrain_locked": bool(lock_ok),
        "samples": samples,
        "threshold_metrics": threshold_metrics,
        "segments": segments,
        "confusion": confusion,
    }


async def evaluate_fraud_external_rows(
    db: AsyncSession,
    rows: list[dict],
    sample_max: int = 1200,
    random_seed: int = 42,
) -> dict[str, Any]:
    payloads = [(i + 1, r or {}) for i, r in enumerate(rows)]
    if not payloads:
        raise ValueError("No rows in external holdout.")
    if len(payloads) > sample_max:
        rng = random.Random(random_seed)
        payloads = rng.sample(payloads, sample_max)

    predict_fn = _load_fraud_predictor()
    X_list: list[list[float]] = []
    y_list: list[int] = []
    skipped = 0
    meta_rows: list[dict[str, Any]] = []

    for row_index, p in payloads:
        ext = str(p.get("external_tx_id") or p.get("transaction_id") or f"ext-{row_index}").strip()
        cls_raw = p.get("classification") or ""
        y = _label_from_classification(cls_raw)
        if y is None:
            skipped += 1
            continue

        amount = float(p.get("amount") or 0.0)
        ts = _parse_ts(str(p.get("tx_timestamp") or p.get("timestamp") or ""))
        merchant_category = str(p.get("merchant_category") or "").strip().upper()
        channel = str(p.get("channel") or "UNKNOWN").strip().upper() or "UNKNOWN"
        customer_risk = float(p.get("customer_risk_score") or 0.0)

        # DB-independent lightweight feature construction for true external files.
        fv = {name: 0.0 for name in FEATURE_NAMES}
        fv["amount"] = amount
        fv["hour_of_day"] = float(ts.hour)
        fv["is_weekend"] = 1.0 if ts.weekday() >= 5 else 0.0
        fv["customer_risk_score"] = customer_risk
        fv["merchant_cat_risk"] = 0.2 if merchant_category in ("GAMBLING", "CRYPTO", "INTERNATIONAL") else 0.0
        X_list.append([float(fv.get(name, 0.0)) for name in FEATURE_NAMES])
        y_list.append(y)
        if amount < 100:
            amt_bucket = "lt_100"
        elif amount < 1000:
            amt_bucket = "100_to_999"
        else:
            amt_bucket = "ge_1000"
        meta_rows.append(
            {
                "row_index": row_index,
                "external_tx_id": ext,
                "y_true": y,
                "channel": channel,
                "amount_bucket": amt_bucket,
            }
        )

    n_scored = len(y_list)
    if n_scored < 10:
        raise ValueError(f"Too few rows scored ({n_scored}); need rows with valid classification labels.")
    X = np.asarray(X_list, dtype=np.float32)
    y_true = np.asarray(y_list, dtype=np.int32)
    y_proba = predict_fn(X).astype(np.float64)
    y_hat = (y_proba >= 0.5).astype(np.int32)

    acc = float(accuracy_score(y_true, y_hat))
    try:
        auc_val = float(roc_auc_score(y_true, y_proba)) if len(np.unique(y_true)) > 1 else None
    except Exception:
        auc_val = None
    samples: list[dict[str, Any]] = []
    for i in range(min(15, len(meta_rows))):
        samples.append(
            {
                "external_tx_id": meta_rows[i]["external_tx_id"],
                "label": int(y_true[i]),
                "fraud_proba": float(y_proba[i]),
                "predicted_fraud": bool(y_hat[i] == 1),
            }
        )
    cm = confusion_matrix(y_true, y_hat, labels=[0, 1])
    confusion = {
        "labels": ["LEGIT", "FRAUD"],
        "matrix": [[int(cm[0][0]), int(cm[0][1])], [int(cm[1][0]), int(cm[1][1])]],
    }
    threshold_metrics: list[dict[str, Any]] = []
    for thr in (0.3, 0.5, 0.7):
        y_thr = (y_proba >= thr).astype(np.int32)
        p, r, f1, _ = precision_recall_fscore_support(
            y_true, y_thr, labels=[1], average="binary", zero_division=0
        )
        threshold_metrics.append(
            {
                "threshold": float(thr),
                "accuracy": float(accuracy_score(y_true, y_thr)),
                "precision": float(p),
                "recall": float(r),
                "f1": float(f1),
            }
        )
    segments: dict[str, list[dict[str, Any]]] = {"channel": [], "amount_bucket": []}
    for key in ("channel", "amount_bucket"):
        buckets: dict[str, list[int]] = {}
        for i, mr in enumerate(meta_rows):
            b = str(mr.get(key) or "UNKNOWN")
            buckets.setdefault(b, []).append(i)
        for b, idxs in buckets.items():
            yt = y_true[idxs]
            yp = y_hat[idxs]
            if len(yt) < 5:
                continue
            p, r, f1, _ = precision_recall_fscore_support(
                yt, yp, labels=[1], average="binary", zero_division=0
            )
            segments[key].append(
                {
                    "segment": b,
                    "n": int(len(yt)),
                    "accuracy": float(accuracy_score(yt, yp)),
                    "precision": float(p),
                    "recall": float(r),
                    "f1": float(f1),
                }
            )
        segments[key].sort(key=lambda x: x["n"], reverse=True)

    return {
        "upload_id": "external_holdout",
        "n_scored": n_scored,
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": auc_val,
        "retrain_locked": False,
        "samples": samples,
        "threshold_metrics": threshold_metrics,
        "segments": segments,
        "confusion": confusion,
    }
