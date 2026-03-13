# BankAI Platform

White-label Fraud Detection + Customer Care API. Multi-tenant, API-first.

## Quick start

### Prerequisites

- Python 3.11+, Node 18+, Docker & Docker Compose
- PostgreSQL 15+ with pgvector (or use Docker)

### 1. Database and API (local)

**Option A — Postgres/Redis in Docker, API on host**

```bash
cd infra && docker compose up -d postgres redis
cd ../backend
cp .env.example .env   # set DATABASE_URL if needed
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

**Option B — No containers (everything on host)**

1. **PostgreSQL 15+** (with pgvector): create DB and user, e.g.  
   `createdb bankaidb` and a user `bankaiuser` with password (or use your own).
2. **Redis** (optional): only needed if you enable real rate-limiting; the app runs without it (stub).
3. **Backend**

```bash
cd backend
cp .env.example .env
# Edit .env: DATABASE_URL=postgresql+asyncpg://bankaiuser:YOUR_PASSWORD@localhost:5432/bankaidb

python -m venv ../.venv
source ../.venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000  
- Docs: http://localhost:8000/docs

### 2. Frontend (local)

```bash
cd frontend
npm install
npm run dev
```

- API: http://localhost:8000  
- Docs: http://localhost:8000/docs  
- Frontend: http://localhost:3000  

### 3. Full stack with Docker

```bash
cd infra
export DB_PASSWORD=yourpassword SECRET_KEY=yoursecret
docker compose up --build
```

- API: http://localhost:8000  
- Frontend: http://localhost:3000  
- Nginx: http://localhost:80 (proxies to API + frontend)  

## First tenant

Create a bank (no auth required on `/admin/onboard` for bootstrap):

```bash
curl -X POST http://localhost:8000/api/v1/admin/onboard \
  -H "Content-Type: application/json" \
  -d '{"name": "Bank A", "country_code": "GH"}'
```

Use the returned `api_key` in `X-API-Key` for all fraud and care endpoints.

## Project layout

- `backend/` — FastAPI app, SQLAlchemy models, Alembic, routers (fraud, care, admin), middleware (auth, rate limit)
- `frontend/` — React + Vite + Tailwind; architecture/flow/stack blueprint UI
- `infra/` — docker-compose (postgres, redis, api, frontend, nginx), nginx.conf
- `models/` — (optional) place Phi-3 GGUF and other model files here; mounted into API container

## Phase 1 — Foundation

- [x] PostgreSQL schema + RLS + migrations
- [x] FastAPI skeleton + multi-tenant auth (X-API-Key → tenant)
- [x] Stub endpoints: POST /fraud/score, POST /care/chat, POST /admin/onboard
- [x] React blueprint dashboard (architecture / flow / stack tabs)
- [x] Docker Compose for local run

## Phase 2 — Fraud Engine

- [x] Feature engineering: velocity (1h/24h/7d), amount deviation, device, time, customer risk
- [x] Fraud engine: LightGBM + Isolation Forest (optional) + SHAP reason codes
- [x] POST /api/v1/fraud/score: create customer/txn, compute features, score, persist fraud_scores + audit
- [x] Training script: `python -m app.ml.train` (synthetic data → `models/fraud/lgb_fraud.txt`, `isolation_forest.joblib`)

Without trained models, the API uses rule-based stub scoring. To use real models, run the training script then place artifacts under `models/fraud/` (or set `MODEL_PATH` so `$(dirname $MODEL_PATH)/fraud` holds the files).

Next: Phase 3 — Customer Care Agent (DistilBERT, RAG, Phi-3).
