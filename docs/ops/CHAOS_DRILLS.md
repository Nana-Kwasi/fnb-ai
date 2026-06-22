# Chaos Drills

Run monthly. Every drill must have: hypothesis, blast radius, abort criteria, evidence, and follow-up owner.

## Drill Matrix

1. **DB primary failover during live traffic**
- Expected: write path recovers without data loss.
- Pass: recovery < 5 min, no permanent failed writes.

2. **Read replica lag spike**
- Expected: read endpoints degrade gracefully; no unsafe decisions.
- Pass: fallback behavior is observable and bounded.

3. **Object storage latency/outage**
- Expected: artifact cache prevents immediate scoring failure.
- Pass: p95 latency within defined emergency budget; errors alert quickly.

4. **Redis unavailable**
- Expected: non-critical features degrade; core scoring continues.
- Pass: no total outage.

## Drill Template

- **Date**
- **Scenario**
- **Systems touched**
- **Traffic profile**
- **Abort criteria**
- **Outcome vs SLO**
- **Evidence links** (dashboards, logs, traces)
- **Action items** (owner + due date)

## Required Evidence

- Pre/post SLI snapshots.
- Incident timeline (minute-by-minute).
- Customer impact estimate.
- Remediation PR/issue links.
