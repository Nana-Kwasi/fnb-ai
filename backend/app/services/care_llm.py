"""
Local care LLM: SmolLM2-360M-Instruct with few-shot bank-care examples.
No OpenAI key required. Set CARE_USE_OPENAI=1 to use OpenAI instead.
"""
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=1)
_pipeline = None
_fewshot_lines = None

MODEL_ID = os.getenv("CARE_MODEL_HF", "HuggingFaceTB/SmolLM2-360M-Instruct")
# Keep generations short so the small model stays fast on CPU.
MAX_NEW_TOKENS = int(os.getenv("CARE_MAX_TOKENS", "96"))


def _load_fewshot():
    global _fewshot_lines
    if _fewshot_lines is not None:
        return _fewshot_lines
    path = Path(__file__).resolve().parent.parent / "ml" / "data" / "care_fewshot.json"
    try:
        with path.open() as f:
            examples = json.load(f)
    except Exception:
        examples = []
    lines = []
    for ex in examples[:3]:
        lines.append(f"User: {ex.get('user', '')}")
        lines.append(f"Assistant: {ex.get('assistant', '')}")
    _fewshot_lines = "\n".join(lines) if lines else ""
    return _fewshot_lines


def _get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    from transformers import pipeline
    import torch
    kwargs = {"model": MODEL_ID, "trust_remote_code": "SmolLM" in MODEL_ID}
    if os.getenv("CARE_DEVICE", "").lower() == "cuda":
        kwargs["device_map"] = "auto"
        kwargs["torch_dtype"] = torch.float16
    else:
        kwargs["torch_dtype"] = torch.float32
    _pipeline = pipeline("text-generation", **kwargs)
    return _pipeline


def _generate_sync(prompt: str) -> str:
    try:
        pipe = _get_pipeline()
    except Exception as e:
        return f"I'm sorry, the care model could not be loaded ({type(e).__name__}). Set CARE_USE_OPENAI=1 and OPENAI_API_KEY to use OpenAI instead."
    few = _load_fewshot()
    if few:
        full = f"{few}\n\nUser: {prompt}\nAssistant:"
    else:
        full = f"User: {prompt}\nAssistant:"
    try:
        out = pipe(
            full,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=True,
            temperature=0.4,
            pad_token_id=pipe.tokenizer.eos_token_id,
            truncation=True,
            max_length=1024,
        )
    except Exception as e:
        return f"I'm sorry, the care model failed to generate a response ({type(e).__name__}). Please try again or contact support."
    text = (out[0]["generated_text"] if out else "")
    if "Assistant:" in text:
        text = text.split("Assistant:")[-1]
    return text.strip().split("\n")[0].strip() or "I'm sorry, I couldn't generate a response. Please try again or contact support."


async def generate_reply(prompt: str):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _generate_sync, prompt)
