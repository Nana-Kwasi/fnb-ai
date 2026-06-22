from __future__ import annotations

import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_CACHE_ROOT = _BACKEND_ROOT / ".artifact_cache"
_CACHE_TTL_SECONDS = int(getattr(settings, "artifact_cache_ttl_seconds", 900) or 900)
_CACHE_MAX_FILES = int(getattr(settings, "artifact_cache_max_files", 5000) or 5000)
_CACHE_MAX_BYTES = int(getattr(settings, "artifact_cache_max_bytes", 2147483648) or 2147483648)
_S3_MAX_RETRIES = int(getattr(settings, "artifact_s3_max_retries", 4) or 4)
_S3_RETRY_BASE_MS = int(getattr(settings, "artifact_s3_retry_base_ms", 200) or 200)


def _artifact_allowed(raw: str) -> bool:
    allowed = {
        x.strip().lower()
        for x in str(getattr(settings, "artifact_allowed_schemes", "file,s3")).split(",")
        if x.strip()
    }
    if raw.startswith("s3://"):
        if "s3" not in allowed:
            return False
        buckets = {
            x.strip()
            for x in str(getattr(settings, "artifact_s3_allowed_buckets", "")).split(",")
            if x.strip()
        }
        if buckets:
            bucket, _ = _s3_parts(raw)
            return bucket in buckets
        return True
    if raw.startswith(("http://", "https://", "gs://")):
        return False
    return "file" in allowed


def _evict_cache_if_needed() -> None:
    if not _CACHE_ROOT.exists():
        return
    files = [p for p in _CACHE_ROOT.rglob("*") if p.is_file() and p.name != ".synced_at"]
    total = sum(int(p.stat().st_size) for p in files)
    if len(files) <= _CACHE_MAX_FILES and total <= _CACHE_MAX_BYTES:
        return
    files.sort(key=lambda p: p.stat().st_mtime)
    while files and (len(files) > _CACHE_MAX_FILES or total > _CACHE_MAX_BYTES):
        victim = files.pop(0)
        try:
            sz = int(victim.stat().st_size)
        except OSError:
            sz = 0
        try:
            victim.unlink(missing_ok=True)
        except OSError:
            continue
        total = max(0, total - sz)


def _safe_rel_path(value: str) -> str:
    out = (value or "").strip().replace("\\", "/")
    out = out.lstrip("/")
    parts = [p for p in out.split("/") if p not in {"", ".", ".."}]
    return "/".join(parts)


def _local_path_from_uri(uri: str) -> Path:
    raw = (uri or "").strip()
    if raw.startswith("file://"):
        raw = raw[7:]
    p = Path(raw)
    if not p.is_absolute():
        p = (_BACKEND_ROOT.parent / raw).resolve()
    return p


def _s3_parts(uri: str) -> tuple[str, str]:
    u = urlparse(uri)
    if u.scheme != "s3" or not u.netloc:
        raise ValueError("Invalid s3 URI")
    bucket = u.netloc
    key = (u.path or "").lstrip("/")
    return bucket, key


def _download_s3_uri(uri: str) -> Path | None:
    try:
        import boto3  # pylint: disable=import-error
    except ImportError:
        return None
    bucket, key = _s3_parts(uri)
    # Support S3-compatible backends (Cloudflare R2, MinIO, etc.).
    # boto3 does NOT automatically read AWS_ENDPOINT_URL, so we plumb it through.
    endpoint_url = os.getenv("AWS_ENDPOINT_URL") or None
    s3 = boto3.client("s3", endpoint_url=endpoint_url)
    safe_key = _safe_rel_path(key)

    def _with_retry(fn):
        for attempt in range(1, max(1, _S3_MAX_RETRIES) + 1):
            try:
                return fn()
            except Exception:
                if attempt >= _S3_MAX_RETRIES:
                    raise
                sleep_s = ((_S3_RETRY_BASE_MS / 1000.0) * (2 ** (attempt - 1))) + random.random() * 0.05
                time.sleep(sleep_s)
    # Exact object URI when key looks like a file.
    if safe_key and not safe_key.endswith("/"):
        target = (_CACHE_ROOT / "s3" / bucket / safe_key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and _CACHE_TTL_SECONDS > 0:
            age = time.time() - float(target.stat().st_mtime)
            if age <= _CACHE_TTL_SECONDS:
                return target
        try:
            _with_retry(lambda: s3.download_file(bucket, key, str(target)))
            _evict_cache_if_needed()
            return target
        except Exception:
            # fall through to prefix mode below
            pass

    prefix = safe_key
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"
    base = (_CACHE_ROOT / "s3" / bucket / prefix).resolve()
    base.mkdir(parents=True, exist_ok=True)
    marker = base / ".synced_at"
    if marker.exists() and _CACHE_TTL_SECONDS > 0:
        age = time.time() - float(marker.stat().st_mtime)
        if age <= _CACHE_TTL_SECONDS:
            return base
    found = False
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        try:
            resp = _with_retry(lambda: s3.list_objects_v2(**kw))
        except Exception:
            return None
        for obj in resp.get("Contents", []) or []:
            k = str(obj.get("Key") or "")
            if not k or k.endswith("/"):
                continue
            rel = _safe_rel_path(k[len(prefix):] if prefix and k.startswith(prefix) else k)
            target = (base / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            _with_retry(lambda: s3.download_file(bucket, k, str(target)))
            found = True
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    marker.touch(exist_ok=True)
    _evict_cache_if_needed()
    return base if found else None


def fetch_artifact_uri_to_local_path(artifact_uri: str | None) -> Path | None:
    raw = (artifact_uri or "").strip()
    if not raw:
        return None
    if not _artifact_allowed(raw):
        return None
    if raw.startswith("s3://"):
        return _download_s3_uri(raw)
    return _local_path_from_uri(raw)

