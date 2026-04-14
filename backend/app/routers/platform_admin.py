import uuid
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import AdminContext, get_jwt_admin_context, hash_password
from app.database import get_db
from app.models.audit import AuditLog
from app.models.platform_user import PlatformUser, PlatformUserTenant
from app.models.tenant import TenantBank

_SYSTEM_AUDIT_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000000")


async def _audit_platform(db: AsyncSession, event_type: str, data: dict, actor: str) -> None:
    db.add(
        AuditLog(
            tenant_id=_SYSTEM_AUDIT_TENANT,
            event_type=event_type,
            entity_type="platform_user",
            actor_type="api",
            actor_id=actor,
            event_data=data,
        )
    )
    await db.flush()

router = APIRouter()


class PlatformUserOut(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    must_change_password: bool
    tenant_ids: List[str]


class CreatePlatformUserIn(BaseModel):
    email: EmailStr
    temporary_password: str = Field(..., min_length=10, max_length=128)
    role: str = Field(..., pattern="^(viewer|editor|owner)$")
    tenant_ids: List[str] = Field(default_factory=list)


class UpdatePlatformUserIn(BaseModel):
    role: str | None = Field(None, pattern="^(viewer|editor|owner)$")
    is_active: bool | None = None
    tenant_ids: List[str] | None = None


class SetPasswordIn(BaseModel):
    new_temporary_password: str = Field(..., min_length=10, max_length=128)


def _require_owner(ctx: AdminContext = Depends(get_jwt_admin_context)) -> AdminContext:
    if ctx.role.lower() != "owner":
        raise HTTPException(status_code=403, detail="Owner role required.")
    return ctx


@router.get("/users", response_model=List[PlatformUserOut])
async def list_platform_users(
    db: AsyncSession = Depends(get_db),
    _owner: AdminContext = Depends(_require_owner),
):
    users = (await db.execute(select(PlatformUser).order_by(PlatformUser.created_at.asc()))).scalars().all()
    out: list[PlatformUserOut] = []
    for u in users:
        tids = (
            await db.execute(select(PlatformUserTenant.tenant_id).where(PlatformUserTenant.user_id == u.id))
        ).all()
        out.append(
            PlatformUserOut(
                id=str(u.id),
                email=u.email,
                role=u.role,
                is_active=u.is_active,
                must_change_password=u.must_change_password,
                tenant_ids=[str(x[0]) for x in tids],
            )
        )
    return out


@router.post("/users", response_model=PlatformUserOut)
async def create_platform_user(
    payload: CreatePlatformUserIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _owner: AdminContext = Depends(_require_owner),
):
    email = str(payload.email).strip().lower()
    exists = (await db.execute(select(PlatformUser).where(PlatformUser.email == email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered.")
    now = datetime.now(timezone.utc)
    user = PlatformUser(
        email=email,
        password_hash=hash_password(payload.temporary_password),
        role=payload.role.lower(),
        must_change_password=True,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    for tid in payload.tenant_ids:
        try:
            t_uuid = UUID(str(tid))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid tenant id: {tid}") from exc
        bank = (await db.execute(select(TenantBank).where(TenantBank.id == t_uuid))).scalar_one_or_none()
        if not bank:
            raise HTTPException(status_code=400, detail=f"Unknown tenant: {tid}")
        db.add(PlatformUserTenant(user_id=user.id, tenant_id=t_uuid, created_at=now))
    await db.flush()
    await _audit_platform(
        db,
        "PLATFORM_USER_CREATED",
        {"user_id": str(user.id), "email": user.email, "role": user.role, "tenant_ids": [str(t) for t in payload.tenant_ids]},
        actor=_owner.actor_id,
    )
    trows = (
        await db.execute(select(PlatformUserTenant.tenant_id).where(PlatformUserTenant.user_id == user.id))
    ).all()
    return PlatformUserOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        tenant_ids=[str(x[0]) for x in trows],
    )


@router.patch("/users/{user_id}", response_model=PlatformUserOut)
async def update_platform_user(
    user_id: UUID,
    payload: UpdatePlatformUserIn | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    _owner: AdminContext = Depends(_require_owner),
):
    user = await db.get(PlatformUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    payload = payload or UpdatePlatformUserIn()
    patch_in = payload.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)
    if payload.role is not None:
        user.role = payload.role.lower()
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.tenant_ids is not None:
        await db.execute(delete(PlatformUserTenant).where(PlatformUserTenant.user_id == user_id))
        for tid in payload.tenant_ids:
            try:
                u = UUID(str(tid))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid tenant id: {tid}") from exc
            bank = (await db.execute(select(TenantBank).where(TenantBank.id == u))).scalar_one_or_none()
            if not bank:
                raise HTTPException(status_code=400, detail=f"Unknown tenant: {tid}")
            db.add(PlatformUserTenant(user_id=user.id, tenant_id=u, created_at=now))
    user.updated_at = now
    await db.flush()
    if patch_in:
        await _audit_platform(
            db,
            "PLATFORM_USER_UPDATED",
            {
                "user_id": str(user.id),
                "patch": patch_in,
            },
            actor=_owner.actor_id,
        )
    trows = (
        await db.execute(select(PlatformUserTenant.tenant_id).where(PlatformUserTenant.user_id == user.id))
    ).all()
    return PlatformUserOut(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        tenant_ids=[str(x[0]) for x in trows],
    )


@router.post("/users/{user_id}/set-temporary-password")
async def set_temporary_password(
    user_id: UUID,
    payload: SetPasswordIn = Body(...),
    db: AsyncSession = Depends(get_db),
    _owner: AdminContext = Depends(_require_owner),
):
    user = await db.get(PlatformUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.password_hash = hash_password(payload.new_temporary_password)
    user.must_change_password = True
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await _audit_platform(
        db,
        "PLATFORM_USER_PASSWORD_RESET",
        {"user_id": str(user.id)},
        actor=_owner.actor_id,
    )
    return {"status": "ok"}
