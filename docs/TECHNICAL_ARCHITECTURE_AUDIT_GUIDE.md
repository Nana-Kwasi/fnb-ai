# Technical Architecture & Audit Guide

This document is for developers, security reviewers, and auditors.

## 1) System Scope

- **Frontend:** Admin console (React)
- **Backend:** FastAPI (`/api/v1/*`)
- **Data:** Postgres primary + optional read replica, Redis
- **Model artifacts:** local filesystem and S3-compatible paths

## 2) Core Backend Domains

- **Fraud scoring APIs:** tenant-scoped via `X-API-Key`
- **Admin APIs:** platform roles (`owner|editor|viewer`) via JWT
- **Model lifecycle:** registry, mapper, calibration, promotion/rollback/pause
- **Compliance APIs:** retention, anonymization, export jobs + signed downloads

## 3) Auth Model

- **Tenant runtime APIs:** `X-API-Key`
- **Platform admin APIs:** `Authorization: Bearer <platform_jwt>`
- **Legacy:** `X-Admin-Token` only if explicitly enabled
- **Provider abstraction:** local + OIDC + SAML bridge integration path

## 4) Lifecycle Safety Controls

- Idempotency keys on critical model registry state mutations
- Concurrency locking for lifecycle mutation safety
- Integrity verification of artifacts before activation/promote/rollback
- Audit logging with request correlation context

## 5) Data Governance Controls

- Tenant-scoped retention preview and apply flows
- Tenant anonymization workflow (dry-run and apply)
- Tenant export jobs with signed URL download flow
- Job run persistence for operational traceability

## 6) Progressive Rollout Controls

- Canary percentage by model entry
- Auto-stop behavior when disagreement thresholds breach policy
- Champion/challenger monitoring endpoints

## 7) Read/Write Separation

- Primary DB used for write-critical paths
- Read session path used for selected heavy monitoring/reporting endpoints
- Replica URL configurable via environment

## 8) Operational Maturity Artifacts

- `docs/ops/SLO_SLI_CATALOG.md`
- `docs/ops/RELEASE_GATES.md`
- `docs/ops/RUNBOOKS.md`
- `docs/ops/ONCALL_PLAYBOOK.md`
- `docs/ops/CHAOS_DRILLS.md`

## 9) Audit Checklist (Quick)

- [ ] Verify auth mode and legacy token setting in environment
- [ ] Verify production policy profile + hardening flags
- [ ] Verify active model/mapper lineage and artifact integrity
- [ ] Verify retention/anonymization/export workflow evidence
- [ ] Verify recent job runs and alerting posture
- [ ] Verify release gate evidence is attached per deployment

## 10) Evidence to Collect

- API logs with request IDs for sampled transactions
- Model registry changes + audit events for releases
- Job run history for guardrails/challenger/compliance jobs
- Signed export/download flow evidence (creation + retrieval)
- CI smoke run results and test summaries

