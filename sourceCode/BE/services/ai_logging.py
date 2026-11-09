# [pic: lam] p2-12 ai error taxonomy logger (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from database import UTC_TZ
from models import AiErrorType
from services.privacy import sanitize_prompt

LOG_PATH = Path(os.getenv("AI_ERROR_LOG_PATH", str(Path(__file__).resolve().parent.parent / "logs" / "ai_errors.jsonl")))
_lock = threading.Lock()

# fine-grained taxonomy -> coarse DB enum (models.py is locked, so the exact category lives in the file log)
CATEGORY_TO_DB: dict[str, AiErrorType] = {
    "TIMEOUT": AiErrorType.TIMEOUT,
    "INFRA_CRASH": AiErrorType.INFRA_CRASH,
    "JSON_PARSE": AiErrorType.SCHEMA_VALIDATION,
    "SCHEMA_VALIDATION": AiErrorType.SCHEMA_VALIDATION,
    "TEMPORAL_HALLUCINATION": AiErrorType.SEMANTIC_FAILURE,
    "SEMANTIC_FAILURE": AiErrorType.SEMANTIC_FAILURE,
    "RAG_EMPTY_RETRIEVAL": AiErrorType.SEMANTIC_FAILURE,
    "RAG_LOW_SCORE": AiErrorType.SEMANTIC_FAILURE,
    "RAG_EXTRACTION_FAILED": AiErrorType.SEMANTIC_FAILURE,
}


def log_ai_failure(
    category: str,
    prompt: str,
    reason: str,
    *,
    retrieved_context: list[str] | None = None,
    raw_output: str | None = None,
    user_id: int | None = None,
    retry_count: int = 0,
) -> dict:
    """
    input: category (key of CATEGORY_TO_DB), the exact prompt, failure reason, retrieved RAG chunks, raw model output.
    core logic: append one JSON line (utc timestamp) to LOG_PATH under a lock; failures to write never propagate.
    output: the record dict that was written (also useful for tests).
    """
    if category not in CATEGORY_TO_DB:
        raise ValueError(f"unknown ai error category: {category}")
    record = {
        "ts": datetime.now(UTC_TZ).isoformat(),
        "category": category,
        "db_error_type": CATEGORY_TO_DB[category].value,
        "user_id": user_id,
        "prompt": sanitize_prompt(prompt, max_chars=2000),
        "retrieved_context": [sanitize_prompt(c, max_chars=600) for c in (retrieved_context or [])],
        "raw_output": (raw_output or "")[:4000] or None,
        "reason": reason[:500],
        "retry_count": retry_count,
    }
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break a request
    return record
