"""
Replay training CSV transactions through the live Fraud API to sanity-check behaviour.

Usage (from backend/):
    export FRAUD_API_KEY=<tenant_api_key_from_tenant_banks_or_admin_onboard>
    python scripts/replay_fraud_training_to_api.py --file app/ml/data/fraud_training_transactions_20k.csv --limit 500

Defaults:
    FRAUD_API_URL = http://127.0.0.1:8000/api/v1

We treat labels as:
    classification == CONFIRMED_FRAUD      -> y = 1
    classification in {FALSE_POSITIVE,
                       CONFIRMED_LEGIT}    -> y = 0
    any other classification               -> row skipped
"""
import argparse
import csv
import os
from pathlib import Path

import httpx


BACKEND = Path(__file__).resolve().parent.parent


def map_row_to_payload(row: dict) -> dict:
    """
    Map one CSV row (see EXCEL_LAYOUT.md) to TransactionIn payload
    for POST /api/v1/fraud/score/detail.
    """
    return {
        "transaction_id": row["external_tx_id"],
        # For training tenant we used customer_id as internal id, but the fraud API
        # expects an external account_id string; using customer_id here is fine.
        "account_id": row["customer_id"],
        "amount": float(row["amount"]),
        "currency": (row.get("currency") or "USD")[:3],
        "merchant_category": row.get("merchant_category") or None,
        "location": row.get("location_country") or None,
        "device_id": row.get("device_id") or None,
        # API accepts raw ip_address; training CSV already has a hashed form.
        "ip_address": row.get("ip_address_hash") or None,
        "timestamp": row["tx_timestamp"],
    }


def get_label(row: dict) -> int | None:
    """Return 1 for fraud, 0 for legit, None to skip."""
    cls = (row.get("classification") or "").strip().upper()
    if cls == "CONFIRMED_FRAUD":
        return 1
    if cls in {"FALSE_POSITIVE", "CONFIRMED_LEGIT"}:
        return 0
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="Replay fraud training CSV rows through live Fraud API")
    p.add_argument("--file", help="CSV path under backend/ or absolute", default="app/ml/data/fraud_training_transactions_20k.csv")
    p.add_argument("--limit", type=int, default=500, help="Max rows to replay")
    args = p.parse_args()

    api_base = os.environ.get("FRAUD_API_URL", "http://127.0.0.1:8000/api/v1")
    api_key = os.environ.get("FRAUD_API_KEY")
    if not api_key:
        raise SystemExit("Set FRAUD_API_KEY to a valid tenant API key.")

    csv_path = Path(args.file)
    if not csv_path.is_absolute():
        csv_path = BACKEND / csv_path
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    client = httpx.Client(
        base_url=api_base,
        timeout=10.0,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
    )

    tp = tn = fp = fn = 0
    total = 0

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            if i > args.limit:
                break
            label = get_label(row)
            if label is None:
                continue

            payload = map_row_to_payload(row)
            r = client.post("/fraud/score/detail", json=payload)
            if r.status_code != 200:
                print(f"[{i}] HTTP {r.status_code}: {r.text[:200]}")
                continue
            data = r.json()

            decision = data.get("decision", "")
            score = float(data.get("risk_score", 0.0))
            is_pred_fraud = 1 if decision in ("BLOCK", "REQUEST_OTP") else 0

            total += 1
            if is_pred_fraud == 1 and label == 1:
                tp += 1
            elif is_pred_fraud == 0 and label == 0:
                tn += 1
            elif is_pred_fraud == 1 and label == 0:
                fp += 1
            else:
                fn += 1

            if total % 25 == 0:
                print(
                    f"[{total}] cls={label} dec={decision} score={score:.3f} "
                    f"TP={tp} FP={fp} TN={tn} FN={fn}"
                )

    if total == 0:
        print("No labelled rows were evaluated.")
        return

    acc = (tp + tn) / total if total else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    print("\n=== Replay summary ===")
    print(f"Rows evaluated: {total}")
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"Accuracy      = {acc:.3f}")
    print(f"Recall (fraud)= {recall:.3f}")
    print(f"Precision     = {precision:.3f}")


if __name__ == "__main__":
    main()

