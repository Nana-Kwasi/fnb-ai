from __future__ import annotations

import json
import urllib.request
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone

from app.config import settings


def _post_json(url: str, body: dict) -> bool:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(2, int(settings.alert_webhook_timeout_seconds))) as resp:
            return 200 <= int(getattr(resp, "status", 0)) < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def send_alert(event_type: str, *, severity: str = "info", payload: dict | None = None) -> bool:
    body = {
        "event_type": str(event_type),
        "severity": str(severity).lower(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": dict(payload or {}),
    }
    ok = False
    primary = str(settings.alert_webhook_url or "").strip()
    if primary:
        ok = _post_json(primary, body) or ok
    paging = str(settings.paging_webhook_url or "").strip()
    if paging and str(severity).lower() == "critical":
        ok = _post_json(paging, body) or ok
    return ok
