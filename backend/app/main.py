import asyncio
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.observability import set_request_id
from app.database import engine, Base
# Register SQLAlchemy models with Base metadata.
from app import models  # pylint: disable=unused-import
from app.database import AsyncSessionLocal
from app.routers import admin, auth, care, fraud, platform_admin, reports
from app.services.platform_bootstrap import ensure_bootstrap_platform_owner
from app.services.production_hardening import assert_production_hardening

_scheduler = None

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.tasks.care_train_scheduled import run_care_training
    from app.tasks.fraud_drift_monitor import run_fraud_drift_checks
    from app.tasks.fraud_train_scheduled import run_fraud_training
    from app.tasks.model_challenger_evaluator import run_challenger_evaluator
    from app.tasks.model_cutover_executor import run_model_cutover_executor
    from app.tasks.model_guardrails import run_model_guardrails
    from app.tasks.model_kpi_snapshots import run_model_kpi_snapshot
    from app.tasks.warehouse_isolation_verify import run_warehouse_isolation_verification
    from app.tasks.tenant_finetune_scout import run_tenant_finetune_scout
    from app.services.report_jobs import cleanup_old_report_artifacts
    from app.services.job_runs import run_tracked_job

    _scheduler = BackgroundScheduler()
    def _run_tracked_sync(job_name: str, runner):
        async def _runner_async():
            out = runner()
            return out if out is not None else {"ok": True}

        return asyncio.run(
            run_tracked_job(
                job_name=job_name,
                trigger_source="scheduler",
                actor_id="scheduler",
                runner=_runner_async,
            )
        )

    def _run_tracked_async(job_name: str, runner):
        async def _runner_async():
            out = await runner()
            return out if out is not None else {"ok": True}

        return asyncio.run(
            run_tracked_job(
                job_name=job_name,
                trigger_source="scheduler",
                actor_id="scheduler",
                runner=_runner_async,
            )
        )

    _scheduler.add_job(lambda: _run_tracked_sync("care_train", run_care_training), "interval", hours=6, id="care_train")
    # Retrain fraud models from labelled data on a regular cadence (e.g. daily).
    _scheduler.add_job(lambda: _run_tracked_sync("fraud_train", run_fraud_training), "interval", hours=24, id="fraud_train")
    # Drift monitoring for fraud features (green/yellow/red status persisted to audit logs).
    _scheduler.add_job(
        lambda: _run_tracked_sync("fraud_drift_monitor", run_fraud_drift_checks),
        "interval",
        minutes=30,
        id="fraud_drift_monitor",
    )
    # Auto-rollback guardrails for tenant models.
    _scheduler.add_job(
        lambda: _run_tracked_async("model_guardrails", run_model_guardrails),
        "interval",
        minutes=30,
        id="model_guardrails",
    )
    # Auto-promotion evaluator for champion/challenger.
    _scheduler.add_job(
        lambda: _run_tracked_async("challenger_evaluator", run_challenger_evaluator),
        "interval",
        minutes=30,
        id="challenger_evaluator",
    )
    # Persist KPI snapshots for trend dashboards and guardrails.
    _scheduler.add_job(
        lambda: _run_tracked_async("model_kpi_snapshots", lambda: run_model_kpi_snapshot(30)),
        "interval",
        hours=6,
        id="model_kpi_snapshots",
    )
    # Optional policy-driven tenant cutover executor.
    _scheduler.add_job(
        lambda: _run_tracked_async("model_cutover_executor", run_model_cutover_executor),
        "interval",
        minutes=30,
        id="model_cutover_executor",
    )
    # Warehouse/data-plane tenant isolation verification.
    _scheduler.add_job(
        lambda: _run_tracked_async(
            "warehouse_isolation_verification",
            run_warehouse_isolation_verification,
        ),
        "interval",
        hours=6,
        id="warehouse_isolation_verification",
    )
    _scheduler.add_job(
        lambda: _run_tracked_async("tenant_finetune_scout", run_tenant_finetune_scout),
        "interval",
        hours=24,
        id="tenant_finetune_scout",
    )
    # Retention cleanup for generated report artifacts.
    _scheduler.add_job(
        lambda: _run_tracked_async(
            "report_artifact_cleanup",
            lambda: cleanup_old_report_artifacts(settings.report_artifact_retention_days),
        ),
        "interval",
        hours=24,
        id="report_artifact_cleanup",
    )
except ImportError:
    _scheduler = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_production_hardening(settings)
    if "sqlite" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await ensure_bootstrap_platform_owner(session)
        await session.commit()
    # Fail-fast: load fraud models at startup (strict mode will prevent silent degradation).
    from app.services.fraud_engine import ensure_fraud_models_loaded

    ensure_fraud_models_loaded()
    if _scheduler is not None:
        _scheduler.start()
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    description="White-label Fraud Detection + Customer Care API",
    version="1.0.2",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    set_request_id(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        set_request_id(None)


app.include_router(fraud.router, prefix="/api/v1/fraud", tags=["fraud"])
app.include_router(care.router, prefix="/api/v1/care", tags=["care"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(platform_admin.router, prefix="/api/v1/platform", tags=["platform"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(reports.router, prefix="/api/v1/admin/reports", tags=["admin-reports"])


@app.get("/api/v1/health")
async def health():
    from app.services.fraud_engine import get_fraud_model_status

    fraud_models = get_fraud_model_status()
    return {"status": "ok", "service": settings.app_name, "fraud_models": fraud_models}
