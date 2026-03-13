import time
from fastapi import Request, HTTPException, Depends
from app.middleware.auth import resolve_tenant
from app.models import TenantBank

# Stub: requires redis client in app state or config
async def rate_limit_middleware(
    request: Request,
    bank: TenantBank = Depends(resolve_tenant),
) -> None:
    # TODO: wire Redis and sliding window per bank.id
    # key = f"rate_limit:{bank.id}:{int(time.time() // 60)}"
    # if await redis.incr(key) > (bank.rate_limit or 1000): raise HTTPException(429)
    pass
