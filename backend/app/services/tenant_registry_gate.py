"""Helpers for gating tenant flows on ModelRegistry rows (per-tenant fraud/care)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_registry import ModelRegistry


async def tenant_has_registered_model(
    db: AsyncSession, *, tenant_id: uuid.UUID, model_type: str
) -> bool:
    """True if this tenant has at least one registry row for the given model_type."""
    if model_type not in {"fraud", "care"}:
        return False
    n = (
        await db.execute(
            select(func.count())
            .select_from(ModelRegistry)
            .where(
                ModelRegistry.tenant_id == tenant_id,
                ModelRegistry.model_type == model_type,
            )
        )
    ).scalar_one()
    return int(n or 0) > 0
