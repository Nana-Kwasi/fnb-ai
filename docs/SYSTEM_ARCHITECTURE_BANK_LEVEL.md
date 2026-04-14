# System Architecture Diagram (Bank-Level)

## Clean Architecture View

```mermaid
flowchart LR
    subgraph Channels["Bank Channels"]
        Mobile["Mobile App"]
        Web["Internet Banking"]
        Ops["Bank Ops Console"]
    end

    subgraph Integration["Integration Layer"]
        Gateway["Bank Payment Gateway / Middleware"]
        FE["BankAI Admin Frontend"]
    end

    subgraph Platform["BankAI Platform"]
        API["FastAPI Services (/api/v1/*)"]
        Auth["Platform Auth (JWT + OIDC/SAML bridge)"]
        Router["Model Router (tenant/global/canary/fallback)"]
        Fraud["Fraud Engine"]
        Care["Care Engine"]
        Admin["Admin + Compliance APIs"]
    end

    subgraph Data["Data Plane"]
        Primary["Primary Postgres"]
        Replica["Read Replica Postgres"]
        Cache["Redis"]
        Artifact["Artifact Store (local/S3-compatible)"]
    end

    subgraph Governance["Ops + Governance"]
        Jobs["Scheduled/Manual Jobs"]
        Mon["Monitoring + Job Runs + Alerts"]
        Runbooks["Runbooks / SLOs / Release Gates"]
    end

    Mobile --> Gateway
    Web --> Gateway
    Ops --> Gateway
    Gateway -->|X-API-Key| API
    FE -->|Bearer JWT| API

    API --> Auth
    API --> Router
    Router --> Fraud
    Router --> Care
    API --> Admin

    Fraud --> Primary
    Care --> Primary
    Admin --> Primary
    API --> Replica
    API --> Cache
    Router --> Artifact
    Fraud --> Artifact
    Care --> Artifact

    Jobs --> Primary
    Jobs --> Artifact
    Jobs --> Mon
    Mon --> Runbooks
```

## What This Means (Non-Technical)

- Bank channels send transactions through the bank gateway to BankAI.
- BankAI decides risk in real time using tenant-specific routing and models.
- Core records live in Postgres; heavy reads can go to a replica.
- Model files are stored in artifact storage (not inside DB rows).
- Governance jobs continuously protect quality (guardrails, challenger checks, retention/export controls).
