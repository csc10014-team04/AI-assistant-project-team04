# [pic: khoi] unified dotenv loader & runtime llm configuration (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import math
import os
import socket
from urllib.parse import urlparse, urlunparse

from database import DEPLOY_ENV_PATH, LOCAL_ENV_PATH, _read_dotenv_file

DEFAULT_VLLM_ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"
DEFAULT_LLM_MODEL = "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"
DEFAULT_NLU_TIMEOUT_SECONDS = 3.0
DEFAULT_ACADEMIC_TIMEOUT_SECONDS = 8.0

_DOTENV_LOADED = False


def load_be_dotenv(force: bool = False) -> dict[str, str]:
    """
    input: force (bool) to re-read .env files even if already loaded in this process.
    core logic: merge deployment and BE .env files and inject unset keys into os.environ via setdefault.
    output: dict[str, str] of merged dotenv entries applied when unset.
    """
    global _DOTENV_LOADED
    merged = {
        **_read_dotenv_file(DEPLOY_ENV_PATH),
        **_read_dotenv_file(LOCAL_ENV_PATH),
    }
    if _DOTENV_LOADED and not force:
        return merged
    for key, val in merged.items():
        if key and val != "":
            os.environ.setdefault(key, val)  # preserve explicit env vars and test monkeypatches
    _DOTENV_LOADED = True
    return merged


load_be_dotenv()


def normalize_chat_completions_url(raw_url: str) -> str:
    """
    input: raw_url (str) configured base or full chat-completions endpoint URL.
    core logic: append /v1/chat/completions or /chat/completions when omitted.
    output: normalized endpoint str, or "" if blank.
    """
    cleaned = (raw_url or "").strip().rstrip("/")
    if not cleaned:
        return ""
    if cleaned.endswith("/v1/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


def sanitize_endpoint_url(url: str) -> str:
    """
    input: url (str) of outbound LLM service.
    core logic: strip any embedded credentials, query string, or fragment before logging.
    output: safe endpoint URL string suitable for audit logs.
    """
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def resolve_vllm_endpoint(explicit_override: str | None = None) -> str:
    """
    input: explicit_override (str | None) optional monkeypatched or caller-supplied endpoint.
    core logic: check override -> VLLM_ENDPOINT -> LLAMA_API_URL -> local ports (8000, 11434) -> default.
    output: normalized /v1/chat/completions endpoint str.
    """
    if explicit_override and explicit_override.strip():
        return normalize_chat_completions_url(explicit_override)
    load_be_dotenv()
    vllm_env = os.getenv("VLLM_ENDPOINT", "").strip()
    if vllm_env:
        return normalize_chat_completions_url(vllm_env)
    llama_env = os.getenv("LLAMA_API_URL", "").strip()
    if llama_env:
        return normalize_chat_completions_url(llama_env)
    try:
        for port in (8000, 11434):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.1)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return f"http://127.0.0.1:{port}/v1/chat/completions"
    except Exception:
        pass
    return DEFAULT_VLLM_ENDPOINT


def resolve_llm_model(explicit_override: str | None = None) -> str:
    """
    input: explicit_override (str | None) optional caller or monkeypatch model override.
    core logic: prefer explicit override, then LLM_MODEL env var, then DEFAULT_LLM_MODEL.
    output: non-empty model identifier str.
    """
    load_be_dotenv()
    raw = (explicit_override or "").strip() or os.getenv("LLM_MODEL", "").strip()
    return raw or DEFAULT_LLM_MODEL


def resolve_llm_timeout(feature: str = "nlu", explicit_override: float | None = None) -> float:
    """
    input: feature ("nlu" | "academic_rag") and optional explicit_override timeout seconds.
    core logic: parse positive finite timeout with feature-specific env override and safe default.
    output: float timeout in seconds.
    """
    default_val = DEFAULT_ACADEMIC_TIMEOUT_SECONDS if feature == "academic_rag" else DEFAULT_NLU_TIMEOUT_SECONDS
    if explicit_override is not None:
        try:
            parsed = float(explicit_override)
            if math.isfinite(parsed) and parsed > 0:
                return parsed
        except (TypeError, ValueError):
            return default_val
    load_be_dotenv()
    candidates: list[str] = []
    if feature == "academic_rag":
        candidates.append(os.getenv("ACADEMIC_LLM_TIMEOUT_SECONDS", "").strip())
    candidates.append(os.getenv("LLM_TIMEOUT_SECONDS", "").strip())
    for raw in candidates:
        if not raw:
            continue
        try:
            parsed = float(raw)
            if math.isfinite(parsed) and parsed > 0:
                return parsed
        except ValueError:
            continue
    return default_val


def describe_runtime_ai_config() -> dict:
    """
    input: none (reads current process env and .env configuration).
    core logic: inspect resolved endpoint, model, timeouts, and private-network allowlist status.
    output: non-secret summary dict safe to expose in /api/v1/debug/logs.
    """
    from services.privacy import is_private_endpoint

    endpoint = resolve_vllm_endpoint()
    return {
        "vllm_endpoint": sanitize_endpoint_url(endpoint),
        "model": resolve_llm_model(),
        "nlu_timeout_seconds": resolve_llm_timeout("nlu"),
        "academic_timeout_seconds": resolve_llm_timeout("academic_rag"),
        "endpoint_allowed": is_private_endpoint(endpoint),
        "allowed_hosts_configured": bool(os.getenv("LLM_ALLOWED_HOSTS", "").strip()),
    }
