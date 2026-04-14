"""
Evaluate trained care intent model against rows from an uploaded care dataset.
"""
from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from sklearn.metrics import precision_recall_fscore_support
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.training_data import TrainingUpload, TrainingUploadRow


def _normalize_care_intent_label(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    u = s.upper()
    if u in {
        "BALANCE_INQUIRY",
        "FRAUD_DISPUTE",
        "ACCOUNT_LOCKED",
        "HUMAN_ESCALATION",
        "TRANSACTION_HISTORY",
        "CARD_BLOCK",
        "PIN_RESET",
        "BRANCH_ATM",
        "COMPLAINT",
        "CONTACT_SUPPORT",
        "GENERAL_SUPPORT",
        "SECURITY_GUIDANCE",
    }:
        return u
    key = s.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fraud_report": "FRAUD_DISPUTE",
        "fraud_inquiry": "FRAUD_DISPUTE",
        "dispute_transaction": "FRAUD_DISPUTE",
        "account_locked": "ACCOUNT_LOCKED",
        "pin_reset": "PIN_RESET",
        "card_block": "CARD_BLOCK",
        "freeze_card": "CARD_BLOCK",
        "transaction_history": "TRANSACTION_HISTORY",
        "payment_methods": "GENERAL_SUPPORT",
        "loan_inquiry": "GENERAL_SUPPORT",
        "refund_request": "COMPLAINT",
        "contact_support": "CONTACT_SUPPORT",
    }
    return aliases.get(key, "")


def _extract_text_intent(payload: dict) -> tuple[str, str]:
    lower = {str(k).strip().lower(): v for k, v in (payload or {}).items()}
    text = (
        lower.get("text")
        or lower.get("prompt")
        or lower.get("message")
        or lower.get("utterance")
        or lower.get("query")
        or ""
    )
    intent_raw = (
        lower.get("intent")
        or lower.get("label")
        or lower.get("intent_name")
        or lower.get("category")
        or ""
    )
    return str(text).strip(), _normalize_care_intent_label(str(intent_raw).strip())


def _extract_raw_intent(payload: dict) -> str:
    lower = {str(k).strip().lower(): v for k, v in (payload or {}).items()}
    raw = (
        lower.get("intent")
        or lower.get("label")
        or lower.get("intent_name")
        or lower.get("category")
        or ""
    )
    return str(raw).strip()


def _classification_breakdown(y_true: list[str], y_pred: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels = sorted(set(y_true) | set(y_pred))
    y_true_arr = np.asarray(y_true, dtype=object)
    y_pred_arr = np.asarray(y_pred, dtype=object)
    p, r, f1, support = precision_recall_fscore_support(
        y_true_arr,
        y_pred_arr,
        labels=labels,
        average=None,
        zero_division=0,
    )
    per_intent = []
    for i, label in enumerate(labels):
        per_intent.append(
            {
                "intent": str(label),
                "precision": float(p[i]),
                "recall": float(r[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
        )

    idx = {lab: i for i, lab in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for t, p_lab in zip(y_true, y_pred):
        matrix[idx[str(t)]][idx[str(p_lab)]] += 1
    confusion = {"labels": labels, "matrix": matrix}
    return per_intent, confusion


def _load_care_model():
    import joblib
    from pathlib import Path

    model_path = Path(__file__).resolve().parents[1] / "ml" / "models" / "care_intent_model.joblib"
    if not model_path.exists():
        raise RuntimeError("Care model not found. Train care model first.")
    model = joblib.load(model_path)
    pipeline = model.get("pipeline")
    le = model.get("label_encoder")
    if pipeline is None:
        raise RuntimeError("Care model is invalid (missing pipeline).")
    if le is None:
        raise RuntimeError("Care model is invalid (missing label_encoder).")
    return pipeline, le


async def evaluate_care_upload(
    db: AsyncSession,
    upload_id: uuid.UUID,
    sample_max: int = 300,
) -> dict[str, Any]:
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == upload_id))).scalar_one_or_none()
    if not upload or upload.model_type != "care":
        raise ValueError("Upload not found or not a care upload.")
    if upload.status != "TRAINED":
        raise ValueError("Upload must be in TRAINED status (run manual train first).")

    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == upload_id).order_by(TrainingUploadRow.row_index.asc())
    )
    row_orms = rows_q.scalars().all()
    if not row_orms:
        raise ValueError("No rows in upload.")

    pipeline, le = _load_care_model()
    valid_rows: list[tuple[int, str, str]] = []
    skipped = 0
    for r in row_orms:
        p = r.payload or {}
        text, intent = _extract_text_intent(p)
        if not text or not intent:
            skipped += 1
            continue
        valid_rows.append((int(r.row_index), text, intent))

    # Prefer exact row-index holdout captured at retrain time.
    holdout_indices = (upload.meta or {}).get("care_holdout_row_indices") or []
    if isinstance(holdout_indices, list) and holdout_indices:
        idx_set = {int(x) for x in holdout_indices}
        eval_rows = [row for row in valid_rows if row[0] in idx_set]
    else:
        # Fallback for older metadata: deterministic random holdout.
        holdout_size = int((upload.meta or {}).get("care_holdout_test_rows") or 0)
        if holdout_size > 0 and len(valid_rows) >= holdout_size:
            idx = list(range(len(valid_rows)))
            import random

            rng = random.Random(upload_id.int & 0xFFFFFFFF)
            rng.shuffle(idx)
            holdout_ids = set(idx[:holdout_size])
            eval_rows = [row for i, row in enumerate(valid_rows) if i in holdout_ids]
        else:
            eval_rows = valid_rows

    if len(eval_rows) > sample_max:
        eval_rows = eval_rows[:sample_max]

    texts = [t for _, t, _ in eval_rows]
    y_true = [intent for _, _, intent in eval_rows]

    if len(texts) < 10:
        raise ValueError("Too few valid rows for care test (need at least 10 rows with text+intent).")

    preds_idx = pipeline.predict(texts)
    y_pred: list[str] = []
    for idx in preds_idx:
        try:
            y_pred.append(str(le.inverse_transform([int(idx)])[0]))
        except Exception:
            y_pred.append(str(idx))

    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    acc = float(correct / max(1, len(y_true)))
    per_intent, confusion = _classification_breakdown(y_true, y_pred)
    samples: list[dict[str, Any]] = []
    for i in range(min(15, len(texts))):
        samples.append(
            {
                "text": texts[i][:120],
                "label": y_true[i],
                "predicted_intent": y_pred[i],
                "correct": y_true[i] == y_pred[i],
            }
        )

    meta = dict(upload.meta or {})
    meta["last_eval"] = {
        "n_scored": len(texts),
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": None,
    }
    upload.meta = meta
    await db.flush()

    return {
        "upload_id": str(upload_id),
        "n_scored": len(texts),
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": None,
        "retrain_locked": False,
        "samples": samples,
        "per_intent": per_intent,
        "confusion": confusion,
    }


