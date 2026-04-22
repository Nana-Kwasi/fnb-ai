"""
Observability: structured JSON logging, Prometheus metrics, Sentry error tracking.

All components are initialised once at app startup via init_observability().
The request_id context var is set per-request in main.py middleware.
"""
from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar
from typing import Any

# ── Request-ID context ────────────────────────────────────────────────────────
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str | None) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


# ── Structured JSON logging ───────────────────────────────────────────────────
def _inject_request_id(logger, method_name, event_dict):  # noqa: ARG001
    request_id = get_request_id()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def init_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output with request_id injection."""
    try:
        import structlog

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                _inject_request_id,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level.upper(), logging.INFO)
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )
    except ImportError:
        # Fallback: stdlib JSON logging
        try:
            from pythonjsonlogger import jsonlogger

            handler = logging.StreamHandler()
            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
            handler.setFormatter(formatter)
            root = logging.getLogger()
            root.handlers = [handler]
            root.setLevel(getattr(logging, level.upper(), logging.INFO))
        except ImportError:
            logging.basicConfig(
                level=getattr(logging, level.upper(), logging.INFO),
                format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}',
            )


def get_logger(name: str = __name__):
    """Return a structlog logger, falling back to stdlib if structlog unavailable."""
    try:
        import structlog
        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)


# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY

    # Fraud scoring
    FRAUD_REQUESTS = Counter(
        "fraud_score_requests_total",
        "Total fraud score requests",
        ["tenant_id", "decision"],
    )
    FRAUD_LATENCY = Histogram(
        "fraud_score_duration_seconds",
        "Fraud scoring latency in seconds",
        ["tenant_id"],
        buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
    )
    FRAUD_ENSEMBLE_SCORE = Histogram(
        "fraud_ensemble_score_distribution",
        "Distribution of ensemble fraud scores",
        ["tenant_id"],
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )
    FRAUD_MODEL_STATUS = Gauge(
        "fraud_model_loaded",
        "Whether the primary fraud model is loaded (1=loaded, 0=fallback)",
    )
    FRAUD_BLOCK_RATE = Gauge(
        "fraud_block_rate_realtime",
        "Rolling block rate (updated on each score request)",
        ["tenant_id"],
    )

    # Care chatbot
    CARE_REQUESTS = Counter(
        "care_chat_requests_total",
        "Total care chat requests",
        ["tenant_id", "intent"],
    )
    CARE_LATENCY = Histogram(
        "care_chat_duration_seconds",
        "Care chat latency in seconds",
        ["tenant_id"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    )
    CARE_ESCALATIONS = Counter(
        "care_escalations_total",
        "Total care escalations to human agent",
        ["tenant_id"],
    )

    # HTTP layer
    HTTP_REQUESTS = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status_code"],
    )
    HTTP_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "path"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    )

    # Training
    TRAINING_RUNS = Counter(
        "model_training_runs_total",
        "Total model training runs",
        ["model_type", "status"],
    )
    TRAINING_DURATION = Histogram(
        "model_training_duration_seconds",
        "Model training duration in seconds",
        ["model_type"],
        buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
    )
    MODEL_AUC = Gauge(
        "fraud_model_auc",
        "Latest fraud model AUC on validation set",
    )

    _PROMETHEUS_AVAILABLE = True

except ImportError:
    _PROMETHEUS_AVAILABLE = False

    class _NoopMetric:
        def labels(self, **_): return self
        def inc(self, *_, **__): pass
        def observe(self, *_, **__): pass
        def set(self, *_, **__): pass
        def time(self): return _NoopCtx()

    class _NoopCtx:
        def __enter__(self): return self
        def __exit__(self, *_): pass

    FRAUD_REQUESTS = _NoopMetric()
    FRAUD_LATENCY = _NoopMetric()
    FRAUD_ENSEMBLE_SCORE = _NoopMetric()
    FRAUD_MODEL_STATUS = _NoopMetric()
    FRAUD_BLOCK_RATE = _NoopMetric()
    CARE_REQUESTS = _NoopMetric()
    CARE_LATENCY = _NoopMetric()
    CARE_ESCALATIONS = _NoopMetric()
    HTTP_REQUESTS = _NoopMetric()
    HTTP_LATENCY = _NoopMetric()
    TRAINING_RUNS = _NoopMetric()
    TRAINING_DURATION = _NoopMetric()
    MODEL_AUC = _NoopMetric()


# ── Sentry ────────────────────────────────────────────────────────────────────
def init_sentry(dsn: str, environment: str = "production", release: str | None = None) -> None:
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release or "fnb-ai@1.0.0",
            traces_sample_rate=0.1,  # 10% of transactions for performance monitoring
            profiles_sample_rate=0.05,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            before_send=_sentry_before_send,
        )
    except ImportError:
        logging.getLogger(__name__).warning("sentry-sdk not installed; error tracking disabled.")


def _sentry_before_send(event: dict, hint: dict) -> dict | None:
    """Strip PII from Sentry events before sending."""
    if "request" in event:
        req = event["request"]
        # Remove sensitive headers
        headers = req.get("headers", {})
        for sensitive in ("x-api-key", "authorization", "cookie", "x-tenant-id"):
            headers.pop(sensitive, None)
            headers.pop(sensitive.upper(), None)
        req["headers"] = headers
        # Clear request body to avoid leaking customer data
        req.pop("data", None)
    return event


# ── Helper wrappers for recording metrics ────────────────────────────────────
class FraudScoringTimer:
    """Context manager that records fraud scoring latency and updates Prometheus."""

    def __init__(self, tenant_id: str):
        self._tenant = tenant_id or "unknown"
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.perf_counter() - self._start
        FRAUD_LATENCY.labels(tenant_id=self._tenant).observe(elapsed)
        return False


def record_fraud_decision(tenant_id: str, decision: str, ensemble_score: float) -> None:
    tid = tenant_id or "unknown"
    FRAUD_REQUESTS.labels(tenant_id=tid, decision=decision).inc()
    FRAUD_ENSEMBLE_SCORE.labels(tenant_id=tid).observe(ensemble_score)


def record_care_request(tenant_id: str, intent: str, latency_s: float, escalated: bool) -> None:
    tid = tenant_id or "unknown"
    CARE_REQUESTS.labels(tenant_id=tid, intent=intent or "UNKNOWN").inc()
    CARE_LATENCY.labels(tenant_id=tid).observe(latency_s)
    if escalated:
        CARE_ESCALATIONS.labels(tenant_id=tid).inc()


def record_training_run(model_type: str, success: bool, duration_s: float, auc: float | None = None) -> None:
    status = "success" if success else "failure"
    TRAINING_RUNS.labels(model_type=model_type, status=status).inc()
    TRAINING_DURATION.labels(model_type=model_type).observe(duration_s)
    if auc is not None and model_type == "fraud":
        MODEL_AUC.set(auc)


def update_model_status(loaded: bool) -> None:
    FRAUD_MODEL_STATUS.set(1.0 if loaded else 0.0)


def init_observability(
    log_level: str = "INFO",
    sentry_dsn: str = "",
    environment: str = "development",
    app_version: str = "1.0.0",
) -> None:
    """Call once at app startup to initialise all observability components."""
    init_logging(level=log_level)
    init_sentry(dsn=sentry_dsn, environment=environment, release=f"fnb-ai@{app_version}")
    logger = get_logger(__name__)
    logger.info(
        "observability_initialised",
        log_level=log_level,
        sentry_enabled=bool(sentry_dsn),
        prometheus_available=_PROMETHEUS_AVAILABLE,
        environment=environment,
    )
