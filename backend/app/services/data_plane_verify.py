from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings

_UUID_DIR = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _parse_table_list(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


async def _verify_sql_tables_bound(
    session_maker: async_sessionmaker,
    tables: list[str],
    label: str,
    *,
    pg_schema: str = "public",
) -> list[str]:
    errors: list[str] = []
    async with session_maker() as db:
        bind = await db.get_bind()
        is_sqlite = bind.dialect.name == "sqlite"
        schema = (pg_schema or "public").strip() or "public"
        for table in tables:
            key = f"{label}:{table}"
            if is_sqlite:
                cols = (await db.execute(text(f"PRAGMA table_info({table})"))).all()
                col_names = {str(c[1]) for c in cols}
            else:
                cols = (
                    await db.execute(
                        text(
                            "select column_name from information_schema.columns "
                            "where table_name = :t and table_schema = :s"
                        ),
                        {"t": table, "s": schema},
                    )
                ).all()
                col_names = {str(c[0]) for c in cols}
            if not col_names:
                errors.append(f"{key}:missing_table")
                continue
            if "tenant_id" not in col_names:
                errors.append(f"{key}:missing_tenant_id")
                continue
            if table in {"model_registry"}:
                continue
            null_count = (
                await db.execute(text(f"select count(*) from {table} where tenant_id is null"))
            ).scalar_one_or_none()
            if int(null_count or 0) > 0:
                errors.append(f"{key}:null_tenant_id_rows={int(null_count or 0)}")
    return errors


async def verify_read_replica_isolation() -> list[str]:
    url = (settings.read_replica_database_url or "").strip()
    if not url:
        return []
    tables = _parse_table_list(settings.warehouse_isolation_required_tables)
    if not tables:
        return []
    try:
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    except Exception as e:  # pylint: disable=broad-except
        return [f"read_replica:connect_failed:{e!s}"]
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sch = (settings.read_replica_table_schema or "public").strip() or "public"
    try:
        return await _verify_sql_tables_bound(session_maker, tables, "read_replica", pg_schema=sch)
    finally:
        await engine.dispose()


async def verify_analytics_warehouse_isolation() -> list[str]:
    url = (settings.analytics_warehouse_url or "").strip()
    if not url:
        return []
    tables = _parse_table_list(
        settings.analytics_warehouse_required_tables or settings.warehouse_isolation_required_tables
    )
    if not tables:
        return []
    try:
        engine = create_async_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    except Exception as e:  # pylint: disable=broad-except
        return [f"analytics_warehouse:connect_failed:{e!s}"]
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sch = (settings.analytics_warehouse_schema or "public").strip() or "public"
    try:
        return await _verify_sql_tables_bound(session_maker, tables, "analytics_wh", pg_schema=sch)
    finally:
        await engine.dispose()


def verify_local_training_partition(*, training_root: Path) -> list[str]:
    if not training_root.is_dir():
        return ["local_training:root_missing"]
    bad: list[str] = []
    for p in training_root.iterdir():
        if p.name.startswith("."):
            continue
        if p.is_file():
            bad.append(f"file_at_root:{p.name}")
            continue
        if p.name != "global" and not _UUID_DIR.match(p.name):
            bad.append(f"bad_top_level_dir:{p.name}")
    if bad:
        return [f"local_training:{bad[:25]}"]
    return []


def verify_s3_tenant_prefixes(*, tenant_ids: list[uuid.UUID]) -> list[str]:
    bucket = (settings.data_plane_s3_bucket or "").strip()
    tmpl = (settings.data_plane_s3_prefix_template or "").strip()
    if not bucket or not tmpl:
        return []
    try:
        import boto3  # type: ignore
        from botocore.exceptions import ClientError  # type: ignore
    except ImportError:
        return ["s3:boto3_not_installed"]
    errs: list[str] = []
    s3 = boto3.client("s3")
    strict = bool(settings.data_plane_s3_require_objects)
    for tid in tenant_ids:
        if "{tenant_id}" in tmpl or "{tenant_id_short}" in tmpl:
            prefix = tmpl.format(tenant_id=str(tid), tenant_id_short=str(tid).replace("-", "")[:12])
        else:
            prefix = f"{tmpl.rstrip('/')}/{tid}/"
        try:
            resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
            if strict and int(resp.get("KeyCount") or 0) < 1:
                errs.append(f"s3:empty_prefix:{prefix}")
        except ClientError as e:
            errs.append(f"s3:list_failed:{prefix}:{e!s}")
    return errs
