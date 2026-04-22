# Fraud Model & Admin: Full Process and Usage

One transaction in → one decision out (APPROVE / REQUEST_OTP / BLOCK / etc.). This doc covers the full fraud process and all Admin API/UI usage.

Conventions reference: `docs/API_CONVENTIONS.md`.

---

## In very simple terms (for your bank)

**How it works for transactions**  
When a customer tries to make a transaction, your system sends that transaction to our API. We look at things like: amount, how often this customer transacts, whether the device or location is new, and whether the same device or IP is used by many accounts. We combine that into a single risk score (0–1). If the score is high, we say BLOCK or REQUEST_OTP; if it’s low, we say APPROVE. Your bank then acts on that (e.g. block the payment or send an OTP).

**How data is exchanged**
- **You send us**: For each transaction, call API with `X-API-Key` and transaction details (transaction ID, account ID, amount, currency, timestamp; optional device/IP/location/merchant fields).
- **We send you back**: Decision (`APPROVE` / `LIMITED_APPROVAL` / `REQUEST_OTP` / `SOFT_DECLINE` / `BLOCK`), risk score, and reasons.
- **We store**: The transaction and score on our side so we can improve the model and show you alerts and dashboards. Your data is tied to your bank (tenant) via the API key.

**Is the model trained on past transactions?**  
Yes. The main fraud model (LightGBM) is trained on **past transactions that were labelled** as fraud or not fraud. Those labels come from your analysts or chargebacks (e.g. “this transaction was CONFIRMED_FRAUD” or “FALSE_POSITIVE”), stored in our system. When a retrain runs, we use that history to update the model so it gets better over time. So: more past data + clear labels → better future decisions.

**Is training automatic or manual?**
Both. Scheduled jobs exist, and you can run training on demand via upload-based admin workflows (`/api/v1/admin/training/upload`, `/api/v1/admin/training/fraud/global-pooled/trigger`).

---

## Part A: Fraud model process

### A.1 End-to-end flow (one transaction)

1. **Request**  
   Bank sends **POST /api/v1/fraud/score** (or `/api/v1/fraud/score/detail`) with `transaction_id`, `account_id`, `amount`, `currency`, `timestamp`, and optional `device_id`, `ip_address`, `location` (country), `merchant_category`. Header: `X-API-Key`.

2. **Auth & tenant**  
   API key is validated; **tenant (TenantBank)** is resolved. Customer is created or looked up by `account_id`; a **Transaction** row is created (PENDING).

3. **Feature vector**  
   `build_feature_vector` runs (see A.2). Result is one dict of numbers (the feature vector) used by all models and rules.

4. **Scores**  
   `score_and_explain` runs:
   - Load per-tenant **fraud policy** (weights + thresholds) from `TenantBank.tone_config["fraud_policy"]` (or defaults).
   - Compute **model (LGB)**, **anomaly (ISO)**, **rule**, **network** scores from the feature vector.
   - **Graph fraud**: `graph_risk_score` is computed in `build_feature_vector` via `fraud_graph_engine` (relationship graph, connected components, shortest path to known fraud); it feeds into the ensemble.
   - **Adaptive Risk**: `adaptive_risk_engine` computes system state (NORMAL / ELEVATED_RISK / HIGH_ATTACK) from recent fraud rates and returns adjusted **block_threshold** and **otp_threshold** plus an **adaptive_risk_modifier** (0–1) for the ensemble.
   - **Ensemble** = 0.35×model + 0.15×anomaly + 0.20×rule + 0.10×network + 0.15×graph_risk_score + 0.05×adaptive_risk_modifier.
   - Optionally compute **SHAP** and reason codes from the LGB model (or stub).
   - Derive **segment** from the feature vector; adjust block/OTP thresholds by segment (A.5).
   - Compare ensemble to (adaptive-adjusted) **block_threshold** and **otp_threshold** → **decision** (A.5).

5. **Persistence**  
   - **fraud_scores**: lgbm_score, isolation_score, rule_score, ensemble_score, decision, confidence, shap_values, reason_codes, feature_vector, model_version.  
   - **transactions**: status set to DECLINED if BLOCK, PENDING_REVIEW if REQUEST_OTP.  
   - **fraud_alerts**: created for BLOCK/REQUEST_OTP only if **shadow_mode** is false.  
   - **Entity maps** (device_account_map, ip_account_map, etc.) updated for fraud ring / network features.  
   - **Transaction fingerprint** computed and stored (transaction_fingerprints, fingerprint_stats) for repeat/bot detection.  
   - **audit_logs**: event_type FRAUD_SCORE with decision and rule_reasons.

