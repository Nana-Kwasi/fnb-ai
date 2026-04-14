# Infrastructure Services Help (Non-Technical)

This document explains the services used with this project in plain language:
- what each service does,
- why we need it,
- and where each one fits in a full production maturity path.

## Big picture

Think of the platform like running a digital bank operations center:

- The **application server** is the office where work happens.
- The **database** is the filing room where records are stored.
- **Model files** are instruction manuals used by fraud/care AI.
- **Monitoring and alerts** are your smoke alarms and security cameras.

This project has three maturity layers:
- **Baseline production (must-have):** enough to run live safely.
- **Production hardening (strongly recommended):** improves reliability and operational control.
- **Scale/compliance maturity (advanced):** supports bigger tenant counts and stricter enterprise controls.

## Baseline production (must-have)

### 1) Render
- **What it is:** Where your app runs online.
- **In this project:** Hosts the backend API (and optionally frontend) and can host managed Postgres.
- **Why we need it:** Without hosting, your app only runs on your laptop.
- **Required now?** Yes (if you want live/public environment).

### 2) Postgres database (often Render Postgres)
- **What it is:** Main storage for banks, users, model registry, mapper configs, scores, outcomes, audit logs.
- **In this project:** Set through `DATABASE_URL`.
- **Why we need it:** This is the single source of truth for live data.
- **Required now?** Yes.

### 3) Redis (example: Upstash Redis)
- **What it is:** Fast temporary data store.
- **In this project:** Used for caching/rate-limit/background support via `REDIS_URL`.
- **Why we need it:** Keeps app responsive and supports operational tasks.
- **Required now?** Yes for production-grade behavior.

### 4) Secret key
- **What it is:** Private cryptographic key.
- **In this project:** `SECRET_KEY` signs/verifies auth tokens and security signatures.
- **Why we need it:** Without it, authentication and token trust are unsafe.
- **Required now?** Yes.

## Production hardening (recommended)

### 5) Cloudflare R2 (or S3/GCS)
- **What it is:** Cloud file storage for large files.
- **In this project:** Store model artifacts (fraud/care model files), training exports, report files.
- **Why we need it:** Model files should not depend on one laptop disk.
- **Required now?** Strongly recommended for production.

Important note:
- The database stores **references** (`artifact_uri`) to model files.
- The model files themselves are stored in file storage/disk, not as rows inside Postgres.

## Monitoring and reliability (production hardening)

### 6) Sentry
- **What it is:** Error tracking system.
- **In this project:** Captures app crashes and failures with stack traces.
- **Why we need it:** Lets the team quickly find and fix issues.
- **Required now?** Strongly recommended.

### 7) Better Stack
- **What it is:** Logs, monitoring, and incident tooling.
- **In this project:** Central place to search logs and set alert rules.
- **Why we need it:** Easier debugging than checking one server console at a time.
- **Required now?** Recommended.

### 8) UptimeRobot
- **What it is:** Website/API uptime checker.
- **In this project:** Pings health endpoints and alerts when app is down.
- **Why we need it:** Confirms availability from outside your server.
- **Required now?** Recommended.

### 9) Instatus
- **What it is:** Public status page.
- **In this project:** Communicate uptime and incidents to users/clients.
- **Why we need it:** Transparent communication during outages.
- **Required now?** Optional (helpful for customer communication).

## Product and user operations (maturity enhancements)

### 10) PostHog
- **What it is:** Product analytics.
- **In this project:** Track how users use onboarding, model registry, reports, etc.
- **Why we need it:** Shows friction points and adoption.
- **Required now?** Optional.

### 11) Resend
- **What it is:** Transactional email service.
- **In this project:** Send notifications, reports, and possible auth-related emails.
- **Why we need it:** Reliable outbound email delivery.
- **Required now?** Optional (required if your workflows depend on email notices).

## Authentication options (enterprise maturity)

### 12) Clerk
- **What it is:** Managed auth platform.
- **In this project:** Could replace/augment custom login and user session handling.
- **Why we need it:** Faster auth setup with MFA/session tools.
- **Required now?** Optional.

### 13) Auth0
- **What it is:** Enterprise authentication and SSO.
- **In this project:** Alternative to Clerk for enterprise identity.
- **Why we need it:** Useful for B2B SSO and enterprise compliance paths.
- **Required now?** Optional.

## Workflow orchestration (scale maturity)

### 14) Prefect
- **What it is:** Workflow/scheduler engine.
- **In this project:** Can orchestrate retraining, drift checks, guardrails, and cutover jobs.
- **Why we need it:** Improves reliability and visibility of background jobs.
- **Required now?** Optional (valuable as operations grow).

## Environment variables referenced in this project

### `SECRET_KEY`
- **Meaning:** Security key used to sign auth tokens.
- **Plain language:** A private seal that proves tokens were issued by your app.
- **Set in production?** Yes.

### `ALERT_WEBHOOK_URL`
- **Meaning:** URL where operational alerts are sent.
- **Plain language:** The phone number your system calls when something is wrong.
- **Set in production?** Recommended; may be required if strict production checks are enabled.

### `READ_REPLICA_DATABASE_URL`
- **Meaning:** Read-only database connection for heavy read/report traffic.
- **Plain language:** A copy of your filing room for reading only, so the main room stays fast for writes.
- **Set in production?** Optional initially; recommended later at scale.

## Full production maturity roadmap

### Stage 1 - Baseline production (must-have)
- Render (app)
- Render Postgres (database)
- Upstash Redis
- Strong `SECRET_KEY`

### Stage 2 - Production hardening (strongly recommended)
- + R2 (artifact storage)
- + Sentry
- + UptimeRobot or Better Stack
- + `ALERT_WEBHOOK_URL`

### Stage 3 - Scale/compliance maturity (advanced)
- + Better Stack logs/alerts
- + PostHog
- + read replica (`READ_REPLICA_DATABASE_URL`)
- + Prefect for robust workflow orchestration

## Implementation notes (current code)

The current codebase already includes:
- model lifecycle idempotency controls (`Idempotency-Key` on critical registry state changes),
- artifact hardening (allowlist, retries/backoff, cache controls),
- read-session routing for selected monitoring/reporting queries,
- tenant compliance controls (retention preview/apply, anonymization, export jobs + signed downloads),
- progressive rollout controls (canary percentage + auto-stop),
- auth provider pluggability (local + OIDC + SAML bridge paths).

## Final takeaway

If you want one clear rule:
- **Baseline production:** Render + Postgres + Redis + `SECRET_KEY`.
- **Production hardening:** add artifact storage + monitoring + alerting.
- **Full maturity:** add analytics, workflow orchestration, and read scaling/compliance controls.

