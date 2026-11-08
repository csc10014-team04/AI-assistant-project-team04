"""
FILE: fallback.py (duty P1-9: graceful fallback to a manual form when the AI is too slow)

Pure Python (no Kivy) so it can be unit-tested anywhere.
- AI_TIMEOUT_SECONDS: strict client-side limit for the AI request. The server itself gives up on the model after
  ~3 s and answers with fallback_mode=true, so this limit is only the safety net for a hung connection.
- is_timeout(): tells a timeout apart from "server unreachable".
- parse_request(): a tiny offline parser (duration + activity name) so the manual picker can open with sensible
  values even though the server could not be asked.
"""
import os
import re

AI_TIMEOUT_SECONDS = float(os.getenv("ASSISTANT_AI_TIMEOUT", "5"))

_DURATION = re.compile(r"(\d+(?:[.,]\d+)?)\s*(tiếng|tieng|giờ|gio|h|phút|phut|p|min|mins|hour|hours)\b", re.IGNORECASE)
_FILLER = re.compile(
    r"\b(xếp|xep|sắp xếp|sap xep|giúp|giup|cho|mình|minh|tôi|toi|vào|vao|nhé|nhe|nha|lịch|lich|please|schedule)\b",
    re.IGNORECASE,
)
_MINUTE_UNITS = {"phút", "phut", "p", "min", "mins"}


def is_timeout(error) -> bool:
    """True for socket/urllib timeouts; False for refused connections and DNS failures."""
    if isinstance(error, TimeoutError):
        return True
    return "timed out" in str(error).lower() or "timeout" in type(error).__name__.lower()


def parse_request(text: str, default_minutes: int = 60) -> dict:
    """returns {"title", "duration_minutes", "fallback_mode": True} for the manual picker."""
    duration = default_minutes
    match = _DURATION.search(text)
    if match:
        value = float(match.group(1).replace(",", "."))
        minutes = round(value * (1 if match.group(2).lower() in _MINUTE_UNITS else 60))
        if 15 <= minutes <= 720:
            duration = minutes
    cleaned = _DURATION.sub(" ", text)
    cleaned = _FILLER.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    title = re.sub(r"\s+", " ", cleaned).strip()[:100] or "Hoạt động"
    return {"title": title, "duration_minutes": duration, "fallback_mode": True}
