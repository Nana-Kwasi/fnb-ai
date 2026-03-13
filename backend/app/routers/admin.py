import hashlib
import secrets
from typing import Dict, List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TenantBank
from app.services.care_engine import summarise_care_events

router = APIRouter()


def generate_api_key(env: str = "live") -> tuple[str, str, str]:
    random_part = secrets.token_urlsafe(24)
    raw_key = f"bankai_{env}_{random_part}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    return raw_key, key_hash, key_prefix


class OnboardIn(BaseModel):
    name: str
    country_code: str


class OnboardOut(BaseModel):
    bank_id: str
    api_key: str


class CareMetricsOut(BaseModel):
    window_hours: int
    total_replies: int
    rule_hits: int
    model_suggestions: int
    fuzzy_suggestions: int
    out_of_scope: int
    escalations: int
    rule_hit_rate: float
    suggestion_rate: float
    out_of_scope_rate: float
    escalation_rate: float
    intent_counts: Dict[str, int]
    low_volume_intents: List[str]
    alerts: List[str]


@router.post("/onboard", response_model=OnboardOut)
async def onboard_bank(
    payload: OnboardIn,
    db: AsyncSession = Depends(get_db),
):
    raw_key, key_hash, key_prefix = generate_api_key()
    bank = TenantBank(
        name=payload.name,
        country_code=payload.country_code,
        api_key_hash=key_hash,
        api_key_prefix=key_prefix,
    )
    db.add(bank)
    await db.flush()
    return OnboardOut(bank_id=str(bank.id), api_key=raw_key)


@router.get("/care/metrics", response_model=CareMetricsOut)
async def get_care_metrics(
    window_hours: int = Query(24, ge=1, le=168),
) -> CareMetricsOut:
    data = summarise_care_events(window_hours=window_hours)
    return CareMetricsOut(**data)
