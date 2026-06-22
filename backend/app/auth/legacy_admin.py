import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ADMIN_RBAC_JSON = BACKEND_ROOT / "app" / "ml" / "data" / "admin_rbac.json"


def admin_token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rbac_defaults() -> dict[str, Any]:
    data: dict[str, Any] = {"tokens": []}
    bootstrap = (settings.admin_write_token or "").strip()
    if bootstrap:
        data["tokens"].append(
            {
                "token_id": "bootstrap",
                "name": "bootstrap",
                "role": "owner",
                "active": True,
                "token_hash": admin_token_hash(bootstrap),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "rotated_at": None,
            }
        )
    return data


def load_admin_rbac() -> dict[str, Any]:
    default_data = rbac_defaults()
    if not ADMIN_RBAC_JSON.exists():
        return default_data
    tokens: list[dict] = []
    try:
        raw = json.loads(ADMIN_RBAC_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("tokens"), list):
            tokens = [dict(t) for t in raw["tokens"] if isinstance(t, dict)]
    except Exception:
        tokens = []
    boot = (settings.admin_write_token or "").strip()
    if boot:
        h = admin_token_hash(boot)
        if not any(t.get("token_hash") == h for t in tokens):
            boot_rec = next((t for t in default_data.get("tokens", []) if t.get("token_id") == "bootstrap"), None)
            if boot_rec:
                tokens.append(dict(boot_rec))
    if not tokens:
        return default_data
    return {"tokens": tokens}


def save_admin_rbac(data: dict[str, Any]) -> None:
    ADMIN_RBAC_JSON.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_RBAC_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_legacy_x_admin_token(raw: str | None) -> tuple[str, str] | None:
    """
    Returns (role, actor_id) if valid legacy token, else None.
    Open mode: no file and no env bootstrap -> treated as owner (dev).
    """
    if not raw or not raw.strip():
        return None
    if not ADMIN_RBAC_JSON.exists() and not (settings.admin_write_token or "").strip():
        return ("owner", "open-admin")
    data = load_admin_rbac()
    h = admin_token_hash(raw.strip())
    rec = next((t for t in data.get("tokens", []) if t.get("token_hash") == h and bool(t.get("active"))), None)
    if not rec:
        return None
    role = str(rec.get("role") or "viewer")
    actor = str(rec.get("token_id") or "unknown")
    return (role, actor)
