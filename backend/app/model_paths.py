"""Resolve packaged ML paths for Docker ``/models/...`` vs git deploy (repo tree).

MODEL_PATH often points at a GGUF under ``/models/*.gguf``. Deriving sibling dirs from its parent
produces ``/models/fraud`` / ``/models/care/...`` which do not exist on PaaS hosts; artifacts live
under ``<repo>/models/...`` and ``<repo>/backend/app/ml/models/...``.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Project root (parent of ``backend/``)."""
    return Path(__file__).resolve().parents[2]


def backend_app_dir() -> Path:
    return repo_root() / "backend" / "app"


def packaged_fraud_models_dir() -> Path:
    env_path = os.getenv("MODEL_PATH", "").strip()
    repo_fraud = repo_root() / "models" / "fraud"
    if env_path and env_path != "/models":
        derived = Path(env_path).parent / "fraud"
        if str(derived) == "/models/fraud":
            return repo_fraud
        return derived
    return repo_fraud


def resolve_default_care_intent_joblib_path() -> Path:
    """Sklearn care intent classifier shipped with the app or beside ``models/fraud``."""
    primary = backend_app_dir() / "ml" / "models" / "care_intent_model.joblib"
    secondary = repo_root() / "models" / "care" / "care_intent_model.joblib"
    if primary.exists():
        return primary
    if secondary.exists():
        return secondary
    return primary


def packaged_care_intent_classifier_train_dir() -> Path:
    """Output dir for ``app.ml.intent_train`` when MODEL_PATH uses ``/models/*.gguf``."""
    env_path = os.getenv("MODEL_PATH", "").strip()
    fallback = backend_app_dir() / "ml" / "models" / "care" / "intent_classifier"
    if not env_path or env_path == "/models":
        return fallback
    if Path(env_path).expanduser().parent.as_posix() == "/models":
        return fallback
    return Path(env_path).parent / "care" / "intent_classifier"


def resolve_llama_gguf_path(env_value: str | None = None) -> Path | None:
    """
    Optional Phi/llama.cpp GGUF for care LLM router. Checks MODEL_PATH, then ``models/llm/<name>``.
    """
    raw = (env_value if env_value is not None else os.getenv("MODEL_PATH", "")).strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_file() and p.exists():
        return p
    bundled = repo_root() / "models" / "llm" / p.name
    if bundled.is_file():
        return bundled
    return p if p.exists() else None
