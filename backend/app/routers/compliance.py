"""
GDPR / POPIA compliance endpoints:
  DELETE /api/v1/admin/tenants/{tenant_id}/customers/{customer_id}  — Right to erasure
  GET    /api/v1/admin/tenants/{tenant_id}/customers/{customer_id}/export — Data portability
  POST   /api/v1/admin/tenants/{tenant_id}/rotate-api-key           — API key rotation

These routes require platform admin auth (owner or editor role).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import AdminContext, ensure_tenant_access, require_platform_roles
from app.database import get_db
from app.models import TenantBank
from app.models.audit import AuditLog
from app.models.chat import ChatMessage, ChatSession
from app.models.customer import Customer
from app.models.fraud import FraudScore
from app.models.fraud_extra import (
    Blacklist,
    CustomerBehaviourProfile,
    DeviceAccountMap,
    DeviceFingerprint,
    FraudAlert,
    FraudOutcome,
    IPAccountMap,
    TransactionFingerprint,
)
from app.models.model_registry import InferenceTrace
from app.models.tenant_extended import TenantCompliancePolicy
from app.models.transaction import Transaction
from app.observability import get_logger as _obs_logger

_logger = _obs_logger(__name__)
router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────

async def _resolve_tenant_or_404(db: AsyncSession, tenant_id: str) -> TenantBank:
    bank = (
        await db.execute(select(TenantBank).where(TenantBank.id == uuid.UUID(tenant_id)))
    ).scalar_one_or_none()
    if not bank:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return bank


async def _resolve_customer_or_404(db: AsyncSession, bank: TenantBank, customer_id: str) -> Customer:
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.tenant_id == bank.id,
                Customer.external_id == customer_id,
            )
        )
    ).scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


async def _compliance_policy(db: AsyncSession, tenant_id: uuid.UUID) -> TenantCompliancePolicy | None:
    return (
        await db.execute(
            select(TenantCompliancePolicy).where(TenantCompliancePolicy.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


# ── Right to Erasure ──────────────────────────────────────────────────────────

class ErasureResult(BaseModel):
    customer_id: str
    tenant_id: str
    erased_tables: list[str]
    anonymized: bool
    timestamp: str


@router.delete("/tenants/{tenant_id}/customers/{customer_id}", response_model=ErasureResult)
async def gdpr_erase_customer(
    tenant_id: str,
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
):
    """
    GDPR / POPIA Right to Erasure.

    Purges all PII-bearing rows for this customer across every table.
    Anonymises the Customer row itself (nulls encrypted fields, zeros risk score)
    rather than deleting it so FK references remain intact.

    Requires TenantCompliancePolicy.right_to_erasure_enabled == True.
    """
    await ensure_tenant_access(db, admin, uuid.UUID(tenant_id))
    bank = await _resolve_tenant_or_404(db, tenant_id)
    customer = await _resolve_customer_or_404(db, bank, customer_id)
    policy = await _compliance_policy(db, bank.id)

    if policy and not policy.right_to_erasure_enabled:
        raise HTTPException(
            status_code=403,
            detail="right_to_erasure_enabled is disabled for this tenant's compliance policy",
        )

    erased: list[str] = []

    # Chat history
    sessions_q = await db.execute(
        select(ChatSession).where(
            ChatSession.tenant_id == bank.id,
            ChatSession.customer_id == customer.id,
        )
    )
    session_ids = [s.id for s in sessions_q.scalars().all()]
    if session_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
        await db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))
        erased.append("chat_sessions")
        erased.append("chat_messages")

    # Transactions + fraud scores
    tx_ids_q = await db.execute(
        select(Transaction.id).where(
            Transaction.tenant_id == bank.id,
            Transaction.customer_id == customer.id,
        )
    )
    tx_ids = [r[0] for r in tx_ids_q.all()]
    if tx_ids:
        await db.execute(delete(FraudScore).where(FraudScore.transaction_id.in_(tx_ids)))
        await db.execute(delete(FraudAlert).where(FraudAlert.transaction_id.in_(tx_ids)))
        await db.execute(delete(FraudOutcome).where(FraudOutcome.transaction_id.in_(tx_ids)))
        await db.execute(delete(TransactionFingerprint).where(TransactionFingerprint.transaction_id.in_(tx_ids)))
        await db.execute(delete(Transaction).where(Transaction.id.in_(tx_ids)))
        erased += ["transactions", "fraud_scores", "fraud_alerts", "fraud_outcomes", "transaction_fingerprints"]

    # Inference traces — JSON path query only supported on PostgreSQL; skip on SQLite
    try:
        from app.database import engine as _engine
        if "postgresql" in str(_engine.url):
            await db.execute(
                delete(InferenceTrace).where(
                    InferenceTrace.tenant_id == bank.id,
                    InferenceTrace.trace_json["customer_id"].astext == customer_id,
                )
            )
            erased.append("inference_traces")
    except Exception:
        pass  # best-effort — traces contain no direct PII

    # Behavioural profile + device mappings
    await db.execute(
        delete(CustomerBehaviourProfile).where(
            CustomerBehaviourProfile.tenant_id == bank.id,
            CustomerBehaviourProfile.customer_id == customer.id,
        )
    )
    await db.execute(
        delete(DeviceAccountMap).where(
            DeviceAccountMap.tenant_id == bank.id,
            DeviceAccountMap.customer_id == customer.id,
        )
    )
    await db.execute(
        delete(IPAccountMap).where(
            IPAccountMap.tenant_id == bank.id,
            IPAccountMap.customer_id == customer.id,
        )
    )
    erased += ["customer_behaviour_profiles", "device_account_maps", "ip_account_maps"]

    # Blacklist entries by customer external_id value
    await db.execute(
        delete(Blacklist).where(
            Blacklist.tenant_id == bank.id,
            Blacklist.entity_type == "customer",
            Blacklist.value == customer_id,
        )
    )
    erased.append("blacklist")

    # Anonymise the Customer row — zero PII fields, keep FK-safe shell
    await db.execute(
        update(Customer)
        .where(Customer.id == customer.id)
        .values(
            name_encrypted=None,
            phone_hash=None,
            risk_score=0.0,
            is_flagged=False,
            metadata_={"gdpr_erased": True},
            updated_at=datetime.now(timezone.utc),
        )
    )
    erased.append("customers (anonymised)")

    # Audit trail (the erasure itself must be logged, not erased)
    db.add(
        AuditLog(
            tenant_id=bank.id,
            actor_id=str(admin.user_id),
            event_type="gdpr_erasure",
            entity_type="customer",
            event_data={"erased_tables": erased, "customer_id": customer_id},
        )
    )

    await db.commit()
    _logger.info(
        "gdpr_erasure_completed",
        tenant_id=tenant_id,
        customer_id=customer_id,
        erased_tables=erased,
        actor=str(admin.user_id),
    )

    return ErasureResult(
        customer_id=customer_id,
        tenant_id=tenant_id,
        erased_tables=erased,
        anonymized=True,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Data Portability ──────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/customers/{customer_id}/export")
async def gdpr_export_customer(
    tenant_id: str,
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminContext = Depends(require_platform_roles({"viewer", "editor", "owner"})),
):
    """
    GDPR / POPIA Data Portability.

    Returns a structured JSON document with all personal data held for this customer.
    Requires TenantCompliancePolicy.data_portability_enabled == True.
    """
    await ensure_tenant_access(db, admin, uuid.UUID(tenant_id))
    bank = await _resolve_tenant_or_404(db, tenant_id)
    customer = await _resolve_customer_or_404(db, bank, customer_id)
    policy = await _compliance_policy(db, bank.id)

    if policy and not policy.data_portability_enabled:
        raise HTTPException(
            status_code=403,
            detail="data_portability_enabled is disabled for this tenant's compliance policy",
        )

    # Transactions (limited to 5000 rows, sorted newest first)
    txs_q = await db.execute(
        select(Transaction)
        .where(Transaction.tenant_id == bank.id, Transaction.customer_id == customer.id)
        .order_by(Transaction.created_at.desc())
        .limit(5000)
    )
    transactions = [
        {
            "transaction_id": str(tx.id),
            "external_tx_id": tx.external_tx_id,
            "amount": float(tx.amount) if tx.amount is not None else None,
            "currency": tx.currency,
            "merchant_id": tx.merchant_id,
            "merchant_category": tx.merchant_category,
            "channel": tx.channel,
            "location_country": tx.location_country,
            "timestamp": tx.tx_timestamp.isoformat() if tx.tx_timestamp else None,
        }
        for tx in txs_q.scalars().all()
    ]

    # Fraud scores for those transactions
    fraud_scores_q = await db.execute(
        select(FraudScore)
        .join(Transaction, FraudScore.transaction_id == Transaction.id)
        .where(Transaction.tenant_id == bank.id, Transaction.customer_id == customer.id)
        .order_by(FraudScore.created_at.desc())
        .limit(5000)
    )
    fraud_scores = [
        {
            "transaction_id": str(fs.transaction_id),
            "ensemble_score": float(fs.ensemble_score) if fs.ensemble_score is not None else None,
            "lgbm_score": float(fs.lgbm_score) if fs.lgbm_score is not None else None,
            "decision": fs.decision,
            "model_version": fs.model_version,
            "timestamp": fs.created_at.isoformat() if fs.created_at else None,
        }
        for fs in fraud_scores_q.scalars().all()
    ]

    # Chat sessions
    sessions_q = await db.execute(
        select(ChatSession)
        .where(ChatSession.tenant_id == bank.id, ChatSession.customer_id == customer.id)
        .order_by(ChatSession.started_at.desc())
        .limit(200)
    )
    sessions = []
    for session in sessions_q.scalars().all():
        msgs_q = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at)
        )
        sessions.append(
            {
                "session_id": str(session.id),
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                    }
                    for msg in msgs_q.scalars().all()
                ],
            }
        )

    # Audit trail
    db.add(
        AuditLog(
            tenant_id=bank.id,
            actor_id=str(admin.user_id),
            event_type="gdpr_export",
            entity_type="customer",
            event_data={"customer_id": customer_id, "transaction_count": len(transactions), "session_count": len(sessions)},
        )
    )
    await db.commit()

    _logger.info(
        "gdpr_export_completed",
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor=str(admin.user_id),
    )

    return {
        "schema_version": "1.0",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "subject": {
            "customer_external_id": customer_id,
            "tenant_id": tenant_id,
            "risk_score": float(customer.risk_score) if customer.risk_score is not None else None,
            "account_count": customer.account_count,
            "is_flagged": customer.is_flagged,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        },
        "transactions": transactions,
        "fraud_scores": fraud_scores,
        "chat_sessions": sessions,
    }


# ── API Key Rotation ──────────────────────────────────────────────────────────

class RotateKeyOut(BaseModel):
    tenant_id: str
    api_key: str          # returned once — store securely
    api_key_prefix: str
    rotated_at: str


@router.post("/tenants/{tenant_id}/rotate-api-key", response_model=RotateKeyOut)
async def rotate_api_key(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminContext = Depends(require_platform_roles({"owner"})),
):
    """
    Rotate the API key for a tenant.

    Generates a cryptographically random 40-character key, hashes it with SHA-256,
    and replaces the current hash in tenant_banks. The plaintext key is returned
    **once** in this response and is never stored — treat it like a password.

    Requires platform owner role.
    """
    await ensure_tenant_access(db, admin, uuid.UUID(tenant_id))
    bank = await _resolve_tenant_or_404(db, tenant_id)

    new_key = secrets.token_urlsafe(30)  # 40 chars, URL-safe
    new_hash = hashlib.sha256(new_key.encode()).hexdigest()
    new_prefix = new_key[:8]

    await db.execute(
        update(TenantBank)
        .where(TenantBank.id == bank.id)
        .values(
            api_key_hash=new_hash,
            api_key_prefix=new_prefix,
            updated_at=datetime.now(timezone.utc),
        )
    )

    db.add(
        AuditLog(
            tenant_id=bank.id,
            actor_id=str(admin.user_id),
            event_type="api_key_rotated",
            entity_type="tenant_bank",
            event_data={"new_prefix": new_prefix, "tenant_id": tenant_id},
        )
    )

    await db.commit()
    _logger.info("api_key_rotated", tenant_id=tenant_id, actor=str(admin.user_id))

    return RotateKeyOut(
        tenant_id=tenant_id,
        api_key=new_key,
        api_key_prefix=new_prefix,
        rotated_at=datetime.now(timezone.utc).isoformat(),
    )
