# Bank Integration Pack

One-page reference for banks integrating with the BankAI Fraud API.

## What We Provide

- **API base URL**: Production URL (e.g. `https://api.bankai.example.com`) and optional sandbox.
- **API key**: Per-bank key delivered at onboarding; used in every request via the `X-API-Key` header.
- **Integration steps**: Onboarding creates a tenant; you receive a `bank_id` (UUID) and a single API key. All fraud and (if enabled) care endpoints are scoped to that tenant.

## What the Bank Sends (per transaction)

**Endpoint**: `POST /api/v1/fraud/score` (or `/score/detail` for full breakdown).

**Headers**: `X-API-Key: <your_key>`, `Content-Type: application/json`.

**Body** (minimal): `transaction_id`, `account_id`, `amount`, `currency`, `timestamp`. Optional: `merchant_category`, `location` (country code), `device_id`, `ip_address`, `channel`.

We use this to compute velocity, device/location novelty, and (when available) fingerprint and network features.

## Response and Behaviour

- **Response**: JSON with `decision` (`APPROVE` / `REVIEW` / `DECLINE`), `risk_score` (0.0–1.0), `reasons` (list of human-readable rule/model reasons), and optional SHAP/breakdown fields for `/score/detail`.
- **Outcomes**:  
  - **APPROVE**: Proceed with the transaction.  
  - **REVIEW**: Often used when score is between OTP and block thresholds; bank may require OTP or step-up.  
  - **DECLINE**: Score above block threshold; bank should block the transaction.
- Thresholds (block vs OTP vs approve) are configurable per tenant (see below).

## Who Sets Thresholds and Rules

- **Per-tenant policy**: Block threshold, OTP threshold, model/ISO/rule/network weights, and shadow mode are set via the **Admin API** for each tenant (`GET/PATCH /api/v1/admin/tenants/{tenant_id}/fraud-policy`). Typically used by platform ops or the bank’s integration owner.
- **Rules**: Global rules (e.g. velocity, new device + amount, high-risk country, fingerprint velocity, device ring) are seeded by the platform. Tenant-specific rules can be added in the `fraud_rules` table with that tenant’s ID. Rule conditions use the same feature names as the engine (e.g. `txn_count_1h`, `amount_threshold`, `suspicious_countries`).

## Optional: Outcomes and Retraining

- **Fraud outcomes**: Analysts or chargeback data can be recorded in `fraud_outcomes` (e.g. CONFIRMED_FRAUD, FALSE_POSITIVE) to improve future models.
- **Retraining**: Ops can trigger a fraud model retrain on demand via `POST /api/v1/admin/trigger-fraud-train`. The job runs in the background; the request returns immediately.

## Dashboard

The Fraud dashboard is scoped to the bank whose API key is used. When you paste your key in the UI, the header shows “Viewing data for key: ***xxxx” (last 4 characters) so it is clear which tenant’s data you are viewing.
