# Model Isolation Rollout (Phase 1/2 Hardening)

## 1) Enable strict mapper + fallback controls in production

Set in `backend/.env`:

- `STRICT_MAPPER_ENFORCEMENT=true`
- `ALLOW_MODEL_FALLBACK=false` (recommended)
- or keep fallback but allowlist only:
  - `ALLOW_MODEL_FALLBACK=true`
  - `MODEL_FALLBACK_ALLOWLIST_TENANTS=<tenant_uuid_1>,<tenant_uuid_2>`

## 2) Mapper backfill ops (before strict mode)

For each tenant and model type (`fraud`, `care`):

1. Create mapper (`POST /api/v1/admin/tenant-mappers`)
2. Validate/dry-run mapper
   - `POST /api/v1/admin/tenant-mappers/validate`
   - `POST /api/v1/admin/tenant-mappers/dry-run`
3. Activate mapper (`POST /api/v1/admin/tenant-mappers/{id}/activate`)

Then enable strict mode.

## 3) Tenant-scoped training storage partitioning

Training uploads are now written to:

- `backend/app/ml/data/training_uploads/<tenant_id|global>/<model_type>/...`

Upload metadata now includes:

- `tenant_id`
- `dataset_version`
- `storage_path`
- `contract_version`

Use `tenant_id` in upload form when dataset is tenant-specific.

## 4) Calibration activation

Create and activate calibration artifacts:

- `POST /api/v1/admin/calibration`
- `POST /api/v1/admin/calibration/{artifact_id}/activate`

Fraud and care inference traces include calibration metadata when active.

## 5) Guardrail auto-rollback

Optional env:

- `AUTO_ROLLBACK_ENABLED=true`
- `AUTO_ROLLBACK_WINDOW_HOURS=24`
- `AUTO_ROLLBACK_MIN_SCORED=300`
- `AUTO_ROLLBACK_MAX_BLOCK_RATE=0.6`
- `AUTO_ROLLBACK_MAX_ALERT_RATE=0.5`

Manual trigger endpoint:

- `POST /api/v1/admin/monitoring/model-guardrails/run`

Scheduler also runs guardrails every 30 minutes.

## 6) Phase 4.1 shadow scoring

Enable in `backend/.env`:

- `SHADOW_SCORING_ENABLED=true`

When enabled, fraud serving will:

- resolve latest tenant `shadow` candidate model from registry
- compute candidate shadow score from same feature vector
- apply candidate calibration (if active for candidate model version)
- log candidate score/decision metadata into `inference_trace.trace_json.mapper_validation.shadow`

This is non-blocking and does not affect customer-facing decision.

## 7) Phase 4.3 auto-promotion evaluator

Optional env flags:

- `AUTO_PROMOTION_ENABLED=false`
- `AUTO_PROMOTION_WINDOW_HOURS=24`
- `AUTO_PROMOTION_MIN_COMPARED=300`
- `AUTO_PROMOTION_MAX_BLOCK_RATE_DELTA=0.02`
- `AUTO_PROMOTION_MAX_OTP_RATE_DELTA=0.03`
- `AUTO_PROMOTION_MAX_DISAGREE_RATE=0.20` (tighter default; override via tenant `challenger_policy` if needed)

Behavior:

- scheduler runs challenger evaluator every 30 minutes
- evaluator reads champion vs shadow decisions from `inference_trace.trace_json.mapper_validation.shadow`
- if candidate satisfies policy constraints, it auto-promotes shadow to active
- writes `MODEL_AUTO_PROMOTED` audit event with KPI snapshot
- if enough labeled outcomes exist, evaluator applies precision-delta gate
  (`AUTO_PROMOTION_MIN_LABELED`, `AUTO_PROMOTION_MIN_PRECISION_DELTA`)

Manual controls:

- `POST /api/v1/admin/monitoring/challenger-evaluator/run`
- `GET /api/v1/admin/monitoring/challenger-policy?tenant_id=<id>`
- `PATCH /api/v1/admin/monitoring/challenger-policy?tenant_id=<id>` (tenant override)
- `DELETE /api/v1/admin/monitoring/challenger-policy?tenant_id=<id>` (reset override)

Guardrails added:

- candidate minimum age gate before promotion
- per-tenant cooldown between auto-promotions

## 8) Lineage and reproducibility stamps

Model publish paths now stamp lineage metadata in registry entries:

- `dataset_version`
- `contract_version`
- `mapper_version`
- `artifact_uri`
- `artifact_sha256` (for local file/dir artifacts)
- tenant fine-tune publish also stamps:
  - `upload_id`
  - `training_storage_path`
  - `training_data_sha256`

`scripts/train_from_uploaded_data.py` also writes trained artifact metadata back to upload meta:

- `trained_artifact_uri`
- `trained_artifact_sha256`

## 9) Production cutover gate

Use the tenant-scoped hard gate before strict prod switch:

- `GET /api/v1/admin/monitoring/cutover-gate?tenant_id=<id>&model_type=<fraud|care>`

Gate blocks if:

- strict mapper enforcement is off
- model fallback is still enabled
- no active tenant model or mapper
- lineage stamps are missing on active model
- fallback-routed traces were observed in last 24h
- no KPI snapshot exists
