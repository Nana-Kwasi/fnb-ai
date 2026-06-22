# API Conventions

Use these rules for all docs and examples in this repository.

## 1) Path style

- Always show full API paths with version prefix:
  - Good: `POST /api/v1/fraud/score`
  - Avoid: `POST /score`
- Admin routes must include full prefix:
  - `GET /api/v1/admin/...`

## 2) Auth/header style

- **Tenant fraud/care APIs**
  - Header: `X-API-Key: <tenant_api_key>`
- **Platform admin APIs**
  - Header: `Authorization: Bearer <platform_jwt>`
  - Legacy `X-Admin-Token` only if `ADMIN_LEGACY_TOKEN_AUTH=true`

## 3) Decision vocabulary (fraud)

Use only current decision labels:

- `APPROVE`
- `LIMITED_APPROVAL`
- `REQUEST_OTP`
- `SOFT_DECLINE`
- `BLOCK`

Do not use deprecated wording like generic `REVIEW`/`DECLINE` unless explicitly mapped.

## 4) Endpoint example format

When documenting endpoints, use one of:

- Inline: ``POST /api/v1/admin/training/upload``
- Table columns:
  - `Method`
  - `Path`
  - `Purpose`
  - optional `Auth`

## 5) Query parameter style

- Show query params explicitly in examples:
  - `GET /api/v1/admin/monitoring/challenger-policy?tenant_id=<id>`
- Use placeholders consistently:
  - `<tenant_id>` for UUID
  - `<job_id>` for UUID
  - `<model_type>` for `fraud|care`

## 6) Compatibility notes

If a legacy route still exists, mark clearly:

- **Legacy (compatibility path):** `POST /api/v1/admin/trigger-fraud-train`

and always include the preferred replacement route(s).

## 7) Documentation quality gate

Before merging docs:

1. Paths include `/api/v1/...`
2. Auth header is shown for each endpoint group
3. Fraud decisions use current labels
4. Legacy routes are labeled as compatibility
