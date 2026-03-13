from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app import models  # noqa: F401 - register tables with Base
from app.routers import admin, care, fraud

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.tasks.care_train_scheduled import run_care_training
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(run_care_training, "interval", hours=6, id="care_train")
except ImportError:
    _scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if "sqlite" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    if _scheduler is not None:
        _scheduler.start()
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    description="White-label Fraud Detection + Customer Care API",
    version="1.0.0",
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
    return {"status": "ok", "service": settings.app_name}
