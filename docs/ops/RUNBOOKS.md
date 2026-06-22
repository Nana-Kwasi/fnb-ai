# Runbooks (Operator Ready)

Use this as the incident execution guide. Keep steps short, exact, and verifiable.

## 1) Auth Incident (OIDC/SAML failure)

- **Trigger signals**
  - Spike in `401/403` across admin routes.
  - Login success drops below SLO.
- **Immediate actions**
  - Confirm `AUTH_PROVIDER`, `OIDC_*` / `SAML_*` env values on live service.
  - Validate token issuer/audience against config.
  - If provider outage: temporarily switch to controlled fallback (`local`) only if approved by incident commander.
- **Verification**
  - `/api/v1/auth/login` success restored for test user.
  - `/api/v1/auth/me` returns expected role and tenant scope.
- **Escalation**
  - Identity owner -> Platform lead -> Security owner.

## 2) Model Rollback Emergency

- **Trigger signals**
  - Guardrail breach (`block/otp/disagree/escalation` thresholds exceeded).
  - Customer-impact alert from fraud/care KPIs.
- **Immediate actions**
  - Run rollback endpoint on affected tenant/model.
  - Confirm active model version changed in registry.
  - Pause challenger/canary on impacted tenant.
- **Verification**
  - Decision distribution returns to baseline window.
  - Error and disagreement rates trend down within 30 min.
- **Escalation**
  - ML owner -> Incident commander -> Risk/compliance owner.

## 3) Canary Auto-Stop Override

- **Trigger signals**
  - Canary auto-stop engaged repeatedly.
  - Canary stuck at 0% after policy adjustment.
- **Immediate actions**
  - Check canary thresholds and recent compare volume.
  - Set per-model `canary_percent` explicitly and re-evaluate.
  - Keep auto-stop enabled; do not disable without explicit approval.
- **Verification**
  - Champion stable and challenger comparison metrics healthy.
- **Escalation**
  - ML owner + SRE owner.

## 4) Export Pipeline Stuck Jobs

- **Trigger signals**
  - Export jobs remain `queued/running` beyond SLA.
- **Immediate actions**
  - Inspect job record and artifact path.
  - Retry failed job once; cancel duplicates.
  - Validate signed download endpoint and artifact existence.
- **Verification**
  - Job transitions to `done`, signed URL downloads artifact.
- **Escalation**
  - Reporting owner -> Backend owner.

## 5) Retention/Anonymization Legal Request

- **Trigger signals**
  - Tenant compliance request ticket.
- **Immediate actions**
  - Run retention preview (dry run), capture output.
  - Run apply with approved retention period.
  - Run anonymization dry run then apply (if enabled/approved).
- **Verification**
  - Audit log present with actor, tenant, counts, timestamp.
  - Post-run spot checks pass.
- **Escalation**
  - Compliance owner -> Legal -> Platform owner.
