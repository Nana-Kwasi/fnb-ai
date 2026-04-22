from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class CloudinaryUploadResult:
    url: str
    public_id: str
    resource_type: str
    delivery_type: str | None = None
    bytes: int | None = None
    format: str | None = None
    original_filename: str | None = None


def _enabled() -> bool:
    return bool(getattr(settings, "cloudinary_uploads_enabled", True)) and bool(_cloudinary_url())


def _cloudinary_url() -> str:
    # Cloudinary SDK reads CLOUDINARY_URL. We allow settings.cloudinary_url too.
    v = (getattr(settings, "cloudinary_url", "") or "").strip()
    if v:
        return v
    return (os.getenv("CLOUDINARY_URL") or "").strip()


def _configure() -> bool:
    """
    Configure Cloudinary SDK from CLOUDINARY_URL.
    Returns False when not configured.
    """
    url = _cloudinary_url()
    if not url:
        return False
    try:
        import cloudinary
        cloudinary.config(cloudinary_url=url, secure=True)
        return True
    except Exception:
        return False


def _safe_public_id(prefix: str, *, name_hint: str | None = None) -> str:
    base = (name_hint or "file").strip() or "file"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
    return f"{prefix.rstrip('/')}/{digest}"


def upload_bytes(
    *,
    content: bytes,
    filename: str,
    folder: str,
    resource_type: str = "raw",
    delivery_type: str | None = None,
    public_id: str | None = None,
    tags: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> CloudinaryUploadResult | None:
    """
    Upload bytes to Cloudinary.

    - resource_type: "image" for images, "raw" for PDFs/XLSX/other files.
    Returns None if Cloudinary is not configured/enabled.
    """
    if not _enabled():
        return None
    if not _configure():
        return None
    try:
        import cloudinary.uploader  # type: ignore
    except Exception:
        return None

    prefix = f"{(getattr(settings, 'cloudinary_folder_prefix', 'bankai') or 'bankai').strip().rstrip('/')}/{folder.strip().strip('/')}"
    pid = public_id or _safe_public_id(prefix, name_hint=filename)

    dtype = (delivery_type or getattr(settings, "cloudinary_delivery_type", "") or "upload").strip().lower()
    if dtype not in {"upload", "private"}:
        dtype = "upload"
    opts: dict[str, Any] = {
        "resource_type": resource_type,
        "public_id": pid,
        "overwrite": True,
        "unique_filename": False,
        "use_filename": True,
        "filename_override": filename,
        "folder": None,  # folder is encoded in public_id
        "type": dtype,
    }
    if tags:
        opts["tags"] = tags
    if context:
        opts["context"] = context

    try:
        resp = cloudinary.uploader.upload(content, **opts)
    except Exception:
        return None
    url = str(resp.get("secure_url") or resp.get("url") or "").strip()
    public_id_out = str(resp.get("public_id") or pid).strip()
    if not url or not public_id_out:
        return None
    return CloudinaryUploadResult(
        url=url,
        public_id=public_id_out,
        resource_type=str(resp.get("resource_type") or resource_type),
        delivery_type=str(resp.get("type") or dtype) if (resp.get("type") or dtype) else None,
        bytes=int(resp.get("bytes")) if resp.get("bytes") is not None else None,
        format=str(resp.get("format")) if resp.get("format") else None,
        original_filename=str(resp.get("original_filename")) if resp.get("original_filename") else None,
    )


def signed_download_url(
    *,
    public_id: str,
    resource_type: str,
    expires_in_seconds: int = 300,
    filename: str | None = None,
) -> str | None:
    """
    Generate a short-lived signed download URL for private Cloudinary assets.
    Returns None if Cloudinary isn't configured.
    """
    if not _enabled():
        return None
    if not _configure():
        return None
    try:
        import time
        import cloudinary.utils  # type: ignore
    except Exception:
        return None

    expires_at = int(time.time()) + max(30, int(expires_in_seconds))
    try:
        # Prefer private_download_url when available (works well for raw files).
        url = cloudinary.utils.private_download_url(
            public_id,
            resource_type=resource_type,
            type=(getattr(settings, "cloudinary_delivery_type", "private") or "private"),
            expires_at=expires_at,
            attachment=filename or None,
        )
        return str(url).strip() or None
    except Exception:
        # Fallback: sign a URL using cloudinary_url
        try:
            url, _opts = cloudinary.utils.cloudinary_url(
                public_id,
                resource_type=resource_type,
                type=(getattr(settings, "cloudinary_delivery_type", "private") or "private"),
                sign_url=True,
                expires_at=expires_at,
            )
            return str(url).strip() or None
        except Exception:
            return None


def destroy(*, public_id: str, resource_type: str = "raw") -> bool:
    if not _enabled():
        return False
    if not _configure():
        return False
    try:
        import cloudinary.uploader  # type: ignore
    except Exception:
        return False
    try:
        resp = cloudinary.uploader.destroy(public_id, resource_type=resource_type, invalidate=True)
        return bool(resp and resp.get("result") in {"ok", "not found"})
    except Exception:
        return False

