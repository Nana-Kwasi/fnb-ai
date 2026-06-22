from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fraud import FraudScore
from app.models.fraud_extra import FraudAlert, FraudOutcome
from app.models.model_registry import InferenceTrace


@dataclass
class FraudKpiResult:
    total_scored: int
    block_rate: float
    otp_rate: float
    alert_rate: float
    precision: float | None
    recall: float | None
    fpr: float | None
    auc: float | None
    labeled_count: int
    decision_mix: dict[str, int]
    avg_latency_ms: float | None = None
    p90_latency_ms: float | None = None
    shadow_disagree_rate: float | None = None
    avg_confidence: float | None = None


def _binary_auc(scores: list[float], labels: list[int]) -> float | None:
    if not scores or len(scores) != len(labels):
        return None
    pos = sum(1 for y in labels if y == 1)
    neg = sum(1 for y in labels if y == 0)
    if pos == 0 or neg == 0:
        return None
    paired = sorted(zip(scores, labels), key=lambda x: x[0])
    rank_sum_pos = 0.0
    i = 0
    n = len(paired)
    while i < n:
        j = i + 1
        while j < n and paired[j][0] == paired[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            if paired[k][1] == 1:
                rank_sum_pos += avg_rank
        i = j
    auc = (rank_sum_pos - (pos * (pos + 1) / 2.0)) / float(pos * neg)
    return max(0.0, min(1.0, float(auc)))


async def compute_fraud_kpis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 30,
) -> FraudKpiResult:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    score_rows = (
        await db.execute(
            select(FraudScore.decision).where(
                FraudScore.tenant_id == tenant_id,
                FraudScore.created_at >= cutoff,
            )
        )
    ).all()
    decision_mix: dict[str, int] = {}
    for (d,) in score_rows:
        key = str(d or "UNKNOWN")
        decision_mix[key] = int(decision_mix.get(key, 0)) + 1
    total_scored = int(sum(decision_mix.values()))
    block = int(decision_mix.get("BLOCK", 0))
    otp = int(decision_mix.get("REQUEST_OTP", 0))
    alert_rows = (
        await db.execute(
            select(FraudAlert.id).where(
                FraudAlert.tenant_id == tenant_id,
                FraudAlert.created_at >= cutoff,
            )
        )
    ).all()
    total_alerts = int(len(alert_rows))

    labeled_rows = (
        await db.execute(
            select(FraudScore.decision, FraudOutcome.classification, FraudScore.ensemble_score)
            .join(FraudOutcome, FraudOutcome.transaction_id == FraudScore.transaction_id)
            .where(
                FraudScore.tenant_id == tenant_id,
                FraudScore.created_at >= cutoff,
            )
        )
    ).all()
    labeled_count = len(labeled_rows)
    tp = fp = fn = tn = 0
    auc_scores: list[float] = []
    auc_labels: list[int] = []
    for dec, cls, ens in labeled_rows:
        decision = str(dec or "").upper()
        c = str(cls or "").upper()
        actual_fraud = c == "CONFIRMED_FRAUD"
        pred_positive = decision in {"BLOCK", "REQUEST_OTP"}
        try:
            auc_scores.append(float(ens))
            auc_labels.append(1 if actual_fraud else 0)
        except (TypeError, ValueError):
            pass
        if pred_positive and actual_fraud:
            tp += 1
        elif pred_positive and not actual_fraud:
            fp += 1
        elif (not pred_positive) and actual_fraud:
            fn += 1
        else:
            tn += 1
    precision = (float(tp) / float(tp + fp)) if (tp + fp) > 0 else None
    recall = (float(tp) / float(tp + fn)) if (tp + fn) > 0 else None
    fpr = (float(fp) / float(fp + tn)) if (fp + tn) > 0 else None
    auc = _binary_auc(auc_scores, auc_labels)
    lat_rows = (
        await db.execute(
            select(FraudScore.processing_ms).where(
                FraudScore.tenant_id == tenant_id,
                FraudScore.created_at >= cutoff,
                FraudScore.processing_ms.is_not(None),
            )
        )
    ).all()
    lats = sorted(int(x[0]) for x in lat_rows if x[0] is not None)
    avg_lat = (float(sum(lats)) / float(len(lats))) if lats else None
    p90_lat = float(lats[int(0.9 * (len(lats) - 1))]) if len(lats) > 1 else (float(lats[0]) if lats else None)

    shadow_rows = (
        await db.execute(
            select(InferenceTrace.decision, InferenceTrace.trace_json).where(
                InferenceTrace.tenant_id == tenant_id,
                InferenceTrace.model_type == "fraud",
                InferenceTrace.created_at >= cutoff,
            ).limit(8000)
        )
    ).all()
    sh_total = sh_dis = 0
    for dec, tj in shadow_rows:
        if not isinstance(tj, dict):
            continue
        mv = tj.get("mapper_validation") if isinstance(tj.get("mapper_validation"), dict) else {}
        sh = mv.get("shadow") if isinstance(mv.get("shadow"), dict) else {}
        cand = str(sh.get("candidate_decision") or "").upper()
        champ = str(dec or "").upper()
        if not cand or not champ:
            continue
        sh_total += 1
        if cand != champ:
            sh_dis += 1
    shadow_dis = (float(sh_dis) / float(sh_total)) if sh_total > 0 else None

    denom = float(total_scored) if total_scored > 0 else 1.0
    return FraudKpiResult(
        total_scored=total_scored,
        block_rate=(round(block / denom, 6) if total_scored else 0.0),
        otp_rate=(round(otp / denom, 6) if total_scored else 0.0),
        alert_rate=(round(total_alerts / denom, 6) if total_scored else 0.0),
        precision=(round(precision, 6) if precision is not None else None),
        recall=(round(recall, 6) if recall is not None else None),
        fpr=(round(fpr, 6) if fpr is not None else None),
        auc=(round(auc, 6) if auc is not None else None),
        labeled_count=labeled_count,
        decision_mix=decision_mix,
        avg_latency_ms=(round(avg_lat, 3) if avg_lat is not None else None),
        p90_latency_ms=(round(p90_lat, 3) if p90_lat is not None else None),
        shadow_disagree_rate=(round(shadow_dis, 6) if shadow_dis is not None else None),
        avg_confidence=None,
    )


