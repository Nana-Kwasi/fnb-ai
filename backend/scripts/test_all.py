"""
Hit onboard, fraud score, and care chat. Backend must be running.
Usage: cd backend && python scripts/test_all.py
Optional: BANKAI_API_KEY=... (skip onboard and use this key); else onboard first and use new key.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

BASE = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("BANKAI_API_KEY", "").strip()


def req(path, method="GET", body=None, headers=None, timeout=60):
    h = {"Content-Type": "application/json", **(headers or {})}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as res:
        return res.getcode(), json.loads(res.read().decode())


def main():
    key = API_KEY
    if not key:
        print("1. Onboard (no key yet)...")
        try:
            code, data = req("/api/v1/admin/onboard", "POST", {"name": "Test Bank", "country_code": "GH"}, timeout=10)
            if code != 200:
                print("   FAIL:", code, data)
                return
            key = data.get("api_key")
            print("   OK  bank_id:", data.get("bank_id"), "| api_key:", key[:20] + "...")
        except Exception as e:
            print("   FAIL:", e)
            return
    else:
        print("1. Using BANKAI_API_KEY (skip onboard)")

    print("2. Fraud score...")
    try:
        code, data = req(
            "/api/v1/fraud/score",
            "POST",
            {
                "transaction_id": "tx-test-001",
                "account_id": "acc-test-001",
                "amount": 100.0,
                "currency": "GHS",
                "merchant_category": "retail",
                "location": "GH",
                "device_id": "dev-1",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            {"X-API-Key": key},
            timeout=45,
        )
        if code != 200:
            print("   FAIL:", code, data)
        else:
            print("   OK  decision:", data.get("decision"), "| score:", data.get("fraud_score"), "| ms:", data.get("processing_time_ms"))
    except Exception as e:
        print("   FAIL:", e)

    print("3. Care chat (local model may be slow first time)...")
    try:
        code, data = req(
            "/api/v1/care/chat",
            "POST",
            {"session_id": "sess-test-1", "customer_id": "acc-test-001", "message": "What is my balance?", "channel": "mobile_app"},
            {"X-API-Key": key},
            timeout=90,
        )
        if code != 200:
            print("   FAIL:", code, data)
        else:
            r = (data.get("response") or "")[:120]
            print("   OK  intent:", data.get("intent"), "| response:", r + ("..." if len((data.get("response") or "")) > 120 else ""))
    except Exception as e:
        print("   FAIL:", e)

    print("Done.")


if __name__ == "__main__":
    main()
