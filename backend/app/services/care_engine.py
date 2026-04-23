import json
import logging
import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
import difflib

from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.care_rules_loader import load_intent_rules
from app.config import settings
from app.services.artifact_store import fetch_artifact_uri_to_local_path
from app.models import (
    TenantBank,
    Customer,
    Transaction,
    ChatSession,
    ChatMessage,
    KnowledgeChunk,
)
from app.model_paths import resolve_default_care_intent_joblib_path
from app.services.care_transactions import (
    customer_transaction_stats,
    fetch_customer_transaction_detail,
    list_customer_transactions,
    parse_time_range,
    TimeRange,
)
from zoneinfo import ZoneInfo
from app.services.care_llm_router import route_message_llm

logger = logging.getLogger(__name__)


def _normalize_phrase(s: str) -> str:
    """Lower, strip punctuation, collapse spaces; drop optional 'a'/'the' so 'apply for a loan' matches 'apply for loan'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", (s or "").strip())
    t = "".join(c for c in s.lower().strip() if c.isalnum() or c.isspace())
    t = " ".join(t.split())
    for word in (" a ", " the "):
        t = t.replace(word, " ")
    return " ".join(t.split())


def _intent_for_suggested_action(text: str) -> str | None:
    """Map certain tappable chips back to canonical intents.

    This keeps system-suggested actions like 'Stay on channel' and 'Contact support'
    from falling into the generic 'Did you mean...' flow.
    """
    nm = _normalize_phrase(text)
    if not nm:
        return None
    if nm == "stay on channel":
        return "HUMAN_ESCALATION"
    if nm in ("contact support", "call support", "email support"):
        return "CONTACT_SUPPORT"
    if nm == "talk to agent":
        return "HUMAN_ESCALATION"
    if nm in ("view transactions", "view transactions in app"):
        return "TRANSACTION_HISTORY"
    return None


def _keyword_intent(text: str) -> str | None:
    """Very strong keyword hints for certain intents, used when rules don't hit.

    This helps with obvious cases like 'balanc' or 'balance' even when the
    exact phrase isn't in the Excel sheet yet.
    """
    t = _normalize_phrase(text)
    if not t:
        return None
    if "balanc" in t or "balance" in t:
        return "BALANCE_INQUIRY"
    return None


def _fuzzy_token_in_text(text_norm: str, targets: List[str], threshold: float) -> bool:
    """Return True if any token in text_norm is similar to any target."""
    tokens = [t for t in text_norm.split() if t]
    for token in tokens:
        for target in targets:
            if token == target:
                return True
            if difflib.SequenceMatcher(None, token, target).ratio() >= threshold:
                return True
    return False


def _looks_like_security_request(user_message: str) -> bool:
    t = _normalize_phrase(user_message)
    if not t:
        return False

    tokens = [tok for tok in t.split() if tok]
    has_passwordish = any(
        tok.startswith("passw")
        or tok in ("password", "passcode", "credential", "credentials", "creds")
        or difflib.SequenceMatcher(None, tok, "password").ratio() >= 0.76
        for tok in tokens
    )
    has_protective_language = any(
        k in t
        for k in (
            "protect",
            "security",
            "safe",
            "safety",
            "secure",
            "account protection",
            "account safe",
        )
    )

    # Hard keywords first (covers most real users fast even with minor typos).
    hard = (
        "otp",
        "one_time_password",
        "one-time_password",
        "verification_code",
        "2fa",
        "two_factor",
        "twofactor",
        "phish",
        "phishing",
        "smish",
        "smishing",
        "scam",
        "social_engineering",
        "impersonation",
        "credentials",
        "passcode",
        "password",
        "credential",
        "never_share",
        "suspicious_link",
        "suspicious_website",
        "malware",
        "public_wifi",
        "update_phone",
        "update_ios",
        "update_android",
        "transfer_scam",
        "beneficiary_scam",
        "wrong_transfer",
    )
    if any(h in t for h in hard):
        return True

    # Common typo case: "passwor", "passw0rd", etc.
    if has_passwordish and has_protective_language:
        return True

    # Fuzzy for common typos like "phishng", "accidnt", etc.
    if _fuzzy_token_in_text(t, ["phishing", "smishing", "otp", "account"], threshold=0.82):
        return True

    # If user explicitly asks to secure their account, route to security guidance.
    contains_secure = _fuzzy_token_in_text(t, ["secure"], threshold=0.80)
    contains_account = _fuzzy_token_in_text(t, ["account"], threshold=0.74)
    contains_card = _fuzzy_token_in_text(t, ["card", "debit", "credit"], threshold=0.80)
    contains_unlock = _fuzzy_token_in_text(t, ["unlock", "locked", "block", "blocked"], threshold=0.80)
    if contains_secure and contains_account and not contains_card and not contains_unlock:
        return True

    return False


def _log_care_event(event: Dict[str, Any]) -> None:
    """Append a single care analytics event as JSONL.

    Kept deliberately lightweight so it can't break the main flow.
    """
    try:
        base = Path(__file__).resolve().parents[1] / "logs"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "care_events.log"
        payload = dict(event)
        payload.setdefault("ts", time.time())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Don't let analytics failures affect the customer flow.
        logger.debug("failed to log care event", exc_info=True)


def _extract_transaction_ref(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
        raw,
    )
    if m:
        return m.group(0)
    compact = raw.replace(" ", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", compact):
        try:
            return str(uuid.UUID(hex=compact))
        except ValueError:
            pass
    if re.fullmatch(r"[0-9a-fA-F\-]{36}", compact):
        try:
            return str(uuid.UUID(compact))
        except ValueError:
            pass
    m = re.search(
        r"(?:transaction|txn|transfer|payment)\s*(?:id|#|number)?\s*[:#]?\s*([A-Za-z0-9_\-]{4,128})\b",
        raw,
        flags=re.I,
    )
    if m:
        return m.group(1).strip().rstrip(".,;)")
    if len(raw) <= 80 and re.fullmatch(r"[A-Za-z0-9_\-]+", raw) and len(raw) >= 4:
        return raw
    return None


def _cancel_tx_lookup_phrase(tnorm: str) -> bool:
    return tnorm in {
        "cancel",
        "never mind",
        "nevermind",
        "stop",
        "forget it",
        "no thanks",
        "no thank you",
        "dont bother",
        "don't bother",
    }


def _tx_list_or_statement_request(tnorm: str) -> bool:
    """True when user wants lists, counts, exports — not a single-tx fraud check."""
    patterns = (
        "how many",
        "list ",
        "list my",
        "show all",
        "show my",
        "show the",
        "show ",
        "recent transactions",
        "transaction history",
        "transactions this",
        "my transactions for",
        "last 10",
        "last ten",
        "last seven",
        "last 7",
        "this week",
        "this month",
        "more transactions",
        "next page",
        "pdf",
        "download",
        "generate statement",
        "bank statement",
        "my statement",
        "statement pdf",
        "e statement",
        "estatement",
    )
    if any(b in tnorm for b in patterns):
        return True
    if "count" in tnorm and ("transaction" in tnorm or "trans " in tnorm or " txn" in tnorm):
        return True
    return False


def _wants_transaction_detail_lookup(user_message: str) -> bool:
    """True when we should ask for a transaction ID (multi-turn) or single-shot lookup."""
    raw = unicodedata.normalize("NFKC", (user_message or "").strip()).casefold()
    tnorm = _normalize_phrase(user_message)
    if not tnorm and not raw:
        return False
    if _tx_list_or_statement_request(tnorm):
        return False
    # Raw substring: survives odd Unicode / keyboard variants the alnum-stripping step can break.
    if ("unauthor" in raw or "fraud" in raw or "scam" in raw) and any(
        w in raw for w in ("payment", "charge", "transaction", "transfer", "txn", "debit", "purchase")
    ):
        return True
    if not tnorm:
        return False
    triggers = (
        "money is gone",
        "money gone",
        "missing money",
        "money missing",
        "stolen",
        "disappeared",
        "check if",
        "is it fraud",
        "is this fraud",
        "fraud or not",
        "was it fraud",
        "verify transaction",
        "transaction fraud",
        "suspicious transaction",
        "suspicious charge",
        "unauthorised transaction",
        "unauthorized transaction",
        "wrong transaction",
        "look up transaction",
        "lookup transaction",
        "track my transaction",
        "track transaction",
        "transaction status",
        "why was my",
        "why was declined",
        "payment declined",
        "can you check",
        "investigate transaction",
        "unauthorised payment",
        "unauthorized payment",
        "someone took",
        "took money",
        "didnt authorize",
        "didn't authorize",
        "charged me",
        "unknown charge",
        "unrecognised",
        "unrecognized",
        "dont recognise",
        "don't recognise",
        "dont recognize",
        "don't recognize",
    )
    if any(x in tnorm for x in triggers):
        return True
    fraud_charge_probe = (
        any(
            k in tnorm
            for k in (
                "unauthor",
                "fraud",
                "fraudulent",
                "scam",
                "stolen",
                "hacked",
                "not me",
                "wasnt me",
                "wasn't me",
                "didnt make",
                "didn't make",
            )
        )
        and any(
            w in tnorm
            for w in (
                "payment",
                "payement",
                "charge",
                "transaction",
                "transfer",
                "money",
                "debit",
                "credit",
                "purchase",
                "withdraw",
            )
        )
    )
    if fraud_charge_probe:
        return True
    dispute_specific = "dispute" in tnorm and any(
        w in tnorm for w in ("charge", "payment", "transaction", "transfer", "fraud", "scam", "wrong")
    )
    return bool(dispute_specific)


def _ref_pairs_with_lookup_intent(tnorm: str, ref: str | None) -> bool:
    if not ref:
        return False
    hints = (
        "check",
        "verify",
        "look up",
        "lookup",
        "find",
        "track",
        "status",
        "fraud",
        "suspicious",
        "wrong",
        "investigate",
        "transaction",
        "txn",
        "payment",
        "transfer",
        "this",
        "that",
    )
    return any(h in tnorm for h in hints)


def _format_transaction_detail_for_care(detail: Dict[str, Any], bank: TenantBank) -> str:
    tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
    tz = ZoneInfo(tz_name)
    ts = detail.get("timestamp")
    ts_h = "—"
    if ts:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            dt = dt.astimezone(tz)
            label = "GMT" if tz_name == "Africa/Accra" else (dt.strftime("%Z") or tz_name)
            ts_h = dt.strftime("%d %b %Y, %H:%M ") + label
        except Exception:
            ts_h = str(ts)
    amt = detail.get("amount")
    try:
        amt_s = f"{float(amt):,.2f}" if amt is not None else "—"
    except Exception:
        amt_s = str(amt)
    merchant = detail.get("merchant_name") or detail.get("merchant_category") or "—"
    lines = [
        f"Here's what I see for transaction **{detail.get('external_tx_id') or '—'}**:",
        f"• When: {ts_h}",
        f"• Amount: {amt_s} {detail.get('currency') or ''}",
        f"• Merchant / category: {merchant}",
        f"• Channel: {detail.get('channel') or '—'} · Status: {detail.get('status') or '—'}",
    ]
    if detail.get("model_decision"):
        fs = detail.get("fraud_score")
        try:
            fs_s = f"{float(fs):.3f}" if fs is not None else "n/a"
        except Exception:
            fs_s = "n/a"
        lines.append(
            f"• Fraud engine decision: **{detail['model_decision']}** (risk score {fs_s}, "
            f"confidence {detail.get('model_confidence') or '—'})."
        )
        dec = str(detail["model_decision"])
        if dec == "BLOCK":
            lines.append("  This payment was blocked or treated as high risk.")
        elif dec == "REQUEST_OTP":
            lines.append("  The system asked for extra verification (e.g. OTP) before approving.")
        elif dec in ("APPROVE", "LIMITED_APPROVAL"):
            lines.append("  The system allowed this payment (possibly with limits).")
    else:
        lines.append("• No fraud-engine score on file yet for this payment (it may still be pending).")
    if detail.get("reason_codes"):
        rc = ", ".join(str(x) for x in (detail["reason_codes"] or [])[:5])
        lines.append(f"• Signals flagged: {rc}")
    if detail.get("outcome_classification"):
        oc = detail["outcome_classification"]
        src = detail.get("outcome_source")
        lines.append(
            f"• Recorded outcome: **{oc}**" + (f" ({src})" if src else "") + "."
        )
    lines.append(
        "\nIf this doesn't match what you expect, tap **Talk to agent** and we'll connect you to a person."
    )
    return "\n".join(lines)


async def _maybe_transaction_detail_lookup_reply(
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer,
    session: ChatSession,
    user_message: str,
) -> tuple[str, str | None] | None:
    """
    Multi-turn: ask for transaction ID, then return DB+fraud details for that payment (this customer only).
    """
    tnorm = _normalize_phrase(user_message)
    ctx = session.metadata_ or {}
    pending = ctx.get("tx_id_lookup_pending") is True

    if pending and "thank" in tnorm and len(tnorm) < 48:
        session.metadata_ = {**ctx, "tx_id_lookup_pending": False}
        await db.flush()
        return "You're welcome! If you need another transaction checked, just ask.", None

    if pending and _cancel_tx_lookup_phrase(tnorm):
        session.metadata_ = {**ctx, "tx_id_lookup_pending": False}
        await db.flush()
        return "Okay — cancelled. Tell me if you need anything else.", None

    ref = _extract_transaction_ref(user_message)

    if pending:
        pivot = any(
            p in tnorm
            for p in (
                "show ",
                "list ",
                "how many",
                "statement",
                "pdf",
                "transaction history",
                "recent transactions",
            )
        )
        if pivot:
            session.metadata_ = {**ctx, "tx_id_lookup_pending": False}
            await db.flush()
            return None
        if not ref:
            return (
                "Please send your **transaction ID** (from the app or bank SMS), or say **cancel**.",
                None,
            )
        detail = await fetch_customer_transaction_detail(
            db=db, bank=bank, customer=customer, ref=ref
        )
        session.metadata_ = {**ctx, "tx_id_lookup_pending": False}
        await db.flush()
        if not detail:
            return (
                f"I couldn't find **{ref}** on your account. Check the ID or open **View transactions** and copy it from the payment details.",
                None,
            )
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "transaction_detail_lookup",
                "intent": "TRANSACTION_DETAIL_LOOKUP",
                "user_message": user_message,
                "ref": ref,
            }
        )
        return _format_transaction_detail_for_care(detail, bank), None

    if ref and _ref_pairs_with_lookup_intent(tnorm, ref):
        detail = await fetch_customer_transaction_detail(
            db=db, bank=bank, customer=customer, ref=ref
        )
        if detail:
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "transaction_detail_lookup",
                    "intent": "TRANSACTION_DETAIL_LOOKUP",
                    "user_message": user_message,
                    "ref": ref,
                    "single_shot": True,
                }
            )
            return _format_transaction_detail_for_care(detail, bank), None
        return (
            f"I couldn't find **{ref}** on your account. Double-check the transaction ID.",
            None,
        )

    if _wants_transaction_detail_lookup(user_message) and not ref:
        session.metadata_ = {**ctx, "tx_id_lookup_pending": True}
        await db.flush()
        _log_care_event(
            {
                "kind": "care_tx_lookup_prompt",
                "user_message": user_message,
            }
        )
        return (
            "I can look up that payment and show what our fraud system decided. "
            "Please send your **transaction ID** (the one in your app or bank message). "
            "If you're not sure where to find it, tap **View transactions** and open the payment — the ID is on the details screen.",
            None,
        )

    return None


async def _maybe_tx_analytics_reply(
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer | None,
    session: ChatSession,
    user_message: str,
) -> tuple[str, str | None] | None:
    """
    Answer user questions about *their* transactions using DB queries.

    This is deliberately deterministic: the request is scoped to the resolved
    Customer row, so it can't leak other users' data.
    """
    if customer is None:
        return None

    t = _normalize_phrase(user_message)
    if not t:
        return None

    ctx = session.metadata_ or {}
    llm_route = None
    if os.getenv("CARE_USE_LLM_ROUTER", "1") == "1":
        try:
            llm_route = route_message_llm(user_message, ctx)
        except Exception:
            llm_route = None
    if llm_route is not None:
        _log_care_event(
            {
                "kind": "care_router",
                "source": "llm_router",
                "session_id": str(session.metadata_.get("external_session_id") if session.metadata_ else ""),
                "customer_external_id": customer.external_id if customer else None,
                "user_message": user_message,
                "route": {
                    "intent": llm_route.intent,
                    "range": llm_route.range,
                    "decision": llm_route.decision,
                    "wants_pdf": llm_route.wants_pdf,
                    "confidence": llm_route.confidence,
                },
            }
        )

    # PDF follow-up: if we previously offered a statement and user agrees, generate link.
    pdf_pending = bool((session.metadata_ or {}).get("pdf_offer_pending"))
    wants_repeat = t in ("again", "do it again", "repeat", "redo", "run it again")
    dissatisfaction = any(
        k in t
        for k in (
            "do it properly",
            "not working",
            "doesnt work",
            "i dont like",
            "i do not like",
            "this is bad",
            "terrible",
            "fix it",
        )
    )

    # If the user moved into a non-transaction security topic while a PDF was
    # pending from the previous turn, cancel the pending PDF flow.
    # This prevents unrelated messages (e.g. PIN reset) from triggering
    # "Done — tap Download PDF statement" after the user presses a lingering "Yes".
    security_interrupt = any(
        k in t
        for k in (
            "pin",
            "reset pin",
            "change pin",
            "forgot pin",
            "password",
            "passcode",
            "phishing",
            "phish",
            "smishing",
            "otp",
            "one time password",
            "block card",
            "card block",
            "freeze card",
            "unlock account",
            "account locked",
        )
    )
    transaction_mention = any(
        k in t
        for k in (
            "transaction",
            "transactions",
            "statement",
            "fraud",
            "approved",
            "limited approval",
            "decision",
        )
    )
    if pdf_pending and security_interrupt and not transaction_mention:
        session.metadata_ = {**ctx, "pdf_offer_pending": False}
        pdf_pending = False
        await db.flush()

    def _regen_pdf(range_key_saved: str) -> tuple[str, str]:
        now = int(datetime.now(timezone.utc).timestamp())
        token = jwt.encode(
            {
                "iss": "bankai",
                "aud": "bankai-care-pdf",
                "tenant_id": str(bank.id),
                "customer_external_id": customer.external_id if customer else None,
                "range": str(range_key_saved),
                "iat": now,
                "exp": now + 60 * 5,
            },
            settings.care_jwt_secret,
            algorithm="HS256",
        )
        pdf_url = "/api/v1/care/statement.pdf?token=" + token
        return token, pdf_url

    if wants_repeat:
        # If user asks to repeat and we recently offered/generated a PDF, regenerate it.
        range_key_saved = ctx.get("pdf_range") or ctx.get("last_range")
        if range_key_saved:
            token, pdf_url = _regen_pdf(str(range_key_saved))
            session.metadata_ = {**ctx, "pdf_offer_pending": False, "pdf_last_token": token, "last_action": "generated_pdf"}
            await db.flush()
            return "Sure — I regenerated your PDF statement. Tap “Download PDF statement”.", pdf_url

    # If user is unhappy while in a PDF flow, keep them on the PDF track.
    if dissatisfaction and (ctx.get("pdf_range") or ctx.get("pdf_last_token") or ctx.get("last_action") in ("generated_pdf", "listed_transactions", "counted_transactions")):
        rk = str(ctx.get("pdf_range") or ctx.get("last_range") or "this_week")
        token, pdf_url = _regen_pdf(rk)
        session.metadata_ = {**ctx, "pdf_offer_pending": False, "pdf_last_token": token, "last_action": "generated_pdf"}
        await db.flush()
        return (
            "Got you. I regenerated it properly. Tap “Download PDF statement”. If the button isn’t visible, scroll a bit and try again.",
            pdf_url,
        )

    if pdf_pending:
        agree = (
            t in ("yes", "y", "ok", "okay", "sure", "yes please")
            or ("generate" in t and "pdf" in t)
            or (t == "pdf")
        )
        if agree:
            range_key_saved = (session.metadata_ or {}).get("pdf_range") or "this_week"
            token, pdf_url = _regen_pdf(str(range_key_saved))
            session.metadata_ = {**ctx, "pdf_offer_pending": False, "pdf_last_token": token, "last_action": "generated_pdf"}
            await db.flush()
            return "Done — tap “Download PDF statement”.", pdf_url
        if t in ("no", "nope") or "not now" in t:
            session.metadata_ = {**ctx, "pdf_offer_pending": False}
            await db.flush()
            return "No problem — tell me anytime if you want a PDF statement.", None

    # Contextual follow-ups (no explicit keywords needed)
    wants_more = t in ("more", "next", "show more", "next page")
    wants_prev = t in ("prev", "previous", "back", "prior")
    wants_download = ("download" in t and ("pdf" in t or "statement" in t)) or t in ("download it", "download", "statement", "pdf statement")

    last_action = ctx.get("last_action")
    if last_action in ("listed_transactions", "counted_transactions"):
        # Allow range-only follow-up like "this week" / "yesterday" to reuse last action.
        range_only = t in ("today", "yesterday", "this week", "this month", "recent", "all", "since monday") or ("between " in t) or ("last " in t and " day" in t)
        if wants_download:
            # Generate PDF for last range immediately.
            range_key_saved = ctx.get("last_range") or "this_week"
            now = int(datetime.now(timezone.utc).timestamp())
            token = jwt.encode(
                {
                    "iss": "bankai",
                    "aud": "bankai-care-pdf",
                    "tenant_id": str(bank.id),
                    "customer_external_id": customer.external_id if customer else None,
                    "range": str(range_key_saved),
                    "iat": now,
                    "exp": now + 60 * 5,
                },
                settings.care_jwt_secret,
                algorithm="HS256",
            )
            session.metadata_ = {**ctx, "pdf_offer_pending": False, "pdf_last_token": token}
            await db.flush()
            return "Done — tap “Download PDF statement”.", "/api/v1/care/statement.pdf?token=" + token

    wants_count = any(k in t for k in ("how many", "count", "number of", "total"))
    wants_list = any(k in t for k in ("show", "list", "recent", "latest", "last ", "today", "yesterday"))
    mentions_tx = "transaction" in t or "transactions" in t or "txn" in t
    mentions_decision = any(k in t for k in ("approved", "approve", "otp", "limited", "block", "blocked", "decision"))
    mentions_fraud = "fraud" in t or "fraudulent" in t or "scam" in t

    # SECURITY vs TRANSACTION-analytics disambiguation:
    # If the user is describing a scam (sms/email/calls asking for otp), treat it as
    # security guidance, not "OTP-related transaction decision" analytics.
    scam_context = any(
        k in t
        for k in (
            "sms",
            "text",
            "email",
            "call",
            "caller",
            "scam",
            "asked",
            "someone",
            "share",
            "sharing",
            "code",
            "verification",
            "one-time",
            "one time",
            "phish",
            "link",
            "website",
            "urgent",
            "act now",
            "verify",
            "suspicious",
        )
    )
    transaction_intent = any(
        k in t
        for k in (
            "transaction",
            "transactions",
            "txn",
            "history",
            "statement",
            "list",
            "show",
            "how many",
            "count",
            "total",
            "breakdown",
            "limited approval",
            "request otp",
            "approved",
            "decision",
        )
    )
    if _looks_like_security_request(user_message) and scam_context and not transaction_intent:
        return None

    # Override with LLM router if it produced a confident route.
    if llm_route and (llm_route.intent != "UNKNOWN") and ((llm_route.confidence or 0.75) >= 0.55):
        if llm_route.intent in ("PAGINATE_NEXT", "PAGINATE_PREV"):
            wants_more = llm_route.intent == "PAGINATE_NEXT"
            wants_prev = llm_route.intent == "PAGINATE_PREV"
            mentions_tx = False  # rely on context pagination handler below
            mentions_decision = False
            mentions_fraud = False
        if llm_route.intent in ("PDF_GENERATE", "PDF_REPEAT"):
            wants_download = True
        if llm_route.intent in ("TX_STATS", "TX_FRAUDLIKE_STATS"):
            wants_count = True
            wants_list = False
            mentions_tx = True
            mentions_fraud = llm_route.intent == "TX_FRAUDLIKE_STATS"
        if llm_route.intent in ("TX_LIST", "TX_FRAUDLIKE_LIST"):
            wants_list = True
            wants_count = False
            mentions_tx = True
            mentions_fraud = llm_route.intent == "TX_FRAUDLIKE_LIST"
        if llm_route.range:
            # Make the range parser see it
            t = t + " " + llm_route.range.lower()
        if llm_route.decision:
            t = t + " " + llm_route.decision.lower()

    if not (mentions_tx or mentions_decision or mentions_fraud):
        # Pagination follow-ups based purely on context
        if last_action == "listed_transactions" and (wants_more or wants_prev):
            tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
            tz = ZoneInfo(tz_name)
            range_key = ctx.get("last_range") or "this_week"
            tr = parse_time_range(time_range_key=str(range_key), tz_name=tz_name)
            decision_in = ctx.get("last_filter")  # list[str] | None
            limit = int(ctx.get("last_limit") or 10)
            offset = int(ctx.get("last_offset") or 0)
            if wants_more:
                offset = offset + limit
            if wants_prev:
                offset = max(0, offset - limit)
            txs = await list_customer_transactions(
                db=db,
                bank=bank,
                customer=customer,
                time_range=tr,
                limit=limit,
                offset=offset,
                decision_in=decision_in,  # type: ignore[arg-type]
            )
            if not txs:
                return "No more transactions in that direction.", None

            def _fmt_ts(value: str | None) -> str:
                if not value:
                    return "—"
                try:
                    v = str(value).strip()
                    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    dt = dt.astimezone(tz)
                    label = "GMT" if (tz_name == "Africa/Accra") else (dt.strftime("%Z") or tz_name)
                    return dt.strftime("%d %b %Y, %H:%M ") + label
                except Exception:
                    v = str(value).strip().replace("T", " ").replace("Z", "+00:00")
                    if "+00:00" in v:
                        v = v.split("+00:00", 1)[0]
                    if "." in v:
                        v = v.split(".", 1)[0]
                    return v

            lines = []
            for x in txs[:limit]:
                amt = x.get("amount")
                try:
                    amt_s = f"{float(amt):,.2f}" if amt is not None else "—"
                except Exception:
                    amt_s = str(amt) if amt is not None else "—"
                lines.append(
                    f"- {_fmt_ts(x.get('timestamp'))} · Transaction ID: {x.get('transaction_id','—')} · {amt_s} {x.get('currency') or ''} · "
                    f"{x.get('merchant') or x.get('merchant_category') or '—'} · {x.get('model_decision') or '—'}"
                )
            session.metadata_ = {**ctx, "last_offset": offset}
            await db.flush()
            return "More transactions (" + str(range_key).replace("_", " ") + "):\n" + "\n".join(lines), None

        return None

    # Time range
    range_key = None

    # Explicit date range: "between 2026-03-01 and 2026-03-10"
    mb = re.search(r"between\\s+(\\d{4}-\\d{2}-\\d{2})\\s+and\\s+(\\d{4}-\\d{2}-\\d{2})", t)
    tz_name = ((bank.tone_config or {}).get("timezone") or "Africa/Accra").strip()
    tz = ZoneInfo(tz_name)

    if mb:
        try:
            # Interpret dates in bank timezone: [start 00:00, end 24:00)
            s_local = datetime.fromisoformat(mb.group(1)).replace(tzinfo=tz)
            e_local = datetime.fromisoformat(mb.group(2)).replace(tzinfo=tz) + timedelta(days=1)
            tr = TimeRange(start=s_local.astimezone(timezone.utc), end=e_local.astimezone(timezone.utc))
        except Exception:
            tr = parse_time_range(time_range_key="this_week", tz_name=tz_name)
        range_key = f"between {mb.group(1)} and {mb.group(2)}"
    else:
        tr = None

    m = re.search(r"last\\s+(\\d{1,3})\\s+day", t)
    if m:
        range_key = f"last_{m.group(1)}d"
    elif "today" in t:
        range_key = "today"
    elif "yesterday" in t:
        range_key = "yesterday"
    elif "since monday" in t:
        range_key = "since_monday"
    elif "this week" in t or "week" in t:
        range_key = "this_week"
    elif "this month" in t or "month" in t:
        range_key = "this_month"
    elif "all" in t or "history" in t:
        range_key = "all"
    elif "recent" in t or "latest" in t or "last" in t:
        range_key = "recent"
    if tr is None:
        tr = parse_time_range(time_range_key=range_key, tz_name=tz_name)

    # If user said something like "today transaction" without "show/list/how many",
    # default to listing recent matching transactions.
    if mentions_tx and not wants_count and not wants_list and range_key in (
        "today",
        "yesterday",
        "this_week",
        "this_month",
        "recent",
        "all",
        "since_monday",
    ):
        wants_list = True

    # Decision filters
    decision_in: list[str] | None = None
    if mentions_fraud:
        decision_in = ["BLOCK", "REQUEST_OTP"]
    else:
        ds: list[str] = []
        if "approve" in t or "approved" in t:
            ds.append("APPROVE")
        if "limited" in t:
            ds.append("LIMITED_APPROVAL")
        if "otp" in t:
            ds.append("REQUEST_OTP")
        if "block" in t or "blocked" in t:
            ds.append("BLOCK")
        if ds:
            decision_in = list(dict.fromkeys(ds))

    def _fmt_ts(value: str | None) -> str:
        if not value:
            return "—"
        try:
            v = str(value).strip()
            # Handle common forms:
            # - 2026-03-18T00:42:34.196607+00:00
            # - 2026-03-18T00:42:34Z
            # - 2026-03-18 00:42:34.196607+00:00
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            dt = dt.astimezone(tz)
            # Prefer stable bank label for users (e.g. "GMT"), but fall back to tz abbreviation.
            label = "GMT" if (tz_name == "Africa/Accra") else (dt.strftime("%Z") or tz_name)
            # Always human-friendly, no seconds/micros.
            return dt.strftime("%d %b %Y, %H:%M ") + label
        except Exception:
            # Last-resort: keep it readable without duplicating parts.
            v = str(value).strip()
            v = v.replace("T", " ").replace("Z", "+00:00")
            if "+00:00" in v:
                v = v.split("+00:00", 1)[0]
            if "." in v:
                v = v.split(".", 1)[0]
            return v

    if wants_list and (mentions_tx or mentions_fraud or mentions_decision):
        limit = 10
        offset = 0
        txs = await list_customer_transactions(
            db=db,
            bank=bank,
            customer=customer,
            time_range=tr,
            limit=limit,
            offset=offset,
            decision_in=decision_in,  # type: ignore[arg-type]
        )
        if not txs:
            return "I couldn’t find any matching transactions for that period.", None
        lines = []
        for x in txs[:limit]:
            amt = x.get("amount")
            try:
                amt_s = f"{float(amt):,.2f}" if amt is not None else "—"
            except Exception:
                amt_s = str(amt) if amt is not None else "—"
            lines.append(
                f"- {_fmt_ts(x.get('timestamp'))} · Transaction ID: {x.get('transaction_id','—')} · {amt_s} {x.get('currency') or ''} · "
                f"{x.get('merchant') or x.get('merchant_category') or '—'} · {x.get('model_decision') or '—'}"
            )
        period = range_key or "this_week"
        if mentions_fraud:
            reply = (
                "Here are your fraud-like transactions (blocked or OTP-required) ("
                + period.replace("_", " ")
                + "):\n"
                + "\n".join(lines)
            )
        else:
            reply = "Here are your matching transactions (" + period.replace("_", " ") + "):\n" + "\n".join(lines)

        session.metadata_ = {
            **ctx,
            "pdf_offer_pending": True,
            "pdf_range": range_key or "this_week",
            "last_action": "listed_transactions",
            "last_range": range_key or "this_week",
            "last_filter": decision_in,
            "last_limit": limit,
            "last_offset": offset,
        }
        await db.flush()
        return reply + "\n\nI can generate a PDF statement for this period. Reply “yes” if you’d like one.", None

    if wants_count or mentions_decision or mentions_fraud:
        stats = await customer_transaction_stats(db=db, bank=bank, customer=customer, time_range=tr)
        by = stats.get("by_decision") or {}
        period = (range_key or "this_week").replace("_", " ")
        parts = []
        for k in ("APPROVE", "LIMITED_APPROVAL", "REQUEST_OTP", "BLOCK"):
            if k in by:
                parts.append(f"{k}: {by.get(k)}")
        total = stats.get("total_transactions", 0)
        scored = stats.get("scored_transactions", 0)
        fraud_like = stats.get("fraud_like_transactions", 0)
        detail = ", ".join(parts) if parts else "No scored decisions yet."
        if mentions_fraud:
            reply = (
                f"Over {period}, you have {fraud_like} fraud-like transactions "
                f"(blocked or OTP-required). Breakdown: {detail}"
            )
        else:
            reply = (
                f"Over {period}, you have {total} transactions ({scored} scored by the fraud engine). "
                f"Decision breakdown: {detail}"
            )

        session.metadata_ = {
            **ctx,
            "pdf_offer_pending": True,
            "pdf_range": range_key or "this_week",
            "last_action": "counted_transactions",
            "last_range": range_key or "this_week",
            "last_filter": decision_in,
        }
        await db.flush()
        return reply + "\n\nI can also generate a PDF statement for this period. Reply “yes” if you’d like one.", None

    return None


async def _get_or_create_session(
    db: AsyncSession,
    bank: TenantBank,
    session_id: str,
    channel: str,
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.tenant_id == bank.id,
            ChatSession.metadata_["external_session_id"].as_string() == session_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is not None:
        return session

    # Create a new chat session
    session = ChatSession(
        tenant_id=bank.id,
        customer_id=None,
        channel=channel,
        metadata_={"external_session_id": session_id},
    )
    db.add(session)
    await db.flush()
    return session


async def _resolve_customer(
    db: AsyncSession,
    bank: TenantBank,
    external_id: str | None,
) -> Customer | None:
    if not external_id:
        return None
    result = await db.execute(
        select(Customer).where(
            Customer.tenant_id == bank.id,
            Customer.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def _recent_transactions(
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer | None,
    limit: int = 10,
) -> List[Transaction]:
    if customer is None:
        return []
    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.tenant_id == bank.id,
            Transaction.customer_id == customer.id,
        )
        .order_by(Transaction.tx_timestamp.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _summarise_customer_context(
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer | None,
) -> Dict[str, Any]:
    if customer is None:
        return {
            "has_customer": False,
        }
    txns = await _recent_transactions(db, bank, customer, limit=10)
    recent = [
        {
            "amount": float(t.amount),
            "currency": t.currency,
            "merchant": t.merchant_name,
            "category": t.merchant_category,
            "country": t.location_country,
            "channel": t.channel,
            "timestamp": t.tx_timestamp.isoformat(),
            "status": t.status,
        }
        for t in txns
    ]
    return {
        "has_customer": True,
        "customer_external_id": customer.external_id,
        "risk_score": customer.risk_score,
        "account_count": customer.account_count,
        "is_flagged": customer.is_flagged,
        "recent_transactions": recent,
    }


def _build_intent_actions(intents: List[Dict], out_of_scope: Dict) -> Tuple[Dict[str, List[str]], List[str]]:
    actions: Dict[str, List[str]] = {"GENERAL_SUPPORT": ["View transactions", "Raise dispute", "Talk to agent"]}
    for r in intents:
        aid = (r.get("id") or "").strip()
        if aid and isinstance(r.get("suggested_actions"), list):
            actions[aid] = [str(a) for a in r["suggested_actions"]]
    oos = out_of_scope.get("suggested_actions")
    oos_actions = list(oos) if isinstance(oos, list) else []
    return actions, oos_actions


_CARE_RULES_DIR = Path(__file__).resolve().parent.parent / "ml" / "data"
_CARE_INTENTS, _CARE_OUT_OF_SCOPE = load_intent_rules(_CARE_RULES_DIR)
INTENT_ACTIONS, OUT_OF_SCOPE_ACTIONS = _build_intent_actions(_CARE_INTENTS, _CARE_OUT_OF_SCOPE)

# Intents where we always want a human in the loop for anything account‑specific
# and should explicitly nudge the user to escalate rather than acting purely
# as self‑service help.
REQUIRES_HUMAN_CONFIRMATION: set[str] = {
    "LOAN_APPLICATION",
    "FRAUD_DISPUTE",
    "ACCOUNT_LOCKED",
    "CARD_BLOCK",
    "PIN_RESET",
    "COMPLAINT",
}


def summarise_care_events(window_hours: int = 24) -> Dict[str, Any]:
    """Summarise recent care behaviour from the JSONL log for a quick health check.

    This scans backend/app/logs/care_events.log for the last `window_hours` and
    returns basic rates that you can show in an internal dashboard.
    """
    path = Path(__file__).resolve().parents[1] / "logs" / "care_events.log"
    if not path.exists():
        return {
            "window_hours": window_hours,
            "total_replies": 0,
            "rule_hits": 0,
            "model_suggestions": 0,
            "fuzzy_suggestions": 0,
            "out_of_scope": 0,
            "escalations": 0,
            "rule_hit_rate": 0.0,
            "suggestion_rate": 0.0,
            "out_of_scope_rate": 0.0,
            "escalation_rate": 0.0,
            "intent_counts": {},
            "low_volume_intents": [],
            "alerts": ["no_events"],
        }

    cutoff = time.time() - window_hours * 3600
    total = 0
    rule_hits = model_sug = fuzzy_sug = oos = escalations = 0
    intent_counts: Dict[str, int] = {}

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                ts = float(ev.get("ts", 0))
                if ts < cutoff:
                    continue
                if ev.get("kind") != "care_reply":
                    continue
                total += 1
                intent = str(ev.get("intent") or "UNKNOWN")
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
                src = ev.get("source")
                if src == "rule":
                    rule_hits += 1
                elif src == "model_suggestions":
                    model_sug += 1
                elif src == "fuzzy_suggestions":
                    fuzzy_sug += 1
                elif src == "out_of_scope":
                    oos += 1
                if ev.get("escalate"):
                    escalations += 1
    except Exception:
        logger.exception("failed to summarise care events")
        return {
            "window_hours": window_hours,
            "total_replies": 0,
            "rule_hits": 0,
            "model_suggestions": 0,
            "fuzzy_suggestions": 0,
            "out_of_scope": 0,
            "escalations": 0,
            "rule_hit_rate": 0.0,
            "suggestion_rate": 0.0,
            "out_of_scope_rate": 0.0,
            "escalation_rate": 0.0,
            "intent_counts": {},
            "low_volume_intents": [],
            "alerts": ["error"],
        }

    if total == 0:
        return {
            "window_hours": window_hours,
            "total_replies": 0,
            "rule_hits": 0,
            "model_suggestions": 0,
            "fuzzy_suggestions": 0,
            "out_of_scope": 0,
            "escalations": 0,
            "rule_hit_rate": 0.0,
            "suggestion_rate": 0.0,
            "out_of_scope_rate": 0.0,
            "escalation_rate": 0.0,
            "intent_counts": intent_counts,
            "low_volume_intents": [],
            "alerts": [],
        }

    suggestion_total = model_sug + fuzzy_sug
    rule_hit_rate = rule_hits / total
    suggestion_rate = suggestion_total / total
    out_of_scope_rate = oos / total
    escalation_rate = escalations / total

    # Heuristic alerts; you can tune these thresholds per bank.
    alerts: List[str] = []
    if out_of_scope_rate > 0.3:
        alerts.append("high_out_of_scope_rate")
    if escalation_rate > 0.5:
        alerts.append("high_escalation_rate")

    # Any known intent that saw 0 traffic in the window might indicate a config issue.
    low_volume_intents: List[str] = []
    for r in _CARE_INTENTS:
        intent_id = (r.get("id") or "").strip()
        if not intent_id:
            continue
        if intent_counts.get(intent_id, 0) == 0:
            low_volume_intents.append(intent_id)

    return {
        "window_hours": window_hours,
        "total_replies": total,
        "rule_hits": rule_hits,
        "model_suggestions": model_sug,
        "fuzzy_suggestions": fuzzy_sug,
        "out_of_scope": oos,
        "escalations": escalations,
        "rule_hit_rate": round(rule_hit_rate, 4),
        "suggestion_rate": round(suggestion_rate, 4),
        "out_of_scope_rate": round(out_of_scope_rate, 4),
        "escalation_rate": round(escalation_rate, 4),
        "intent_counts": intent_counts,
        "low_volume_intents": low_volume_intents,
        "alerts": alerts,
    }


def _build_suggestion_index(intents: List[Dict]) -> List[Dict[str, str]]:
    """Flatten all phrases from rules into a suggestion index."""
    index: List[Dict[str, str]] = []
    for r in intents:
        intent_id = (r.get("id") or "").strip()
        if not intent_id:
            continue
        for p in r.get("phrases") or []:
            phrase = (p or "").strip()
            if phrase:
                index.append({"phrase": phrase, "intent": intent_id})
    return index


_SUGGESTION_INDEX: List[Dict[str, str]] = _build_suggestion_index(_CARE_INTENTS)


def _phrases_for_intent(intent_id: str) -> List[str]:
    phrases: List[str] = []
    for r in _CARE_INTENTS:
        if (r.get("id") or "").strip() == intent_id:
            for p in r.get("phrases") or []:
                text = (p or "").strip()
                if text:
                    phrases.append(text)
    return phrases


def _load_general_chat() -> List[Dict[str, str]]:
    path = Path(__file__).resolve().parent.parent / "ml" / "data" / "general_chat.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


GENERAL_CHAT: List[Dict[str, str]] = _load_general_chat()

_CARE_INTENT_MODEL: Any = None
_CARE_INTENT_MODEL_BY_ARTIFACT: Dict[str, Any] = {}


def _resolve_care_artifact_model_path(model_artifact_uri: str | None) -> Path:
    if model_artifact_uri:
        p = fetch_artifact_uri_to_local_path(model_artifact_uri)
        if p is None:
            # unresolved remote URI; preserve existing behavior by returning a missing path.
            return Path("/nonexistent/care_intent_model.joblib")
        if p.is_dir():
            return p / "care_intent_model.joblib"
        return p
    return resolve_default_care_intent_joblib_path()


def _load_care_intent_model(model_artifact_uri: str | None = None) -> Any:
    global _CARE_INTENT_MODEL
    if not model_artifact_uri and _CARE_INTENT_MODEL is not None:
        return _CARE_INTENT_MODEL
    path = _resolve_care_artifact_model_path(model_artifact_uri)
    if model_artifact_uri:
        cached = _CARE_INTENT_MODEL_BY_ARTIFACT.get(str(path))
        if cached is not None:
            return cached
    if not path.exists():
        return None
    try:
        import joblib
        model = joblib.load(path)
        if model_artifact_uri:
            _CARE_INTENT_MODEL_BY_ARTIFACT[str(path)] = model
            return model
        _CARE_INTENT_MODEL = model
        return _CARE_INTENT_MODEL
    except Exception:
        return None


def _predict_intent_from_model(message: str, model_artifact_uri: str | None = None) -> Tuple[str | None, float]:
    """Returns (intent, confidence) or (None, 0) if no model or low confidence."""
    model = _load_care_intent_model(model_artifact_uri=model_artifact_uri)
    if model is None:
        return None, 0.0
    pipeline = model.get("pipeline")
    le = model.get("label_encoder")
    if not pipeline or not le:
        return None, 0.0
    try:
        pred = pipeline.predict([message])
        proba = pipeline.predict_proba([message])[0]
        idx = int(pred[0])
        conf = float(proba[idx])
        intent = str(le.inverse_transform([idx])[0])
        return intent, conf
    except Exception:
        pass
    return None, 0.0


def _did_you_mean_suggestions(
    text: str,
    max_suggestions: int = 5,
) -> List[str]:
    """Return up to N similar phrases from rules for clarification.

    More forgiving than exact matching:
    - uses token overlap (including substrings) plus a light similarity score
    - always returns top matches when there is *any* reasonable overlap
    """
    msg = text.lower().strip()
    if not msg:
        return []

    # Ensure we have an index even if initial load failed
    global _SUGGESTION_INDEX
    if not _SUGGESTION_INDEX:
        _SUGGESTION_INDEX = _build_suggestion_index(_CARE_INTENTS)
        if not _SUGGESTION_INDEX:
            return []

    # Simple tokenisation – enough for our banking phrases
    raw_tokens = [t.strip(".,!?;:") for t in msg.split()]
    tokens = [t for t in raw_tokens if t]
    if not tokens:
        return []

    scored: List[Tuple[float, str]] = []
    for entry in _SUGGESTION_INDEX:
        phrase = entry["phrase"]
        pl = phrase.lower()
        phrase_tokens = [p.strip(".,!?;:") for p in pl.split()]

        overlap = 0
        for t in tokens:
            for p in phrase_tokens:
                if not t or not p:
                    continue
                # direct containment or loose prefix matching for typos (balanc ~ balance)
                if t in p or p in t or (len(t) >= 4 and len(p) >= 4 and t[:4] == p[:4]):
                    overlap += 1
                    break
        # also include a coarse similarity score for insurance
        ratio = difflib.SequenceMatcher(None, msg, pl).ratio()
        score = overlap + ratio  # overlap dominates, ratio nudges ranking
        if score > 0:
            scored.append((score, phrase))

    if not scored:
        # Fallback: pure similarity over all phrases so we *always* offer something
        backup: List[Tuple[float, str]] = []
        for entry in _SUGGESTION_INDEX:
            phrase = entry["phrase"]
            pl = (phrase or "").lower()
            if not pl:
                continue
            ratio = difflib.SequenceMatcher(None, msg, pl).ratio()
            backup.append((ratio, phrase))
        if not backup:
            return []
        backup.sort(reverse=True, key=lambda x: x[0])
        scored = backup[:max_suggestions * 2]
    scored.sort(reverse=True, key=lambda x: x[0])
    seen: set[str] = set()
    suggestions: List[str] = []
    for _, phrase in scored:
        if phrase in seen:
            continue
        seen.add(phrase)
        suggestions.append(phrase)
        if len(suggestions) >= max_suggestions:
            break
    return suggestions


async def _get_recent_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    limit: int = 20,
) -> List[Dict[str, str]]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())[::-1]
    return [{"role": m.role, "content": (m.content or "").strip()} for m in rows]


async def _get_recent_messages_by_customer(
    db: AsyncSession,
    bank: TenantBank,
    customer: Customer,
    limit: int = 20,
) -> List[Dict[str, str]]:
    """Load last N messages across all sessions for this customer so we recall their convos."""
    result = await db.execute(
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.tenant_id == bank.id,
            ChatSession.customer_id == customer.id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())[::-1]
    return [{"role": m.role, "content": (m.content or "").strip()} for m in rows]


async def _retrieve_knowledge_chunks(
    db: AsyncSession,
    bank: TenantBank,
    message: str,
    top_k: int = 4,
) -> List[KnowledgeChunk]:
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.tenant_id == bank.id)
        .order_by(KnowledgeChunk.created_at.desc())
        .limit(top_k)
    )
    return list(result.scalars().all())


def _is_escalation_confirmation(text: str, last_assistant: str) -> bool:
    """Detect a short, explicit 'yes, escalate me' reply after an escalation offer."""
    if not last_assistant:
        return False
    la = last_assistant.lower()
    is_offer = (
        "escalate" in la
        or "human agent" in la
        or "human adviser" in la
        or ("reply" in la and "yes" in la and ("connect" in la or "agent" in la or "adviser" in la or "human" in la))
    )
    if not is_offer:
        return False
    msg = text.lower().strip()
    if not msg or len(msg) > 25:
        return False
    explicit = {
        "yes",
        "yes please",
        "yes, please",
        "ok",
        "okay",
        "ok please",
        "sure",
        "please do",
        "do it",
        "connect me",
        "connect me to an agent",
        "connect me to a human",
        "talk to agent",
        "talk to a human",
    }
    return msg in explicit


def _build_llm_prompt(
    bank: TenantBank,
    user_message: str,
    customer_ctx: Dict[str, Any],
    knowledge_chunks: List[KnowledgeChunk],
) -> str:
    tone_cfg = bank.tone_config or {}
    tone = tone_cfg.get("tone", "friendly, clear, professional")
    voice = tone_cfg.get("voice", "speak as the bank's virtual assistant")

    kb_parts = [f"- ({kc.category or 'general'}) {kc.content[:400]}" for kc in knowledge_chunks]
    kb_text = "\n".join(kb_parts) if kb_parts else "No specific knowledge base entries were found."

    customer_text = "No customer context was found for this identifier."
    if customer_ctx.get("has_customer"):
        recent = customer_ctx.get("recent_transactions") or []
        lines = []
        for t in recent[:5]:
            lines.append(
                f"{t['timestamp']} — {t['amount']} {t['currency']} at {t.get('merchant') or 'merchant'} "
                f"({t.get('category') or 'N/A'}) via {t.get('channel') or 'N/A'} [{t['status']}]"
            )
        tx_block = "\n".join(lines) if lines else "No recent transactions recorded."
        customer_text = (
            f"Customer external id: {customer_ctx.get('customer_external_id')}\n"
            f"Risk score: {customer_ctx.get('risk_score')}, "
            f"accounts: {customer_ctx.get('account_count')}, "
            f"flagged: {customer_ctx.get('is_flagged')}\n"
            f"Recent transactions:\n{tx_block}"
        )

    return f"""
