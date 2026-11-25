# [pic: khoi] p1-2 data privacy isolation & fernet encryption (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import base64
from functools import lru_cache
import hashlib
import ipaddress
import logging
import os
import re
import unicodedata
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from services.llm_config import load_be_dotenv

load_be_dotenv()  # load LLM_ALLOWED_HOSTS and DATA_ENCRYPTION_KEY when running outside docker

MAX_PROMPT_CHARS = 500  # keeps system+user prompt inside the 2048-token vllm context window
_DEFAULT_ENCRYPTION_KEY = "dev-encryption-key-change-in-production"
_KDF_SALT = b"hcmus-university-life-assistant-v1-salt"
_KDF_ITERATIONS = 310_000
_logger = logging.getLogger(__name__)
_warned_default_enc_key = False

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.-]?\d){8,10}(?!\d)")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_DOCKER_SERVICE_HOSTS = {"llama_engine", "local_llama_inference", "localhost"}


def sanitize_prompt(text: str, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """
    input: text (str) raw user prompt and max_chars (int) hard length cap.
    core logic: NFC-normalize, strip control chars, redact emails/phones/urls, collapse whitespace, truncate.
    output: str safe to embed in an llm prompt or persist to ai_error_logs.
    typical flow: "mail a@b.com 0901234567" -> "mail [email] [phone]".
    """
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = _CONTROL_CHARS_RE.sub(" ", cleaned)
    cleaned = _EMAIL_RE.sub("[email]", cleaned)
    cleaned = _URL_RE.sub("[url]", cleaned)
    cleaned = _PHONE_RE.sub("[phone]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def is_private_endpoint(url: str) -> bool:
    """
    input: url (str) of the llm / internal service endpoint.
    core logic: accept only loopback, RFC1918/link-local ips, docker service names or *.local hosts.
    output: bool, True when the host is not a public internet address.
    typical flow: http://127.0.0.1:8000 -> True; https://api.openai.com -> False.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if host in _DOCKER_SERVICE_HOSTS or host.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    allowed = [x.strip().lower() for x in os.getenv("LLM_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if host in allowed:
        return True  # explicit opt-in for the team's own AI host (e.g. a Radmin/Hamachi 26.x.x.x address)
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False  # unknown public-looking dns name
    if addr in _CGNAT:
        return True  # tailscale range
    for rule in allowed:
        if "/" in rule and addr in ipaddress.ip_network(rule, strict=False):
            return True  # allowlisted CIDR, e.g. 26.0.0.0/8
    return addr.is_private or addr.is_loopback or addr.is_link_local


def assert_private_endpoint(url: str) -> str:
    """
    input: url (str) outbound target for personal schedule data.
    core logic: raise instead of letting schedule data leave the private network.
    output: the same url when private; raises ValueError otherwise.
    """
    if not is_private_endpoint(url):
        raise ValueError(f"refusing to send schedule data to non-private endpoint: {url}")
    return url


@lru_cache(maxsize=32)
def _derive_fernet_key(secret: str) -> bytes:
    """derive a cached 32-byte urlsafe key via PBKDF2-HMAC-SHA256."""
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        _KDF_SALT,
        _KDF_ITERATIONS,
        dklen=32,
    )
    return base64.urlsafe_b64encode(derived)


def _fernet() -> Fernet:
    """derive a Fernet key from DATA_ENCRYPTION_KEY (reject default in production)."""
    global _warned_default_enc_key
    secret = os.getenv("DATA_ENCRYPTION_KEY", _DEFAULT_ENCRYPTION_KEY)
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env in {"production", "prod"} and (
        not secret or secret == _DEFAULT_ENCRYPTION_KEY or len(secret) < 32
    ):
        raise RuntimeError("DATA_ENCRYPTION_KEY must be set to a non-default secret (>= 32 chars) in production")
    if secret == _DEFAULT_ENCRYPTION_KEY and not _warned_default_enc_key:
        _warned_default_enc_key = True
        _logger.warning("Using development default DATA_ENCRYPTION_KEY; set DATA_ENCRYPTION_KEY in production.")
    return Fernet(_derive_fernet_key(secret))


def encrypt_text(plain: str) -> str:
    """
    input: plain (str) sensitive text such as a stored prompt.
    output: str urlsafe Fernet token (AES-128-CBC + HMAC) safe for a TEXT column.
    """
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str | None:
    """
    input: token (str) produced by encrypt_text.
    output: original str, or None when the token is corrupted / key mismatched.
    """
    try:
        token_bytes = token.encode("ascii")
        return _fernet().decrypt(token_bytes).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError):
        if os.getenv("ALLOW_LEGACY_SHA256_DECRYPT", "0") == "1":
            secret = os.getenv("DATA_ENCRYPTION_KEY", _DEFAULT_ENCRYPTION_KEY)
            legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
            try:
                return Fernet(legacy_key).decrypt(token.encode("ascii")).decode("utf-8")
            except (InvalidToken, ValueError, UnicodeEncodeError):
                return None
        return None
