# Admin RBAC — route → role

Prefix: `/api/v1/admin`. Prefer **`Authorization: Bearer <JWT>`** from `POST /api/v1/auth/login`. Legacy: `X-Admin-Token` if `ADMIN_LEGACY_TOKEN_AUTH=true`.

| Min role | Method | Path |
|----------|--------|------|
| **viewer+** | GET | `/monitoring/fraud-drift` |
| **viewer+** | GET | `/training/fraud/model-lifecycle` |
| **viewer+** | GET | `/audit/config-changes` |
| **viewer+** | GET | `/monitoring/fraud-drift-status` |
| **viewer+** | GET | `/monitoring/fraud-drift-alerts` |
| **editor+** | PATCH | `/training/care/retrain-reco-config` |
| **editor+** | POST | `/training/care/retrain-reco-config/reset` |
| **editor+** | PATCH | `/tenants/{tenant_id}/fraud-policy` |
| **editor+** | POST | `/training/fraud/model-lifecycle/register-challenger` |
| **editor+** | POST | `/training/fraud/model-lifecycle/promote-challenger` |
| **editor+** | POST | `/training/fraud/model-lifecycle/rollback` |
| **owner** | GET | `/rbac/tokens` |
| **owner** | POST | `/rbac/tokens/create` |
| **owner** | POST | `/rbac/tokens/rotate` |
| **owner** | POST | `/rbac/tokens/revoke` |

**Not in this table:** other `/api/v1/admin/*` routes (onboard, uploads, training trigger, fraud-train-status, etc.) may use different role guards — check `admin.py` for current handler-level enforcement.

**Bootstrap:** `ADMIN_WRITE_TOKEN` in env behaves like an **owner** token (`token_id=bootstrap`) until revoked.
