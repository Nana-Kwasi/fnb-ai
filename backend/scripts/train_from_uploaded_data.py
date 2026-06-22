"""
Train fraud/care models from uploaded training rows stored in DB.

Usage:
  cd backend && python scripts/train_from_uploaded_data.py --model fraud --upload-id <uuid>
  cd backend && python scripts/train_from_uploaded_data.py --model care --upload-id <uuid>
"""

import argparse
import asyncio
import csv
import json
import os
import random
import re
import subprocess
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import AsyncSessionLocal
from app.models.training_data import TrainingUpload, TrainingUploadRow
from app.tasks.care_train_scheduled import train_intent_from_external_jsonl


def _normalize_care_intent_label(raw: str) -> str:
    """
    Map common dataset labels to the canonical intents expected by care training.
    """
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

    key = s.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fraud_report": "FRAUD_DISPUTE",
        "fraud_inquiry": "FRAUD_DISPUTE",
        "dispute_transaction": "FRAUD_DISPUTE",
        "chargeback": "FRAUD_DISPUTE",
        "unauthorized_payment": "FRAUD_DISPUTE",
        "unauthorised_payment": "FRAUD_DISPUTE",
        "account_locked": "ACCOUNT_LOCKED",
        "lock_account": "ACCOUNT_LOCKED",
        "unlock_account": "ACCOUNT_LOCKED",
        "pin_reset": "PIN_RESET",
        "reset_pin": "PIN_RESET",
        "card_block": "CARD_BLOCK",
        "freeze_card": "CARD_BLOCK",
        "transaction_history": "TRANSACTION_HISTORY",
        "payment_methods": "GENERAL_SUPPORT",
        "loan_inquiry": "GENERAL_SUPPORT",
        "refund_request": "COMPLAINT",
        "support": "CONTACT_SUPPORT",
        "contact_support": "CONTACT_SUPPORT",
        "human_escalation": "HUMAN_ESCALATION",
    }
    return aliases.get(key, "")


async def _mark_training_started(upload_id: uuid.UUID) -> TrainingUpload:
    async with AsyncSessionLocal() as db:
        upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == upload_id))).scalar_one_or_none()
        if not upload:
            raise RuntimeError(f"Upload not found: {upload_id}")
        upload.status = "TRAINING"
        m = dict(upload.meta or {})
        m.pop("retrain_locked", None)
        m.pop("last_eval", None)
        m.pop("last_error", None)
        m["training_started_at"] = datetime.now(timezone.utc).isoformat()
        upload.meta = m or None
        await db.commit()
        return upload


async def _fetch_rows(upload_id: uuid.UUID) -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows_q = await db.execute(
            select(TrainingUploadRow).where(TrainingUploadRow.upload_id == upload_id).order_by(TrainingUploadRow.row_index.asc())
        )
        rows = []
        for r in rows_q.scalars().all():
            payload = dict(r.payload or {})
            payload["__row_index"] = int(r.row_index)
            rows.append(payload)
        return rows


async def _load_rows(upload_id: uuid.UUID) -> tuple[TrainingUpload, list[dict]]:
    upload = await _mark_training_started(upload_id)
    rows = await _fetch_rows(upload_id)
    return upload, rows


