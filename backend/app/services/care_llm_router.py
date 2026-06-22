from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from app.config import settings
from app.model_paths import resolve_llama_gguf_path


Intent = Literal[
    "TX_LIST",
    "TX_STATS",
    "TX_FRAUDLIKE_LIST",
    "TX_FRAUDLIKE_STATS",
    "PDF_GENERATE",
    "PDF_REPEAT",
    "PAGINATE_NEXT",
    "PAGINATE_PREV",
    "UNKNOWN",
]


@dataclass(frozen=True)
class Route:
    intent: Intent
    range: str | None = None
    decision: str | None = None
    wants_pdf: bool | None = None
    confidence: float | None = None


_llm = None


def _model_available() -> bool:
    p = resolve_llama_gguf_path(os.getenv("MODEL_PATH") or settings.model_path)
    return bool(p and p.is_file())


def _get_llm():
    global _llm
    if _llm is not None:
        return _llm
    from llama_cpp import Llama

    resolved = resolve_llama_gguf_path(os.getenv("MODEL_PATH") or settings.model_path)
    model_path = str(resolved) if resolved else os.getenv("MODEL_PATH", settings.model_path)
    _llm = Llama(
        model_path=model_path,
        n_ctx=2048,
        n_threads=int(os.getenv("LLAMA_THREADS", "4")),
        verbose=False,
    )
    return _llm


_SYSTEM = """You are a routing function for a banking customer-care chat.
Return ONLY valid JSON matching this schema:
{
  "intent": "TX_LIST|TX_STATS|TX_FRAUDLIKE_LIST|TX_FRAUDLIKE_STATS|PDF_GENERATE|PDF_REPEAT|PAGINATE_NEXT|PAGINATE_PREV|UNKNOWN",
  "range": "today|yesterday|this_week|this_month|recent|all|since_monday|last_3d|between 2026-03-01 and 2026-03-10" (optional),
  "decision": "APPROVE|LIMITED_APPROVAL|REQUEST_OTP|BLOCK" or comma-separated list (optional),
  "wants_pdf": true|false (optional),
  "confidence": number between 0 and 1 (optional)
}

Rules:
- If user asks to download/export/statement/pdf, intent should be PDF_GENERATE.
- If user says again/repeat/redo and context indicates PDF, intent should be PDF_REPEAT.
- If user says more/next, intent PAGINATE_NEXT. If previous/back, PAGINATE_PREV.
- If user asks "how many" or counts, intent TX_STATS or TX_FRAUDLIKE_STATS.
- "fraud transactions" means fraud-like (blocked or OTP-required): TX_FRAUDLIKE_LIST or TX_FRAUDLIKE_STATS.
- If unclear, set intent UNKNOWN.
"""


def route_message_llm(message: str, context: dict[str, Any] | None = None) -> Route | None:
    """
    Optional LLM router. Returns None if model unavailable or routing fails.
    """
    if not _model_available():
        return None
    msg = (message or "").strip()
    if not msg:
        return None
    ctx = context or {}
    # Keep context minimal and non-sensitive.
    ctx_payload = {
        "last_action": ctx.get("last_action"),
        "last_range": ctx.get("last_range"),
        "pdf_offer_pending": bool(ctx.get("pdf_offer_pending")),
        "has_pdf": bool(ctx.get("pdf_last_token")) or bool(ctx.get("pdf_range")),
    }
    prompt = (
        _SYSTEM
        + "\nContext:\n"
        + json.dumps(ctx_payload, ensure_ascii=False)
        + "\nUser:\n"
        + msg
        + "\nJSON:\n"
    )
    llm = _get_llm()
    out = llm(
        prompt,
        max_tokens=180,
        temperature=0.0,
        stop=["\n\n", "\nUser:", "\nContext:"],
    )
    text = (out.get("choices") or [{}])[0].get("text") or ""
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception as exc:
        # Sometimes models prefix junk; attempt to extract JSON object.
        if "{" in text and "}" in text:
            frag = text[text.find("{") : text.rfind("}") + 1]
            try:
                data = json.loads(frag)
            except Exception as exc2:
                return None
        else:
            return None

    intent = str(data.get("intent") or "UNKNOWN").strip().upper()
    allowed = {
        "TX_LIST",
        "TX_STATS",
        "TX_FRAUDLIKE_LIST",
        "TX_FRAUDLIKE_STATS",
        "PDF_GENERATE",
        "PDF_REPEAT",
        "PAGINATE_NEXT",
        "PAGINATE_PREV",
        "UNKNOWN",
    }
    if intent not in allowed:
        intent = "UNKNOWN"
    rng = data.get("range")
    rng = str(rng).strip() if rng else None
    dec = data.get("decision")
    dec = str(dec).strip().upper() if dec else None
    wants_pdf = data.get("wants_pdf")
    wants_pdf = bool(wants_pdf) if wants_pdf is not None else None
    conf = data.get("confidence")
    try:
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf = None
    return Route(intent=intent, range=rng, decision=dec, wants_pdf=wants_pdf, confidence=conf)

