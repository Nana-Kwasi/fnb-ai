import hashlib
from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import TenantBank


api_key_header = APIKeyHeader(name=settings.api_key_header, auto_error=False)


async def resolve_tenant(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> TenantBank:
    if not api_key:
        raise HTTPException(401, "Missing X-API-Key header")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(
        select(TenantBank).where(
            TenantBank.api_key_hash == key_hash,
            TenantBank.is_active == True,
        )
    )
    bank = result.scalar_one_or_none()
    if not bank:
        raise HTTPException(403, "Invalid or inactive API key")

    tid = str(bank.id)
    await db.execute(__import__("sqlalchemy").text(f"SET LOCAL app.tenant_id = '{tid}'"))
    return bank
