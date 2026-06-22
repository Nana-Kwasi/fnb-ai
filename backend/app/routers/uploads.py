from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import AdminContext, ensure_tenant_access, require_platform_roles
from app.config import settings
from app.database import get_db
from app.services.cloudinary_store import upload_bytes, signed_download_url
from jose import jwt

router = APIRouter()


class UploadOut(BaseModel):
    download_url: str
    expires_in_seconds: int
    public_id: str
    resource_type: str
    filename: str
    size_bytes: int


@router.post("/uploads", response_model=UploadOut)
async def upload_to_cloudinary(
    tenant_id: uuid.UUID = Query(..., description="Tenant to associate this upload with"),
    kind: str = Query("user_upload", description="Folder kind: user_upload|report_attachment|other"),
    file: UploadFile = File(...),
    admin: AdminContext = Depends(require_platform_roles({"editor", "owner"})),
    db: AsyncSession = Depends(get_db),
):
    await ensure_tenant_access(db, admin, tenant_id)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Use image resource_type for common image extensions so Cloudinary transforms/CDN work.
    name = str(file.filename)
    lower = name.lower()
    resource_type = "image" if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) else "raw"
    folder = f"uploads/{tenant_id}/{kind}"
    res = upload_bytes(
        content=content,
        filename=name,
        folder=folder,
        resource_type=resource_type,
        delivery_type="private",
        tags=["upload", kind],
        context={"tenant_id": str(tenant_id), "kind": kind, "uploaded_by": str(admin.actor_id)},
    )
    if res is None:
        raise HTTPException(status_code=503, detail="Cloudinary not configured or upload failed")

    ttl = 10 * 60  # 10 minutes for admin download link
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "bankai",
            "aud": "bankai-admin-upload",
            "tenant_id": str(tenant_id),
            "public_id": res.public_id,
            "resource_type": res.resource_type,
            "filename": name,
            "iat": now,
            "exp": now + ttl,
        },
        settings.secret_key,
        algorithm="HS256",
    )
    download_url = "/api/v1/admin/uploads/download?token=" + token

    return UploadOut(
        download_url=download_url,
        expires_in_seconds=ttl,
        public_id=res.public_id,
        resource_type=res.resource_type,
        filename=name,
        size_bytes=len(content),
    )


@router.get("/uploads/download")
async def admin_download_uploaded_file(
    token: str = Query(..., description="Signed download token"),
):
    """
    Redirect to a short-lived signed Cloudinary URL for an admin upload.

    Token auth is used so browsers/webviews can download without attaching headers.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience="bankai-admin-upload",
            issuer="bankai",
            options={"verify_aud": True, "verify_iss": True},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    public_id = str(payload.get("public_id") or "").strip()
    resource_type = str(payload.get("resource_type") or "raw").strip()
    filename = str(payload.get("filename") or "download").strip()
    if not public_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    url = signed_download_url(
        public_id=public_id,
        resource_type=resource_type,
        expires_in_seconds=10 * 60,
        filename=filename,
    )
    if not url:
        raise HTTPException(status_code=503, detail="Download unavailable")
    from fastapi.responses import Response
    return Response(status_code=302, headers={"Location": url})

