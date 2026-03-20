# Prompts to send to another AI to create the fraud training dataset (Option 1)

Copy one of the prompts below and paste it into another AI. Use **Prompt 1** first; use **Prompt 2** only if you want a different size or format.

---

## Prompt 1 — Main (create the CSV dataset)

```
Create a CSV file for training a fraud detection model. The file will be imported into a database: each row = one transaction + its fraud label.

**Required columns (exact names):**
- tenant_id (UUID string, same for all rows e.g. 550e8400-e29b-41d4-a716-446655440000)
- customer_id (UUID string; reuse the same 20–50 customer IDs across many rows so each customer has multiple transactions)
- external_tx_id (unique string per row, e.g. txn-00001, txn-00002, …)
- amount (number, e.g. 10.50 or 5000.00)
- currency (3 letters: USD or GHS)
- tx_timestamp (ISO datetime with Z, e.g. 2025-02-15T10:30:00Z; spread over at least 7–30 days and keep time order)
- classification (exactly one of: CONFIRMED_FRAUD, FALSE_POSITIVE, CONFIRMED_LEGIT)

**Optional columns (include with empty or placeholder if not used):**
- merchant_category (e.g. RETAIL, GAMBLING, CRYPTO)
- device_id (string; reuse the same device_id across 3–10 different customer_ids for some rows to simulate shared device / fraud rings)
- ip_address_hash (string; can be empty or e.g. ip-hash-1)
- location_country (2 letters: GH, US, etc.)
- channel (e.g. MOBILE, WEB)
- source (e.g. CHARGEBACK, ANALYST)
- notes (free text or empty)

**Rules:**
1. Generate 800–2000 rows (or 500 minimum).
2. Label mix: about 20–25% CONFIRMED_FRAUD, the rest FALSE_POSITIVE or CONFIRMED_LEGIT (e.g. 70% FALSE_POSITIVE, 10% CONFIRMED_LEGIT).
3. Each customer_id should appear in multiple rows (e.g. 5–30 transactions per customer) with different tx_timestamp and amount so there is transaction history.
4. For a subset of rows, use the same device_id for different customer_ids (e.g. 2–3 device_ids each shared by 5–8 customers) to simulate device fraud rings.
5. Fraud rows: slightly higher amounts on average, more GAMBLING/CRYPTO merchant_category, and more shared device_id usage.
6. Output: valid CSV with header row, quoted strings if needed, no extra spaces. First line must be the column names.
```

---

## Prompt 2 — Shorter (if you need a smaller or larger file)

```
Using the same column names and rules as in Prompt 1, create a CSV with exactly 500 rows. Use one tenant_id, 30 customer_ids (each with several transactions), and 3 shared device_ids. 20% CONFIRMED_FRAUD, 80% FALSE_POSITIVE or CONFIRMED_LEGIT. Output only the CSV (header + rows), no explanation.
```

---

## Prompt 3 — “I already have a tenant_id and customer_ids”

```
I have a tenant_id and a list of customer_ids. Create a fraud training CSV with these columns: tenant_id, customer_id, external_tx_id, amount, currency, tx_timestamp, merchant_category, device_id, ip_address_hash, location_country, classification, source. Use my tenant_id and customer_ids; generate 1000 rows. 25% CONFIRMED_FRAUD, 75% legit (FALSE_POSITIVE / CONFIRMED_LEGIT). Reuse the same customer_id across multiple rows (many transactions per customer). Reuse the same device_id across 5–10 different customer_ids for some rows. Output valid CSV with header.
```

*(Replace “my tenant_id and customer_ids” with your actual values when you paste, or ask the AI to generate placeholder UUIDs.)*

---

## After you get the CSV

1. Save the model’s output as a `.csv` file (e.g. `fraud_training_data.csv`).
2. You still need to **import** it into the platform database (into `transactions`, `fraud_outcomes`, and ensure `customers` exist). The platform does not auto-import CSV; use a one-off script or Admin/API that reads the CSV and inserts rows.
3. Then run “Trigger fraud train” in the Admin dashboard (or wait for the 24h job) to train the model from the DB.
