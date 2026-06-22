"""
Scheduled job: export chat_messages and train intent model (every 6h).
Manual: train from rules JSON only (no DB) — use when you update care_intent_rules.

  python -m app.tasks.care_train_scheduled              # export history + train (seed + history) — what scheduler runs
  python -m app.tasks.care_train_scheduled --from-rules # train from rules file only (manual, no DB)
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.ml.care_rules_loader import load_intent_rules
from app.models import ChatMessage

INTENT_LABELS = [
    "BALANCE_INQUIRY",
    "FRAUD_DISPUTE",
    "ACCOUNT_LOCKED",
    "HUMAN_ESCALATION",
    "TRANSACTION_HISTORY",
    "CARD_BLOCK",
    "PIN_RESET",
    "BRANCH_ATM",
    "COMPLAINT",
    "CONTACT_SUPPORT",
    "GENERAL_SUPPORT",
    # Newly added / already used by care_engine rules.
    "SECURITY_GUIDANCE",
]
VALID_INTENTS = frozenset(INTENT_LABELS)

DATA_DIR = Path(__file__).resolve().parent.parent / "ml" / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "ml" / "models"
HISTORY_JSONL = DATA_DIR / "care_intents_from_history.jsonl"


def get_seed_from_rules() -> list[tuple[str, str]]:
    """(text, intent) pairs from care_intent_rules (JSON/Excel/CSV) for training seed."""
    intents, _ = load_intent_rules(DATA_DIR)
    seed: list[tuple[str, str]] = []
    for rule in intents:
        intent_id = (rule.get("id") or "").strip()
        if intent_id not in VALID_INTENTS:
            continue
        for p in rule.get("phrases") or []:
            t = (p or "").strip()
            if t:
                seed.append((t, intent_id))
        for p in rule.get("short_phrases") or []:
            t = (p or "").strip()
            if t:
                seed.append((t, intent_id))
    return seed


def _sync_engine():
    url = settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql", 1)
    return create_engine(url, pool_pre_ping=True)


def export_chat_history_to_jsonl(max_pairs: int = 50_000) -> int:
    """Query chat_messages: pair each user message with the next assistant message's intent. Write JSONL."""
    engine = _sync_engine()
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pairs: list[dict] = []

    with SessionLocal() as session:
        # Get (session_id, created_at, role, content, intent) ordered by session and time
        q = (
            select(
                ChatMessage.session_id,
                ChatMessage.created_at,
                ChatMessage.role,
                ChatMessage.content,
                ChatMessage.intent,
            )
            .order_by(ChatMessage.session_id, ChatMessage.created_at)
        )
        rows = session.execute(q).all()

    # Pair user msg with next assistant's intent
    prev_user_content = None
    for r in rows:
        if r.role == "user" and (r.content or "").strip():
            prev_user_content = (r.content or "").strip()
        elif (
            r.role == "assistant"
            and prev_user_content is not None
            and r.intent
            and r.intent in VALID_INTENTS
        ):
            assistant_text = (r.content or "").strip().lower()
            # Skip low-signal clarification / out-of-scope assistant replies so
            # we don't train on noisy labels.
            if assistant_text.startswith("i'm not sure i understood that") and "did you mean" in assistant_text:
                prev_user_content = None
                continue
            if "virtual assistant" in assistant_text and "outside what i can answer" in assistant_text:
                prev_user_content = None
                continue

            pairs.append({"text": prev_user_content, "intent": r.intent})
            prev_user_content = None
        else:
            if r.role != "user":
                prev_user_content = None

    pairs = pairs[-max_pairs:]
    with open(HISTORY_JSONL, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    return len(pairs)


def train_intent_from_jsonl() -> bool:
    """Build examples from rules seed + history JSONL, then train. Used by scheduler."""
    examples = list(get_seed_from_rules())
    seed_count = len(examples)
    if HISTORY_JSONL.exists():
        with open(HISTORY_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                intent = obj.get("intent")
                if intent not in VALID_INTENTS:
                    continue
                msg = (obj.get("text") or "").strip()
                if not msg:
                    continue
                examples.append((msg, intent))
    if len(examples) < 10:
        print(f"Care training skipped: need >= 10 examples, got {len(examples)} (seed={seed_count}, history={len(examples)-seed_count}).")
        return False
    return _train_on_examples(examples)


def train_intent_from_external_jsonl(path: str) -> bool:
    """Build examples from rules seed + provided JSONL, then train."""
    p = Path(path)
    examples = list(get_seed_from_rules())
    seed_count = len(examples)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                intent = obj.get("intent")
                if intent not in VALID_INTENTS:
                    continue
                msg = (obj.get("text") or "").strip()
                if not msg:
                    continue
                examples.append((msg, intent))
    if len(examples) < 10:
        print(
            f"Care training skipped: need >= 10 examples, got {len(examples)} "
            f"(seed={seed_count}, uploaded={len(examples)-seed_count})."
        )
        return False
    return _train_on_examples(examples)


def run_care_training() -> dict:
    """Export history and train (seed + history). Used by the 6h scheduler."""
    count = export_chat_history_to_jsonl()
    trained = train_intent_from_jsonl()
    return {"exported_pairs": count, "trained": trained}


def run_care_training_from_rules_only() -> dict:
    """Train from care_intent_rules (JSON/Excel/CSV) only. No DB export. Use after editing rules."""
    examples = list(get_seed_from_rules())
    if len(examples) < 10:
        print(f"Rules-only training skipped: need >= 10 phrase/intent pairs in rules, got {len(examples)}.")
        return {"from_rules": True, "examples": len(examples), "trained": False}
    trained = _train_on_examples(examples)
    return {"from_rules": True, "examples": len(examples), "trained": trained}


def _train_on_examples(examples: list[tuple[str, str]]) -> bool:
    """Fit pipeline on (text, intent) list and save joblib."""
    try:
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import LabelEncoder
    except ImportError as e:
        print("Training skipped: pip install scikit-learn joblib.", e)
        return False
    texts, intents = zip(*examples)
    le = LabelEncoder()
    y = le.fit_transform(list(intents))
    pipeline = Pipeline([
        # Use character n-grams so the intent model is robust to typos like
        # "passwor", "phishng", "piin" even when word tokens don't match well.
        ("tfidf", TfidfVectorizer(max_features=20000, analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
        ("clf", LogisticRegression(max_iter=500, C=0.5)),
    ])
    pipeline.fit(list(texts), y)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "label_encoder": le, "labels": INTENT_LABELS}, MODEL_DIR / "care_intent_model.joblib")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Care intent model training")
    parser.add_argument("--from-rules", action="store_true", help="Train from rules file only (no DB); use after editing care_intent_rules")
    parser.add_argument("--from-jsonl", type=str, default=None, help="Train from external JSONL (merged with rules seed)")
    args = parser.parse_args()
    if args.from_jsonl:
        ok = train_intent_from_external_jsonl(args.from_jsonl)
        print("Care training (external jsonl):", {"path": args.from_jsonl, "trained": ok})
    elif args.from_rules:
        out = run_care_training_from_rules_only()
        print("Care training (rules only):", out)
    else:
        out = run_care_training()
        print("Care training:", out)
