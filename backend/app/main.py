import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.observability import (
    set_request_id,
    init_observability,
    HTTP_REQUESTS,
    HTTP_LATENCY,
    update_model_status,
)
from app.database import engine, Base
# Register SQLAlchemy models with Base metadata.
from app import models  # pylint: disable=unused-import
from app.database import AsyncSessionLocal
from app.routers import admin, auth, care, compliance, fraud, platform_admin, reports
from app.routers import uploads
from app.services.platform_bootstrap import ensure_bootstrap_platform_owner
from app.services.production_hardening import assert_production_hardening


def _production_warnings() -> None:
    import logging

    log = logging.getLogger("app.bootstrap")
    env = (settings.environment or "").strip().lower()
    if env != "production":
        return
    raw = __import__("os").environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw or "YOUR_FRONTEND" in raw.upper():
        log.warning(
            "CORS_ALLOWED_ORIGINS is empty or still contains YOUR_FRONTEND — "
            "set it to your real frontend origin(s) before going live."
        )


def _build_cors_origins() -> list[str]:
    """
    CORS origin allowlist resolution order:
    1. CORS_ALLOWED_ORIGINS env var (comma-separated) — use this in production to lock down to real domains.
    2. Always include localhost origins for local dev/Docker — safe because the API requires
       X-API-Key authentication on every tenant endpoint regardless of origin.
    """
    import os
    _LOCALHOST_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:8080",
    ]
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        explicit = [o.strip() for o in raw.split(",") if o.strip()]
        # Merge localhost origins so Docker dev still works alongside prod domains
        return list(dict.fromkeys(explicit + _LOCALHOST_ORIGINS))
    return _LOCALHOST_ORIGINS


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_observability(
        log_level=settings.log_level,
        sentry_dsn=settings.sentry_dsn,
        environment=settings.environment,
        app_version=settings.release_version,
    )
    assert_production_hardening(settings)
    _production_warnings()
    if "sqlite" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await ensure_bootstrap_platform_owner(session)
        await session.commit()
    from app.services.fraud_engine import ensure_fraud_models_loaded

    status = ensure_fraud_models_loaded()
    update_model_status(status.get("mode") == "model")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    # AsyncIOScheduler runs jobs on the *existing* uvicorn event loop.
    # Never use BackgroundScheduler + asyncio.run() — that creates a second loop
    # which breaks asyncpg connections and SQLAlchemy async sessions.
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.services.job_runs import run_tracked_job

        # ── job wrappers ───────────────────────────────────────────────────────
        # Each wrapper is a plain async function — APScheduler calls it directly
        # on the running event loop, no asyncio.run() needed.

        import asyncio as _asyncio

        async def _tracked(job_name: str, runner, is_async: bool = True):
            async def _body():
                if is_async:
                    out = await runner()
                else:
                    # Blocking sync work (e.g. ML training) — offload to thread pool
                    # so the event loop stays unblocked.
                    out = await _asyncio.get_event_loop().run_in_executor(None, runner)
                return out if out is not None else {"ok": True}
            try:
                await run_tracked_job(
                    job_name=job_name,
                    trigger_source="scheduler",
                    actor_id="scheduler",
                    runner=_body,
                )
            except Exception as exc:
                # Jobs must never crash the scheduler — log and move on.
                from app.observability import get_logger as _lg
                _lg(__name__).error("scheduled_job_error", job=job_name, error=str(exc))

        from app.tasks.care_train_scheduled import run_care_training
        from app.tasks.fraud_drift_monitor import run_fraud_drift_checks
        from app.tasks.fraud_train_scheduled import run_fraud_training
        from app.tasks.webhook_retry import run_webhook_retry
        from app.tasks.retention_purge import run_retention_purge
        from app.tasks.model_challenger_evaluator import run_challenger_evaluator
        from app.tasks.model_cutover_executor import run_model_cutover_executor
        from app.tasks.model_guardrails import run_model_guardrails
        from app.tasks.model_kpi_snapshots import run_model_kpi_snapshot
        from app.tasks.warehouse_isolation_verify import run_warehouse_isolation_verification
        from app.tasks.tenant_finetune_scout import run_tenant_finetune_scout
        from app.services.report_jobs import cleanup_old_report_artifacts

        scheduler = AsyncIOScheduler()

        async def _kpi_runner(): return await run_model_kpi_snapshot(30)
        async def _cleanup_runner(): return await cleanup_old_report_artifacts(settings.report_artifact_retention_days)

        # AsyncIOScheduler requires the job to be a coroutine function (async def), not a lambda.
        # We use functools.partial-style closures via default-arg capture to bind each job name+runner.
        import functools

        def _make_job(name, runner, is_async=True):
            async def _job():
                await _tracked(name, runner, is_async=is_async)
            return _job

        scheduler.add_job(_make_job("care_train", run_care_training, is_async=False), "interval", hours=6, id="care_train")
        scheduler.add_job(_make_job("fraud_train", run_fraud_training, is_async=False), "interval", hours=24, id="fraud_train")
        scheduler.add_job(_make_job("fraud_drift_monitor", run_fraud_drift_checks), "interval", minutes=30, id="fraud_drift_monitor")
        scheduler.add_job(_make_job("model_guardrails", run_model_guardrails), "interval", minutes=30, id="model_guardrails")
        scheduler.add_job(_make_job("challenger_evaluator", run_challenger_evaluator), "interval", minutes=30, id="challenger_evaluator")
        scheduler.add_job(_make_job("model_kpi_snapshots", _kpi_runner), "interval", hours=6, id="model_kpi_snapshots")
        scheduler.add_job(_make_job("model_cutover_executor", run_model_cutover_executor), "interval", minutes=30, id="model_cutover_executor")
        scheduler.add_job(_make_job("warehouse_isolation_verification", run_warehouse_isolation_verification), "interval", hours=6, id="warehouse_isolation_verification")
        scheduler.add_job(_make_job("tenant_finetune_scout", run_tenant_finetune_scout), "interval", hours=24, id="tenant_finetune_scout")
        scheduler.add_job(_make_job("report_artifact_cleanup", _cleanup_runner), "interval", hours=24, id="report_artifact_cleanup")
        scheduler.add_job(_make_job("webhook_retry", run_webhook_retry), "interval", seconds=60, id="webhook_retry")
        scheduler.add_job(_make_job("retention_purge", run_retention_purge), "interval", hours=24, id="retention_purge")

        scheduler.start()
    except ImportError:
        scheduler = None

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)


