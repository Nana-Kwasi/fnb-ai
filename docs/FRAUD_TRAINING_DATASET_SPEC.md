# Fraud model training dataset spec

You create the dataset; the platform trains the fraud model from it. Two ways to do it:

---

: Transaction history + labels (for DB import, then train)

The trainer in **real mode** loads data from the database: it finds transactions that have a **FraudOutcome** row, then builds the feature vector for each using the same logic as live scoring. So your dataset should be designed to be **imported into the platform** (into `transactions`, `customers`, and `fraud_outcomes`). After import, run the normal training job (scheduled or “Trigger fraud train”).

### What to create

**1. Mix of labels**

- Include both **fraud** and **legit** outcomes so the model can learn the difference.
- A typical mix: roughly **15–30% CONFIRMED_FRAUD**, the rest **FALSE_POSITIVE** or **CONFIRMED_LEGIT** (or a mix of both). Avoid 50/50 unless you deliberately balance later (e.g. with SMOTE); real traffic is usually mostly legit.

**2. Per-row shape (one row = one transaction + its label)**

Each row in your dataset should map to one **transaction** and one **outcome**. Suggested columns:

| Column / concept        | Required | Notes |
|-------------------------|----------|--------|
| **tenant_id**           | Yes      | UUID of the bank (tenant). Must exist in `tenant_banks`. |
| **customer_id** (or account_id) | Yes | UUID (or external account id you can resolve to a customer). Customer must exist in `customers` with a `risk_score`. |
| **external_tx_id**      | Yes      | Your unique transaction id (string). |
| **amount**              | Yes      | Numeric, e.g. 99.99. |
| **currency**            | Yes      | 3-letter, e.g. USD, GHS. |
| **tx_timestamp**        | Yes      | ISO datetime with timezone, e.g. 2025-03-01T14:30:00Z. |
| **merchant_category**   | No       | e.g. RETAIL, GAMBLING, CRYPTO. Affects merchant_cat_risk. |
| **device_id**           | No       | Same value across rows to simulate shared device (ring). |
| **ip_address_hash**     | No       | Hashed IP (or placeholder). Same value across rows for shared-IP signals. |
| **location_country**    | No       | 2-letter, e.g. GH, US. |
| **channel**             | No       | e.g. MOBILE, WEB. |
| **classification**      | Yes      | **CONFIRMED_FRAUD** | **FALSE_POSITIVE** | **CONFIRMED_LEGIT**. This is the label. |
| **source** (outcome)    | No       | e.g. CHARGEBACK, ANALYST. |
| **notes** (outcome)     | No       | Free text. |

**3. What the trainer needs in the DB**

- **transactions**: One row per transaction (tenant_id, customer_id, external_tx_id, amount, currency, tx_timestamp, and optional merchant_category, device_id, ip_address_hash, location_country, channel).
- **customers**: Each customer_id must exist; `risk_score` (0–1) is used in features. Create/update customers as needed when you import.
- **fraud_outcomes**: One row per labelled transaction: `transaction_id` (after insert), `tenant_id`, `classification` (CONFIRMED_FRAUD / FALSE_POSITIVE / CONFIRMED_LEGIT), optional `source`, `notes`.

**4. Making features meaningful**

- **Velocity / history**: For each customer, include **multiple transactions over time** (e.g. 1h, 24h, 7d windows) so that `txn_count_1h`, `txn_count_24h`, `amount_vs_avg_ratio`, etc. are non-zero and varied.
- **Device / IP**: Reuse the same `device_id` (and optionally `ip_address_hash`) across **several customers** for some rows so that ring-style features (e.g. `accounts_seen_for_device_7d`, `device_risk_score`) can be computed.
- **Time order**: Insert or order transactions by `tx_timestamp` so that “past” vs “current” is correct when the trainer builds features for each labelled transaction.

**5. Example row (conceptual)**

