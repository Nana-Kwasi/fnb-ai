"""
1. Run Alembic migrations (create/update DB tables).
2. Run care training (export chat history -> JSONL, train intent model if enough data).
3. Print instructions to test care (start server + run test_care.py or test_all.py).

Usage: cd backend && python scripts/run_migrate_train_care.py
Uses .env for DATABASE_URL; activate venv first if needed.
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))
env = os.environ.copy()
env["PYTHONPATH"] = str(BACKEND)

def run(cmd, desc):
    print("\n---", desc, "---")
    r = subprocess.run(cmd, shell=True, env=env, cwd=BACKEND)
    if r.returncode != 0:
        print("FAILED:", desc)
        sys.exit(r.returncode)
    print("OK")

run("alembic upgrade head", "Migrations")
run("python -m app.tasks.care_train_scheduled", "Care training (export + train)")

print("\n--- Next: test care ---")
print("1. Start backend: uvicorn app.main:app --reload")
print("2. In another terminal: cd backend && python scripts/test_care.py")
print("   Or use BANKAI_API_KEY=... python scripts/test_all.py")
