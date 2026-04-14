# Ops Docs Index

Use this folder as the operational source of truth for production readiness.

## Read in this order

1. `SLO_SLI_CATALOG.md`  
   Define what "healthy" means and what must be measured.
2. `RELEASE_GATES.md`  
   Defines deployment blockers and mandatory evidence.
3. `RUNBOOKS.md`  
   Exact response steps for common high-impact incidents.
4. `ONCALL_PLAYBOOK.md`  
   First-15-minute triage and communication flow.
5. `CHAOS_DRILLS.md`  
   Scheduled resilience validation and evidence requirements.

## Operating cadence

- **Every release:** enforce `RELEASE_GATES.md`.
- **Weekly:** review SLI trend drift and noisy alerts.
- **Monthly:** run one chaos drill and log outcomes.
- **Quarterly:** run game day and update runbooks.

## Minimum artifact pack per release

- Test report (unit/integration/smoke)
- Load or capacity evidence
- Rollback plan validation
- Compliance workflow verification (retention/export/anonymization)