_app_docs = "/docs" if settings.expose_openapi else None
_app_redoc = "/redoc" if settings.expose_openapi else None

app = FastAPI(
    title=settings.app_name,
    description="White-label Fraud Detection + Customer Care API",
    version=settings.release_version,
    lifespan=lifespan,
    docs_url=_app_docs,
    redoc_url=_app_redoc,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Tenant-ID", "X-Request-ID"],
)


@app.middleware("http")
async def production_security_headers(request: Request, call_next):
    response = await call_next(request)
    if (settings.environment or "").strip().lower() == "production":
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    set_request_id(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        path = request.url.path
        HTTP_REQUESTS.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        HTTP_LATENCY.labels(method=request.method, path=path).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        set_request_id(None)


if settings.prometheus_metrics_enabled:
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_respect_env_var=False,
            excluded_handlers=["/api/v1/health", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics")
    except ImportError:
        pass


@app.get("/api/v1/metrics/prometheus", include_in_schema=False)
async def prometheus_raw():
    """Raw Prometheus text exposition (fallback if /metrics not mounted)."""
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return {"error": "prometheus_client not installed"}


app.include_router(fraud.router, prefix="/api/v1/fraud", tags=["fraud"])
app.include_router(care.router, prefix="/api/v1/care", tags=["care"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(platform_admin.router, prefix="/api/v1/platform", tags=["platform"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(reports.router, prefix="/api/v1/admin/reports", tags=["admin-reports"])
app.include_router(uploads.router, prefix="/api/v1/admin", tags=["admin-uploads"])
app.include_router(compliance.router, prefix="/api/v1/admin", tags=["compliance"])


@app.get("/api/v1/health")
async def health():
    from app.services.fraud_engine import get_fraud_model_status

    fraud_models = get_fraud_model_status()
    return {"status": "ok", "service": settings.app_name, "fraud_models": fraud_models}
