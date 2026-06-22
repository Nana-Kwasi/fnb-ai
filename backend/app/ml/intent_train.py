"""
Train a DistilBERT intent classifier for customer support.
Reads JSONL from app/ml/data/customer_intents.jsonl with fields: text, intent.
Saves model under: $(dirname MODEL_PATH)/care/intent_classifier

Run from backend/ (with PYTHONPATH=.) or repo root:
  python -m app.ml.intent_train
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import torch
from torch.utils.data import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
)

from app.model_paths import packaged_care_intent_classifier_train_dir

INTENT_LABELS = [
    "FRAUD_INQUIRY",
    "BALANCE_INQUIRY",
    "DISPUTE_TRANSACTION",
    "ACCOUNT_LOCKED",
    "GENERAL_SUPPORT",
    "HUMAN_ESCALATION",
]
LABEL2ID: Dict[str, int] = {l: i for i, l in enumerate(INTENT_LABELS)}
ID2LABEL: Dict[int, str] = {i: l for l, i in LABEL2ID.items()}


@dataclass
class IntentExample:
    text: str
    label: int


class IntentDataset(Dataset):
    def __init__(self, tokenizer, examples: List[IntentExample], max_length: int = 128):
        self.tokenizer = tokenizer
        self.examples = examples
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int):
        ex = self.examples[idx]
        enc = self.tokenizer(
            ex.text,
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
        )
        enc["labels"] = ex.label
        return {k: torch.tensor(v) for k, v in enc.items()}


def load_examples(path: Path) -> List[IntentExample]:
    examples: List[IntentExample] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            intent = obj["intent"]
            if intent not in LABEL2ID:
                continue
            examples.append(IntentExample(text=obj["text"], label=LABEL2ID[intent]))
    return examples


def main():
    data_path = Path(__file__).parent / "data" / "customer_intents.jsonl"
    examples = load_examples(data_path)
    # simple train/val split
    split = int(0.8 * len(examples))
    train_examples = examples[:split]
    val_examples = examples[split:]

    model_name = "distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(INTENT_LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    train_ds = IntentDataset(tokenizer, train_examples)
    val_ds = IntentDataset(tokenizer, val_examples)

    out_dir = packaged_care_intent_classifier_train_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=5,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        learning_rate=5e-5,
        weight_decay=0.01,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        logging_steps=10,
        save_total_limit=2,
    )

    def compute_metrics(eval_pred):
        import numpy as np
        from sklearn.metrics import f1_score, accuracy_score

        logits, labels = eval_pred
        preds = logits.argmax(axis=-1)
        return {
            "accuracy": accuracy_score(labels, preds),
            "f1_macro": f1_score(labels, preds, average="macro"),
        }

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    print("Intent classifier saved to", out_dir)


if __name__ == "__main__":
    main()

