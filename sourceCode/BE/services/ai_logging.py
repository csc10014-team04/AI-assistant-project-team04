# [pic: lam] p2-12 ai error taxonomy logger (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from database import UTC_TZ
from models import AiErrorType
from services.llm_config import sanitize_endpoint_url
from services.privacy import sanitize_prompt

LOG_PATH = Path(os.getenv("AI_ERROR_LOG_PATH", str(Path(__file__).resolve().parent.parent / "logs" / "ai_errors.jsonl")))
_ENV_CALL_LOG = os.getenv("AI_CALL_LOG_PATH", "").strip()
CALL_LOG_PATH: Path | None = Path(_ENV_CALL_LOG) if _ENV_CALL_LOG else None
_lock = threading.Lock()
_logger = logging.getLogger(__name__)

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
        "raw_output": sanitize_prompt(raw_output or "", max_chars=4000) or None,
        "reason": sanitize_prompt(reason, max_chars=500),
        "retry_count": retry_count,
    }
    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        _logger.warning("Could not append the AI error log at %s", LOG_PATH, exc_info=True)
    return record


def get_call_log_path() -> Path:
    """
    input: none.
    core logic: resolve AI call audit log path via CALL_LOG_PATH, AI_CALL_LOG_PATH env, or LOG_PATH directory.
    output: Path to jsonl audit file (isolated in tmp_path automatically when tests monkeypatch LOG_PATH).
    """
    if CALL_LOG_PATH is not None:
        return CALL_LOG_PATH
    env_path = os.getenv("AI_CALL_LOG_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return LOG_PATH.parent / "ai_calls.jsonl"


def _sanitize_usage(usage: dict | None) -> dict[str, int] | None:
    """keep only integer token counters from an openai-compatible usage object."""
    if not isinstance(usage, dict):
        return None
    clean: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = usage.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            clean[key] = val
    return clean or None


def log_ai_call(
    feature: str,
    status: str,
    endpoint: str,
    model: str,
    prompt: str,
    *,
    http_status: int | None = None,
    latency_ms: float | None = None,
    raw_output: str | None = None,
    usage: dict | None = None,
    user_id: int | None = None,
    source: str = "llm",
    fallback_reason: str | None = None,
) -> dict:
    """
    input: feature name, status ("OK" | "FALLBACK"), endpoint, model, sanitized prompt, and response metadata.
    core logic: redact PII in prompt/output, record structured proof of AI invocation to ai_calls.jsonl and logger.
    output: dict record written to the AI call audit log.
    """
    safe_endpoint = sanitize_endpoint_url(endpoint)
    safe_latency = round(float(latency_ms), 1) if latency_ms is not None else None
    record = {
        "ts": datetime.now(UTC_TZ).isoformat(),
        "feature": feature,
        "status": status,
        "endpoint": safe_endpoint,
        "model": model,
        "http_status": http_status,
        "latency_ms": safe_latency,
        "user_id": user_id,
        "source": source,
        "prompt": sanitize_prompt(prompt or "", max_chars=600),
        "raw_output": sanitize_prompt(raw_output or "", max_chars=1200) or None,
        "usage": _sanitize_usage(usage),
        "fallback_reason": sanitize_prompt(fallback_reason, max_chars=300) if fallback_reason else None,
    }
    target = get_call_log_path()
    try:
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        _logger.warning("Could not append the AI call log at %s", target, exc_info=True)
    _logger.info(
        "[AI CALL %s] feature=%s source=%s endpoint=%s model=%s http=%s latency_ms=%s",
        status,
        feature,
        source,
        safe_endpoint,
        model,
        http_status,
        safe_latency,
    )
    return record


def read_recent_ai_calls(limit: int = 30) -> list[dict]:
    """read up to `limit` newest AI call audit records from ai_calls.jsonl (newest first)."""
    if limit <= 0:
        return []
    target = get_call_log_path()
    if not target.exists():
        return []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    parsed: list[dict] = []
    for raw_line in lines[-limit:]:
        if not raw_line.strip():
            continue
        try:
            parsed.append(json.loads(raw_line))
        except json.JSONDecodeError:
            parsed.append({"raw_line": raw_line})
    parsed.reverse()
    return parsed
