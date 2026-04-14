from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from urllib.request import urlopen

from fastapi import HTTPException
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

ALGORITHM = "HS256"
_JWKS_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_TTL_SECONDS = 300


@dataclass
class ProviderAuthResult:
    user_id: uuid.UUID
    role: str
    email: str | None = None


def _decode_local_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def _decode_saml_bridge_token(token: str) -> dict:
    claims = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if str(claims.get("typ") or "") != "saml_bridge":
        raise HTTPException(status_code=401, detail="Invalid SAML bridge token type.")
    iss = str(claims.get("iss") or "")
    aud = claims.get("aud")
    exp_iss = (settings.saml_expected_issuer or "").strip()
    exp_aud = (settings.saml_expected_audience or "").strip()
    if exp_iss and iss != exp_iss:
        raise HTTPException(status_code=401, detail="Invalid SAML issuer.")
    if exp_aud:
        if isinstance(aud, list):
            if exp_aud not in [str(x) for x in aud]:
                raise HTTPException(status_code=401, detail="Invalid SAML audience.")
        elif str(aud or "") != exp_aud:
            raise HTTPException(status_code=401, detail="Invalid SAML audience.")
    return claims


def _jwks_for(url: str) -> dict:
    now = time.time()
    cached = _JWKS_CACHE.get(url)
    if cached and now - cached[0] <= _JWKS_TTL_SECONDS:
        return cached[1]
    with urlopen(url, timeout=5) as resp:  # nosec B310
        body = resp.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=401, detail="Invalid OIDC JWKS response.")
    _JWKS_CACHE[url] = (now, parsed)
    return parsed


def _decode_oidc_token(token: str) -> dict:
    jwks_url = (settings.oidc_jwks_url or "").strip()
    issuer = (settings.oidc_issuer or "").strip()
    audience = (settings.oidc_audience or "").strip()
    if not jwks_url or not issuer or not audience:
        raise HTTPException(status_code=500, detail="OIDC is not fully configured.")
    try:
        headers = jwt.get_unverified_header(token)
        kid = str(headers.get("kid") or "")
        if not kid:
            raise HTTPException(status_code=401, detail="Missing kid in OIDC token header.")
        keys = (_jwks_for(jwks_url).get("keys") or [])
        key_data = next((k for k in keys if str(k.get("kid") or "") == kid), None)
        if not key_data:
            raise HTTPException(status_code=401, detail="OIDC signing key not found.")
        message, encoded_sig = token.rsplit(".", 1)
        decoded_sig = base64url_decode(encoded_sig.encode("utf-8"))
        pub = jwk.construct(key_data)
        if not pub.verify(message.encode("utf-8"), decoded_sig):
            raise HTTPException(status_code=401, detail="Invalid OIDC token signature.")
        return jwt.decode(
            token,
            key_data,
            algorithms=[str(key_data.get("alg") or "RS256")],
            audience=audience,
            issuer=issuer,
            options={"verify_aud": True, "verify_iss": True},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid OIDC token.") from exc


async def authenticate_token_via_provider(db: AsyncSession, token: str) -> ProviderAuthResult:
    del db
    provider = (settings.auth_provider or "local").strip().lower()
    if provider == "local":
        try:
            claims = _decode_local_access_token(token)
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token.") from exc
        if claims.get("typ") != "platform":
            raise HTTPException(status_code=401, detail="Invalid token type.")
        uid = uuid.UUID(str(claims.get("sub")))
        role = str(claims.get("role") or "").strip().lower()
        return ProviderAuthResult(user_id=uid, role=role, email=claims.get("email"))

    if provider == "oidc":
        claims = _decode_oidc_token(token)
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise HTTPException(status_code=401, detail="OIDC subject missing.")
        try:
            uid = uuid.UUID(subject)
        except ValueError:
            uid = uuid.uuid5(uuid.NAMESPACE_URL, subject)
        role = str(claims.get("role") or claims.get("bankai_role") or "viewer").strip().lower()
        return ProviderAuthResult(user_id=uid, role=role, email=claims.get("email"))

    if provider == "saml":
        try:
            claims = _decode_saml_bridge_token(token)
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid SAML bridge token.") from exc
        subject = str(claims.get("sub") or claims.get("email") or "").strip()
        if not subject:
            raise HTTPException(status_code=401, detail="SAML subject missing.")
        try:
            uid = uuid.UUID(subject)
        except ValueError:
            uid = uuid.uuid5(uuid.NAMESPACE_URL, f"saml:{subject}")
        role = str(claims.get("role") or claims.get("bankai_role") or "viewer").strip().lower()
        email = str(claims.get("email") or "").strip() or None
        return ProviderAuthResult(user_id=uid, role=role, email=email)

    raise HTTPException(status_code=500, detail=f"Unsupported auth provider '{provider}'.")