```text
tenant_id,customer_id,external_tx_id,amount,currency,tx_timestamp,merchant_category,device_id,ip_address_hash,location_country,classification,source
550e8400-e29b-41d4-a716-446655440000,6ba7b810-9dad-11d1-80b4-00c04fd430c8,txn-001,250.00,USD,2025-02-15T10:00:00Z,RETAIL,dev-abc,,GH,FALSE_POSITIVE,ANALYST
550e8400-e29b-41d4-a716-446655440000,6ba7b810-9dad-11d1-80b4-00c04fd430c8,txn-002,5000.00,USD,2025-02-15T14:00:00Z,GAMBLING,dev-xyz,ip-hash-1,US,CONFIRMED_FRAUD,CHARGEBACK
```

---

## Option 2: Flat feature matrix (CSV / Parquet) — same features as the model

If you prefer to build the **feature vectors yourself** (e.g. from your own warehouse), create one row per sample with **exactly** the features the model uses, in the **same order**, plus a **label** column. The current trainer does **not** read this file by default; you (or we) would add a small loader that reads it and runs the same training code.

### Feature columns (order matters)

Use these names in this order. Missing columns can be filled with 0. All numeric (float).

1. amount  
2. txn_count_1h  
3. total_amount_1h  
4. txn_count_24h  
5. total_amount_24h  
6. txn_count_7d  
7. total_amount_7d  
8. amount_vs_avg_ratio  
9. is_new_device  
10. hour_of_day  
11. is_weekend  
12. days_since_last_txn  
13. customer_risk_score  
14. merchant_cat_risk  
15. devices_seen_last_30d_for_customer  
16. customers_seen_last_7d_for_device  
17. ips_seen_last_30d_for_customer  
18. device_reuse_ratio  
19. email_reuse_ratio  
20. device_fraud_ratio_90d  
21. ip_fraud_ratio_90d  
22. card_fraud_ratio_90d  
23. merchant_fraud_rate_90d  
24. merchant_volume_7d  
25. merchant_country_mismatch  
26. accounts_seen_for_device_7d  
27. accounts_seen_for_device_30d  
28. device_risk_score  
29. accounts_seen_for_ip_7d  
30. accounts_seen_for_ip_30d  
31. ip_risk_score  
32. merchant_fraud_rate_30d  
33. merchant_transaction_volume_7d  
34. merchant_risk_score  
35. device_shared_account_count  
36. ip_shared_account_count  
37. shared_email_accounts  
38. shared_phone_accounts  
39. fraud_cluster_size  
40. fingerprint_repeat_count  
41. fingerprint_repeat_count_30d  
42. fingerprint_fraud_rate  
43. fingerprint_velocity_1h  
44. shortest_path_to_known_fraud  
45. graph_risk_score  

### Label column

- Name: **label** (or **is_fraud**).
- Values: **0** = legit (FALSE_POSITIVE / CONFIRMED_LEGIT), **1** = fraud (CONFIRMED_FRAUD).

### Example (CSV header)

```text
amount,txn_count_1h,total_amount_1h,txn_count_24h,total_amount_24h,txn_count_7d,total_amount_7d,amount_vs_avg_ratio,is_new_device,hour_of_day,is_weekend,days_since_last_txn,customer_risk_score,merchant_cat_risk,...,graph_risk_score,label
250.0,0,0.0,2,500.0,5,1200.0,1.2,0,14,0,2.0,0.1,0.0,...,0.0,0
5000.0,3,7500.0,8,15000.0,20,45000.0,3.5,1,9,0,30.0,0.4,0.2,...,0.6,1
```

Again: mix of labels (e.g. 20–30% ones, rest zeros) and varied feature values so the model can learn.

---

## Summary

| Approach | You provide | Platform does |
|----------|-------------|----------------|
| **Option 1** | Dataset of transactions + labels (and customers / tenant) that you import into the DB. | Builds features via `build_feature_vector`, trains from DB. |
| **Option 2** | Flat file (CSV/Parquet) with the 45 feature columns above + `label` (0/1). | Needs a loader (not in repo today); then same training pipeline. |

For **Option 1**, ensure: (1) mix of CONFIRMED_FRAUD and FALSE_POSITIVE/CONFIRMED_LEGIT, (2) enough transaction history per customer and shared device/IP where you want ring/velocity signals, (3) time order so “past” is correct when features are built.
