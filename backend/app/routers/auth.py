from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import (
    AdminContext,
    create_access_token,
    get_jwt_admin_context,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.platform_user import PlatformUser, PlatformUserTenant
from app.models.tenant import TenantBank

router = APIRouter()


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


class TenantBrief(BaseModel):
    id: str
    name: str
    country_code: str
    logo_url: str | None = None


class MeOut(BaseModel):
    email: str
    role: str
    must_change_password: bool
    is_owner: bool
    needs_bank_selection: bool
    default_tenant_id: str | None
    banks: List[TenantBrief]


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=10, max_length=128)


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)):
    email = str(payload.email).strip().lower()
    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.email == email, PlatformUser.is_active.is_(True)))
    ).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    user.last_login_at = datetime.now(timezone.utc)
    user.updated_at = user.last_login_at
    await db.flush()
    token = create_access_token(user_id=user.id, email=user.email, role=user.role)
    return LoginOut(access_token=token, must_change_password=bool(user.must_change_password))


@router.get("/me", response_model=MeOut)
async def me(db: AsyncSession = Depends(get_db), ctx: AdminContext = Depends(get_jwt_admin_context)):
    user = await db.get(PlatformUser, ctx.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found.")
    is_owner = user.role.lower() == "owner"
    all_rows = (
        await db.execute(
            select(TenantBank.id, TenantBank.name, TenantBank.country_code, TenantBank.logo_path).order_by(TenantBank.name.asc())
        )
    ).all()
    all_banks = [
        TenantBrief(
            id=str(r.id),
            name=r.name,
            country_code=r.country_code,
            logo_url=(f"/api/v1/admin/tenants/{r.id}/logo" if r.logo_path else None),
        )
        for r in all_rows
    ]
    if is_owner:
        return MeOut(
            email=user.email,
            role=user.role,
            must_change_password=bool(user.must_change_password),
            is_owner=True,
            needs_bank_selection=True,
            default_tenant_id=None,
            banks=all_banks,
        )
    links = (
        await db.execute(
            select(PlatformUserTenant.tenant_id).where(PlatformUserTenant.user_id == user.id),
        )
    ).all()
    tids = [row[0] for row in links]
    banks = [b for b in all_banks if UUID(b.id) in set(tids)]
    if len(tids) == 1:
        return MeOut(
            email=user.email,
            role=user.role,
            must_change_password=bool(user.must_change_password),
            is_owner=False,
            needs_bank_selection=False,
            default_tenant_id=str(tids[0]),
            banks=banks,
        )
    if len(tids) > 1:
        return MeOut(
            email=user.email,
            role=user.role,
            must_change_password=bool(user.must_change_password),
            is_owner=False,
            needs_bank_selection=True,
            default_tenant_id=None,
            banks=banks,
        )
    return MeOut(
        email=user.email,
        role=user.role,
        must_change_password=bool(user.must_change_password),
        is_owner=False,
        needs_bank_selection=False,
        default_tenant_id=None,
        banks=[],
    )


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordIn,
    db: AsyncSession = Depends(get_db),
    ctx: AdminContext = Depends(get_jwt_admin_context),
):
    user = await db.get(PlatformUser, ctx.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok"}
