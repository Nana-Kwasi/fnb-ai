# Code-Only Gap Checklist: Stage 3 -> 10/10 (and all stages to 10 quickly)

This checklist focuses on **code and architecture gaps only** (not environment provisioning).

Goal:
- Raise **Stage 3 (scale/compliance)** from ~5.5 to 10.
- Also harden Stage 1 and Stage 2 to 10 with minimal rework.

---

## How to use this checklist

- [ ] means not done yet
- [~] means in progress
- [x] means complete
- Priority tags:
  - **P0** = must do first
  - **P1** = high-value next
  - **P2** = polish/advanced

---

## Implementation status (updated)

This file started as a gap list. Many P0/P1 items are now implemented.

- Completed highlights:
  - Artifact fetch abstraction with S3 support, allowlist checks, retries/backoff, and cache eviction controls.
  - Idempotency keys + lifecycle locking on activate/promote/rollback/pause.
  - Request correlation ID propagation and tracked job runs.
  - Read-session plumbing and routing for selected monitoring/reporting endpoints.
  - Retention preview/apply + anonymization + export job workflows with signed downloads.
  - Canary percentage controls and auto-stop guardrails.
  - Auth provider pluggability with local/OIDC/SAML bridge support.
  - CI smoke workflow added (`.github/workflows/backend-smoke.yml`).

Remaining items are mostly enterprise-scale validation (load/chaos evidence, deeper integration tests, and process maturity).

---

## P0 - Fastest path to major maturity gains

### 1) Artifact storage abstraction (filesystem + object storage)
- [x] Create `ArtifactStore` interface in backend services layer:
  - `exists(uri)`, `fetch_to_local(uri)`, `sha256(uri)`, `list(uri_prefix)`.
- [x] Implement providers:
  - Local FS provider
  - S3-compatible provider (works for R2/S3)
- [x] Refactor fraud/care model loading to call `ArtifactStore` instead of direct `Path(...)` assumptions.
- [x] Add local artifact cache with TTL + max size controls.
- [x] Add integrity check: verify downloaded artifact hash against model registry lineage hash before activation/use.

**Done when:** `artifact_uri` works for `file://`, relative path, and `s3://...` in scoring/training paths.

---

### 2) Idempotent, safe model lifecycle operations
- [x] Add idempotency keys for critical admin actions:
  - activate, promote, rollback, cutover execute, tenant fine-tune start.
- [~] Add optimistic locking/version check on `model_registry` and `tenant_mappers` rows during status transitions.
- [~] Add explicit lifecycle state machine guardrails:
  - forbid invalid transitions (example: disabled -> active without promote/activate flow).
- [x] Add transactional audit envelope:
  - every lifecycle mutation must include one audit event with request id and actor.

**Done when:** repeated clicks/retries cannot create inconsistent active model/mapper states.

---

### 3) Mapper/contract compatibility enforcement
- [ ] On model activation, enforce:
  - active mapper exists,
  - mapper contract matches model contract,
  - mapper version referenced by model exists for same tenant/model_type.
- [ ] Remove hardcoded `mapper-v0` from fine-tune auto-row creation:
  - require explicit mapper version or infer current active mapper version safely.
- [ ] Add "pre-activate validation" endpoint returning actionable errors.

**Done when:** a model cannot become active with broken mapper lineage.

---

### 4) Unified background job framework + retry policy
- [x] Wrap all jobs (guardrails, challenger evaluator, cutover, finetune scout, KPI snapshots) with:
  - standard retry policy,
  - bounded exponential backoff,
  - dead-letter/error recording.
- [~] Add distributed lock per job key to avoid duplicate overlapping runs.
- [x] Persist job run records in DB (`job_runs` table) with status, duration, error summary, correlation id.

**Done when:** every scheduled/manual job has deterministic status history and safe retries.

---

### 5) Security hardening in code paths
- [ ] Enforce secret redaction globally in logs (token/password/api key/artifact credentials).
- [ ] Add strict request size limits for upload and admin endpoints.
- [ ] Add structured allowlist validation for webhook URLs and artifact URIs.
- [ ] Add per-route rate limit policies for admin write endpoints (stricter than read endpoints).
- [ ] Add anti-replay protection for critical webhooks/admin actions (nonce/timestamp window).

**Done when:** common abuse vectors are blocked at app layer.

---

## P1 - High-value scale/compliance tasks

### 6) Observability standardization (logs, metrics, traces)
- [ ] Add request correlation id middleware (`X-Request-ID`) and propagate across tasks/audit events.
- [ ] Emit structured JSON logs everywhere (single schema).
- [ ] Add OpenTelemetry spans for:
  - score request
  - model routing decision
  - artifact fetch/load
  - calibration apply
  - cutover checks
