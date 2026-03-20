from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app import models  # pylint: disable=unused-import - register tables with Base
from app.routers import admin, care, fraud

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.tasks.care_train_scheduled import run_care_training
    from app.tasks.fraud_train_scheduled import run_fraud_training

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(run_care_training, "interval", hours=6, id="care_train")
    # Retrain fraud models from labelled data on a regular cadence (e.g. daily).
    _scheduler.add_job(run_fraud_training, "interval", hours=24, id="fraud_train")
except ImportError:
    _scheduler = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if "sqlite" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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
    version="1.0.1",
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

app.include_router(fraud.router, prefix="/api/v1/fraud", tags=["fraud"])
app.include_router(care.router, prefix="/api/v1/care", tags=["care"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])


@app.get("/api/v1/health")
async def health():
    from app.services.fraud_engine import get_fraud_model_status

    fraud_models = get_fraud_model_status()
    return {"status": "ok", "service": settings.app_name, "fraud_models": fraud_models}
