# Platform auth — production checklist

See also **[ops-governance-rollout.md](./ops-governance-rollout.md)** for strict flags, isolation, calibration, pooled training, and Phase 4 automation.

## What this repo implements

- DB-backed `platform_users` + `platform_user_tenants` (Alembic `011`)
- bcrypt password hashes, JWT (`HS256`, `SECRET_KEY`) for admin API calls
- Roles: `owner` | `editor` | `viewer` with tenant scoping for non-owners
- Owner: all banks + bank picker; assigned users: 0 / 1 / N banks → modal only when needed
- Forced password change (`must_change_password`) after owner-created users log in
- Legacy `X-Admin-Token` optional (`ADMIN_LEGACY_TOKEN_AUTH`) for break-glass / scripts
- Audit hooks on existing admin_config events (extend with `LOGIN_SUCCESS` / `LOGIN_FAIL` when you add rate limiting)

## Not “world-class production” yet (typical gaps)

- **No full MFA / WebAuthn end-to-end flow yet**.
- **OIDC/SAML provider hooks are implemented** in code; production-grade identity governance (group-to-role policy, session inventory, advanced step-up controls) still needs completion.
- **No refresh tokens / rotation** — access JWT is long-lived (configurable). Prefer short access + opaque refresh in HTTP-only cookie.
- **No login rate limit / lockout / CAPTCHA** — add reverse-proxy + app-level limiter on `/auth/login`.
- **bcrypt vs Argon2id** — Argon2id is often preferred for new systems; migration is optional.
- **Email verification & password reset via email** — not implemented (reset is owner-driven or change-password while logged in).
- **Session inventory / remote logout** — not implemented.
- **PII in logs** — avoid logging emails on failed auth in shared log stacks.
- **HTTPS-only cookies** if you move JWT to cookies — set `Secure`, `SameSite`, CSRF strategy for cookie auth.
- **Pen test + threat model** — required for regulated environments.

## Bootstrap owner (do not commit real passwords)

1. Run migrations: `alembic upgrade head`
2. In `backend/.env` set **once**:

   `PLATFORM_BOOTSTRAP_OWNER_EMAIL`  
   `PLATFORM_BOOTSTRAP_OWNER_PASSWORD`

3. Restart API — user row is created if the table was empty.
4. Remove or blank bootstrap password from `.env` after confirming you can log in and mint other owners (optional hardening).

Never commit your personal email + password; use secrets manager in real deployments.
