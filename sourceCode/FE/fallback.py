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
    r"\b(xếp|xep|sắp xếp|sap xep|giúp|giup|cho|mình|minh|tôi|toi|vào|vao|nhé|nhe|nha|hãy|lịch|lich|please|schedule)\b",
    re.IGNORECASE,
)
_MINUTE_UNITS = {"phút", "phut", "p", "min", "mins"}


_CLOCK_RANGE = re.compile(
    r"(?:từ|tu|from)?\s*(\d{1,2})\s*(?:h|giờ|gio|:)\s*(\d{2})?\s*(?:đến|den|tới|toi|to|until|-|–)\s*(\d{1,2})\s*(?:h|giờ|gio|:)?\s*(\d{2})?",
    re.IGNORECASE,
)
_CLOCK_POINT = re.compile(r"(?:lúc|luc|vào\s+lúc|at|trước|truoc|sau)\s*\d{1,2}\s*(?:h|giờ|gio|:)\s*\d{0,2}", re.IGNORECASE)
_HOURS_MINUTES = re.compile(r"(\d{1,2})\s*(?:h|giờ|gio|tiếng|tieng)\s*(\d{1,2})\s*(?:phút|phut|p|min)?\b", re.IGNORECASE)


def _strip_clock(text: str) -> str:
    """times of day ("từ 7h đến 18h", "lúc 9h") are not durations"""
    return _CLOCK_POINT.sub(" ", _CLOCK_RANGE.sub(" ", text))


def _range_minutes(text: str) -> int | None:
    m = _CLOCK_RANGE.search(text)
    if not m or int(m.group(1)) >= 24 or int(m.group(3)) > 24:
        return None
    minutes = (int(m.group(3)) * 60 + int(m.group(4) or 0)) - (int(m.group(1)) * 60 + int(m.group(2) or 0))
    return minutes if 15 <= minutes <= 720 else None


def is_timeout(error) -> bool:
    """True for socket/urllib timeouts; False for refused connections and DNS failures."""
    if isinstance(error, TimeoutError):
        return True
    return "timed out" in str(error).lower() or "timeout" in type(error).__name__.lower()


def parse_request(text: str, default_minutes: int = 60) -> dict:
    """returns {"title", "duration_minutes", "fallback_mode": True} for the manual picker."""
    stripped = _strip_clock(text)
    duration = default_minutes
    hm = _HOURS_MINUTES.search(stripped)
    match = _DURATION.search(stripped)
    if hm and 15 <= int(hm.group(1)) * 60 + int(hm.group(2)) <= 720:
        duration = int(hm.group(1)) * 60 + int(hm.group(2))
    elif match:
        value = float(match.group(1).replace(",", "."))
        minutes = round(value * (1 if match.group(2).lower() in _MINUTE_UNITS else 60))
        if 15 <= minutes <= 720:
            duration = minutes
    elif _range_minutes(text):
        duration = _range_minutes(text)
    cleaned = _HOURS_MINUTES.sub(" ", stripped)
    cleaned = _DURATION.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:xếp|xep|sắp xếp|sap xep)\s+lịch\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = _FILLER.sub(" ", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    title = re.sub(r"\s+", " ", cleaned).strip()[:100] or "Hoạt động"
    return {"title": title, "duration_minutes": duration, "fallback_mode": True}
