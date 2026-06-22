# On-Call Playbook

## First 15 Minutes

1. Declare incident severity and owner.
2. Confirm blast radius: tenant(s), model type, APIs affected.
3. Freeze risky changes (new activations/cutovers).
4. Start timeline log.
5. Execute matching runbook from `RUNBOOKS.md`.

## Alert Routing Matrix

- **Critical**: Pager + Slack + Incident channel
- **High**: Slack + owner page if unresolved 10 min
- **Medium**: Slack only, triage within business SLA

## Triage Checklist

- Is this auth, model lifecycle, scoring, export, or infra?
- Any tenant isolation breach indicators?
- Can we rollback safely now?
- Is customer-facing comms required?

## Communication Template

- **What happened**
- **Who is impacted**
- **Current mitigation**
- **Next update ETA**

## Closure Checklist

- Incident timeline finalized.
- Root cause and contributing factors documented.
- Action items created with owners and due dates.
- Follow-up chaos drill scheduled if needed.
