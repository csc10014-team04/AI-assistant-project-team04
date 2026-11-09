# [pic: lam] p2-3 deterministic relative date resolution (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from database import VN_TZ

_WEEKDAYS = {"hai": 0, "2": 0, "ba": 1, "3": 1, "tư": 2, "4": 2, "năm": 3, "5": 3,
             "sáu": 4, "6": 4, "bảy": 5, "7": 5}
_VAGUE = ("sớm", "lúc nào đó", "sắp tới", "dạo này", "khi nào rảnh", "một lúc nào", "vài hôm nữa", "soon", "sometime", "whenever")


@dataclass
class ResolvedWindow:
    start: date
    end: date  # inclusive
    assumed: bool = False  # True when a default was applied instead of an explicit user statement
    clarification_question: str | None = None
    note: str | None = None


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def resolve_date_hint(hint: str | None, reference_now: datetime) -> ResolvedWindow:
    """
    input: hint (str|None) literal date words from the prompt, reference_now (aware datetime).
    core logic: map relative Vietnamese/English expressions to an inclusive VN-local date window using only
                reference_now (no model involvement => zero temporal hallucination). Vague phrases produce a
                clarifying question plus a safe default (next 7 days). Missing hint => default window, assumed.
    output: ResolvedWindow.
    """
    if reference_now.tzinfo is None:
        raise ValueError("reference_now must be timezone-aware")
    today = reference_now.astimezone(VN_TZ).date()
    default = ResolvedWindow(today, today + timedelta(days=6), assumed=True,
                             note="no date given; searching the next 7 days")
    if not hint or not hint.strip():
        return default
    h = unicodedata.normalize("NFC", hint).lower().strip()

    if any(v in h for v in _VAGUE):
        default.clarification_question = "Bạn muốn xếp vào ngày nào? (ví dụ: ngày mai, thứ sáu, tuần sau)"
        default.note = "vague date; defaulted to next 7 days"
        return default

    m = re.search(r"(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{2,4}))?", h)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = date(year, month, day)
        except ValueError:
            default.clarification_question = f"Ngày {m.group(0)} không hợp lệ, bạn muốn ngày nào?"
            return default
        if not m.group(3) and d < today:
            d = date(year + 1, month, day)
        return ResolvedWindow(d, d)

    if "hôm nay" in h or h == "today":
        return ResolvedWindow(today, today)
    if "ngày mai" in h or h == "tomorrow":
        return ResolvedWindow(today + timedelta(days=1), today + timedelta(days=1))
    if "ngày kia" in h:
        return ResolvedWindow(today + timedelta(days=2), today + timedelta(days=2))

    next_week = "tuần sau" in h or "next week" in h
    wd = re.search(r"thứ\s*(hai|ba|tư|năm|sáu|bảy|[2-7])", h)
    sunday = "chủ nhật" in h and not wd

    if next_week and not wd and not sunday:
        mon = _week_monday(today) + timedelta(days=7)
        return ResolvedWindow(mon, mon + timedelta(days=6))
    if "tuần này" in h or "this week" in h:
        return ResolvedWindow(today, _week_monday(today) + timedelta(days=6))
    if "cuối tuần" in h:
        sat = _week_monday(today) + timedelta(days=5)
        return ResolvedWindow(max(sat, today), sat + timedelta(days=1))
    if "tháng sau" in h:
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return ResolvedWindow(first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1))
    if "cuối tháng" in h:
        last = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return ResolvedWindow(max(today, last - timedelta(days=6)), last)

    if wd or sunday:
        target = 6 if sunday else _WEEKDAYS[wd.group(1)]
        if next_week:
            d = _week_monday(today) + timedelta(days=7 + target)
            return ResolvedWindow(d, d)
        d = today + timedelta(days=(target - today.weekday()) % 7)
        window = ResolvedWindow(d, d)
        if d == today:
            window.assumed = True
            window.note = "weekday is today; assumed today (say 'tuần sau' for next week)"
        return window

    default.clarification_question = f'Mình chưa hiểu "{hint}". Bạn muốn xếp vào ngày nào?'
    return default