6. **Response**  
   decision, fraud_score (ensemble), confidence, reasons (SHAP + rule_reasons), recommended_action, processing_time_ms. `/score/detail` also returns model_score, anomaly_score, rule_score, network_risk_score, graph_risk_score, shap_values, rule_reasons.

---

### A.2 Feature vector (build_feature_vector)

Built in `feature_engine.build_feature_vector`. All steps use the same tenant_id, customer_id, and tx_timestamp.

| Step | What it does | Key outputs |
|------|----------------|-------------|
| **Velocity** | `get_velocity`: count and sum of tx in 1h, 24h, 7d before tx_timestamp for this customer. | txn_count_1h/24h/7d, total_amount_1h/24h/7d |
| **Amount ratio** | avg_24h = total_amount_24h / txn_count_24h; ratio = amount / avg_24h (capped). | amount_vs_avg_ratio |
| **Device** | `get_last_txn_and_device`: last tx time and whether this device_id was seen for this customer. | days_since_last_txn, is_new_device (0/1) |
| **Location** | `get_last_location`: last country for this customer. | is_new_location (0/0.5/1) |
| **Time** | From tx_timestamp. | hour_of_day, is_weekend |
| **Customer** | Passed in (from Customer.risk_score). | customer_risk_score |
| **Merchant** | GAMBLING/CRYPTO/INTERNATIONAL → merchant_cat_risk 0.2 else 0. Merchant stats from DB. | merchant_cat_risk, merchant_fraud_rate_*, merchant_volume_*, etc. |
| **Network** | `_network_features`: devices/customers/IPs seen for this customer/device; reuse ratios; fraud ratios. | devices_seen_*, customers_seen_*, device_reuse_ratio, *_fraud_ratio_90d, etc. |
| **Ring** | `get_network_risk_features`: accounts per device/IP, device/IP risk scores, shared accounts, fraud cluster size. | accounts_seen_for_device_7d/30d, accounts_seen_for_ip_*, device_risk_score, ip_risk_score, merchant_risk_score, etc. |
| **Fingerprint** | `compute_transaction_fingerprint` + `get_fingerprint_features`: same pattern (cust+device+ip+merchant+amount bucket+hour) repeat count and velocity. | fingerprint_repeat_count, fingerprint_velocity_1h, fingerprint_fraud_rate, etc. |

The final dict includes all **FEATURE_NAMES** used by the LGB/ISO models, plus `location_country` and `_fingerprint_id` for rules and fingerprint storage.

---

### A.3 Four scores

| Score | Meaning | Source |
|-------|--------|--------|
| **Model (LGB)** | “How much does this look like known fraud?” | LightGBM (or sklearn fallback) on feature vector; trained from fraud_outcomes. `fraud_engine._score_lgb()`. |
| **Anomaly (ISO)** | “How weird vs normal?” | Isolation Forest; outlier → 1.0, inlier → 0.0. Loaded from `isolation_forest.joblib`. |
| **Rule** | Max weight among triggered DB rules. | `rule_engine.rule_score()`: loads enabled rules (global + tenant) from `fraud_rules`, evaluates condition_expression over feature vector + amount_threshold, velocity_1h_threshold, suspicious_countries. |
| **Network** | Device/IP/merchant ring risk. | `fraud_ring.compute_network_risk_score(feature_vector)`. |

---

### A.4 Policy and ensemble

- **Policy** is read from `TenantBank.tone_config["fraud_policy"]` (or defaults) in `_fraud_policy_from_tenant`.
- **Defaults**: model_weight=0.5, iso_weight=0.2, rule_weight=0.2, network_weight=0.1 (normalized to sum 1); fraud_block_threshold=0.85; fraud_otp_threshold=0.60; shadow_mode=False.
- **Ensemble**:  
  `ensemble = model_weight*LGB + iso_weight*ISO + rule_weight*rule + network_weight*network`  
  (ISO omitted if no ISO model; weights normalized so the four sum to 1.)

---

### A.5 Segments and decision