- [ ] Add Prometheus-style metrics:
  - route_source counters
  - model load latency
  - fallback rate
  - activation failures
  - job success/failure rates.

**Done when:** one request/job can be traced end-to-end with consistent IDs.

---

### 7) Read scaling and query isolation
- [x] Implement read-replica routing in DB layer:
  - monitoring/reporting/audit list endpoints use replica session when configured.
- [x] Mark write-critical endpoints as primary-only.
- [~] Add fallback behavior if replica unhealthy (with circuit breaker + warning logs).

**Done when:** heavy reads can move off primary with safe fallback.

---

### 8) Data retention + compliance workflows
- [x] Add retention policy jobs for:
  - inference traces
  - raw training uploads
  - stale artifacts
  - transient feature payloads.
- [x] Add tenant-scoped delete/anonymize workflow for regulated requests.
- [~] Add immutable audit export endpoint/package (hash + manifest) for compliance reviews.

**Done when:** data lifecycle is explicit and automatable.

---

### 9) Safer rollout strategy in code
- [x] Add progressive rollout support:
  - canary percentage by tenant/model_type
  - auto-stop on KPI breach.
- [~] Add shadow-vs-champion quality gates as reusable policy module.
- [~] Add emergency kill switch per tenant/model route.

**Done when:** deployments can be gradual and reversible without manual DB edits.

---

### 10) Stronger training lineage and reproducibility
- [ ] Capture full lineage object for every model row:
  - dataset hash/version,
  - code commit SHA,
  - mapper version,
  - feature contract,
  - artifact hash,
  - trainer parameters.
- [ ] Add reproducibility endpoint: "show exact inputs that created model X".
- [ ] Enforce lineage completeness before activation in strict mode.

**Done when:** any active model can be fully reconstructed and audited.

---

## P2 - Final 10/10 polish

### 11) Enterprise auth integration layer
- [x] Add pluggable identity provider adapter:
  - local auth (existing),
  - OIDC/SAML provider mode hooks.
- [~] Map external claims/groups to internal platform roles + tenant scopes.
- [~] Add session hardening:
  - token rotation,
  - optional device/session binding,
  - step-up auth for dangerous actions (activate/cutover).

---

### 12) Configuration governance
- [ ] Add startup config validator with fatal errors for unsafe combinations in production mode.
- [ ] Add machine-readable config policy profile:
  - `baseline`, `hardened`, `strict_compliance`.
- [ ] Add endpoint to report current policy profile + violations.

---

### 13) Test coverage upgrades (critical path)
- [ ] Add integration tests for full lifecycle:
  - mapper create/validate/activate
  - model create/activate/rollback/promote
  - cutover gate pass/fail cases
  - guardrails rollback
  - challenger promotion.
- [ ] Add chaos/failure tests:
  - missing artifact
  - corrupted artifact
  - replica unavailable
  - duplicate activation race.
- [ ] Add contract tests for external payload schemas per model_type.

---

### 14) Developer/operator UX
- [ ] Add "Preflight diagnostics" panel in UI:
  - exact blockers for activation/cutover with fix suggestions.
- [ ] Add one-click "validate tenant readiness" action.
- [ ] Add richer activity timeline combining model, mapper, calibration, cutover events.

---

## Stage scoring rubric (code-only)

Use this to track movement to 10/10:

### Stage 1 (Baseline production)
- [ ] Core auth/rbac stable
- [ ] Multi-tenant routing deterministic
- [ ] Safe activation/rollback semantics
- [ ] Minimal observability and audit completeness

### Stage 2 (Production hardening)
- [ ] Guardrails + challenger jobs reliable
- [ ] Calibration + mapper validation enforced
- [ ] Alert and webhook safety controls
- [ ] Operational dashboards trustworthy

### Stage 3 (Scale/compliance)
- [ ] Artifact abstraction and integrity checks
- [ ] Read scaling + retention + immutable audit export
- [ ] Progressive rollout and strong lineage
- [ ] Enterprise identity and policy profiles

---

## Suggested execution plan (fastest)

### Sprint A (P0 only, highest ROI)
- [ ] Items 1, 2, 3, 4, 5

### Sprint B (scale readiness)
- [ ] Items 6, 7, 8, 9, 10

### Sprint C (finish to 10/10)
- [ ] Items 11, 12, 13, 14

If you complete Sprint A + B cleanly, Stage 3 should move close to 9/10. Sprint C closes remaining enterprise/compliance gaps.

