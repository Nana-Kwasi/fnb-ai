from __future__ import annotations

import math
import uuid
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fraud import FraudScore


def ks_statistic(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    aa = np.sort(np.asarray(a, dtype=np.float64))
    bb = np.sort(np.asarray(b, dtype=np.float64))
    vals = np.unique(np.concatenate([aa, bb]))
    cdf_a = np.searchsorted(aa, vals, side="right") / max(1, len(aa))
    cdf_b = np.searchsorted(bb, vals, side="right") / max(1, len(bb))
    return float(np.max(np.abs(cdf_a - cdf_b)))


def psi(a: list[float], b: list[float], bins: int = 10) -> float:
    if not a or not b:
        return 0.0
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    qs = np.quantile(aa, np.linspace(0, 1, bins + 1))
    eps = 1e-9
    total = 0.0
    for i in range(len(qs) - 1):
        lo, hi = qs[i], qs[i + 1]
        if i == len(qs) - 2:
            pa = np.mean((aa >= lo) & (aa <= hi))
            pb = np.mean((bb >= lo) & (bb <= hi))
        else:
            pa = np.mean((aa >= lo) & (aa < hi))
            pb = np.mean((bb >= lo) & (bb < hi))
        pa = max(float(pa), eps)
        pb = max(float(pb), eps)
        total += (pa - pb) * math.log(pa / pb)
    return float(total)


async def compute_tenant_drift(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    recent_limit: int = 600,
    baseline_limit: int = 3000,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(FraudScore.feature_vector)
            .where(FraudScore.tenant_id == tenant_id)
            .order_by(FraudScore.created_at.desc())
            .limit(recent_limit + baseline_limit)
        )
    ).scalars().all()
    fvs = [r for r in rows if isinstance(r, dict)]
    recent = fvs[:recent_limit]
    baseline = fvs[recent_limit : recent_limit + baseline_limit]
    if len(recent) < 100 or len(baseline) < 200:
        return {
            "tenant_id": str(tenant_id),
            "status": "insufficient_data",
            "features": [],
            "alerts": [],
        }
    features = []
    for feat in ("amount", "customer_risk_score", "txn_count_1h", "network_risk_score"):
        base_vals = [float(x.get(feat, 0.0) or 0.0) for x in baseline]
        rec_vals = [float(x.get(feat, 0.0) or 0.0) for x in recent]
        psi_v = round(psi(base_vals, rec_vals, bins=10), 4)
        ks_v = round(ks_statistic(base_vals, rec_vals), 4)
        sev = "green"
        if psi_v >= 0.35 or ks_v >= 0.35:
            sev = "red"
        elif psi_v >= 0.2 or ks_v >= 0.2:
            sev = "yellow"
        features.append({"feature": feat, "psi": psi_v, "ks": ks_v, "severity": sev})
    severity_rank = {"green": 0, "yellow": 1, "red": 2}
    worst = max(features, key=lambda x: severity_rank.get(x["severity"], 0))
    status = worst["severity"]
    alerts = [f for f in features if f["severity"] in {"yellow", "red"}]
    return {
        "tenant_id": str(tenant_id),
        "status": status,
        "features": features,
        "alerts": alerts,
    }
