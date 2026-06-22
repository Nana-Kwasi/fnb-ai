"""Startup validation when ENVIRONMENT=production and ENFORCE_PRODUCTION_HARDENING=true."""

from __future__ import annotations

from app.config import Settings


def _is_truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def collect_policy_profile_violations(s: Settings) -> list[str]:
    """
    Validate the configured production hardening profile.

    Profiles:
    - baseline: minimal safe production settings
    - hardened: baseline + operational safety controls
    - strict_compliance: hardened + stricter governance/read patterns
    """
    profile = (getattr(s, "production_policy_profile", "baseline") or "baseline").strip().lower()
    if profile not in {"baseline", "hardened", "strict_compliance"}:
        return [f"Invalid PRODUCTION_POLICY_PROFILE '{profile}'. Use baseline|hardened|strict_compliance."]

    bad: list[str] = []
    sk = (s.secret_key or "").strip()
    if not sk or sk == "change-me-in-production":
        bad.append("SECRET_KEY must be set to a non-default value")
    if s.debug:
        bad.append("DEBUG must be false in production")

    if profile in {"hardened", "strict_compliance"}:
        if not s.strict_mapper_enforcement:
            bad.append("STRICT_MAPPER_ENFORCEMENT must be true for hardened/strict_compliance profiles")
        if not s.strict_training_governance:
            bad.append("STRICT_TRAINING_GOVERNANCE must be true for hardened/strict_compliance profiles")
        if s.allow_model_fallback and not (s.model_fallback_allowlist_tenants or "").strip():
            bad.append("ALLOW_MODEL_FALLBACK should be false (or use explicit MODEL_FALLBACK_ALLOWLIST_TENANTS)")
        if not (s.alert_webhook_url or "").strip():
            bad.append("ALERT_WEBHOOK_URL should be configured for hardened/strict_compliance profiles")

    if profile == "strict_compliance":
        if not (s.read_replica_database_url or "").strip():
            bad.append("READ_REPLICA_DATABASE_URL should be configured for strict_compliance profile")
        if not s.warehouse_isolation_verification_enabled:
            bad.append("WAREHOUSE_ISOLATION_VERIFICATION_ENABLED should be true for strict_compliance profile")
        if not _is_truthy(str(getattr(s, "enforce_production_hardening", ""))):
            bad.append("ENFORCE_PRODUCTION_HARDENING should be true for strict_compliance profile")

    return bad


def collect_production_violations(s: Settings) -> list[str]:
    env = (s.environment or "").strip().lower()
    if env != "production":
        return []
    if not s.enforce_production_hardening:
        return []

    bad: list[str] = []
    if not s.strict_mapper_enforcement:
        bad.append("STRICT_MAPPER_ENFORCEMENT must be true in production when ENFORCE_PRODUCTION_HARDENING=true")
    if not s.strict_training_governance:
        bad.append("STRICT_TRAINING_GOVERNANCE must be true in production when ENFORCE_PRODUCTION_HARDENING=true")
    if s.allow_model_fallback and not (s.model_fallback_allowlist_tenants or "").strip():
        bad.append(
            "ALLOW_MODEL_FALLBACK should be false in production unless MODEL_FALLBACK_ALLOWLIST_TENANTS is an explicit break-glass allowlist"
        )
    sk = (s.secret_key or "").strip()
    if not sk or sk == "change-me-in-production":
        bad.append("SECRET_KEY must be set to a non-default value")
    if s.debug:
        bad.append("DEBUG must be false in production")
    if s.admin_legacy_token_auth:
        bad.append("ADMIN_LEGACY_TOKEN_AUTH should be false in production (break-glass only with process)")
    if not s.warehouse_isolation_verification_enabled:
        bad.append("WAREHOUSE_ISOLATION_VERIFICATION_ENABLED should be true in production")
    if s.production_require_alert_webhook and not (s.alert_webhook_url or "").strip():
        bad.append("ALERT_WEBHOOK_URL required when PRODUCTION_REQUIRE_ALERT_WEBHOOK=true")
    if s.production_require_read_replica and not (s.read_replica_database_url or "").strip():
        bad.append("READ_REPLICA_DATABASE_URL required when PRODUCTION_REQUIRE_READ_REPLICA=true")
    if s.production_require_analytics_warehouse and not (s.analytics_warehouse_url or "").strip():
        bad.append("ANALYTICS_WAREHOUSE_URL required when PRODUCTION_REQUIRE_ANALYTICS_WAREHOUSE=true")
    if s.calibration_activation_requires_validation and float(s.calibration_activation_min_accuracy) <= 0:
        bad.append("CALIBRATION_ACTIVATION_MIN_ACCURACY should be > 0 when CALIBRATION_ACTIVATION_REQUIRES_VALIDATION=true")
    bad.extend(collect_policy_profile_violations(s))
    return bad


def assert_production_hardening(s: Settings) -> None:
    violations = collect_production_violations(s)
    if violations:
        msg = "Production hardening failed:\n- " + "\n- ".join(violations)
        raise RuntimeError(msg)
