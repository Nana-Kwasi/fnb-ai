from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.model_registry import TenantMapper
from app.models.training_data import TrainingUpload


async def assert_training_upload_allowed(
    db: AsyncSession,
    *,
    upload: TrainingUpload,
    model_type: str,
) -> None:
    if not settings.strict_training_governance:
        return
    meta = upload.meta if isinstance(upload.meta, dict) else {}
    tid_raw = meta.get("tenant_id")
    if tid_raw is None or str(tid_raw).strip().lower() in ("", "none"):
        return
    try:
        tenant_uuid = uuid.UUID(str(tid_raw))
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Upload meta tenant_id is not a valid UUID.") from e
    row = (
        await db.execute(
            select(TenantMapper.id).where(
                TenantMapper.tenant_id == tenant_uuid,
                TenantMapper.model_type == model_type,
                TenantMapper.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "strict_training_governance: an active tenant mapper is required for this model_type "
                "before training tenant-scoped uploads. Create/activate a mapper or use a global upload "
                "(omit tenant_id on upload)."
            ),
        )


async def assert_global_pooled_uploads(
    _db: AsyncSession,
    *,
    uploads: list[TrainingUpload],
    model_type: str,
) -> None:
    if not uploads:
        raise HTTPException(status_code=400, detail="global_pooled: no uploads.")
    for u in uploads:
        if u.model_type != model_type:
            raise HTTPException(status_code=400, detail="global_pooled: model_type mismatch in upload set.")
        meta = u.meta if isinstance(u.meta, dict) else {}
        tid_raw = meta.get("tenant_id")
        if tid_raw is not None and str(tid_raw).strip():
            raise HTTPException(
                status_code=400,
                detail="global_pooled: all uploads must be global (no tenant_id in upload meta).",
            )
