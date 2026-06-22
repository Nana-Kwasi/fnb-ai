"""
Background task: retry failed/pending webhook deliveries with exponential backoff.

Schedule: every 60 seconds.
Max attempts: 5. Delays: 1s, 2s, 4s, 8s, 16s (2^(attempt-1)).
After 5 failures: status → FAILED (dead letter).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.tenant_extended import TenantWebhookLog, WebhookStatus
from app.observability import get_logger as _obs_logger

_logger = _obs_logger(__name__)

MAX_ATTEMPTS = 5
_BACKOFF_DELAYS = [1, 2, 4, 8, 16]  # seconds — 2^(attempt-1)
_HTTP_TIMEOUT = 10.0
_BATCH_SIZE = 100


def _next_retry_delay(attempt_count: int) -> int:
    idx = min(attempt_count, len(_BACKOFF_DELAYS) - 1)
    return _BACKOFF_DELAYS[idx]


async def _deliver(log: TenantWebhookLog) -> tuple[bool, int | None, str | None]:
    """Attempt a single HTTP POST delivery. Returns (success, http_status, error_msg)."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                log.target_url,
                json={"event_type": log.event_type, "payload": log.payload},
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Event": log.event_type,
                    "X-Delivery-ID": str(log.id),
                },
            )
        success = resp.status_code < 400
        return success, resp.status_code, None if success else resp.text[:500]
    except Exception as exc:
        return False, None, str(exc)[:500]


async def run_webhook_retry() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    delivered = failed = skipped = 0

    async with AsyncSessionLocal() as db:
        pending = (
            await db.execute(
                select(TenantWebhookLog)
                .where(
                    TenantWebhookLog.status.in_([WebhookStatus.PENDING, WebhookStatus.RETRYING]),
                    TenantWebhookLog.next_retry_at <= now,
                )
                .order_by(TenantWebhookLog.created_at)
                .limit(_BATCH_SIZE)
            )
        ).scalars().all()

        for log in pending:
            if log.attempt_count >= MAX_ATTEMPTS:
                log.status = WebhookStatus.FAILED
                log.error_message = "Max retry attempts exceeded"
                failed += 1
                _logger.warning(
                    "webhook_dead_letter",
                    webhook_id=str(log.id),
                    tenant_id=str(log.tenant_id),
                    event_type=log.event_type,
                )
                continue

            success, http_status, error_msg = await _deliver(log)
            log.attempt_count += 1
            log.http_status_code = http_status
            log.updated_at = now

            if success:
                log.status = WebhookStatus.DELIVERED
                log.delivered_at = now
                log.error_message = None
                delivered += 1
                _logger.info(
                    "webhook_delivered",
                    webhook_id=str(log.id),
                    tenant_id=str(log.tenant_id),
                    event_type=log.event_type,
                    attempts=log.attempt_count,
                )
            else:
                log.status = WebhookStatus.RETRYING
                log.error_message = error_msg
                delay_s = _next_retry_delay(log.attempt_count)
                log.next_retry_at = now + timedelta(seconds=delay_s)
                if log.attempt_count >= MAX_ATTEMPTS:
                    log.status = WebhookStatus.FAILED
                    failed += 1
                else:
                    skipped += 1
                _logger.warning(
                    "webhook_retry_scheduled",
                    webhook_id=str(log.id),
                    tenant_id=str(log.tenant_id),
                    event_type=log.event_type,
                    attempt=log.attempt_count,
                    next_retry_in_s=delay_s,
                    http_status=http_status,
                    error=error_msg,
                )

        await db.commit()

    return {"delivered": delivered, "failed_dead_letter": failed, "rescheduled": skipped}


async def enqueue_webhook(
    db: AsyncSession,
    *,
    tenant_id: str,
    event_type: str,
    payload: dict,
    target_url: str,
) -> TenantWebhookLog:
    """Create a PENDING webhook log entry. Call this whenever you need to fire an outbound event."""
    log = TenantWebhookLog(
        tenant_id=tenant_id,
        event_type=event_type,
        payload=payload,
        target_url=target_url,
        status=WebhookStatus.PENDING,
        next_retry_at=datetime.now(timezone.utc),
    )
    db.add(log)
    return log
