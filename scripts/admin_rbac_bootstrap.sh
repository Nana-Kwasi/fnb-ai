#!/usr/bin/env bash
# Mint RBAC tokens with env bootstrap (ADMIN_WRITE_TOKEN). Owner-only revoke after.
set -euo pipefail
BASE="${BASE_URL:-http://localhost:8000}"
BOOT="${1:-${ADMIN_WRITE_TOKEN:-}}"
if [[ -z "$BOOT" ]]; then
  echo "Set ADMIN_WRITE_TOKEN or: $0 <bootstrap_raw_token>"
  exit 1
fi

hdr=(-H "X-Admin-Token: $BOOT")

echo "=== create owner (save token output) ==="
curl -sS -X POST "$BASE/api/v1/admin/rbac/tokens/create" "${hdr[@]}" \
  -F "name=owner-primary" -F "role=owner"
echo
echo "=== optional editor ==="
curl -sS -X POST "$BASE/api/v1/admin/rbac/tokens/create" "${hdr[@]}" \
  -F "name=editor-ops" -F "role=editor"
echo
echo "=== optional viewer ==="
curl -sS -X POST "$BASE/api/v1/admin/rbac/tokens/create" "${hdr[@]}" \
  -F "name=viewer-readonly" -F "role=viewer"
echo
echo "=== revoke bootstrap (after UI uses new owner token) ==="
echo "curl -sS -X POST \"$BASE/api/v1/admin/rbac/tokens/revoke\" -H \"X-Admin-Token: <NEW_OWNER>\" -F \"token_id=bootstrap\""
echo "Then remove ADMIN_WRITE_TOKEN from .env and restart API (optional)."