async def _mark_status(
    upload_id: uuid.UUID,
    status: str,
    error: str | None = None,
    extra_meta: dict | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        upload = (await db.execute(select(TrainingUpload).where(TrainingUpload.id == upload_id))).scalar_one_or_none()
        if upload:
            upload.status = status
            m = dict(upload.meta or {})
            now_iso = datetime.now(timezone.utc).isoformat()
            if status == "FAILED" and error:
                m["last_error"] = error[:500]
            elif status in {"TRAINED", "TRAINING"}:
                m.pop("last_error", None)
            if extra_meta:
                m.update(extra_meta)
            if status == "TRAINED":
                m["last_retrained_at"] = now_iso
                started_s = m.get("training_started_at")
                if started_s:
                    try:
                        started = datetime.fromisoformat(str(started_s).replace("Z", "+00:00"))
                        ended = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
                        m["last_training_duration_s"] = round(max(0.0, (ended - started).total_seconds()), 3)
                    except Exception:
                        pass
                m.pop("training_started_at", None)
            elif status == "FAILED":
                started_s = m.get("training_started_at")
                if started_s:
                    try:
                        started = datetime.fromisoformat(str(started_s).replace("Z", "+00:00"))
                        ended = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
                        m["last_training_duration_s"] = round(max(0.0, (ended - started).total_seconds()), 3)
                    except Exception:
                        pass
                m.pop("training_started_at", None)
            upload.meta = m or None
            await db.commit()


def _run(cmd: list[str], env: dict | None = None) -> None:
    result = subprocess.run(cmd, env=env, cwd=str(BACKEND), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr or result.stdout}")


def _sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    import hashlib

    h = hashlib.sha256()
    if path.is_file():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    files = sorted([p for p in path.rglob("*") if p.is_file()])
    if not files:
        return None
    for fp in files:
        rel = str(fp.relative_to(path)).replace("\\", "/").encode("utf-8")
        h.update(rel)
        with open(fp, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    return h.hexdigest()


def _train_fraud(upload_id: uuid.UUID, rows: list[dict]) -> dict:
    data_dir = BACKEND / "app" / "ml" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_csv = data_dir / f"uploaded_fraud_{upload_id}.csv"
    fieldnames = [
        "tenant_id",
        "customer_id",
        "external_tx_id",
        "amount",
        "currency",
        "tx_timestamp",
        "merchant_category",
        "merchant_id",
        "device_id",
        "ip_address_hash",
        "location_country",
        "channel",
        "classification",
        "source",
        "notes",
    ]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in fieldnames}
            w.writerow(row)

    _run([sys.executable, "scripts/import_fraud_training_csv.py", "--files", out_csv.name])
    env = os.environ.copy()
    env.setdefault("FRAUD_TRAIN_MODE", "real")
    _run([sys.executable, "-m", "app.ml.train"], env=env)
    model_dir = BACKEND / "models" / "fraud"
    return {
        "trained_artifact_uri": str(model_dir),
        "trained_artifact_sha256": _sha256_path(model_dir),
    }


def _split_train_holdout(
    examples: list[tuple[str, str, int]],
    upload_id: uuid.UUID,
    holdout_ratio: float = 0.2,
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    if not examples:
        return [], []
    n = len(examples)
    if n < 20:
        return examples, []

    def _norm_text_key(text: str) -> str:
        t = unicodedata.normalize("NFKC", (text or "").lower())
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())
        return t[:160]

    groups: dict[str, list[tuple[str, str, int]]] = {}
    for ex in examples:
        key = _norm_text_key(ex[0])
        groups.setdefault(key, []).append(ex)

    keys = list(groups.keys())
    rng = random.Random(upload_id.int & 0xFFFFFFFF)
    rng.shuffle(keys)

    target = max(1, int(n * holdout_ratio))
    holdout: list[tuple[str, str, int]] = []
    holdout_count = 0
    holdout_keys: set[str] = set()
    for k in keys:
        if holdout_count >= target:
            break
        chunk = groups[k]
        holdout.extend(chunk)
        holdout_count += len(chunk)
        holdout_keys.add(k)

    train = [ex for ex in examples if _norm_text_key(ex[0]) not in holdout_keys]
    if not train:
        # Fallback: avoid empty train due to an oversized first group.
        holdout = holdout[: max(1, n // 10)]
        holdout_row_set = {row_idx for _, _, row_idx in holdout}
        train = [ex for ex in examples if ex[2] not in holdout_row_set]
    return train, holdout


def _train_care(upload_id: uuid.UUID, rows: list[dict]) -> dict:
    data_dir = BACKEND / "app" / "ml" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = data_dir / f"uploaded_care_{upload_id}.jsonl"
    holdout_jsonl = data_dir / f"uploaded_care_holdout_{upload_id}.jsonl"

    valid_examples: list[tuple[str, str, int]] = []
    for r in rows:
        lower = {str(k).strip().lower(): v for k, v in (r or {}).items()}
        text = (
            (lower.get("text"))
            or (lower.get("prompt"))
            or (lower.get("message"))
            or (lower.get("utterance"))
            or (lower.get("query"))
            or ""
        )
        intent = (
            (lower.get("intent"))
            or (lower.get("label"))
            or (lower.get("intent_name"))
            or (lower.get("category"))
            or ""
        )
        text = str(text).strip()
        intent = _normalize_care_intent_label(str(intent).strip())
        row_index = int((r or {}).get("__row_index") or 0)
        if not text or not intent:
            continue
        valid_examples.append((text, intent, row_index))

    if not valid_examples:
        raise RuntimeError(
            "Care upload has no valid rows. Expected text column like text/prompt/message/utterance/query and intent column like intent/label."
        )

    train_examples, holdout_examples = _split_train_holdout(valid_examples, upload_id, holdout_ratio=0.2)
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for text, intent, _ in train_examples:
            f.write(json.dumps({"text": text, "intent": intent}, ensure_ascii=False) + "\n")

    with open(holdout_jsonl, "w", encoding="utf-8") as f:
        for text, intent, _ in holdout_examples:
            f.write(json.dumps({"text": text, "intent": intent}, ensure_ascii=False) + "\n")

    trained = train_intent_from_external_jsonl(str(out_jsonl))
    if not trained:
        raise RuntimeError(
            "Care retrain skipped: too few valid mapped examples after label mapping. "
            "Use Label map to fix/normalize labels, then retrain."
        )
    holdout_row_indices = [row_idx for _, _, row_idx in holdout_examples]
    model_path = BACKEND / "app" / "ml" / "models" / "care_intent_model.joblib"
    return {
        "care_holdout_total_rows": len(valid_examples),
        "care_holdout_train_rows": len(train_examples),
        "care_holdout_test_rows": len(holdout_examples),
        "care_holdout_row_indices": holdout_row_indices,
        "care_holdout_strategy": "grouped_normalized_text",
        "care_holdout_source": str(holdout_jsonl),
        "trained_artifact_uri": str(model_path),
        "trained_artifact_sha256": _sha256_path(model_path),
    }


async def _load_merge_rows(upload_ids: list[uuid.UUID]) -> tuple[uuid.UUID, list[dict], list[uuid.UUID]]:
    primary = upload_ids[0]
    for uid in upload_ids:
        await _mark_training_started(uid)
    all_rows: list[dict] = []
    for uid in upload_ids:
        part = await _fetch_rows(uid)
        for r in part:
            r = dict(r)
            r["__source_upload_id"] = str(uid)
            all_rows.append(r)
    return primary, all_rows, upload_ids


async def main() -> None:
    parser = argparse.ArgumentParser(description="Train model from uploaded DB rows")
    parser.add_argument("--model", choices=["fraud", "care"], required=True)
    parser.add_argument("--upload-id", default=None)
    parser.add_argument(
        "--merge-upload-ids",
        default=None,
        help="Comma-separated UUIDs; global pooled train (concat rows), status written on all uploads.",
    )
    args = parser.parse_args()
    merge_raw = (args.merge_upload_ids or "").strip()
    if merge_raw:
        ids = [uuid.UUID(x.strip()) for x in merge_raw.split(",") if x.strip()]
        if len(ids) < 2:
            raise SystemExit("merge-upload-ids requires at least two UUIDs")
        primary, rows, all_ids = await _load_merge_rows(ids)
    else:
        if not args.upload_id:
            raise SystemExit("Provide --upload-id or --merge-upload-ids")
        upload_id = uuid.UUID(args.upload_id)
        _upload, rows = await _load_rows(upload_id)
        primary = upload_id
        all_ids = [upload_id]

    if not rows:
        await _mark_status(primary, "FAILED")
        raise RuntimeError("Upload has no rows.")
    try:
        if args.model == "fraud":
            extra_meta = _train_fraud(primary, rows)
        else:
            extra_meta = _train_care(primary, rows)
        if merge_raw:
            extra_meta = {
                **(extra_meta or {}),
                "global_pooled_upload_ids": [str(x) for x in all_ids],
                "global_pooled_row_count": len(rows),
            }
        for uid in all_ids:
            await _mark_status(uid, "TRAINED", extra_meta=extra_meta if uid == primary else {"global_pooled_primary": str(primary)})
    except Exception as exc:
        for uid in all_ids:
            await _mark_status(uid, "FAILED", str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(main())

