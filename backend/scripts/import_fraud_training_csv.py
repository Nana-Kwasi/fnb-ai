"""
Import fraud training CSV(s) into the database (transactions + fraud_outcomes, ensure tenant + customers exist).
Then you can run the fraud trainer (FRAUD_TRAIN_MODE=real).

Usage (from repo root or backend):
  cd backend && python scripts/import_fraud_training_csv.py
  cd backend && python scripts/import_fraud_training_csv.py --files app/ml/data/fraud_training_transactions_20k.csv

Reads CSVs from backend/app/ml/data/ by default: fraud_training_transactions.csv,
fraud_training_transactions_20000.csv, fraud_training_transactions_20k.csv.
"""
import asyncio
import csv
import hashlib
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import AsyncSessionLocal
from app.models import TenantBank, Customer, Transaction, FraudOutcome

DATA_DIR = BACKEND / "app" / "ml" / "data"
DEFAULT_FILES = [
    "fraud_training_transactions.csv",
    "fraud_training_transactions_20000.csv",
    "fraud_training_transactions_20k.csv",
]

def _training_tenant_hash(tenant_id: uuid.UUID) -> str:
    return hashlib.sha256(f"training_tenant_{tenant_id}".encode()).hexdigest()


def parse_ts(s: str) -> datetime:
    s = (s or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.utcnow()


def load_rows(file_paths: list[Path]) -> list[dict]:
    rows = []
    for fp in file_paths:
        if not fp.exists():
            print("Skip (not found):", fp)
            continue
        with open(fp, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if not row.get("external_tx_id") or not row.get("classification"):
                    continue
                rows.append(row)
        print("Loaded", len(rows), "rows from", fp.name, "so far")
    return rows


async def ensure_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    r = await session.execute(select(TenantBank).where(TenantBank.id == tenant_id))
    if r.scalar_one_or_none():
        return
    session.add(
        TenantBank(
            id=tenant_id,
            name="Training Tenant",
            country_code="GH",
            api_key_hash=_training_tenant_hash(tenant_id),
            api_key_prefix="train01",
        )
    )
    await session.flush()
    print("Created tenant", tenant_id)


async def ensure_customer(session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> None:
    r = await session.execute(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if r.scalar_one_or_none():
        return
    session.add(
        Customer(
            id=customer_id,
            tenant_id=tenant_id,
            external_id=str(customer_id),
            risk_score=0.0,
        )
    )
    await session.flush()


async def run_import(session: AsyncSession, rows: list[dict]) -> None:
    rows_sorted = sorted(rows, key=lambda r: parse_ts(r.get("tx_timestamp", "")))
    seen_tenant = set()
    seen_customer = set()
    for i, row in enumerate(rows_sorted):
        tenant_id = uuid.UUID(row["tenant_id"].strip())
        customer_id = uuid.UUID(row["customer_id"].strip())
        if tenant_id not in seen_tenant:
            await ensure_tenant(session, tenant_id)
            seen_tenant.add(tenant_id)
        key = (tenant_id, customer_id)
        if key not in seen_customer:
            await ensure_customer(session, tenant_id, customer_id)
            seen_customer.add(key)

        tx = Transaction(
            tenant_id=tenant_id,
            customer_id=customer_id,
            external_tx_id=row["external_tx_id"].strip(),
            amount=Decimal(row.get("amount", 0) or "0"),
            currency=(row.get("currency") or "USD").strip()[:3],
            tx_timestamp=parse_ts(row.get("tx_timestamp", "")),
            merchant_category=(row.get("merchant_category") or "").strip() or None,
            merchant_id=(row.get("merchant_id") or row.get("merchant_category") or "").strip() or None,
            device_id=(row.get("device_id") or "").strip() or None,
            ip_address_hash=(row.get("ip_address_hash") or "").strip() or None,
            location_country=(row.get("location_country") or "").strip() or None,
            channel=(row.get("channel") or "").strip() or None,
            status="PENDING",
        )
        session.add(tx)
        await session.flush()

        session.add(
            FraudOutcome(
                tenant_id=tenant_id,
                transaction_id=tx.id,
                classification=row["classification"].strip(),
                source=(row.get("source") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
            )
        )
        if (i + 1) % 2000 == 0:
            print("Imported", i + 1, "transactions...")
    await session.commit()
    print("Imported", len(rows_sorted), "transactions with outcomes.")


async def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Import fraud training CSVs into DB")
    p.add_argument("--files", nargs="*", help="CSV paths under backend/app/ml/data or absolute")
    args = p.parse_args()
    if args.files:
        file_paths = [Path(f) if Path(f).is_absolute() else DATA_DIR / Path(f).name for f in args.files]
    else:
        file_paths = [DATA_DIR / f for f in DEFAULT_FILES]
    rows = load_rows(file_paths)
    if not rows:
        print("No rows to import. Check CSV paths and content.")
        sys.exit(1)
    print("Total rows to import:", len(rows))
    async with AsyncSessionLocal() as session:
        await run_import(session, rows)
    print("Done. Run fraud training: FRAUD_TRAIN_MODE=real python -m app.ml.train")
    print("Or use Admin dashboard -> Trigger fraud train.")


if __name__ == "__main__":
    asyncio.run(main())
