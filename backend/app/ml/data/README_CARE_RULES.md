# Care intent rules – file formats

You can maintain rules in any of these (first found is used):

| Format | File name | Use case |
|--------|-----------|----------|
| JSON | `care_intent_rules.json` | Version control, APIs |
| Excel | `care_intent_rules.xlsx` | Edit in Excel or Google Sheets (export as .xlsx) |
| Word | `care_intent_rules.docx` | Edit in Word – use tables (see below) |
| CSV | `care_intent_rules.csv` | Simple spreadsheets, any editor |

**Priority:** `.json` → `.xlsx` → `.docx` → `.csv`. If both `care_intent_rules.json` and `care_intent_rules.xlsx` exist, JSON is used. Rename or remove the one you don’t want to use.

---

## Excel (.xlsx)

- **Sheet name: `intents`** (or the first sheet)
  - Row 1 = headers (spaces become underscores). Suggested columns:
    - `intent_id` or `id` – e.g. BALANCE_INQUIRY, CONTACT_SUPPORT
    - `phrases` – comma-separated trigger phrases (e.g. `balance, my balance, check balance`)
    - `response` – main reply text
    - `short_response` – optional; used for quick follow-ups
    - `short_phrases` – comma-separated; if user message matches, use `short_response`
    - `suggested_actions` – comma-separated chip labels
    - `response_no_contact` – for CONTACT_SUPPORT when no phone/email
    - `response_with_contact` – for CONTACT_SUPPORT; use `{{contact}}` where to insert phone/email
    - `prepend_tx_context` – true/false or 1/0
    - `append_kb` – true/false or 1/0
    - `max_message_len` – number (e.g. 80) or leave empty
- **Sheet name: `out_of_scope`** (optional)
  - Row 1 = headers: `response`, `suggested_actions` (comma-separated)
  - Row 2 = one row with the fallback message and actions

---

## Word (.docx)

- **First table** = intents. Same columns as Excel (first row = headers).
- **Second table** (optional) = out of scope: headers `response`, `suggested_actions`; one data row.

---

## CSV

- One file: `care_intent_rules.csv`
- Same column names as Excel (e.g. `intent_id`, `phrases`, `response`, …). Use comma inside quoted fields if a cell contains commas.
- For out-of-scope, add a row with `intent_id` = empty or `OUT_OF_SCOPE` and set `response` and `suggested_actions`.

---

After you add or change a file, restart the app (or reload rules) and run care training so the intent model is retrained from the file + chat history.