- **Segment** is derived from the feature vector: LOW_RISK_LONG_TENURE, NEW_CUSTOMER, HIGH_RISK_REGION, HIGH_VELOCITY_USER. Used to tweak thresholds:
  - **LOW_RISK_LONG_TENURE** (and low risk): block/OTP thresholds raised slightly (fewer false positives).
  - **NEW_CUSTOMER**, **HIGH_RISK_REGION**, **HIGH_VELOCITY_USER** (or high customer_risk_score): block/OTP thresholds lowered (stricter).
  - High **network_risk_score** in a risky segment: thresholds lowered further; low network_risk in low-risk segment: thresholds raised slightly.

- **Decision** (after adjustments):
  - ensemble ≥ block_threshold → **BLOCK**
  - ensemble ≥ otp_threshold → **REQUEST_OTP**
  - Else: if rule_score ≥ 0.8 → **MANUAL_REVIEW**; else if ensemble ≥ 0.8×otp → **SOFT_DECLINE**; else if ensemble ≥ 0.5×otp → **LIMITED_APPROVAL**; else **APPROVE** (confidence HIGH if ensemble < 0.3 else MEDIUM).

---

### A.6 Rule engine (fraud_rules)

- **Table**: `fraud_rules` (tenant_id nullable = global rule, else tenant-specific).
- **Columns**: rule_id, condition_expression, weight, reason_code, enabled.
- **Context** for expression: the feature vector plus `amount_threshold`, `velocity_1h_threshold`, `suspicious_countries` (set). Example expressions: `txn_count_1h >= velocity_1h_threshold`, `is_new_device == 1 and amount >= amount_threshold * 0.2`, `location_country in suspicious_countries`, `fingerprint_velocity_1h >= 3`, `accounts_seen_for_device_7d >= 5`.
- **Seeded global rules** (migration 005): velocity_1h, new_device_amount, high_risk_country, fingerprint_velocity, device_ring.

---

### A.7 Training

- **Labels**: `fraud_outcomes` (classification: CONFIRMED_FRAUD, FALSE_POSITIVE, CONFIRMED_LEGIT, etc.) plus synthetic data if needed.
- **Features**: same `build_feature_vector` / FEATURE_NAMES.
- **Job**: `fraud_train_scheduled.run_fraud_training(limit=5000, mode="real")` builds feature vectors from outcome-linked transactions, trains LightGBM (and optionally Isolation Forest), saves to `models/fraud/` (e.g. `lgb_fraud.txt`, `isolation_forest.joblib`).
- **When**: Scheduled (e.g. daily) or on demand via Admin (see Part B).

---

### A.8 Fraud API endpoints (reference)

| Method | Path | Purpose |
|--------|------|--------|
| POST | /api/v1/fraud/score | Score transaction; return decision, fraud_score, reasons, recommended_action. |
| POST | /api/v1/fraud/score/detail | Same + model_score, anomaly_score, rule_score, network_risk_score, shap_values, rule_reasons. |
| POST | /api/v1/fraud/predict | Lighter predict (risk_score, decision, reason). |
| GET | /api/v1/fraud/alerts | List fraud alerts for tenant. |
| GET | /api/v1/fraud/customer-risk/{account_id} | Customer risk profile. |
| POST | /api/v1/fraud/device-check | Check device risk. |
| GET | /api/v1/fraud/transactions | Recent transactions (monitor). |
| GET | /api/v1/fraud/network/graph | Network graph (nodes/edges). |
| GET | /api/v1/fraud/network/rings | Fraud ring alerts. |
| GET | /api/v1/fraud/network/analytics | Accounts per device, shared IP, fraud clusters, high-risk merchants. |
| POST | /api/v1/fraud/outcome | Submit analyst/chargeback outcome (for training labels). |
| GET | /api/v1/fraud/metrics/summary | Metrics summary. |
| GET | /api/v1/fraud/feature-importances | LightGBM gain importances (`feature_importances.json`). Response: `{ "features": [...], "meta": { "route_source", "model_version", "artifact_uri", "resolved_from", "reason" } }`. Prefer the fraud **artifact directory** from the same registry routing as scoring (tenant → global); if that bundle has no JSON, falls back to the default bundled `models/fraud` tree. |

All fraud endpoints require **X-API-Key** (tenant-scoped). Dashboard shows “Viewing data for key: ***xxxx” when a key is set.

---

## Part B: Admin API and usage

Base path: **/api/v1/admin**. Requires platform admin auth (JWT; legacy token optional if enabled).

### B.1 Admin API endpoints

