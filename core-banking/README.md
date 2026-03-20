# Core Banking (demo)

Simulated **app → fraud → core banking** flow: the customer pays in the app; the request **passes through the fraud model first**; only if fraud approves does it hit core banking (ledger).

## Flow

```
App (customer pays) → Payment Gateway → Fraud API (Bankai) → if APPROVE → Core Banking Ledger
```

1. Customer initiates payment **in the app** (frontend).
2. App sends the payment to the **payment gateway** (BFF).
3. Gateway sends the transaction to the **Fraud API (Bankai)** first. Fraud sits **between** the app and core banking.
4. If **BLOCK** or **REQUEST_OTP**: gateway returns to app; **core banking is never called** (no debit).
5. If **APPROVE**: gateway calls **core banking ledger** to complete (debit and record).

So core banking only sees payments that fraud has already approved.

## Run

**1. Bankai backend** (fraud API):

```bash
cd backend && source ../.venv/bin/activate && uvicorn app.main:app --reload --port 8000
```

**2. Core banking ledger** (port 8001) — no fraud, just balance and complete:

```bash
cd core-banking/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

**3. Payment gateway** (port 8002) — app talks to this; gateway calls Fraud then Ledger:

```bash
cd core-banking/backend
export BANKAI_API_URL=http://127.0.0.1:8000/api/v1
export BANKAI_API_KEY=<your-tenant-api-key>
export CORE_BANKING_URL=http://127.0.0.1:8001
uvicorn gateway:app --reload --port 8002
```

**4. App frontend** (port 5175):

```bash
cd core-banking/frontend
npm install && npm run dev
```

Open **http://localhost:5175**. The app calls the **gateway** (8002) only. Gateway calls Fraud first, then Core banking on approve.

## Env

| Service   | Variable            | Default                         |
|----------|---------------------|---------------------------------|
| Gateway  | `BANKAI_API_URL`    | `http://127.0.0.1:8000/api/v1`  |
| Gateway  | `BANKAI_API_KEY`    | — (required)                    |
| Gateway  | `CORE_BANKING_URL`  | `http://127.0.0.1:8001`         |
| Frontend | `VITE_CORE_BANKING_API` | `http://127.0.0.1:8002` (gateway) |

Get `BANKAI_API_KEY` from the Bankai Admin UI (Onboard) or `tenant_banks.api_key`.
