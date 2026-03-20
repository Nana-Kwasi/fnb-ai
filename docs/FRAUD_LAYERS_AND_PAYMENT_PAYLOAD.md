# Fraud layers and payment-screen payload alignment

## 1. Fraud API input (TransactionIn)

**Contract:** `POST /api/v1/fraud/score` (Bankai) accepts JSON:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transaction_id` | str | yes | Unique external transaction id |
| `account_id` | str | yes | Payer account (customer external id) |
| `amount` | float | yes | Transaction amount |
| `currency` | str | yes | e.g. USD, GHS |
| `timestamp` | str | yes | ISO datetime (e.g. with Z) |
| `merchant_category` | str \| null | no | e.g. TRANSFER, POS, GAMBLING |
| `location` | str \| null | no | Country code or string (first 2 chars used as location_country) |
| `device_id` | str \| null | no | Device identifier |
| `ip_address` | str \| null | no | Client IP (stored hashed, first 64 chars) |

---

## 2. What each fraud layer uses (from this payload)

### Layer 1 – Persisted transaction row (router creates `Transaction`)

- `transaction_id` → `external_tx_id`
- `account_id` → resolved to `customer_id`, links to Customer
- `amount`, `currency` → stored
- `merchant_category` → stored (used as merchant context)
- `device_id` → stored
- `ip_address` → truncated to 64 → `ip_address_hash`
- `location` → first 2 chars uppercase → `location_country`
- `timestamp` → `tx_timestamp`

### Layer 2 – Feature engine (`build_feature_vector`)

- **Velocity / behaviour:** `account_id` (customer_id), `amount`, `tx_timestamp` → txn counts 1h/24h/7d, amount vs avg, days_since_last_txn
- **Device:** `device_id` → is_new_device, devices_seen_30d, customers_seen_7d_for_device, device_reuse_ratio, device_fraud_ratio_90d
- **IP:** `ip_address` (as ip_hash) → ips_seen_30d_for_customer, ip_fraud_ratio_90d; passed to network/graph for IP-based features
- **Location:** `location` → location_country → is_new_location, get_last_location, merchant_country_mismatch
- **Merchant:** `merchant_category` → merchant_fraud_rate_90d, merchant_volume_7d, merchant_country_mismatch, merchant_cat_risk (GAMBLING/CRYPTO/INTERNATIONAL)

### Layer 3 – Network / ring (`get_network_risk_features`, `update_entity_maps`)

- `device_id` → accounts_seen_for_device_7d/30d, device_risk_score, device rings
- `ip_address` → accounts_seen_for_ip_7d/30d, ip_risk_score, IP rings
- `merchant_category` → merchant_risk_score, merchant fraud hub

### Layer 4 – Graph (`get_graph_features_for_scoring`)

- `device_id`, `ip_address`, `customer_id` → graph_risk_score, fraud_cluster_size, shortest_path_to_known_fraud

### Layer 5 – Transaction fingerprint (`compute_transaction_fingerprint`, `store_fingerprint`, `get_fingerprint_features`)

- `account_id` (customer_id), `device_id`, `ip_address`, `merchant_category`, `amount`, `tx_timestamp.hour` → fingerprint ID → fingerprint_repeat_count, fingerprint_velocity_1h, fingerprint_fraud_rate

### Layer 6 – Rule engine (`rule_score`)

- Uses feature vector derived from above: `amount`, `is_new_device`, `is_new_location`, `txn_count_1h`, `location_country` → amount threshold, new device + new location, suspicious countries

### Layer 7 – ML / ensemble (`score_and_explain`)

- Full feature vector (all FEATURE_NAMES) → LGBM model, isolation forest, ensemble, decision (BLOCK / REQUEST_OTP / APPROVE / etc.)

---

## 3. What the payment screen sends (end-to-end)

### App → Gateway (`POST /api/transfers`)

| Field | Source | Notes |
|-------|--------|------|
| `from_account_id` | User-selected account | Payer |
| `to_account_id` | User-entered receiver account number | Not sent to fraud API |
| `amount` | User input | |
| `currency` | User input (default USD) | |
| `device_id` | SecureStore stable ID (mobile-{os}-...) | Persisted per device |
| `location` | User-editable country code (default GH) | 2-letter for fraud |

(IP is not sent by the app; gateway sets it from the request.)

### Gateway → Bankai (`POST /api/v1/fraud/score`)

Gateway builds the body sent to the fraud model:

| Fraud API field | Gateway source | Matches API? |
|-----------------|----------------|---------------|
| `transaction_id` | Generated: `cb-tr-{uuid}` | yes |
| `account_id` | `payload.from_account_id` | yes |
| `amount` | `payload.amount` | yes |
| `currency` | `payload.currency` | yes |
| `timestamp` | Gateway-generated ISO UTC (Z) | yes |
| `merchant_category` | `"TRANSFER"` (fixed) | yes |
| `location` | `payload.location` (from app) | yes |
| `device_id` | `payload.device_id` (from app) | yes |
| `ip_address` | Request client IP or X-Forwarded-For | yes |

---

## 4. Alignment summary

- The **payment screen** (transfer) sends: `from_account_id`, `to_account_id`, `amount`, `currency`, `device_id`, `location`.
- The **gateway** maps these (plus generated `transaction_id`, `timestamp`, and client IP) into the **same structure** as the fraud API’s `TransactionIn`.
- Every fraud layer that uses `transaction_id`, `account_id`, `amount`, `currency`, `timestamp`, `merchant_category`, `location`, `device_id`, or `ip_address` gets them from that single payload; no extra fields are required for the current design.

**Conclusion:** The payment screen (via the gateway) submits the same transaction data structure the fraud model expects; all layers are fed from this single payload.
