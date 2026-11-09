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


_PERIOD = r"(sáng|sang|trưa|trua|chiều|chieu|tối|pm|am)"
_CLOCK_RANGE = re.compile(
    r"(?:từ|tu|from)?\s*(\d{1,2})\s*(?:h|giờ|gio|:)\s*(\d{2})?\s*" + _PERIOD + r"?\s*"
    r"(?:đến|den|tới|toi|to|until|-|–)\s*(\d{1,2})\s*(?:h|giờ|gio|:)?\s*(\d{2})?\s*" + _PERIOD + r"?",
    re.IGNORECASE,
)
_CLOCK_POINT = re.compile(r"(?:lúc|luc|vào\s+lúc|at|trước|truoc|sau)\s*\d{1,2}\s*(?:h|giờ|gio|:)\s*\d{0,2}", re.IGNORECASE)
_HOURS_MINUTES = re.compile(r"(\d{1,2})\s*(?:h|giờ|gio|tiếng|tieng)\s*(\d{1,2})\s*(?:phút|phut|p|min)?\b", re.IGNORECASE)


def _strip_clock(text: str) -> str:
    """times of day ("từ 7h đến 18h", "lúc 9h") are not durations"""
    return _CLOCK_POINT.sub(" ", _CLOCK_RANGE.sub(" ", text))


def _hour24(hour: int, period: str | None) -> int:
    period = (period or "").lower()
    if period in {"chiều", "chieu", "tối", "pm"} and hour < 12:
        return hour + 12
    if period in {"trưa", "trua"} and hour < 11:
        return hour + 12
    return hour


def parse_clock_window(text: str) -> tuple[int, int] | None:
    """"từ 11h sáng đến 5h chiều" -> (660, 1020) minutes after midnight; None if absent or not 15..720 minutes."""
    m = _CLOCK_RANGE.search(text)
    if not m or int(m.group(1)) >= 24 or int(m.group(4)) > 24:
        return None
    start_h, end_h = _hour24(int(m.group(1)), m.group(3)), _hour24(int(m.group(4)), m.group(6))
    if not m.group(3) and not m.group(6) and 1 <= start_h <= 5 and end_h <= 11:
        start_h, end_h = start_h + 12, end_h + 12  # "từ 3h đến 5h" without a period: nobody studies at 3 a.m.
    start, end = start_h * 60 + int(m.group(2) or 0), end_h * 60 + int(m.group(5) or 0)
    if end <= start and not m.group(6) and start_h < 12 and end_h < 12:
        end += 12 * 60
    return (start, end) if 15 <= end - start <= 720 else None


def _range_minutes(text: str) -> int | None:
    window = parse_clock_window(text)
    return window[1] - window[0] if window else None


def clip_slot_to_window(slot_start: str, slot_end: str, window: tuple[str, str] | None) -> tuple[str, str]:
    """
    place the task inside the chosen free gap at the user's requested clock window ("11:00".."17:00").
    The gap is returned unchanged when there is no window or the window does not fit entirely inside the gap.
    """
    from datetime import datetime

    if not window:
        return slot_start, slot_end
    try:
        gs, ge = datetime.fromisoformat(slot_start), datetime.fromisoformat(slot_end)
        sh, sm = map(int, window[0].split(":"))
        eh, em = map(int, window[1].split(":"))
        ws, we = gs.replace(hour=sh, minute=sm, second=0, microsecond=0), gs.replace(hour=eh, minute=em, second=0, microsecond=0)
    except (ValueError, TypeError):
        return slot_start, slot_end
    if gs <= ws < we <= ge:
        return ws.isoformat(), we.isoformat()
    return slot_start, slot_end


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
    result = {"title": title, "duration_minutes": duration, "fallback_mode": True}
    window = parse_clock_window(text)
    if window:
        result["requested_start"] = f"{window[0] // 60:02d}:{window[0] % 60:02d}"
        result["requested_end"] = f"{window[1] // 60:02d}:{window[1] % 60:02d}"
    return result
