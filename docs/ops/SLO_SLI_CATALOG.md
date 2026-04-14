# SLO / SLI Catalog

Define these as release gates. If unmet, do not promote.

## Core API

- **SLI:** request success rate (`2xx/3xx`)
  - **SLO:** >= 99.9% (30-day rolling)
- **SLI:** p95 latency (admin + scoring APIs)
  - **SLO:** <= 500ms steady state

## Scoring Path

- **SLI:** scoring success rate
  - **SLO:** >= 99.95%
- **SLI:** model route fallback rate
  - **SLO:** <= 0.5% (except declared incident windows)

## Lifecycle Operations

- **SLI:** activation/rollback endpoint success
  - **SLO:** >= 99.9%
- **SLI:** idempotent replay correctness
  - **SLO:** 100% in test suite

## Export/Compliance

- **SLI:** export job completion within SLA
  - **SLO:** >= 99% within 10 min
- **SLI:** retention/anonymization audit completeness
  - **SLO:** 100% with actor/tenant/count/timestamp

## Alerting

- **SLI:** critical alert delivery success
  - **SLO:** >= 99.9%
- **SLI:** false-positive ratio
  - **SLO:** <= 15%
