#!/usr/bin/env python3
"""
Build care_intent_model.joblib from care_intent_rules.json only (no DB / SQLAlchemy).

Writes:
  backend/app/ml/models/care_intent_model.joblib   (primary)
  models/care/care_intent_model.joblib             (deploy bundle beside models/fraud)

Run from repo after: pip install scikit-learn joblib
  cd backend && PYTHONPATH=. python scripts/bootstrap_care_intent_model.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RULES_PATH = BACKEND_ROOT / "app" / "ml" / "data" / "care_intent_rules.json"
PRIMARY_OUT = BACKEND_ROOT / "app" / "ml" / "models" / "care_intent_model.joblib"
REPO_BUNDLE_OUT = REPO_ROOT / "models" / "care" / "care_intent_model.joblib"

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
    "SECURITY_GUIDANCE",
]
VALID = frozenset(INTENT_LABELS)


def _examples_from_rules() -> list[tuple[str, str]]:
    if not RULES_PATH.exists():
        raise SystemExit(f"Missing rules file: {RULES_PATH}")
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    seed: list[tuple[str, str]] = []
    for rule in data.get("intents") or []:
        intent_id = (rule.get("id") or "").strip()
        if intent_id not in VALID:
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


def main() -> None:
    try:
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import LabelEncoder
    except ImportError:
        print("Install: pip install scikit-learn joblib", file=sys.stderr)
        raise SystemExit(1)

    examples = _examples_from_rules()
    if len(examples) < 10:
        raise SystemExit(f"Need >= 10 phrase/intent pairs from rules; got {len(examples)}.")

    texts, intents = zip(*examples)
    le = LabelEncoder()
    y = le.fit_transform(list(intents))
    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(max_features=20000, analyzer="char_wb", ngram_range=(3, 5), min_df=1),
            ),
            ("clf", LogisticRegression(max_iter=500, C=0.5)),
        ]
    )
    pipeline.fit(list(texts), y)

    payload = {"pipeline": pipeline, "label_encoder": le, "labels": INTENT_LABELS}
    PRIMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPO_BUNDLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, PRIMARY_OUT)
    joblib.dump(payload, REPO_BUNDLE_OUT)
    print(f"Wrote {PRIMARY_OUT}")
    print(f"Wrote {REPO_BUNDLE_OUT}")


if __name__ == "__main__":
    main()