| Method | Path | Purpose |
|--------|------|--------|
| POST | /api/v1/admin/onboard | Create a new bank tenant. Body: `name`, `country_code`. Returns `bank_id` (UUID), `api_key` (show once). |
| GET | /api/v1/admin/tenants | List all tenants. Returns `[{ id, name, country_code }]`. |
| GET | /api/v1/admin/tenants/{tenant_id}/fraud-policy | Get fraud policy for tenant: model_weight, iso_weight, rule_weight, network_weight, fraud_block_threshold, fraud_otp_threshold, shadow_mode. |
| PATCH | /api/v1/admin/tenants/{tenant_id}/fraud-policy | Update fraud policy (any subset of the above). Body: same keys, optional. |
| POST | /api/v1/admin/training/upload | Upload labelled training data. |
| POST | /api/v1/admin/training/fraud/global-pooled/trigger | Trigger pooled fraud training from uploaded data. |
| POST | /api/v1/admin/trigger-fraud-train | Legacy trigger endpoint (compatibility path). |
| GET | /api/v1/admin/care/metrics | Customer care metrics (window_hours, total_replies, rule_hit_rate, suggestion_rate, escalation_rate, intent_counts, alerts). Query: `window_hours` (default 24). |

### B.2 Fraud policy fields (what each does, in simple terms)

| Field | What it does |
|-------|----------------|
| **Model weight** | How much the **LightGBM score** (“looks like past fraud”) counts in the blend. Higher = the ML model’s opinion matters more. |
| **ISO weight** | How much the **Isolation Forest** score (“how weird vs normal”) counts. Higher = we react more to odd, never-seen-before behaviour. |
| **Rule weight** | How much the **rule engine** (e.g. “velocity too high”, “new device + big amount”) counts. Higher = rule hits push the score up more. |
| **Network weight** | How much **device/IP/merchant ring** risk counts (same device or IP on many accounts). Higher = we trust network signals more. |
| **Block threshold** | The score above which we **block** the transaction (e.g. 0.85 → score ≥ 0.85 ⇒ BLOCK). Lower = block more often. |
| **OTP threshold** | The score above which we **request OTP** (e.g. 0.60 → score between 0.60 and block ⇒ REQUEST_OTP). Lower = challenge more often. |
| **Shadow mode** | If **on**, we still score and log but **don’t create fraud alerts** and don’t actually block or request OTP in the response (test without affecting customers). If **off**, BLOCK/OTP decisions are real and alerts are created. |

*Note: The current ensemble uses fixed weights (0.35 model, 0.15 ISO, 0.20 rule, 0.10 network, 0.15 graph, 0.05 adaptive), so the four weights in Admin are stored and available for future use; **block threshold**, **OTP threshold**, and **shadow mode** are the ones that directly control behaviour today.*

### B.3 Admin UI usage (dashboard → Admin tab)

- **Onboard**  
  1. Fill Bank name and Country code.  
  2. Click “Onboard bank”.  
  3. Copy and store the returned API key (used as X-API-Key for that bank).  

- **Care metrics**  
  1. Click “Load metrics”.  
  2. View total replies, rule hit rate, suggestion rate, escalation rate, intent counts, and any alerts.  

- **Fraud policy & training**  
  1. Click “Load tenants” to fetch the tenant list.  
  2. Select a bank from the dropdown.  
  3. Click “Load policy” to load that tenant’s fraud policy into the form.  
  4. Edit model/ISO/rule/network weights, block threshold, OTP threshold, shadow mode.  
  5. Click “Save policy” to PATCH the policy for the selected tenant.  
  6. Click “Trigger fraud train” to start a background retrain; message confirms start.  

### B.4 Who uses what

- **Onboarding**: ops when adding a new bank; API key is given to the bank for fraud (and care) APIs.  
- **Fraud policy**: ops or bank’s integration owner; controls how strict the model is (weights and thresholds) and whether to run in shadow_mode (no real alerts).  
- **Training triggers**: prefer upload-based trigger endpoints; keep legacy trigger only for backward compatibility.
- **Care metrics**: ops to monitor customer care health.  

---

## TL;DR

**Fraud flow**: Request → tenant + customer + transaction → build_feature_vector (velocity, device, location, network, ring, fingerprint) → four scores (LGB, ISO, rule, network) → ensemble (weighted) → segment-adjusted thresholds → decision → persist scores/alerts/maps/fingerprint/audit → response.  

**Admin**: Onboard (new bank + API key); list tenants; get/patch fraud policy per tenant; trigger fraud train; view care metrics. All of this is used from the Admin tab in the dashboard as described in B.2.
