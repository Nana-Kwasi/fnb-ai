"""
1) Train fraud models (LightGBM/sklearn + Isolation Forest).
2) Send sample care questions to POST /api/v1/care/chat and print responses.

Requires: BANKAI_API_KEY (tenant API key from onboard), BACKEND_URL (default http://localhost:8000).
Backend must be running and OPENAI_API_KEY set for care.

Run from backend: python scripts/run_training_and_care_test.py
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("BANKAI_API_KEY", "")

SAMPLE_QUESTIONS = [
    "What is my balance?",
    "I think there was a fraudulent charge on my account.",
    "How do I unlock my account?",
    "I want to speak to a human agent.",
    "Where can I find my recent transactions?",
]


def run_fraud_training():
    backend = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    if str(backend) not in env.get("PYTHONPATH", ""):
        env["PYTHONPATH"] = f"{backend}{os.pathsep}{env.get('PYTHONPATH', '')}"
    print("Training fraud models (LightGBM + Isolation Forest)...")
    r = subprocess.run(
        [sys.executable, "-m", "app.ml.train"],
        cwd=backend,
        env=env,
    )
    if r.returncode != 0:
        print("Fraud training failed (non-zero exit). Continuing to care test.")
    else:
        print("Fraud training done.\n")


def test_care_questions():
    if not API_KEY or not API_KEY.strip():
        print("BANKAI_API_KEY not set. Skipping care test. Example:")
        print("  BANKAI_API_KEY=bankai_live_xxx python scripts/run_training_and_care_test.py")
        return
    import urllib.request
    import json

    url = f"{BACKEND_URL}/api/v1/care/chat"
    session_id = "test-session-" + str(hash(__file__) % 10**6)
    customer_id = "acc-demo-001"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY.strip(),
    }
    print("Testing care with sample questions:\n")
    for i, q in enumerate(SAMPLE_QUESTIONS, 1):
        body = {
            "session_id": session_id,
            "customer_id": customer_id,
            "message": q,
            "channel": "mobile_app",
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
                print(f"Q{i}: {q}")
                print(f"    Intent: {data.get('intent', '')}")
                print(f"    Response: {data.get('response', '')[:300]}{'...' if len(data.get('response','')) > 300 else ''}")
                print(f"    Escalate: {data.get('escalate_to_human', False)} | Time: {data.get('processing_time_ms', 0)}ms\n")
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                err = json.loads(body)
                detail = err.get("detail", body.decode())
            except Exception:
                detail = body.decode()
            print(f"Q{i}: {q}")
            print(f"    Error: {e.code} {detail}\n")
        except Exception as e:
            print(f"Q{i}: {q}")
            print(f"    Error: {e}\n")


def main():
    run_fraud_training()
    test_care_questions()
    print("Done.")


if __name__ == "__main__":
    main()
