from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog
from app.models.fraud_extra import FraudOutcome
from app.models.tenant import TenantBank
from app.models.model_registry import InferenceTrace, ModelRegistry


def _rate(vals: list[str], target: str) -> float:
    if not vals:
        return 0.0
    return float(sum(1 for v in vals if v == target)) / float(len(vals))


def _tenant_policy(bank: TenantBank | None) -> dict:
    tone = (bank.tone_config or {}) if bank else {}
    p = tone.get("challenger_policy") if isinstance(tone.get("challenger_policy"), dict) else {}
    return dict(p or {})


async def run_challenger_evaluator() -> dict:
    if not settings.auto_promotion_enabled:
        return {"enabled": False, "scanned_tenants": 0, "promoted_count": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(settings.auto_promotion_window_hours)))
    promoted_count = 0
    scanned_tenants = 0
    async with AsyncSessionLocal() as db:
        active_rows = (
            await db.execute(
                select(ModelRegistry).where(
                    ModelRegistry.model_type == "fraud",
                    ModelRegistry.status == "active",
                    ModelRegistry.tenant_id.is_not(None),
                )
            )
        ).scalars().all()

        for active in active_rows:
            tenant_id = active.tenant_id
            if tenant_id is None:
                continue
            scanned_tenants += 1
            challenger = (
                await db.execute(
                    select(ModelRegistry)
                    .where(
                        ModelRegistry.model_type == "fraud",
                        ModelRegistry.tenant_id == tenant_id,
                        ModelRegistry.status == "shadow",
                    )
                    .order_by(ModelRegistry.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not challenger:
                continue
            now = datetime.now(timezone.utc)
            bank = (await db.execute(select(TenantBank).where(TenantBank.id == tenant_id))).scalar_one_or_none()
            tp = _tenant_policy(bank)
            cooldown_hours = int(tp.get("cooldown_hours") or settings.auto_promotion_cooldown_hours)
            candidate_min_age_hours = int(tp.get("candidate_min_age_hours") or settings.auto_promotion_candidate_min_age_hours)
            min_compared = int(tp.get("min_compared") or settings.auto_promotion_min_compared)
            max_block_delta = float(tp.get("max_block_rate_delta") or settings.auto_promotion_max_block_rate_delta)
            max_otp_delta = float(tp.get("max_otp_rate_delta") or settings.auto_promotion_max_otp_rate_delta)
            max_disagree = float(tp.get("max_disagree_rate") or settings.auto_promotion_max_disagree_rate)
            if challenger.created_at and challenger.created_at > (now - timedelta(hours=max(1, candidate_min_age_hours))):
                continue
            last_promo = (
                await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == tenant_id,
                        AuditLog.event_type == "MODEL_AUTO_PROMOTED",
                    )
                    .order_by(AuditLog.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_promo and last_promo.created_at and last_promo.created_at > (now - timedelta(hours=max(1, cooldown_hours))):
                continue

            traces = (
                await db.execute(
                    select(InferenceTrace)
                    .where(
                        InferenceTrace.tenant_id == tenant_id,
                        InferenceTrace.model_type == "fraud",
                        InferenceTrace.created_at >= cutoff,
                    )
                    .order_by(InferenceTrace.created_at.desc())
                    .limit(5000)
                )
            ).scalars().all()

            champion_decisions: list[str] = []
            challenger_decisions: list[str] = []
            tx_ids: list[str] = []
            disagreements = 0
            for t in traces:
                tjson = t.trace_json if isinstance(t.trace_json, dict) else {}
                mv = tjson.get("mapper_validation") if isinstance(tjson.get("mapper_validation"), dict) else {}
                sh = mv.get("shadow") if isinstance(mv.get("shadow"), dict) else {}
                tx_id = str(tjson.get("transaction_id") or "")
                cand_version = str(sh.get("candidate_model_version") or "")
                cand_decision = str(sh.get("candidate_decision") or "").upper()
                champ_decision = str(t.decision or "").upper()
                if cand_version != challenger.version or not cand_decision or not champ_decision or not tx_id:
                    continue
                champion_decisions.append(champ_decision)
                challenger_decisions.append(cand_decision)
                tx_ids.append(tx_id)
                if champ_decision != cand_decision:
                    disagreements += 1

            compared = len(champion_decisions)
            if compared < min_compared:
                continue

            champ_block = _rate(champion_decisions, "BLOCK")
            chall_block = _rate(challenger_decisions, "BLOCK")
            champ_otp = _rate(champion_decisions, "REQUEST_OTP")
            chall_otp = _rate(challenger_decisions, "REQUEST_OTP")
            disagree_rate = float(disagreements) / float(compared)
            tx_uuid_ids: list[uuid.UUID] = []
            for tx in tx_ids:
                try:
                    tx_uuid_ids.append(uuid.UUID(tx))
                except ValueError:
                    continue
            outcome_rows = []
            if tx_uuid_ids:
                outcome_rows = (
                    await db.execute(
                        select(FraudOutcome).where(
                            FraudOutcome.tenant_id == tenant_id,
                            FraudOutcome.transaction_id.in_(tx_uuid_ids),
                        )
                    )
                ).scalars().all()
            outcome_map = {str(o.transaction_id): str(o.classification or "").upper() for o in outcome_rows}
            labeled_n = 0
            champ_tp = 0
            champ_pred_pos = 0
            chall_tp = 0
            chall_pred_pos = 0
            for i in range(len(tx_ids)):
                cls = outcome_map.get(tx_ids[i])
                if not cls:
                    continue
                labeled_n += 1
                is_fraud = cls == "CONFIRMED_FRAUD"
                cpos = champion_decisions[i] in {"BLOCK", "REQUEST_OTP"}
                spos = challenger_decisions[i] in {"BLOCK", "REQUEST_OTP"}
                if cpos:
                    champ_pred_pos += 1
                    if is_fraud:
                        champ_tp += 1
                if spos:
                    chall_pred_pos += 1
                    if is_fraud:
                        chall_tp += 1
            champ_precision = (float(champ_tp) / float(champ_pred_pos)) if champ_pred_pos > 0 else None
            chall_precision = (float(chall_tp) / float(chall_pred_pos)) if chall_pred_pos > 0 else None

            promote = (
                (chall_block - champ_block) <= max_block_delta
                and (chall_otp - champ_otp) <= max_otp_delta
                and disagree_rate <= max_disagree
            )
            if labeled_n >= int(settings.auto_promotion_min_labeled):
                if champ_precision is None or chall_precision is None:
                    promote = False
                else:
                    promote = promote and (
                        (chall_precision - champ_precision) >= float(settings.auto_promotion_min_precision_delta)
                    )
            if not promote:
                continue

            active.status = "rollback"
            challenger.status = "active"
            challenger.activated_at = datetime.now(timezone.utc)
            promoted_count += 1
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    event_type="MODEL_AUTO_PROMOTED",
                    entity_type="model_registry",
                    entity_id=challenger.id,
                    actor_type="system",
                    actor_id="challenger_evaluator",
                    event_data={
                        "tenant_id": str(tenant_id),
                        "from_model_id": str(active.id),
                        "from_model_version": active.version,
                        "to_model_id": str(challenger.id),
                        "to_model_version": challenger.version,
                        "window_hours": int(settings.auto_promotion_window_hours),
                        "compared_traces": compared,
                        "champion_block_rate": round(champ_block, 6),
                        "challenger_block_rate": round(chall_block, 6),
                        "champion_otp_rate": round(champ_otp, 6),
                        "challenger_otp_rate": round(chall_otp, 6),
                        "disagree_rate": round(disagree_rate, 6),
                        "labeled_compared": int(labeled_n),
                        "champion_precision": round(float(champ_precision), 6) if champ_precision is not None else None,
                        "challenger_precision": round(float(chall_precision), 6) if chall_precision is not None else None,
                        "cooldown_hours": cooldown_hours,
                        "candidate_min_age_hours": candidate_min_age_hours,
                    },
                )
            )

        await db.commit()

    return {
        "enabled": True,
        "scanned_tenants": scanned_tenants,
        "promoted_count": promoted_count,
        "window_hours": int(settings.auto_promotion_window_hours),
        "min_compared": int(settings.auto_promotion_min_compared),
    }
