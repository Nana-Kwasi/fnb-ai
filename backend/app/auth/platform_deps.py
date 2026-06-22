from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt
from fastapi import Depends, Header, HTTPException
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.legacy_admin import (
    ADMIN_RBAC_JSON,
    load_admin_rbac,
    resolve_legacy_x_admin_token,
)
from app.auth.provider import authenticate_token_via_provider
from app.config import settings
from app.database import get_db
from app.models.platform_user import PlatformUser, PlatformUserTenant

ALGORITHM = "HS256"


@dataclass
class AdminContext:
    user_id: uuid.UUID | None
    email: str | None
    role: str
    actor_id: str
    legacy: bool

    def to_audit_actor(self) -> str:
        return self.actor_id


def hash_password(password: str) -> str:
    # bcrypt limit 72 bytes; passlib is incompatible with bcrypt>=4.1 — use library directly
    raw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: uuid.UUID, email: str, role: str) -> str:
    minutes = max(5, int(settings.platform_jwt_expire_minutes))
    exp = int((datetime.now(timezone.utc) + timedelta(minutes=minutes)).timestamp())
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": exp,
        "typ": "platform",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    from jose import jwt

    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


async def _load_user(db: AsyncSession, user_id: uuid.UUID) -> PlatformUser | None:
    return (
        await db.execute(select(PlatformUser).where(PlatformUser.id == user_id, PlatformUser.is_active.is_(True)))
    ).scalar_one_or_none()


async def _load_user_by_email(db: AsyncSession, email: str | None) -> PlatformUser | None:
    e = str(email or "").strip().lower()
    if not e:
        return None
    return (
        await db.execute(select(PlatformUser).where(PlatformUser.email == e, PlatformUser.is_active.is_(True)))
    ).scalar_one_or_none()


async def resolve_admin_context(
    db: AsyncSession,
    authorization: str | None,
    x_admin_token: str | None,
) -> AdminContext:
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
        if raw:
            try:
                auth = await authenticate_token_via_provider(db, raw)
                uid = auth.user_id
                user = await _load_user(db, uid)
                if not user:
                    user = await _load_user_by_email(db, auth.email)
                if not user:
                    raise HTTPException(status_code=401, detail="User inactive or missing.")
                role = str(auth.role or user.role).lower()
                if role != user.role.lower():
                    role = user.role.lower()
                return AdminContext(
                    user_id=user.id,
                    email=auth.email or user.email,
                    role=role,
                    actor_id=str(user.id),
                    legacy=False,
                )
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc

    if settings.admin_legacy_token_auth:
        leg = resolve_legacy_x_admin_token(x_admin_token)
        if leg:
            role, actor = leg
            return AdminContext(user_id=None, email=None, role=role, actor_id=actor, legacy=True)

    if settings.debug and (not ADMIN_RBAC_JSON.exists()) and not (settings.admin_write_token or "").strip():
        return AdminContext(None, None, "owner", "open-admin", True)

    raise HTTPException(status_code=401, detail="Authentication required.")


async def get_jwt_admin_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> AdminContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required.")
    ctx = await resolve_admin_context(db, authorization, None)
    if ctx.legacy or not ctx.user_id:
        raise HTTPException(status_code=401, detail="JWT session required.")
    return ctx


def require_platform_roles(required: set[str]) -> Callable:
    async def _dep(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
        db: AsyncSession = Depends(get_db),
    ) -> AdminContext:
        ctx = await resolve_admin_context(db, authorization, x_admin_token)
        if ctx.role not in required:
            raise HTTPException(status_code=403, detail="Insufficient platform role.")
        return ctx

    return _dep


async def user_assigned_tenant_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (await db.execute(select(PlatformUserTenant.tenant_id).where(PlatformUserTenant.user_id == user_id))).all()
    return {r[0] for r in rows}


async def ensure_tenant_access(db: AsyncSession, ctx: AdminContext, tenant_id: uuid.UUID) -> None:
    if ctx.legacy or ctx.role == "owner":
        return
    if not ctx.user_id:
        raise HTTPException(status_code=403, detail="Tenant access denied.")
    allowed = await user_assigned_tenant_ids(db, ctx.user_id)
    if tenant_id not in allowed:
        raise HTTPException(status_code=403, detail="No access to this bank.")


async def visible_tenant_ids_for_list(db: AsyncSession, ctx: AdminContext) -> list[uuid.UUID] | None:
    """
    None means all tenants; else filter to these IDs.
    """
    if ctx.legacy or ctx.role == "owner":
        return None
    if not ctx.user_id:
        return []
    return list(await user_assigned_tenant_ids(db, ctx.user_id))
