import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple
import difflib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.care_rules_loader import load_intent_rules
from app.models import (
    TenantBank,
    Customer,
    Transaction,
    ChatSession,
    ChatMessage,
    KnowledgeChunk,
)

logger = logging.getLogger(__name__)


def _normalize_phrase(s: str) -> str:
    """Lower, strip punctuation, collapse spaces; drop optional 'a'/'the' so 'apply for a loan' matches 'apply for loan'."""
    if not s:
        return ""
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


def _load_care_intent_model() -> Any:
    global _CARE_INTENT_MODEL
    if _CARE_INTENT_MODEL is not None:
        return _CARE_INTENT_MODEL
    path = Path(__file__).resolve().parent.parent / "ml" / "models" / "care_intent_model.joblib"
    if not path.exists():
        return None
    try:
        import joblib
        _CARE_INTENT_MODEL = joblib.load(path)
        return _CARE_INTENT_MODEL
    except Exception:
        return None


def _predict_intent_from_model(message: str) -> Tuple[str | None, float]:
    """Returns (intent, confidence) or (None, 0) if no model or low confidence."""
    model = _load_care_intent_model()
    if model is None:
        return None, 0.0
    pipeline = model.get("pipeline")
    le = model.get("label_encoder")
    labels = model.get("labels")
    if not pipeline or not le or not labels:
        return None, 0.0
    try:
        import numpy as np
        pred = pipeline.predict([message])
        proba = pipeline.predict_proba([message])[0]
        idx = int(pred[0])
        conf = float(proba[idx])
        if idx < len(labels):
            return labels[idx], conf
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
        msg_tokens = set(_normalize_phrase(user_message).split())
        if not msg_tokens:
            continue
        matched_phrase = ""
        best_overlap = 0
        best_rel = 0.0
        for p in phrases:
            np = _normalize_phrase(p or "")
            if not np:
                continue
            ptokens = set(np.split())
            if not ptokens:
                continue
            inter = msg_tokens & ptokens
            if not inter:
                continue
            overlap = len(inter)
            rel = overlap / max(1, len(ptokens))
            if overlap > best_overlap or (overlap == best_overlap and rel > best_rel):
                best_overlap = overlap
                best_rel = rel
                matched_phrase = p
        # Require at least one non‑trivial shared word; ignore overlaps that
        # only share a single weak token like "what" or "my".
        if not matched_phrase or best_overlap == 0:
            continue
        if best_overlap == 1 and best_rel < 0.5:
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
    pred_intent, _ = _predict_intent_from_model(user_message)
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
        pred_intent, pred_conf = _predict_intent_from_model(message)
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

