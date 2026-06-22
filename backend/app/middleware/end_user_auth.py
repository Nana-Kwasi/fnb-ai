from fastapi import Depends, Header, HTTPException
from jose import jwt

from app.models import TenantBank
from app.middleware.auth import resolve_tenant
from app.config import settings


CARE_JWT_SECRET = settings.care_jwt_secret


async def resolve_end_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    bank: TenantBank = Depends(resolve_tenant),
) -> str:
    """
    Resolve the logged-in end user from a signed JWT.

    Returns the external customer id (we use the core-banking account_id as Customer.external_id).
    The token is bound to the tenant by comparing its bank_key_hash with bank.api_key_hash.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    try:
        payload = jwt.decode(
            token,
            CARE_JWT_SECRET,
            algorithms=["HS256"],
            audience="bankai-care",
            issuer="core-banking",
            options={"verify_aud": True, "verify_iss": True},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    if payload.get("bank_key_hash") != bank.api_key_hash:
        raise HTTPException(status_code=403, detail="Token tenant mismatch")

    customer_external_id = payload.get("customer_external_id")
    if not customer_external_id:
        raise HTTPException(status_code=401, detail="Token missing customer id")
    return str(customer_external_id)