async def evaluate_care_external_rows(
    rows: list[dict],
    sample_max: int = 1000,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("No rows found in test file.")

    pipeline, le = _load_care_model()
    valid_rows: list[tuple[str, str]] = []
    skipped = 0
    for p in rows[: max(1, sample_max)]:
        text, intent = _extract_text_intent(p or {})
        if not text or not intent:
            skipped += 1
            continue
        valid_rows.append((text, intent))

    if len(valid_rows) < 10:
        raise ValueError("Too few valid rows for care test (need at least 10 rows with text+intent).")

    texts = [t for t, _ in valid_rows]
    y_true = [intent for _, intent in valid_rows]
    preds_idx = pipeline.predict(texts)
    y_pred: list[str] = []
    for idx in preds_idx:
        try:
            y_pred.append(str(le.inverse_transform([int(idx)])[0]))
        except Exception:
            y_pred.append(str(idx))

    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    acc = float(correct / max(1, len(y_true)))
    per_intent, confusion = _classification_breakdown(y_true, y_pred)
    samples: list[dict[str, Any]] = []
    for i in range(min(15, len(texts))):
        samples.append(
            {
                "text": texts[i][:120],
                "label": y_true[i],
                "predicted_intent": y_pred[i],
                "correct": y_true[i] == y_pred[i],
            }
        )

    return {
        "upload_id": "external_holdout",
        "n_scored": len(texts),
        "n_skipped": skipped,
        "accuracy": acc,
        "auc": None,
        "retrain_locked": False,
        "samples": samples,
        "per_intent": per_intent,
        "confusion": confusion,
    }


async def summarize_care_label_mapping(
    db: AsyncSession,
    upload_id: uuid.UUID,
) -> dict[str, Any]:
    upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == upload_id))).scalar_one_or_none()
    if not upload or upload.model_type != "care":
        raise ValueError("Upload not found or not a care upload.")

    rows_q = await db.execute(
        select(TrainingUploadRow).where(TrainingUploadRow.upload_id == upload_id).order_by(TrainingUploadRow.row_index.asc())
    )
    rows = rows_q.scalars().all()
    if not rows:
        raise ValueError("No rows in upload.")

    grouped: dict[tuple[str, str], int] = {}
    for r in rows:
        payload = r.payload or {}
        raw = _extract_raw_intent(payload)
        mapped = _normalize_care_intent_label(raw) if raw else ""
        k = (raw or "(empty)", mapped or "(ignored)")
        grouped[k] = grouped.get(k, 0) + 1

    pairs = sorted(grouped.items(), key=lambda kv: kv[1], reverse=True)
    rows_out = [
        {
            "raw_label": raw,
            "mapped_intent": mapped,
            "count": count,
        }
        for (raw, mapped), count in pairs
    ]
    ignored = sum(item["count"] for item in rows_out if item["mapped_intent"] == "(ignored)")
    return {
        "upload_id": str(upload_id),
        "total_rows": len(rows),
        "ignored_rows": ignored,
        "rows": rows_out,
    }

