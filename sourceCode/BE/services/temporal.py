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
    if reference_now.tzinfo is None or reference_now.utcoffset() is None:
        raise ValueError("reference_now must be timezone-aware")
    today = reference_now.astimezone(VN_TZ).date()
    default = ResolvedWindow(today, today + timedelta(days=6), assumed=True,
                             note="no date given; searching the next 7 days")
    if not hint or not hint.strip():
        return default
    h = unicodedata.normalize("NFC", hint).lower().strip()
    months = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }
    month_pattern = "|".join(sorted(months, key=len, reverse=True))
    month_date = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b"
        rf"|\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})(?:,?\s+(\d{{4}}))?\b",
        h,
    )
    if month_date:
        if month_date.group(1):
            month = months[month_date.group(1)]
            day = int(month_date.group(2))
            year = int(month_date.group(3)) if month_date.group(3) else today.year
            has_year = month_date.group(3) is not None
        else:
            day = int(month_date.group(4))
            month = months[month_date.group(5)]
            year = int(month_date.group(6)) if month_date.group(6) else today.year
            has_year = month_date.group(6) is not None
        try:
            d = date(year, month, day)
        except ValueError:
            default.clarification_question = f'The date "{month_date.group(0)}" is invalid. Which date would you like to choose?'
            return default
        if not has_year and d < today:
            try:
                d = date(year + 1, month, day)
            except ValueError:
                default.clarification_question = (
                    f'The date "{month_date.group(0)}" is invalid in the next year. Which date would you like to choose?'
                )
                return default
        return ResolvedWindow(d, d)
    if any(v in h for v in _VAGUE):
        default.clarification_question = "Which date would you like to schedule this for? (e.g., tomorrow, Friday, next week)"
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
            default.clarification_question = f'The date "{m.group(0)}" is invalid. Which date would you like to choose?'
            return default
        if not m.group(3) and d < today:
            d = date(year + 1, month, day)
        return ResolvedWindow(d, d)
    ordinal = re.search(r"\b(\d{1,2})(st|nd|rd|th)\b", h)
    if ordinal:
        day = int(ordinal.group(1))
        year = today.year
        try:
            d = date(year, today.month, day)
        except ValueError:
            default.clarification_question = f'The date "{ordinal.group(0)}" is invalid. Which date would you like to choose?'
            return default
        if d < today:
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            try:
                d = date(next_month.year, next_month.month, day)
            except ValueError:
                default.clarification_question = (
                    f'The date "{ordinal.group(0)}" is invalid in the next month. Which date would you like to choose?'
                )
                return default
        return ResolvedWindow(d, d)
    if "hôm nay" in h or h == "today":
        return ResolvedWindow(today, today)
    if "ngày mai" in h or h == "tomorrow":
        return ResolvedWindow(today + timedelta(days=1), today + timedelta(days=1))
    if "ngày kia" in h:
        return ResolvedWindow(today + timedelta(days=2), today + timedelta(days=2))

    next_week = "tuần sau" in h or "next week" in h
    is_weekend = "cuối tuần" in h or "weekend" in h
    next_weekend = "next weekend" in h
    wd = re.search(r"thứ\s*(hai|ba|tư|năm|sáu|bảy|[2-7])", h)
    sunday = "chủ nhật" in h and not wd

    if next_week and not wd and not sunday and not is_weekend:
        mon = _week_monday(today) + timedelta(days=7)
        return ResolvedWindow(mon, mon + timedelta(days=6))
    if ("tuần này" in h or "this week" in h) and not wd and not sunday and not is_weekend:
        return ResolvedWindow(today, _week_monday(today) + timedelta(days=6))
    if is_weekend:
        sat = _week_monday(today) + timedelta(days=5)
        if next_week or next_weekend:
            sat += timedelta(days=7)
            return ResolvedWindow(sat, sat + timedelta(days=1))
        return ResolvedWindow(max(sat, today), sat + timedelta(days=1))
    if "tháng sau" in h:
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return ResolvedWindow(first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1))
    if "cuối tháng" in h:
        last = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return ResolvedWindow(max(today, last - timedelta(days=6)), last)

    if wd or sunday:
        target = 6 if (sunday or wd is None) else _WEEKDAYS[wd.group(1)]
        if next_week:
            d = _week_monday(today) + timedelta(days=7 + target)
            return ResolvedWindow(d, d)
        d = today + timedelta(days=(target - today.weekday()) % 7)
        window = ResolvedWindow(d, d)
        if d == today:
            window.assumed = True
            window.note = "weekday is today; assumed today (say 'tuần sau' for next week)"
        return window

    default.clarification_question = f'I could not understand the date "{hint}". Which date would you like to schedule this for?'
    return default
