"""
Per-endpoint rate limiting using an in-process token bucket (no Redis required).
Falls back gracefully if slowapi/redis are unavailable.

Endpoint-specific limits (requests per minute per tenant):
  /api/v1/fraud/score          → 600 rpm  (10 rps)
  /api/v1/care/chat            → 120 rpm  (2 rps)
  /api/v1/admin/*              → 300 rpm  (5 rps)
  Everything else              → settings.rate_limit_per_minute (global default)
"""
from __future__ import annotations

import time
import threading
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import Request, HTTPException

from app.config import settings

_ENDPOINT_LIMITS: Dict[str, int] = {
    "/api/v1/fraud/score": 600,
    "/api/v1/care/chat": 120,
}
_ADMIN_PREFIX_LIMIT = 300

_lock = threading.Lock()
# {(tenant_id, path_key): (tokens, last_refill_ts)}
_buckets: Dict[Tuple[str, str], list] = defaultdict(lambda: [None, 0.0])


def _get_limit(path: str) -> int:
    if path in _ENDPOINT_LIMITS:
        return _ENDPOINT_LIMITS[path]
    if path.startswith("/api/v1/admin"):
        return _ADMIN_PREFIX_LIMIT
    return settings.rate_limit_per_minute


def _check_token_bucket(tenant_id: str, path: str) -> None:
    limit = _get_limit(path)
    refill_rate = limit / 60.0  # tokens per second

    now = time.monotonic()
    key = (tenant_id, path if path in _ENDPOINT_LIMITS else ("admin" if path.startswith("/api/v1/admin") else "_global"))

    with _lock:
        bucket = _buckets[key]
        if bucket[0] is None:
            bucket[0] = float(limit)
            bucket[1] = now

        elapsed = now - bucket[1]
        bucket[0] = min(float(limit), bucket[0] + elapsed * refill_rate)
        bucket[1] = now

        if bucket[0] < 1.0:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "rate_limit_exceeded",
                    "limit_per_minute": limit,
                    "path": path,
                },
                headers={"Retry-After": "5"},
            )
        bucket[0] -= 1.0


async def per_endpoint_rate_limit(request: Request) -> None:
    """FastAPI dependency — call via Depends() on any router."""
    bank = getattr(request.state, "tenant_bank", None)
    tenant_id = str(bank.id) if bank else request.client.host if request.client else "anon"
    _check_token_bucket(tenant_id, request.url.path)