async def compute_care_kpis(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    days: int = 30,
) -> FraudKpiResult:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    rows = (
        await db.execute(
            select(InferenceTrace.decision, InferenceTrace.processing_ms, InferenceTrace.trace_json).where(
                InferenceTrace.tenant_id == tenant_id,
                InferenceTrace.model_type == "care",
                InferenceTrace.created_at >= cutoff,
            ).limit(12000)
        )
    ).all()
    decision_mix: dict[str, int] = {}
    lats: list[int] = []
    conf_vals: list[float] = []
    labeled_rows: list[tuple[str, str, float | None]] = []
    sh_total = sh_dis = 0
    for dec, proc_ms, tj in rows:
        key = str(dec or "UNKNOWN")
        decision_mix[key] = int(decision_mix.get(key, 0)) + 1
        if proc_ms is not None:
            lats.append(int(proc_ms))
        tjson = tj if isinstance(tj, dict) else {}
        cp = tjson.get("confidence_proxy") if isinstance(tjson.get("confidence_proxy"), dict) else {}
        cal = cp.get("calibrated")
        row_conf = 0.55
        try:
            if cal is not None:
                row_conf = float(cal)
                conf_vals.append(row_conf)
        except (TypeError, ValueError):
            pass
        hf = tjson.get("human_feedback") if isinstance(tjson.get("human_feedback"), dict) else {}
        true_intent = str(hf.get("true_intent") or "").strip()
        shadow = tjson.get("shadow") if isinstance(tjson.get("shadow"), dict) else {}
        cand = str(shadow.get("candidate_intent") or "").strip()
        champ = str(dec or "").strip()
        if cand and champ:
            sh_total += 1
            if cand.upper() != champ.upper():
                sh_dis += 1
        if true_intent:
            labeled_rows.append((champ, true_intent, row_conf))

    total_scored = int(sum(decision_mix.values()))
    low_conf = int(decision_mix.get("UNKNOWN", 0)) + int(decision_mix.get("GENERAL_SUPPORT", 0))
    denom = float(total_scored) if total_scored > 0 else 1.0
    lats_sorted = sorted(lats)
    avg_lat = (float(sum(lats_sorted)) / float(len(lats_sorted))) if lats_sorted else None
    p90_lat = (
        float(lats_sorted[int(0.9 * (len(lats_sorted) - 1))])
        if len(lats_sorted) > 1
        else (float(lats_sorted[0]) if lats_sorted else None)
    )
    avg_conf = (sum(conf_vals) / len(conf_vals)) if conf_vals else None
    shadow_dis = (float(sh_dis) / float(sh_total)) if sh_total > 0 else None

    auc_scores: list[float] = []
    auc_labels: list[int] = []
    correct = 0
    for pred, true_i, sc in labeled_rows:
        match = pred.strip().upper() == true_i.strip().upper()
        if match:
            correct += 1
        try:
            auc_scores.append(float(sc or 0.5))
            auc_labels.append(1 if match else 0)
        except (TypeError, ValueError):
            pass
    labeled_n = len(labeled_rows)
    acc = (float(correct) / float(labeled_n)) if labeled_n > 0 else None
    precision = acc
    recall = acc
    fpr = None
    auc = _binary_auc(auc_scores, auc_labels) if len(auc_scores) > 5 else None

    return FraudKpiResult(
        total_scored=total_scored,
        block_rate=round(low_conf / denom, 6) if total_scored else 0.0,
        otp_rate=0.0,
        alert_rate=0.0,
        precision=(round(precision, 6) if precision is not None else None),
        recall=(round(recall, 6) if recall is not None else None),
        fpr=(round(fpr, 6) if fpr is not None else None),
        auc=(round(auc, 6) if auc is not None else None),
        labeled_count=labeled_n,
        decision_mix=decision_mix,
        avg_latency_ms=(round(avg_lat, 3) if avg_lat is not None else None),
        p90_latency_ms=(round(p90_lat, 3) if p90_lat is not None else None),
        shadow_disagree_rate=(round(shadow_dis, 6) if shadow_dis is not None else None),
        avg_confidence=(round(avg_conf, 6) if avg_conf is not None else None),
    )
