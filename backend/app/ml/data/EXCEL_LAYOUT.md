# Excel layout for care intent rules

Use **either** layout below. File name: `bank_chatbot_v2.xlsx`, `bank_chatbbot.xlsx`, or `bank_chatbot_training_data.xlsx` in this folder (`backend/app/ml/data/`).

---

## Layout A: Training data (one row per phrase) — recommended

**Sheet name:** `intents` (or make it the first sheet).

**Row 1 – column headers (exact spelling, any case):**

| Intent | User Input (Phrase) | Expected Response | Suggested Actions | Short Response |
|--------|---------------------|-------------------|-------------------|----------------|
| CONTACT_SUPPORT | What are your contact options? | Please check the app under Help or Contact us... | Call support, Email support, Talk to agent | |
| CONTACT_SUPPORT | how to contact | ... | Call support, Email support | |
| BALANCE_INQUIRY | what is my balance | I don't have direct access to your live balance... | View balance in app, Talk to agent | You can see your balance in the app... |
| BALANCE_INQUIRY | check balance | ... | View balance in app | |
| TRANSACTION_HISTORY | view transactions | You can view recent transactions in the app... | View transactions in app | Open the app → Activity or Transactions... |

- **Intent** – required. Intent ID (e.g. `CONTACT_SUPPORT`, `BALANCE_INQUIRY`, `TRANSACTION_HISTORY`, `HUMAN_ESCALATION`, `FRAUD_DISPUTE`, `ACCOUNT_LOCKED`, `CARD_BLOCK`, `PIN_RESET`, `BRANCH_ATM`, `COMPLAINT`).
- **User Input (Phrase)** – required. One user phrase per row. Same intent can have many rows (one phrase per row).
- **Expected Response** – optional. Used as the main reply for that intent (first non‑empty row wins per intent).
- **Suggested Actions** – optional. Comma-, semicolon-, or pipe‑separated (e.g. `Call support, Email support, Talk to agent`).
- **Short Response** – optional. Shown for short follow‑ups (first non‑empty row per intent).

Headers are matched after lowercasing and replacing spaces with `_` (e.g. "User Input (Phrase)" → `user_input_(phrase)`). The loader needs a column whose name **starts with** `user_input` and a column **named** `intent`.

---

## Layout B: One row per intent

**Sheet name:** `intents` (or first sheet).

**Row 1 – column headers:**

| id | phrases | response | short_response | short_phrases | suggested_actions | response_no_contact | response_with_contact | max_message_len |
|----|---------|----------|----------------|---------------|-------------------|---------------------|------------------------|-----------------|

- **id** or **intent_id** – required. Intent ID.
- **phrases** – required. All phrases in one cell, separated by commas, semicolons, or pipes (e.g. `contact support, support number, what are your contact options`).
- **response** – main reply.
- **short_response**, **short_phrases** – for short follow‑ups.
- **suggested_actions** – comma/semicolon/pipe separated.
- **response_no_contact** / **response_with_contact** – for CONTACT_SUPPORT (use `{{contact}}` in response_with_contact).
- **max_message_len** – optional number (e.g. 80).
- **prepend_tx_context**, **append_kb** – optional; use `true`/`1`/`yes` for true.

---

## Out-of-scope message (optional)

Add a second sheet named **out_of_scope**.

**Row 1:** `response` | `suggested_actions`  
**Row 2:** Your fallback message text | Balance inquiry, Report fraud, ...

---

## Checklist so the loader uses the Excel (not JSON)

1. File is in `backend/app/ml/data/` and named `bank_chatbot_v2.xlsx`, `bank_chatbbot.xlsx`, or `bank_chatbot_training_data.xlsx`.
2. Sheet with intents is named **intents** or is the **first (active) sheet**.
3. **Layout A:** Row 1 has **Intent** and **User Input (Phrase)** (or any header starting with “User Input”). At least one data row has both Intent and User Input (Phrase) non‑empty.
4. **Layout B:** Row 1 has **id** (or **intent_id**) and **phrases**. At least one data row has id and phrases non‑empty.
5. No empty sheet or completely empty data rows only.

Restart the app (or reload the module) after saving the Excel so `load_intent_rules` runs again.