You are a customer care assistant for bank "{bank.name}" in country {bank.country_code}.
Tone: {tone}. Instructions: {voice}.

You MUST:
- Use only the information given below about the customer and bank.
- If you do not know something, say you don't know and suggest contacting human support.
- Never invent account balances, card numbers, or transaction IDs.

Customer context:
{customer_text}

Bank / product knowledge:
{kb_text}

User message:
\"\"\"{user_message}\"\"\"

Answer as a conversational customer-care agent. Be concise but helpful.
"""


def _rag_snippet(chunks: List[KnowledgeChunk], max_len: int = 200) -> str:
    if not chunks:
        return ""
    first = (chunks[0].content or "").strip()
    if not first:
        return ""
    return first[:max_len] + ("..." if len(first) > max_len else "")


def _tx_context_line(customer_ctx: Dict[str, Any], max_items: int = 2) -> str:
    recent = customer_ctx.get("recent_transactions") or []
    if not recent:
        return ""
    lines = []
    for t in recent[:max_items]:
        amt = t.get("amount", 0)
        curr = t.get("currency", "")
        merchant = t.get("merchant") or "merchant"
        lines.append(f"{amt} {curr} at {merchant}")
    return "Your recent activity includes: " + "; ".join(lines) + ". "


def _rule_based_reply(
    user_message: str,
    customer_ctx: Dict[str, Any],
    history: List[Dict[str, str]],
    chunks: List[KnowledgeChunk],
    support_contact: Dict[str, str] | None = None,
    closing_message: str | None = None,
    max_suggestions: int = 5,
    model_artifact_uri: str | None = None,
) -> Tuple[str, str, List[str], bool]:
    text = user_message.lower().strip()
    has_customer = customer_ctx.get("has_customer", False)
    recent = customer_ctx.get("recent_transactions") or []
    kb = _rag_snippet(chunks)
    tx_line = _tx_context_line(customer_ctx, max_items=2) if recent else ""

    last_assistant = ""
    if history:
        for m in reversed(history):
            if m.get("role") == "assistant":
                last_assistant = (m.get("content") or "").lower()
                break

    # If the previous turn showed a "Did you mean" list and the user did NOT
    # pick one of the suggested phrases, log it so we can mine new training data.
    if last_assistant.startswith("i'm not sure i understood that. did you mean one of these?"):
        prev_suggestions: List[str] = []
        for line in last_assistant.splitlines()[1:]:
            line = line.strip()
            if line.startswith("- "):
                prev_suggestions.append(line[2:].strip())
        norm_msg = _normalize_phrase(user_message)
        picked = any(_normalize_phrase(s) == norm_msg for s in prev_suggestions)
        if not picked:
            _log_care_event(
                {
                    "kind": "did_you_mean_not_accepted",
                    "user_message": user_message,
                    "suggestions": prev_suggestions,
                    "has_customer": has_customer,
                }
            )

    if _is_escalation_confirmation(user_message, last_assistant):
        reply = "I've escalated this to a human agent. Please stay on this channel; someone will be with you shortly."
        actions = INTENT_ACTIONS.get("HUMAN_ESCALATION", OUT_OF_SCOPE_ACTIONS)
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "escalation_confirmation",
                "intent": "HUMAN_ESCALATION",
                "escalate": True,
                "user_message": user_message,
                "has_customer": has_customer,
            }
        )
        return reply, "HUMAN_ESCALATION", actions, True

    # Short acknowledgements and closing
    if len(text) <= 25 and "thank" in text:
        reply = "You're welcome! Is there anything else I can help you with?"
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "thanks",
                "intent": "GENERAL_SUPPORT",
                "escalate": False,
                "user_message": user_message,
                "has_customer": has_customer,
            }
        )
        return reply, "GENERAL_SUPPORT", INTENT_ACTIONS["GENERAL_SUPPORT"], False

    if last_assistant and "anything else" in last_assistant and len(text) <= 30:
        decline = text in ("no", "nope", "nah", "nothing", "that's all", "that's it", "no thanks", "no thank you", "im good", "i'm good", "all good", "we're good", "we are good")
        if decline:
            msg = (closing_message or "").strip() or "Thank you for banking with First National Bank, hopefully to see you soon."
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "closing",
                    "intent": "GENERAL_SUPPORT",
                    "escalate": False,
                    "user_message": user_message,
                    "has_customer": has_customer,
                }
            )
            return msg, "GENERAL_SUPPORT", INTENT_ACTIONS["GENERAL_SUPPORT"], False

    # Handle certain tappable chips explicitly so they don't fall into 'Did you mean'
    sa_intent = _intent_for_suggested_action(user_message)
    if sa_intent == "HUMAN_ESCALATION":
        # If we've already escalated, just reassure the user.
        if last_assistant and "escalated this to a human agent" in last_assistant:
            reply = "You're already in the right place. A human agent will reply on this channel as soon as they're available."
            actions = INTENT_ACTIONS.get("HUMAN_ESCALATION", OUT_OF_SCOPE_ACTIONS)
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "suggested_action",
                    "intent": "HUMAN_ESCALATION",
                    "escalate": True,
                    "user_message": user_message,
                    "has_customer": has_customer,
                    "matched": "stay on channel / talk to agent",
                }
            )
            return reply, "HUMAN_ESCALATION", actions, True
        # Otherwise, reuse HUMAN_ESCALATION rule to offer escalation.
        rule = next((r for r in _CARE_INTENTS if (r.get("id") or "").strip() == "HUMAN_ESCALATION"), None)
        if rule is not None:
            reply = (rule.get("response") or "").strip()
            actions = INTENT_ACTIONS.get("HUMAN_ESCALATION", OUT_OF_SCOPE_ACTIONS)
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "suggested_action",
                    "intent": "HUMAN_ESCALATION",
                    "escalate": False,
                    "user_message": user_message,
                    "has_customer": has_customer,
                    "matched": "talk to agent",
                }
            )
            return reply, "HUMAN_ESCALATION", actions, False

    if sa_intent == "CONTACT_SUPPORT":
        # Reuse CONTACT_SUPPORT rule, if present
        rule = next((r for r in _CARE_INTENTS if (r.get("id") or "").strip() == "CONTACT_SUPPORT"), None)
        if rule is not None:
            phone = (support_contact or {}).get("phone") or (support_contact or {}).get("support_phone")
            email = (support_contact or {}).get("email") or (support_contact or {}).get("support_email")
            if phone or email:
                parts = []
                if phone:
                    parts.append(f"Phone: {phone}")
                if email:
                    parts.append(f"Email: {email}")
                reply = (rule.get("response_with_contact") or "").replace("{{contact}}", ". ".join(parts))
            else:
                reply = rule.get("response_no_contact") or ""
            actions = INTENT_ACTIONS.get("CONTACT_SUPPORT", OUT_OF_SCOPE_ACTIONS)
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "suggested_action",
                    "intent": "CONTACT_SUPPORT",
                    "escalate": False,
                    "user_message": user_message,
                    "has_customer": has_customer,
                    "matched": "contact/call/email support",
                }
            )
            return reply, "CONTACT_SUPPORT", actions, False

    if sa_intent == "TRANSACTION_HISTORY":
        # Direct chip like "View transactions" – reuse TRANSACTION_HISTORY rule.
        rule = next((r for r in _CARE_INTENTS if (r.get("id") or "").strip() == "TRANSACTION_HISTORY"), None)
        if rule is not None:
            reply = (rule.get("response") or "").strip()
            actions = INTENT_ACTIONS.get("TRANSACTION_HISTORY", OUT_OF_SCOPE_ACTIONS)
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "suggested_action",
                    "intent": "TRANSACTION_HISTORY",
                    "escalate": False,
                    "user_message": user_message,
                    "has_customer": has_customer,
                    "matched": "view transactions",
                }
            )
            return reply, "TRANSACTION_HISTORY", actions, False

    # Security override: avoid accidental matches like "account" -> BALANCE_INQUIRY.
    if _looks_like_security_request(user_message):
        sec_rule = next(
            (r for r in _CARE_INTENTS if (r.get("id") or "").strip() == "SECURITY_GUIDANCE"),
            None,
        )
        if sec_rule is not None:
            short_phrases = sec_rule.get("short_phrases") or []
            quick_follow = bool(short_phrases) and len(text) < 60 and any(
                (p or "").lower() in text for p in short_phrases
            )
            if quick_follow:
                reply = (sec_rule.get("short_response") or sec_rule.get("response") or "").strip()
            else:
                reply = (sec_rule.get("response") or "").strip()
            actions = INTENT_ACTIONS.get("SECURITY_GUIDANCE", OUT_OF_SCOPE_ACTIONS)
            _log_care_event(
                {
                    "kind": "care_reply",
                    "source": "security_keyword_override",
                    "intent": "SECURITY_GUIDANCE",
                    "escalate": False,
                    "user_message": user_message,
                    "has_customer": has_customer,
                    "matched": "security keywords",
                }
            )
            return reply, "SECURITY_GUIDANCE", actions, False

    for entry in GENERAL_CHAT:
        key = (entry.get("user") or "").lower().strip()
        if not key:
            continue
        if text == key or (len(text) <= 12 and key in text):
            reply = (entry.get("assistant") or "").strip()
            if reply:
                _log_care_event(
                    {
                        "kind": "care_reply",
                        "source": "general_chat",
                        "intent": "GENERAL_SUPPORT",
                        "escalate": False,
                        "user_message": user_message,
                        "has_customer": has_customer,
                        "matched": key,
                    }
                )
                return reply, "GENERAL_SUPPORT", INTENT_ACTIONS["GENERAL_SUPPORT"], False

    def _is_quick_follow(msg: str, short_phrases: List[str]) -> bool:
        if not short_phrases or len(msg) >= 60:
            return False
        return any(p in msg for p in (p.lower() for p in short_phrases))

    for rule in _CARE_INTENTS:
        intent_id = (rule.get("id") or "").strip()
        if not intent_id:
            continue
        phrases = rule.get("phrases") or []
        if not phrases:
            continue
        max_len = rule.get("max_message_len")
        if max_len is not None and len(text) > max_len:
            continue

        # Try to find the phrase for this intent whose tokens overlap best with
        # the user's message. This is more forgiving than raw substring match
        # and lets e.g. "what is my balance" hit "what is my current account balance".
        # Token overlap scoring uses fuzzy similarity, but we must ignore
        # ultra-common filler words; otherwise "want/need/help/account"
        # overlaps will route users to the wrong intent.
        stop_tokens = {
            "i",
            "im",
            "i'm",
            "me",
            "my",
            "we",
            "you",
            "your",
            "they",
            "them",
            "he",
            "she",
            "it",
            "this",
            "that",
            "these",
            "those",
            "a",
            "an",
            "the",
            "to",
            "of",
            "for",
            "and",
            "or",
            "in",
            "on",
            "at",
            "by",
            "with",
            "from",
            "is",
            "are",
            "am",
            "be",
            "do",
            "does",
            "did",
            "can",
            "could",
            "should",
            "would",
            "please",
            "want",
            "need",
            "help",
            "file",
        }
        msg_tokens = {tok for tok in _normalize_phrase(user_message).split() if tok and tok not in stop_tokens}
        if not msg_tokens:
            continue
        msg_norm = _normalize_phrase(user_message)
        matched_phrase = ""
        best_overlap = 0
        best_rel = 0.0
        best_ratio = 0.0
        for p in phrases:
            np = _normalize_phrase(p or "")
            if not np:
                continue
            ptokens = {tok for tok in np.split() if tok and tok not in stop_tokens}
            if not ptokens:
                continue
            # Compute overlap score: a user token counts as shared if it
            # exactly matches a phrase token OR is close enough via fuzzy
            # similarity. This is what makes misspellings like "passwor"
            # and "phishng" still hit the right intent.
            overlap = 0
            for token in msg_tokens:
                if not token or token.isdigit() or len(token) < 3:
                    continue
                if token in ptokens:
                    overlap += 1
                    continue
                best_tok = 0.0
                for pt in ptokens:
                    if not pt or pt.isdigit() or len(pt) < 3:
                        continue
                    r = difflib.SequenceMatcher(None, token, pt).ratio()
                    if r > best_tok:
                        best_tok = r
                    if best_tok >= 0.86:
                        break
                if best_tok >= 0.86:
                    overlap += 1

            rel = overlap / max(1, len(ptokens))
            ratio = difflib.SequenceMatcher(None, msg_norm, np).ratio()
            if overlap > best_overlap or (
                overlap == best_overlap
                and (rel > best_rel or (rel == best_rel and ratio > best_ratio))
            ) or (best_overlap == 0 and overlap == 0 and ratio > best_ratio):
                best_overlap = overlap
                best_rel = rel
                best_ratio = ratio
                matched_phrase = p
        # Require at least one non‑trivial shared word; ignore overlaps that
        # only share a single weak token like "what" or "my".
        if not matched_phrase:
            continue
        if best_overlap == 0:
            # Misspellings / paraphrases: fall back to fuzzy similarity score.
            if best_ratio < 0.90:
                continue
        if best_overlap == 1 and best_rel <= 0.55 and best_ratio < 0.80:
            continue

        if intent_id == "CONTACT_SUPPORT":
            phone = (support_contact or {}).get("phone") or (support_contact or {}).get("support_phone")
            email = (support_contact or {}).get("email") or (support_contact or {}).get("support_email")
            if phone or email:
                parts = []
                if phone:
                    parts.append(f"Phone: {phone}")
                if email:
                    parts.append(f"Email: {email}")
                reply = (rule.get("response_with_contact") or "").replace("{{contact}}", ". ".join(parts))
            else:
                reply = rule.get("response_no_contact") or ""
        else:
            short_phrases = rule.get("short_phrases") or []
            if _is_quick_follow(text, short_phrases):
                reply = (rule.get("short_response") or rule.get("response") or "").strip()
            else:
                reply = (rule.get("response") or "").strip()
            if rule.get("prepend_tx_context") and tx_line:
                reply = (tx_line + reply).strip()
            if rule.get("append_kb") and kb:
                reply += f" According to our information: {kb}" if "balance" in intent_id.lower() or "BALANCE" in intent_id else f" Policy note: {kb}"
        actions = INTENT_ACTIONS.get(intent_id, OUT_OF_SCOPE_ACTIONS)

        # For sensitive intents, always make it clear that a human can help
        # and rely on explicit user confirmation before escalation.
        if intent_id in REQUIRES_HUMAN_CONFIRMATION:
            low = reply.lower()
            if "reply 'yes'" not in low and "reply \"yes\"" not in low and "talk to an agent" not in low:
                extra = " If you'd like, I can connect you to a human agent to help with this — just reply 'yes'."
                reply = (reply + " " + extra).strip()
            if "Talk to agent" not in actions:
                actions = actions + ["Talk to agent"]
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "rule",
                "intent": intent_id,
                "escalate": intent_id == "HUMAN_ESCALATION",
                "user_message": user_message,
                "has_customer": has_customer,
                "matched": matched_phrase,
            }
        )
        return reply, intent_id, actions, False

    # No direct rule hit: fall back to the TF‑IDF model-based intent to propose example phrases,
    # but allow strong keyword hints to override the model when obvious.
    pred_intent, _ = _predict_intent_from_model(user_message, model_artifact_uri=model_artifact_uri)
    kw_intent = _keyword_intent(user_message)
    if kw_intent:
        pred_intent = kw_intent
    candidates = _phrases_for_intent(pred_intent) if pred_intent else []
    logger.info("care_rule_reply: pred_intent=%s candidates=%d", pred_intent, len(candidates))
    if pred_intent and candidates:
        # Re-rank the phrases for that intent by similarity to the user message
        msg = text
        scored: List[Tuple[float, str]] = []
        for phrase in candidates:
            pl = phrase.lower()
            ratio = difflib.SequenceMatcher(None, msg, pl).ratio()
            scored.append((ratio, phrase))
        scored.sort(reverse=True, key=lambda x: x[0])
        top_phrases = [p for _, p in scored[:5]]
        reply = (
            "I'm not sure I understood that. Did you mean one of these?\n"
            + "\n".join(f"- {s}" for s in top_phrases)
        )
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "model_suggestions",
                "intent": pred_intent,
                "escalate": False,
                "user_message": user_message,
                "has_customer": has_customer,
                "suggestions": top_phrases,
            }
        )
        return reply, pred_intent, top_phrases, False

    # If model can't help, fall back to fuzzy string suggestions over all phrases
    suggestions = _did_you_mean_suggestions(text, max_suggestions=max_suggestions)
    logger.info("care_rule_reply: did_you_mean_suggestions=%d", len(suggestions))
    if suggestions:
        reply = (
            "I'm not sure I understood that. Did you mean one of these?\n"
            + "\n".join(f"- {s}" for s in suggestions)
        )
        # suggestions list doubles as tappable chips; sending the full phrases back will
        # trigger the normal rule / model path on the second turn.
        _log_care_event(
            {
                "kind": "care_reply",
                "source": "fuzzy_suggestions",
                "intent": "GENERAL_SUPPORT",
                "escalate": False,
                "user_message": user_message,
                "has_customer": has_customer,
                "suggestions": suggestions,
            }
        )
        return reply, "GENERAL_SUPPORT", suggestions, False

    logger.info("care_rule_reply: fallback to out_of_scope msg=%r", user_message[:50])
    reply = (_CARE_OUT_OF_SCOPE.get("response") or "").strip()
    if not reply:
        reply = (
            "I'm your bank's virtual assistant. I'm here to help only with: account balance, fraud and disputes, "
            "locked account, recent transactions, blocking your card, PIN reset, branch and ATM locations, complaints, "
            "and connecting you to a human agent. Your question is outside what I can answer — please pick one of these "
            "topics or ask to speak to an agent for anything else."
        )
    _log_care_event(
        {
            "kind": "care_reply",
            "source": "out_of_scope",
            "intent": "no_intent",
            "escalate": False,
            "user_message": user_message,
            "has_customer": has_customer,
        }
    )
    return reply, "GENERAL_SUPPORT", OUT_OF_SCOPE_ACTIONS, False


async def handle_chat(
    db: AsyncSession,
    bank: TenantBank,
    session_id: str,
    customer_id: str,
    message: str,
    channel: str,
    model_artifact_uri: str | None = None,
) -> Dict[str, Any]:
    t0 = time.perf_counter()

    session = await _get_or_create_session(db, bank, session_id, channel)

    customer = await _resolve_customer(db, bank, customer_id)
    customer_ctx = await _summarise_customer_context(db, bank, customer)
    if customer:
        session.customer_id = customer.id
        await db.flush()

    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=message,
        intent=None,
        confidence=None,
    )
    db.add(user_msg)
    await db.flush()

    if customer:
        history = await _get_recent_messages_by_customer(db, bank, customer, limit=20)
    else:
        history = await _get_recent_messages(db, session.id, limit=20)

    if customer:
        detail_lookup = await _maybe_transaction_detail_lookup_reply(
            db, bank, customer, session, message
        )
        if detail_lookup is not None:
            dl_reply, dl_pdf = detail_lookup
            assistant_msg = ChatMessage(
                session_id=session.id,
                role="assistant",
                content=dl_reply,
                intent="TRANSACTION_DETAIL_LOOKUP",
                confidence=None,
            )
            db.add(assistant_msg)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "session_id": str(session_id),
                "intent": "TRANSACTION_DETAIL_LOOKUP",
                "response": dl_reply,
                "escalate_to_human": False,
                "suggested_actions": ["View transactions", "Talk to agent"],
                "processing_time_ms": elapsed_ms,
                "pdf_url": dl_pdf,
            }

    # Transaction analytics / history Q&A (DB-backed, scoped to this customer)
    analytics = await _maybe_tx_analytics_reply(db, bank, customer, session, message)
    if analytics is not None:
        analytics_reply, pdf_url = analytics
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=analytics_reply,
            intent="TRANSACTION_ANALYTICS",
            confidence=None,
        )
        db.add(assistant_msg)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "session_id": str(session_id),
            "intent": "TRANSACTION_ANALYTICS",
            "response": analytics_reply,
            "escalate_to_human": False,
            "suggested_actions": ["View transactions"],
            "processing_time_ms": elapsed_ms,
            "pdf_url": pdf_url,
        }
    chunks = await _retrieve_knowledge_chunks(db, bank, message, top_k=4)
    support_contact = {}
    closing_message = None
    max_suggestions = 5
    model_threshold = 0.5
    if bank.tone_config:
        tc = bank.tone_config
        if tc.get("support_phone"):
            support_contact["phone"] = str(tc["support_phone"])
        if tc.get("support_email"):
            support_contact["email"] = str(tc["support_email"])
        if tc.get("closing_message"):
            closing_message = str(tc["closing_message"]).strip()
        elif tc.get("bank_name"):
            closing_message = f"Thank you for banking with {tc['bank_name']}, hopefully to see you soon."
        if tc.get("care_max_suggestions") is not None:
            try:
                max_suggestions = max(1, int(tc["care_max_suggestions"]))
            except (TypeError, ValueError):
                pass
        if tc.get("care_model_threshold") is not None:
            try:
                model_threshold = float(tc["care_model_threshold"])
            except (TypeError, ValueError):
                pass
    reply, intent, suggested_actions, escalate = _rule_based_reply(
        message,
        customer_ctx,
        history,
        chunks,
        support_contact=support_contact or None,
        closing_message=closing_message,
        max_suggestions=max_suggestions,
        model_artifact_uri=model_artifact_uri,
    )
    # Simple per‑session rate‑limit: if we've already escalated to a human in
    # this conversation, don't trigger another escalation flag.
    if escalate:
        already_escalated = any(
            (m.get("role") == "assistant" and "escalated this to a human agent" in (m.get("content") or "").lower())
            for m in history
        )
        if already_escalated:
            escalate = False
    if intent == "GENERAL_SUPPORT":
        pred_intent, pred_conf = _predict_intent_from_model(message, model_artifact_uri=model_artifact_uri)
        if pred_intent and pred_conf >= model_threshold and pred_intent in INTENT_ACTIONS:
            intent = pred_intent
            suggested_actions = INTENT_ACTIONS.get(intent, suggested_actions)

    assistant_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=reply,
        intent=intent,
        confidence=None,
    )
    db.add(assistant_msg)

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "session_id": str(session_id),
        "intent": intent,
        "response": reply,
        "escalate_to_human": escalate,
        "suggested_actions": suggested_actions,
        "processing_time_ms": elapsed_ms,
    }


def predict_intent_shadow(message: str, *, model_artifact_uri: str | None = None) -> Tuple[str | None, float]:
    return _predict_intent_from_model(message, model_artifact_uri=model_artifact_uri)

