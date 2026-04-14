# Operations: production hardening, isolation, training, calibration, Phase 4

## 1. Flip strict flags (production)

Set in `backend/.env` (see `backend/.env.example` **Production** section):

| Variable | Purpose |
|----------|---------|
| `ENVIRONMENT=production` | Enables production-oriented checks when combined with `ENFORCE_PRODUCTION_HARDENING`. |
| `ENFORCE_PRODUCTION_HARDENING=true` | **Fail process startup** if mandatory invariants are missing (strict mapper/training, no default secret, etc.). |
| `STRICT_MAPPER_ENFORCEMENT=true` | No implicit engine fallback; registry + mapper path required for score/train governance. |
| `STRICT_TRAINING_GOVERNANCE=true` | Tenant-scoped uploads require an active mapper before training. |
| `ALLOW_MODEL_FALLBACK=false` | Or set `MODEL_FALLBACK_ALLOWLIST_TENANTS` to explicit UUIDs only. |
| `ADMIN_LEGACY_TOKEN_AUTH=false` | JWT only; legacy token only for controlled break-glass. |
| `WAREHOUSE_ISOLATION_VERIFICATION_ENABLED=true` | Periodic DB + optional replica/analytics/S3 + local layout checks. |
| `WAREHOUSE_ISOLATION_REQUIRE_LOCAL_TRAINING_LAYOUT=true` | Fail isolation job if `training_uploads/` top-level dirs are not `global` or tenant UUIDs. |

Optional **infra gates** (also enforced when hardening is on if you set):

- `PRODUCTION_REQUIRE_ALERT_WEBHOOK=true` → requires `ALERT_WEBHOOK_URL`
- `PRODUCTION_REQUIRE_READ_REPLICA=true` → requires `READ_REPLICA_DATABASE_URL`
- `PRODUCTION_REQUIRE_ANALYTICS_WAREHOUSE=true` → requires `ANALYTICS_WAREHOUSE_URL`

## 2. Infra isolation (finish the loop)

1. **Primary DB**: all tenant tables carry `tenant_id`; warehouse job flags unexpected `NULL` tenant rows (except allowlisted tables like `model_registry`).
2. **Read replica**: point `READ_REPLICA_DATABASE_URL` at a read-only follower; same table list + schema as primary check.
3. **Analytics warehouse**: separate URL + `ANALYTICS_WAREHOUSE_REQUIRED_TABLES` if you mirror aggregates there.
4. **Object store**: `DATA_PLANE_S3_BUCKET` + `DATA_PLANE_S3_PREFIX_TEMPLATE` with `{tenant_id}`; set `DATA_PLANE_S3_REQUIRE_OBJECTS=true` once prefixes are populated.
5. **On-disk training files**: uploads land under `training_uploads/global/` or `training_uploads/<tenant-uuid>/`; enable `WAREHOUSE_ISOLATION_REQUIRE_LOCAL_TRAINING_LAYOUT` in prod.

Wire **ALERT_WEBHOOK_URL** and **PAGING_WEBHOOK_URL** for isolation failures (critical) and KPI staleness (warning).

## 3. Calibration governance

1. Create calibration artifact (shadow → validate).
2. Run holdout: `POST /api/v1/admin/calibration/{artifact_id}/holdout-validate` with `upload_id` (trained/evaluated upload) and `sample_max`.
3. When `CALIBRATION_ACTIVATION_REQUIRES_VALIDATION=true`, activate rejects missing holdout or metrics below `CALIBRATION_ACTIVATION_MIN_ACCURACY` / optional `CALIBRATION_ACTIVATION_MIN_AUC` (fraud).

## 4. Global / pooled training governance

- **Single global upload**: omit `tenant_id` on `POST /api/v1/admin/training/upload` → `training_scope=global` in meta.
- **Multi-upload global base**: `POST /api/v1/admin/training/{fraud|care}/global-pooled/trigger` with `upload_ids` = comma-separated UUIDs (all must be global uploads).
- **Tenant uploads**: require active mapper when `STRICT_TRAINING_GOVERNANCE=true`.
- **Legacy** `POST /api/v1/admin/trigger-fraud-train` may be blocked under strict governance — use upload-based triggers only.

## 5. Phase 4 automation (tune, then enable)

Recommended order:

1. **Shadow + KPIs**: `SHADOW_SCORING_ENABLED=true`; run KPI snapshots; watch **Tenant observability** + batch cutover gate.
2. **Challenger auto-promote**: `AUTO_PROMOTION_ENABLED=true` only after shadow burn-in. Default `AUTO_PROMOTION_MAX_DISAGREE_RATE` is **0.20** (tighter than older 0.25); override per tenant via `challenger_policy` on the bank if needed.
3. **Auto-rollback**: `AUTO_ROLLBACK_ENABLED=true` — fraud uses block/alert rates; care uses **HUMAN_ESCALATION** rate on inference traces (`AUTO_ROLLBACK_CARE_MAX_ESCALATION_RATE`, default 0.45). Set `AUTO_ROLLBACK_MODEL_TYPES=fraud,care` for parity.
4. **Auto-cutover**: keep `AUTO_CUTOVER_DRY_RUN=true` until batch gate is green; then set `AUTO_CUTOVER_DRY_RUN=false` with `AUTO_CUTOVER_ENABLED=true`.

## 6. Smoke test after deploy

- `GET /api/v1/health` — API up.
- `GET /api/v1/admin/monitoring/deployment-readiness` — flags match intent.
- Trigger `POST /api/v1/admin/monitoring/warehouse-isolation/verify` (owner) once in staging.
- Score one fraud and one care request in shadow with strict flags on.
