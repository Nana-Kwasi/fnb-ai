# Test care API: general chat, intents, out-of-scope. Backend must be running.
# Usage: cd backend && BANKAI_API_KEY=key python scripts/test_care.py
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("BANKAI_API_KEY", "").strip()
TIMEOUT = 30


def req(path, method="GET", body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=TIMEOUT) as res:
        return res.getcode(), json.loads(res.read().decode())


def main():
    key = API_KEY
    if not key:
        print("Onboarding...")
        code, data = req("/api/v1/admin/onboard", "POST", {"name": "Test Bank", "country_code": "GH"})
        if code != 200:
            print("FAIL onboard:", code, data)
            sys.exit(1)
        key = data.get("api_key")
        print("OK  api_key:", key[:20] + "...")

    sid = "sess-care-" + datetime.now(timezone.utc).strftime("%H%M%S")
    cid = "cust-test-001"

    cases = [
        ("hello", lambda d: "hi" in (d.get("response") or "").lower()),
        ("what can you do", lambda d: "balance" in (d.get("response") or "").lower()),
        ("What is my balance?", lambda d: d.get("intent") == "BALANCE_INQUIRY"),
        ("fraudulent charge", lambda d: d.get("intent") == "FRAUD_DISPUTE"),
        ("block my card", lambda d: d.get("intent") == "CARD_BLOCK"),
        ("what is the capital of france", lambda d: "virtual assistant" in (d.get("response") or "").lower()),
    ]
    failed = []
    for msg, check in cases:
        try:
            code, data = req("/api/v1/care/chat", "POST", {"session_id": sid, "customer_id": cid, "message": msg, "channel": "mobile_app"}, {"X-API-Key": key})
            if code != 200:
                failed.append((msg, f"HTTP {code}"))
            elif not check(data):
                failed.append((msg, f"intent={data.get('intent')} resp={(data.get('response') or '')[:50]}"))
            else:
                print("OK", msg[:40], "->", data.get("intent"), (data.get("response") or "")[:50] + "...")
        except Exception as e:
            failed.append((msg, str(e)))
    if failed:
        print("FAILED:", failed)
        sys.exit(1)
    print("All care tests passed.")


if __name__ == "__main__":
    main()
