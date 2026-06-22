"""
One-time repair job: rebuild Fraud aggregates from source-of-truth.

Recomputes:
  - MerchantRisk (total_transactions, fraud_transactions, fraud_rate, last_updated)
  - FingerprintStats (total_transactions, fraud_transactions, fraud_rate, last_seen)

from:
  - Transaction
  - TransactionFingerprint
  - FraudOutcome (classification)

Usage:
  cd backend && python scripts/rebuild_fraud_aggregates.py --all
  cd backend && python scripts/rebuild_fraud_aggregates.py --tenant-id <uuid>
"""

import argparse
import asyncio
import uuid

import sqlalchemy as sa
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import TenantBank, Transaction, FraudOutcome, TransactionFingerprint
from app.models.fraud_extra import MerchantRisk, FingerprintStats


def _fraud_case():
    return case((FraudOutcome.classification == "CONFIRMED_FRAUD", 1), else_=0)


async def _upsert_merchant_risk(session: AsyncSession, tenant_id) -> int:
    q = (
        select(
            func.coalesce(Transaction.merchant_id, Transaction.merchant_category).label("merchant_id"),
            func.count(func.distinct(Transaction.id)).label("total_transactions"),
            func.sum(_fraud_case()).label("fraud_transactions"),
            func.max(Transaction.tx_timestamp).label("last_updated"),
        )
        .outerjoin(
            FraudOutcome,
            sa.and_(
                FraudOutcome.transaction_id == Transaction.id,
                FraudOutcome.tenant_id == tenant_id,
            ),
        )
        .where(
            Transaction.tenant_id == tenant_id,
            func.coalesce(Transaction.merchant_id, Transaction.merchant_category).isnot(None),
        )
        .group_by(func.coalesce(Transaction.merchant_id, Transaction.merchant_category))
    )
    rows = (await session.execute(q)).all()
    if not rows:
        return 0

    count = 0
    for merchant_id, total_transactions, fraud_transactions, last_updated in rows:
        total_transactions = int(total_transactions or 0)
        fraud_transactions = int(fraud_transactions or 0)
        fraud_rate = float(fraud_transactions) / total_transactions if total_transactions > 0 else 0.0

        mr = (
            await session.execute(
                select(MerchantRisk).where(
                    sa.and_(
                        MerchantRisk.tenant_id == tenant_id,
                        MerchantRisk.merchant_id == merchant_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if not mr:
            session.add(
                MerchantRisk(
                    tenant_id=tenant_id,
                    merchant_id=str(merchant_id),
                    total_transactions=total_transactions,
                    fraud_transactions=fraud_transactions,
                    fraud_rate=fraud_rate,
                    last_updated=last_updated,
                )
            )
            count += 1
        else:
            mr.total_transactions = total_transactions
            mr.fraud_transactions = fraud_transactions
            mr.fraud_rate = fraud_rate
            mr.last_updated = last_updated
            count += 1
    await session.flush()
    return count


async def _upsert_fingerprint_stats(session: AsyncSession, tenant_id) -> int:
    q = (
        select(
            TransactionFingerprint.fingerprint_id.label("fingerprint_id"),
            func.count(func.distinct(TransactionFingerprint.transaction_id)).label("total_transactions"),
            func.sum(_fraud_case()).label("fraud_transactions"),
            func.max(Transaction.tx_timestamp).label("last_seen"),
        )
        .select_from(TransactionFingerprint)
        .join(
            Transaction,
            sa.and_(Transaction.id == TransactionFingerprint.transaction_id, Transaction.tenant_id == tenant_id),
        )
        .outerjoin(
            FraudOutcome,
            sa.and_(
                FraudOutcome.transaction_id == Transaction.id,
                FraudOutcome.tenant_id == tenant_id,
            ),
        )
        .where(TransactionFingerprint.tenant_id == tenant_id)
        .group_by(TransactionFingerprint.fingerprint_id)
    )

    rows = (await session.execute(q)).all()
    if not rows:
        return 0

    count = 0
    for fingerprint_id, total_transactions, fraud_transactions, last_seen in rows:
        total_transactions = int(total_transactions or 0)
        fraud_transactions = int(fraud_transactions or 0)
        fraud_rate = float(fraud_transactions) / total_transactions if total_transactions > 0 else 0.0

        row = (
            await session.execute(
                select(FingerprintStats).where(
                    sa.and_(
                        FingerprintStats.tenant_id == tenant_id,
                        FingerprintStats.fingerprint_id == fingerprint_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if not row:
            session.add(
                FingerprintStats(
                    tenant_id=tenant_id,
                    fingerprint_id=str(fingerprint_id),
                    total_transactions=total_transactions,
                    fraud_transactions=fraud_transactions,
                    fraud_rate=fraud_rate,
                    last_seen=last_seen,
                )
            )
            count += 1
        else:
            row.total_transactions = total_transactions
            row.fraud_transactions = fraud_transactions
            row.fraud_rate = fraud_rate
            row.last_seen = last_seen
            count += 1

    await session.flush()
    return count


async def rebuild_for_tenant(session: AsyncSession, tenant_id) -> None:
    # Clear any cached network/risk features.
    try:
        from app.services.feature_engine import clear_feature_caches

        clear_feature_caches()
    except Exception:
        pass

    m = await _upsert_merchant_risk(session, tenant_id)
    f = await _upsert_fingerprint_stats(session, tenant_id)
    await session.commit()
    print(f"Tenant {tenant_id}: MerchantRisk rows updated/created={m}, FingerprintStats rows updated/created={f}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild fraud aggregates from fraud_outcomes.")
    parser.add_argument("--all", action="store_true", help="Rebuild for all tenants")
    parser.add_argument("--tenant-id", type=str, default=None, help="Tenant UUID to rebuild")
    args = parser.parse_args()

    if not args.all and not args.tenant_id:
        raise SystemExit("Provide --all or --tenant-id <uuid>")

    async with AsyncSessionLocal() as session:
        if args.all:
            tenants = (await session.execute(select(TenantBank.id))).scalars().all()
            if not tenants:
                print("No tenants found.")
                return
            for tid in tenants:
                await rebuild_for_tenant(session, tid)
        else:
            tenant_id = uuid.UUID(args.tenant_id)
            await rebuild_for_tenant(session, tenant_id)


if __name__ == "__main__":
    asyncio.run(main())

