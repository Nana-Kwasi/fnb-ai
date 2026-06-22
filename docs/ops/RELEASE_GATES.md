# Release Gates

A release is blocked unless all gates pass.

## Gate 1: Code + Test Health

- Backend smoke workflow green.
- Unit/integration suites pass.
- No critical lint/type errors.

## Gate 2: Model Lifecycle Safety

- Idempotency + lock tests pass.
- Rollback path tested on staging in current release cycle.
- Canary policy + auto-stop settings validated.

## Gate 3: Performance + Capacity

- Latest load test report attached.
- Peak and 2x burst profile within SLO budgets.
- No unresolved saturation hotspot above threshold.

## Gate 4: Compliance Operations

- Retention preview/apply tested on staging.
- Anonymization flow tested (dry run + controlled apply).
- Export signing/download tested with expiry.

## Gate 5: Operational Readiness

- Runbook links attached to release.
- On-call owner acknowledged release window.
- Rollback commander assigned.

## Required Artifacts Per Release

- Test report
- Load/chaos evidence
- Risk notes
- Approval list (engineering, SRE, compliance for sensitive releases)
