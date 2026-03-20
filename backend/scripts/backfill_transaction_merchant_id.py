"""
Backfill transactions.merchant_id from transaction_fingerprints.merchant_id.

Why:
  - New scoring/features use stable merchant identity (MID) instead of merchant_category.
  - Historical transactions may have NULL transactions.merchant_id.

What it does per tenant:
  1) Set transactions.merchant_id (only when NULL) to the fingerprint-provided merchant_id.
  2) For any remaining NULLs, fall back to transactions.merchant_category.
  3) Runs rebuild_fraud_aggregates for the tenant to re-stitch MerchantRisk aggregates and clear caches.

Usage:
  cd backend && python scripts/backfill_transaction_merchant_id.py --all
  cd backend && python scripts/backfill_transaction_merchant_id.py --tenant-id <uuid>
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Iterable
import uuid

from sqlalchemy import func, select, update

# Ensure `app.*` imports work when executed from `backend/`.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.database import AsyncSessionLocal
from app.models import TenantBank, Transaction
from app.models.fraud_extra import TransactionFingerprint


async def _count_nulls(session, tenant_id: uuid.UUID) -> int:
    q = select(func.count()).select_from(Transaction).where(
        Transaction.tenant_id == tenant_id,
        Transaction.merchant_id.is_(None),
    )
    return int((await session.execute(q)).scalar() or 0)


async def _backfill_for_tenant(session, tenant_id: uuid.UUID) -> None:
    null_before = await _count_nulls(session, tenant_id)
    print(f"[{tenant_id}] NULL merchant_id before: {null_before}")

    # Prefer the merchant_id stored on fingerprint rows for true MID.
    # If multiple fingerprint rows disagree, MAX() provides deterministic selection.
    mid_subq = (
        select(
            TransactionFingerprint.transaction_id.label("tx_id"),
            func.max(TransactionFingerprint.merchant_id).label("mid"),
        )
        .where(
            TransactionFingerprint.tenant_id == tenant_id,
            TransactionFingerprint.merchant_id.isnot(None),
        )
        .group_by(TransactionFingerprint.transaction_id)
        .subquery()
    )

    stmt1 = (
        update(Transaction)
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.merchant_id.is_(None),
            Transaction.id == mid_subq.c.tx_id,
        )
        .values(merchant_id=mid_subq.c.mid)
    )
    await session.execute(stmt1)
    await session.flush()

    null_mid_after = await _count_nulls(session, tenant_id)
    print(f"[{tenant_id}] NULL merchant_id after fp-backfill: {null_mid_after}")

    # Remaining NULLs: safe fallback to stored merchant_category.
    stmt2 = (
        update(Transaction)
        .where(
            Transaction.tenant_id == tenant_id,
            Transaction.merchant_id.is_(None),
        )
        .values(merchant_id=Transaction.merchant_category)
    )
    await session.execute(stmt2)
    await session.flush()

    null_final = await _count_nulls(session, tenant_id)
    print(f"[{tenant_id}] NULL merchant_id after category-fallback: {null_final}")

    await session.commit()

    # Re-stitch aggregates + clear feature caches.
    from scripts.rebuild_fraud_aggregates import rebuild_for_tenant

    # Use a new transaction scope for rebuild (separate from update commits).
    await rebuild_for_tenant(session, tenant_id)


def _parse_tenant_ids(all_tenants: Iterable, tenant_id_arg: str | None):
    if tenant_id_arg:
        # Provided as UUID string.
        return [tenant_id_arg]
    return [str(t.id) for t in all_tenants]


async def main() -> None:
    p = argparse.ArgumentParser(description="Backfill transactions.merchant_id from transaction_fingerprints")
    p.add_argument("--all", action="store_true", help="Backfill all tenants")
    p.add_argument("--tenant-id", type=str, help="Single tenant id")
    args = p.parse_args()

    if not args.all and not args.tenant_id:
        raise SystemExit("Provide --all or --tenant-id <uuid>.")

    async with AsyncSessionLocal() as session:
        if args.all:
            tenant_ids = (await session.execute(select(TenantBank.id))).scalars().all()
        else:
            tenant_ids = [uuid.UUID(args.tenant_id)]

        for tid in tenant_ids:
            await _backfill_for_tenant(session, tid)

    print("Backfill complete.")


if __name__ == "__main__":
    asyncio.run(main())

