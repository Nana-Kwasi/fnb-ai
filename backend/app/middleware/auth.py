import hashlib
import uuid
from fastapi import Security, HTTPException, Depends, Header
from fastapi.security import APIKeyHeader
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import TenantBank
from app.models.platform_user import PlatformUser, PlatformUserTenant


api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)


async def resolve_tenant(
    api_key: str | None = Security(api_key_header),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> TenantBank:
    bank = None
    if api_key:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        result = await db.execute(
            select(TenantBank).where(
                TenantBank.api_key_hash == key_hash,
                TenantBank.is_active == True,
            )
        )
        bank = result.scalar_one_or_none()
    elif authorization and authorization.lower().startswith("bearer ") and x_tenant_id:
        try:
            claims = jwt.decode(authorization.split(" ", 1)[1].strip(), settings.secret_key, algorithms=["HS256"])
            if claims.get("typ") != "platform":
                raise HTTPException(401, "Invalid token type")
            uid = uuid.UUID(str(claims.get("sub")))
            tenant_id = uuid.UUID(str(x_tenant_id))
        except (JWTError, ValueError, TypeError) as exc:
            raise HTTPException(401, "Invalid auth context") from exc
        user = (
            await db.execute(select(PlatformUser).where(PlatformUser.id == uid, PlatformUser.is_active.is_(True)))
        ).scalar_one_or_none()
        if not user:
            raise HTTPException(401, "User inactive or missing")
        bank = (
            await db.execute(select(TenantBank).where(TenantBank.id == tenant_id, TenantBank.is_active == True))
        ).scalar_one_or_none()
        if not bank:
            raise HTTPException(403, "Invalid or inactive tenant")
        if str(user.role).lower() != "owner":
            allowed = (
                await db.execute(
                    select(PlatformUserTenant).where(
                        PlatformUserTenant.user_id == uid,
                        PlatformUserTenant.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if not allowed:
                raise HTTPException(403, "No access to this tenant")
    else:
        raise HTTPException(401, "Missing X-API-Key header")

    if not bank:
        raise HTTPException(403, "Invalid or inactive API key")

    tid = str(bank.id)
    await db.execute(__import__("sqlalchemy").text(f"SET LOCAL app.tenant_id = '{tid}'"))
    return bank
