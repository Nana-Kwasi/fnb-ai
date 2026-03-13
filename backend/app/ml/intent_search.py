"""Embedding-based nearest-phrase search for care intents. Handles typos/paraphrases."""
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
_MODEL = None
_EMB = None
_PHRASES: List[dict] = []


def _build_phrases() -> List[dict]:
    from app.ml.care_rules_loader import load_intent_rules
    intents, _ = load_intent_rules(DATA_DIR)
    out = []
    for r in intents:
        iid = (r.get("id") or "").strip()
        if not iid:
            continue
        for p in r.get("phrases") or []:
            phrase = (p or "").strip()
            if phrase:
                out.append({"phrase": phrase, "intent": iid})
    return out


def _ensure_index() -> bool:
    global _MODEL, _EMB, _PHRASES
    if _EMB is not None:
        return True
    try:
        from sentence_transformers import SentenceTransformer
        _PHRASES = _build_phrases()
        if not _PHRASES:
            logger.info("intent_search: no phrases from rules, index empty")
            return False
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        texts = [x["phrase"] for x in _PHRASES]
        _EMB = _MODEL.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return True
    except ImportError as e:
        logger.info("intent_search: SentenceTransformer import failed: %s", e)
        return False
    except Exception as e:
        logger.warning("intent_search: index build failed (numpy/torch ABI?): %s", e, exc_info=True)
        return False


def find_similar_phrases(text: str, top_k: int = 5, min_score: float = 0.3) -> List[Tuple[str, str, float]]:
    """Return [(phrase, intent, cosine_score), ...] for top_k matches."""
    if not text or not text.strip():
        return []
    if not _ensure_index():
        msg = text.strip()[:60]
        logger.info("intent_search: index not available, returning no hits for %r", msg)
        print(f"[INTENT_SEARCH] index not available, no hits for {msg!r}")
        return []
    import numpy as np
    q = _MODEL.encode([text.strip()], convert_to_numpy=True, normalize_embeddings=True)[0]
    scores = np.dot(_EMB, q)
    idx = np.argsort(scores)[::-1][:top_k]
    out = []
    best = float(scores[idx[0]]) if len(idx) else None
    for i in idx:
        s = float(scores[i])
        if s < min_score:
            continue
        out.append((_PHRASES[i]["phrase"], _PHRASES[i]["intent"], s))
    msg = text.strip()[:60]
    logger.info("intent_search: text=%r hits=%d top_score=%s best_raw=%s", msg, len(out), out[0][2] if out else None, best)
    print(f"[INTENT_SEARCH] text={msg!r} hits={len(out)} top_score={(out[0][2] if out else None)!r} best_raw={best!r}")
    return out
