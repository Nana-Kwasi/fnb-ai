import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV_FILE = _BACKEND_ROOT / ".env"
_PROD_ENV_FILE = _BACKEND_ROOT / ".env.production"


def _pick_env_file() -> Path:
    # Allows Render/containers to specify a different dotenv file when desired.
    env_file_override_raw = os.environ.get("ENV_FILE")
    env_file_override = (Path.cwd() / env_file_override_raw).resolve() if env_file_override_raw else None
    if env_file_override and env_file_override.exists():
        return env_file_override
    if _PROD_ENV_FILE.exists():
        return _PROD_ENV_FILE
    return _DEFAULT_ENV_FILE


_ENV_FILE = _pick_env_file()


class Settings(BaseSettings):
    app_name: str = "BankAI Platform"
    debug: bool = False
    # Set to "production" in deployed environments; used with enforce_production_hardening.
    environment: str = "development"
    # baseline|hardened|strict_compliance for policy-profile checks and readiness reporting.
    production_policy_profile: str = "baseline"
    enforce_production_hardening: bool = False
    production_require_alert_webhook: bool = False
    production_require_read_replica: bool = False
    production_require_analytics_warehouse: bool = False

    database_url: str = "sqlite+aiosqlite:///./bankai.db"
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"
    model_path: str = "/models/Phi-3-mini-4k-instruct-q4.gguf"
    care_jwt_secret: str = "dev-care-secret-change-me"
    strict_model_loading: bool = True
    allow_heuristic_fallback: bool = False

    rate_limit_per_minute: int = 1000
    api_key_header: str = "X-API-Key"
    tenant_header: str = "X-Tenant-ID"
    admin_write_token: str = ""
    admin_legacy_token_auth: bool = True
    auth_provider: str = "local"
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    saml_expected_issuer: str = ""
    saml_expected_audience: str = ""
    platform_jwt_expire_minutes: int = 720
    platform_bootstrap_owner_email: str = ""
    platform_bootstrap_owner_password: str = ""
    report_artifact_retention_days: int = 30
    strict_mapper_enforcement: bool = False
    # When True, tenant-scoped training uploads require an active TenantMapper for that model_type.
    strict_training_governance: bool = False
    allow_model_fallback: bool = True
    model_fallback_allowlist_tenants: str = ""
    auto_rollback_enabled: bool = False
    # Comma-separated: fraud, care (care uses InferenceTrace escalation rate).
    auto_rollback_model_types: str = "fraud"
    auto_rollback_window_hours: int = 24
    auto_rollback_min_scored: int = 300
    auto_rollback_max_block_rate: float = 0.6
    auto_rollback_max_alert_rate: float = 0.5
    auto_rollback_care_max_escalation_rate: float = 0.45
    shadow_scoring_enabled: bool = False
    auto_promotion_enabled: bool = False
    auto_promotion_window_hours: int = 24
    auto_promotion_min_compared: int = 300
    auto_promotion_max_block_rate_delta: float = 0.02
    auto_promotion_max_otp_rate_delta: float = 0.03
    # Tighter production tuning: start at 0.20 when enabling auto_promotion in prod.
    auto_promotion_max_disagree_rate: float = 0.20
    auto_promotion_cooldown_hours: int = 24
    auto_promotion_candidate_min_age_hours: int = 6
    auto_promotion_min_labeled: int = 100
    auto_promotion_min_precision_delta: float = -0.01
    auto_cutover_enabled: bool = False
    # Production: run dry_run=true until batch gate burn-down is green, then false.
    auto_cutover_dry_run: bool = True
    auto_cutover_require_no_prior_execution: bool = True
    auto_cutover_model_types: str = "fraud,care"
    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: int = 5
    warehouse_isolation_verification_enabled: bool = False
    # When True, missing/bad local training_uploads layout fails the isolation check (stricter data-plane).
    warehouse_isolation_require_local_training_layout: bool = False
    warehouse_isolation_required_tables: str = "fraud_scores,fraud_alerts,fraud_outcomes,inference_trace,model_registry,tenant_mappers,model_kpi_snapshots,training_uploads"
    read_replica_database_url: str = ""
    read_replica_table_schema: str = "public"
    artifact_allowed_schemes: str = "file,s3"
    artifact_s3_allowed_buckets: str = ""
    artifact_cache_ttl_seconds: int = 900
    artifact_cache_max_files: int = 5000
    artifact_cache_max_bytes: int = 2147483648
    artifact_s3_max_retries: int = 4
    artifact_s3_retry_base_ms: int = 200
    tenant_data_retention_days: int = 365
    tenant_anonymization_enabled: bool = False
    canary_rollout_enabled: bool = False
    canary_default_percent: float = 0.0
    canary_auto_stop_enabled: bool = False
    canary_auto_stop_window_hours: int = 6
    canary_auto_stop_min_compared: int = 200
    canary_auto_stop_max_disagree_rate: float = 0.25
    analytics_warehouse_url: str = ""
    analytics_warehouse_schema: str = "public"
    analytics_warehouse_required_tables: str = ""
    data_plane_s3_bucket: str = ""
    data_plane_s3_prefix_template: str = ""
    data_plane_s3_require_objects: bool = False
    calibration_activation_requires_validation: bool = False
    calibration_activation_min_accuracy: float = 0.0
    calibration_activation_min_auc: float | None = None
    model_kpi_snapshot_max_stale_hours: int = 12
    paging_webhook_url: str = ""
    # Phase 3: periodic job logs eligible tenants (audit + optional alert); does not train automatically.
    auto_tenant_finetune_scout_enabled: bool = False
    auto_tenant_finetune_scout_min_rows: int = 800

    # ── Observability ──────────────────────────────────────────────────────────
    sentry_dsn: str = ""
    log_level: str = "INFO"
    # Set to "false" to disable the /metrics Prometheus endpoint
    prometheus_metrics_enabled: bool = True
    # Reject inference: include blocked transactions with pseudo-labels in retraining
    reject_inference_enabled: bool = True
    reject_inference_fraud_threshold: float = 0.80
    reject_inference_legit_threshold: float = 0.40
    # GNN embeddings: compute graph-based node risk scores during feature engineering
    gnn_embeddings_enabled: bool = True
    # Behavioral biometrics: accept biometric signals from mobile SDK
    biometrics_enabled: bool = True

    # ── Cloudinary (optional file storage) ─────────────────────────────────────
    # Prefer setting CLOUDINARY_URL in the environment.
    cloudinary_url: str = ""
    cloudinary_uploads_enabled: bool = True
    cloudinary_folder_prefix: str = "bankai"
    # If true, report/statements are uploaded to Cloudinary and download endpoints redirect.
    cloudinary_store_reports: bool = True
    # If true, the Care statement.pdf endpoint uploads to Cloudinary (raw) and redirects.
    cloudinary_store_statements: bool = True
    # Upload delivery type: "upload" (public) or "private" (requires signed URLs).
    cloudinary_delivery_type: str = "private"

    # End-user uploads (Care) quotas + limits
    care_uploads_enabled: bool = True
    care_upload_max_bytes: int = 8 * 1024 * 1024  # 8MB per file
    care_upload_max_files_per_day: int = 20  # per (tenant, customer) per UTC day
    care_upload_max_bytes_per_day: int = 40 * 1024 * 1024  # 40MB per day per (tenant, customer)
    care_upload_download_token_ttl_seconds: int = 300  # 5 minutes

    # Optional malware scan hook (best-effort)
    malware_scan_webhook_url: str = ""
    malware_scan_timeout_seconds: int = 6
    malware_scan_require_clean: bool = False

    @field_validator("calibration_activation_min_auc", mode="before")
    @classmethod
    def _empty_optional_float(cls, v):
        if v is None or v == "":
            return None
        return v

    class Config:
        env_file = _ENV_FILE
        env_file_encoding = "utf-8"


settings = Settings()
