# owner: Database & AI (P1-7 natural language understanding: intent + entity extraction with deterministic fallback)
import json
import os
import re
import time
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from database import VN_TZ
from models import AiErrorLog, AiErrorType
from services import rag
from services.ai_logging import log_ai_failure
from services.inference_queue import QueueWaitTimeout, broker
from services.normalizer import normalize_text
from services.privacy import assert_private_endpoint, sanitize_prompt
from services.telemetry import record_latency_ms
from services.temporal import resolve_date_hint

def _detect_default_vllm_endpoint() -> str:
    env_val = os.getenv("VLLM_ENDPOINT")
    if env_val:
        return env_val
    try:
        import socket
        for port in (8000, 11434):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    return f"http://127.0.0.1:{port}/v1/chat/completions"
    except Exception:
        pass
    return "http://127.0.0.1:8000/v1/chat/completions"


VLLM_ENDPOINT = _detect_default_vllm_endpoint()
MODEL_NAME = os.getenv("LLM_MODEL", "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "3.0"))  # architecture A1: fallback < 1s after 3s
MAX_SCHEMA_RETRIES = 1

Intent = Literal["schedule_task", "query_schedule", "delete_event", "reschedule", "unknown"]
TimeOfDay = Literal["morning", "afternoon", "evening"]

SYSTEM_PROMPT = (
    "You extract scheduling info from a Vietnamese/English student message. "
    "Reply with ONE JSON object only, no prose. Keys: "
    'intent (schedule_task|query_schedule|delete_event|reschedule|unknown), '
    "title (string|null), duration_minutes (int|null), priority (1-3|null, 1=highest), "
    "preferred_time_of_day (morning|afternoon|evening|null), avoid_time_of_day "
    "(morning|afternoon|evening|null), date_hint (copy the user's date words or null), "
    "deadline_hint (copy the user's deadline/due-date words if stated, else null). "
    "Never invent values the user did not state; use null instead. "
    "Never output calendar dates, only copy the user's own date words. "
    "Distinguish schedule_task vs query_schedule: 'xếp lịch', 'sắp xếp', or scheduling an activity is schedule_task; "
    "'xem lịch', 'có lịch gì', 'khi nào rảnh' is query_schedule. "
    "Do not include time of day words (sáng, chiều, tối) in date_hint or deadline_hint."
)

FEW_SHOT: list[dict[str, str]] = [
    {"role": "user", "content": "xếp 3 tiếng làm đồ án CTDL, không làm buổi tối"},
    {"role": "assistant", "content": '{"intent":"schedule_task","title":"làm đồ án CTDL","duration_minutes":180,"priority":null,"preferred_time_of_day":null,"avoid_time_of_day":"evening","date_hint":null,"deadline_hint":null}'},
    {"role": "user", "content": "mình cần học bài gấp 90 phút chiều thứ sáu"},
    {"role": "assistant", "content": '{"intent":"schedule_task","title":"học bài","duration_minutes":90,"priority":1,"preferred_time_of_day":"afternoon","avoid_time_of_day":null,"date_hint":"thứ sáu","deadline_hint":null}'},
    {"role": "user", "content": "hạn nộp bài tập CTDL là thứ sáu, xếp cho mình 2 tiếng làm bài trong tuần này"},
    {"role": "assistant", "content": '{"intent":"schedule_task","title":"làm bài tập CTDL","duration_minutes":120,"priority":1,"preferred_time_of_day":null,"avoid_time_of_day":null,"date_hint":"tuần này","deadline_hint":"thứ sáu"}'},
    {"role": "user", "content": "xóa buổi gym ngày mai"},
    {"role": "assistant", "content": '{"intent":"delete_event","title":"gym","duration_minutes":null,"priority":null,"preferred_time_of_day":null,"avoid_time_of_day":null,"date_hint":"ngày mai","deadline_hint":null}'},
    {"role": "user", "content": "tuần này mình có lịch gì"},
    {"role": "assistant", "content": '{"intent":"query_schedule","title":null,"duration_minutes":null,"priority":null,"preferred_time_of_day":null,"avoid_time_of_day":null,"date_hint":"tuần này","deadline_hint":null}'},
    {"role": "user", "content": "xếp lịch học bài"},
    {"role": "assistant", "content": '{"intent":"schedule_task","title":"học bài","duration_minutes":null,"priority":null,"preferred_time_of_day":null,"avoid_time_of_day":null,"date_hint":null,"deadline_hint":null}'},
    {"role": "user", "content": "hôm nay trời đẹp quá"},
    {"role": "assistant", "content": '{"intent":"unknown","title":null,"duration_minutes":null,"priority":null,"preferred_time_of_day":null,"avoid_time_of_day":null,"date_hint":null,"deadline_hint":null}'},
]


class NluResult(BaseModel):
    intent: Intent = "unknown"
    title: str | None = Field(default=None, max_length=255)
    duration_minutes: int | None = Field(default=None)
    priority: int | None = Field(default=None)
    preferred_time_of_day: TimeOfDay | None = None
    avoid_time_of_day: TimeOfDay | None = None
    date_hint: str | None = Field(default=None, max_length=100)
    # deadline_hint separates hard due-date phrases (e.g., "hạn nộp thứ 6", "trước thứ 6") from general search windows
    # so find_user_free_slots and the 35-point slot scorer clamp window_end <= deadline and never suggest late slots
    deadline_hint: str | None = Field(default=None, max_length=100)
    window_start: date | None = None  # resolved deterministically from date_hint (P2-3)
    window_end: date | None = None
    deadline: date | None = None  # hard upper-bound date resolved from deadline_hint for No-Missed-Deadline gate
    date_assumed: bool = False  # True when a default window was applied
    needs_clarification: bool = False
    clarification_question: str | None = None
    profanity_found: bool = False
    fallback_mode: bool = False  # True when the llm failed and rules produced this result
    source: Literal["llm", "rules"] = "llm"
    fallback_reason: str | None = None  # "<CATEGORY>: <reason>" when fallback_mode is True (for diagnosis)

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def _validate_duration(cls, v: int | float | None) -> int | None:
        if v is None:
            return None
        try:
            val = round(float(v))
        except (ValueError, TypeError):
            return None
        return val if 15 <= val <= 720 else None

    @field_validator("priority", mode="before")
    @classmethod
    def _validate_priority(cls, v: int | None) -> int | None:
        if v is None:
            return None
        try:
            val = int(v)
        except (ValueError, TypeError):
            return None
        return val if 1 <= val <= 3 else None


# ---------------------------------------------------------------------------
# deterministic rule-based extractor (also the zero-hallucination fallback)
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(tiếng|tieng|giờ|gio|h|hours?|hrs?|phút|phut|p|mins?|minutes?)\b",
    re.IGNORECASE,
)
_DATE_HINT_RE = re.compile(
    r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?|hôm nay|hom nay|ngày mai|ngay mai|ngày kia|tuần này|tuan nay|tuần sau|tuan sau|"
    r"cuối tuần|cuoi tuan|cuối tháng|tháng sau|"
    r"thứ\s*(?:hai|ba|tư|năm|sáu|bảy|[2-7])|chủ nhật|today|tomorrow|this week|next week|"
    # vague phrases (P2-3): captured so temporal.resolve_date_hint can ask a clarifying question
    r"sớm|som|lúc nào đó|luc nao do|sắp tới|sap toi|dạo này|dao nay|khi nào rảnh|khi nao ranh|"
    r"một lúc nào|mot luc nao|vài hôm nữa|vai hom nua|soon|sometime|whenever)",
    re.IGNORECASE,
)
# matches explicit deadline clauses ("hạn nộp bài tập CTDL là thứ 6", "deadline 25/11", "nộp trước thứ sáu")
_DEADLINE_HINT_RE = re.compile(
    r"\b(?:hạn\s+nộp|hạn\s+chót|deadline|nộp\s+trước|hoàn\s+thành\s+trước|due)"
    r"[^,.;\n]{0,60}?"
    r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?|hôm nay|hom nay|ngày mai|ngay mai|ngày kia|tuần này|tuan nay|tuần sau|tuan sau|"
    r"cuối tuần|cuoi tuan|thứ\s*(?:hai|ba|tư|năm|sáu|bảy|[2-7])|chủ nhật|today|tomorrow)",
    re.IGNORECASE,
)
_TIME_OF_DAY = {
    "morning": ("sáng", "sang", "morning"),
    "afternoon": ("chiều", "chieu", "afternoon"),
    "evening": ("tối", "toi", "evening", "night"),
}
_NEGATION = ("không", "khong", "ko", "đừng", "dung", "tránh", "tranh", "not", "avoid", "no")
_HIGH_PRIORITY = ("gấp", "gap", "quan trọng", "quan trong", "urgent", "asap", "deadline", "thi", "exam")


# clock times are NOT durations: "từ 7h đến 18h" is a time range, "lúc 9h" is a moment. Reading "7h" in them as
# "7 hours" produced wrong durations and left words such as "từ ... đến" in the title.
_CLOCK_RANGE_RE = re.compile(
    r"(?:từ|tu|from)?\s*(\d{1,2})\s*(?:h|giờ|gio|:)\s*(\d{2})?\s*(?:đến|den|tới|toi|to|until|-|–)\s*(\d{1,2})\s*(?:h|giờ|gio|:)?\s*(\d{2})?",
    re.IGNORECASE,
)
_CLOCK_POINT_RE = re.compile(r"(?:lúc|luc|vào\s+lúc|at|trước|truoc|sau)\s*\d{1,2}\s*(?:h|giờ|gio|:)\s*\d{0,2}", re.IGNORECASE)
_HOURS_MINUTES_RE = re.compile(r"(\d{1,2})\s*(?:h|giờ|gio|tiếng|tieng)\s*(\d{1,2})\s*(?:phút|phut|p|min)?\b", re.IGNORECASE)


def _strip_clock_times(text: str) -> str:
    """remove time ranges and clock moments so that their numbers are not read as durations."""
    return _CLOCK_POINT_RE.sub(" ", _CLOCK_RANGE_RE.sub(" ", text))


def extract_time_range_minutes(text: str) -> int | None:
    """length in minutes of "từ 7h đến 18h" (660); None when there is no range or it is not 15..720 minutes."""
    m = _CLOCK_RANGE_RE.search(text)
    if not m:
        return None
    start = int(m.group(1)) * 60 + int(m.group(2) or 0)
    end = int(m.group(3)) * 60 + int(m.group(4) or 0)
    return end - start if 15 <= end - start <= 720 and int(m.group(1)) < 24 and int(m.group(3)) <= 24 else None


def has_duration_phrase(text: str) -> bool:
    """true when the text states a length ("2 tiếng", "1h30", "45 phút") or a time range ("từ 7h đến 11h")."""
    return bool(_DURATION_RE.search(_strip_clock_times(text)) or extract_time_range_minutes(text))


def extract_duration_minutes(text: str) -> int | None:
    """
    input: text (str) sanitized prompt.
    output: int minutes (15..720) from the first "<number> <unit>" phrase, else None.
    typical flow: "1,5 tiếng" -> 90; "45 phút" -> 45; "3h" -> 180; "1h30" -> 90; "từ 7h đến 18h" -> 660.
    """
    hm = _HOURS_MINUTES_RE.search(_strip_clock_times(text))
    if hm:  # "1h30" / "2 tiếng 15 phút" -> hours plus minutes
        total = int(hm.group(1)) * 60 + int(hm.group(2))
        if 15 <= total <= 720:
            return total
    match = _DURATION_RE.search(_strip_clock_times(text))
    if not match:
        return extract_time_range_minutes(text)  # no explicit length: a range such as "từ 7h đến 11h" gives one
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    minutes = round(value * (1 if unit in {"phút", "phut", "p", "min", "mins", "minute", "minutes"} else 60))
    return minutes if 15 <= minutes <= 720 else None


def _time_of_day_flags(text: str) -> tuple[TimeOfDay | None, TimeOfDay | None]:
    """returns (preferred, avoided) by checking a negation word right before the period word."""
    lowered = text.lower()
    preferred: TimeOfDay | None = None
    avoided: TimeOfDay | None = None
    for period, words in _TIME_OF_DAY.items():
        for word in words:
            for m in re.finditer(rf"\b{word}\b", lowered):
                before = lowered[: m.start()].split()[-3:]
                if any(neg in before for neg in _NEGATION):
                    avoided = period  # type: ignore[assignment]
                else:
                    preferred = period  # type: ignore[assignment]
    return preferred, avoided


def _extract_title(text: str) -> str | None:
    """strip request boilerplate, duration and date words; what remains is the activity name."""
    cleaned = _strip_clock_times(text)
    cleaned = _HOURS_MINUTES_RE.sub(" ", cleaned)
    cleaned = _DURATION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:xếp|xep|sắp xếp|sap xep)\s+lịch\b", " ", cleaned, flags=re.IGNORECASE)  # the request words, not the activity
    cleaned = _DATE_HINT_RE.sub(" ", cleaned)
    cleaned = re.sub(
        r"\b(xếp|xep|sắp xếp|sap xep|hãy|giúp|giup|cho|mình|minh|tôi|toi|vào|vao|không|khong|buổi|buoi|lịch|lich|"
        r"hạn\s+nộp|hạn\s+chót|deadline|nộp\s+trước|là|trong|"
        r"sáng|sang|chiều|chieu|tối|toi|nhé|nhe|nha|please|schedule|for|me)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:255] or None


def rule_based_understand(text: str) -> NluResult:
    """
    input: text (str) sanitized prompt.
    core logic: regex extraction of duration, time-of-day, date hint, deadline hint, priority and intent.
    output: NluResult(source="rules"); every field is None when not literally present in the text.
    """
    lowered = text.lower()
    duration = extract_duration_minutes(text)
    preferred, avoided = _time_of_day_flags(text)
    deadline_match = _DEADLINE_HINT_RE.search(text)
    deadline_hint = deadline_match.group(1) if deadline_match else None
    text_without_deadline = (
        text[: deadline_match.start(1)] + " " + text[deadline_match.end(1) :]
        if deadline_match
        else text
    )
    date_match = _DATE_HINT_RE.search(text_without_deadline)

    if re.search(r"\b(xóa|xoa|hủy|huy|delete|cancel)\b", lowered):
        intent: Intent = "delete_event"
    elif re.search(r"\b(dời|doi|đổi|chuyển|chuyen|move|reschedule)\b", lowered):
        intent = "reschedule"
    elif duration is not None or re.search(r"\b(xếp|xep|sắp xếp|sap xep)\b", lowered):
        intent = "schedule_task"
    elif re.search(
        r"\b(lịch|lich|có gì|co gi|khi nào|khi nao|mấy giờ|quy chế|quy định|tín chỉ|học vụ|schedule|what)\b",
        lowered,
    ):
        intent = "query_schedule"
    else:
        intent = "unknown"

    priority = 1 if any(re.search(rf"\b{w}\b", lowered) for w in _HIGH_PRIORITY) else None
    return NluResult(
        intent=intent,
        title=_extract_title(text_without_deadline) if intent == "schedule_task" else None,
        duration_minutes=duration,
        priority=priority,
        preferred_time_of_day=preferred,
        avoid_time_of_day=avoided,
        date_hint=date_match.group(0) if date_match and intent != "unknown" else None,
        deadline_hint=deadline_hint if intent != "unknown" else None,
        fallback_mode=False,
        source="rules",
    )


# ---------------------------------------------------------------------------
# llm call + schema validation + retry
# ---------------------------------------------------------------------------

def _extract_json_object(raw: str) -> dict:
    """pull the first {...} block out of a model reply and parse it (raises ValueError / JSONDecodeError)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no json object in model output")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json root is not an object")
    return parsed


def log_ai_error(
    db: Session | None,
    user_id: int | None,
    prompt: str,
    raw_output: str | None,
    error_type: AiErrorType,
    retry_count: int,
) -> None:
    """persist one AiErrorLog row (flush only; the request owner commits). No-op when db is None."""
    if db is None:
        return
    db.add(
        AiErrorLog(
            user_id=user_id,
            prompt_text=prompt,
            raw_output=(raw_output or "")[:4000] or None,
            error_type=error_type,
            retry_count=retry_count,
            triggered_fallback=True,
        )
    )
    db.flush()


def _finalize(result: NluResult, rules: NluResult, prompt: str, now: datetime, norm_profanity: bool) -> NluResult:
    """shared post-processing: literal-text guards, deterministic date window, clarification, profanity flag."""
    if rules.duration_minutes is not None:
        result.duration_minutes = rules.duration_minutes  # literal text wins over the model
    elif not has_duration_phrase(prompt):
        result.duration_minutes = None  # model invented a duration
    # literal text guard: arranging/scheduling words must never be treated as schedule query
    if result.intent == "query_schedule" and rules.intent == "schedule_task":
        result.intent = "schedule_task"
        if not result.title:
            result.title = rules.title
    # temporal hallucination guard: only a date phrase that literally occurs in the prompt is accepted
    hint = rules.date_hint
    if hint is None and result.date_hint and result.date_hint.lower() in prompt.lower():
        if not any(tod in result.date_hint.lower() for tod in ("sáng", "sang", "chiều", "chieu", "tối", "toi")):
            hint = result.date_hint
    result.date_hint = hint

    # deadline hallucination guard: only a deadline phrase literally present in the prompt is accepted
    dl_hint = rules.deadline_hint
    if dl_hint is None and result.deadline_hint and result.deadline_hint.lower() in prompt.lower():
        if not any(tod in result.deadline_hint.lower() for tod in ("sáng", "sang", "chiều", "chieu", "tối", "toi")):
            dl_hint = result.deadline_hint
    result.deadline_hint = dl_hint

    if result.intent in {"schedule_task", "query_schedule", "reschedule"}:
        window = resolve_date_hint(hint, now)
        result.window_start, result.window_end = window.start, window.end
        result.date_assumed = window.assumed
        if window.clarification_question:
            result.needs_clarification, result.clarification_question = True, window.clarification_question
        if dl_hint is not None:
            dl_window = resolve_date_hint(dl_hint, now)
            result.deadline = dl_window.end
            # clamp search window upper bound to hard deadline so sort-and-sweep never suggests late slots
            if result.window_end is not None and result.deadline is not None and result.window_end > result.deadline:
                result.window_end = result.deadline
            if result.window_start is not None and result.deadline is not None and result.window_start > result.deadline:
                result.window_start = now.astimezone(VN_TZ).date()
    if result.intent == "schedule_task" and result.duration_minutes is None:
        result.needs_clarification = True
        result.clarification_question = result.clarification_question or "Bạn muốn dành bao lâu cho hoạt động này?"
    if result.priority is None:
        result.priority = rules.priority
    result.profanity_found = norm_profanity
    return result


def understand_prompt(
    prompt: str,
    reference_now: datetime,
    *,
    db: Session | None = None,
    user_id: int | None = None,
    client: httpx.Client | None = None,
) -> NluResult:
    """
    input: prompt (str) raw user message, reference_now (aware datetime), optional db/user_id for error logs.
    core logic: sanitize + normalize (P2-6) -> RAG context (P2-2) -> few-shot llm call through the FIFO broker
                (P2-10) -> strict json/pydantic validation with one retry (P2-1) -> deterministic date window
                and clarification (P2-3). Any failure (TIMEOUT, INFRA_CRASH, JSON_PARSE/SCHEMA_VALIDATION,
                SEMANTIC_FAILURE) is logged to ai_error_logs + the jsonl taxonomy file (P2-12) and the
                rule-based result is returned with fallback_mode=True.
    output: NluResult. Never raises for AI failures, so the mobile UI can always open the manual picker.
    """
    if reference_now.tzinfo is None:
        raise ValueError("reference_now must be timezone-aware")
    started = time.monotonic()
    normalized = normalize_text(sanitize_prompt(prompt))
    safe_prompt = normalized.text
    if not safe_prompt:
        return NluResult(intent="unknown", fallback_mode=True, source="rules", profanity_found=normalized.profanity_found)

    base = rule_based_understand(safe_prompt)
    rules = _finalize(base.model_copy(), base, safe_prompt, reference_now, normalized.profanity_found)
    context: list[str] = []
    if user_id is not None:
        try:
            context = [h.text for h in rag.retrieve(user_id, safe_prompt, k=2)]
        except Exception:
            context = []  # a corrupt/missing index must never block the request
    now_vn = reference_now.astimezone(VN_TZ)
    system = f"{SYSTEM_PROMPT} Now: {now_vn:%Y-%m-%d %A %H:%M} (+07:00)."
    if context:
        system += " Known schedule: " + " | ".join(c.replace("\n", "; ")[:200] for c in context)
    messages = [{"role": "system", "content": system}, *FEW_SHOT, {"role": "user", "content": safe_prompt}]
    payload = {"model": MODEL_NAME, "messages": messages, "max_tokens": 200, "temperature": 0.0}

    http = client or httpx.Client(timeout=LLM_TIMEOUT_SECONDS)
    raw_output: str | None = None
    retries = 0
    category = "SEMANTIC_FAILURE"
    reason = "unresolvable intent"
    try:
        assert_private_endpoint(VLLM_ENDPOINT)
        while True:
            try:
                response = broker.run(
                    lambda: http.post(VLLM_ENDPOINT, json=payload, timeout=LLM_TIMEOUT_SECONDS), user_id=user_id
                )
                response.raise_for_status()
                raw_output = response.json()["choices"][0]["message"]["content"]
                result = NluResult.model_validate(_extract_json_object(raw_output))
            except (ValueError, ValidationError, KeyError, IndexError) as exc:
                category = "SCHEMA_VALIDATION" if isinstance(exc, ValidationError) else "JSON_PARSE"
                reason = f"{type(exc).__name__}: {str(exc)[:200]}"
                if retries < MAX_SCHEMA_RETRIES:
                    retries += 1  # reject malformed output and retry once
                    continue
                break
            if result.intent == "unknown" and rules.intent != "unknown":
                category, reason = "SEMANTIC_FAILURE", "model failed to detect intent recognized by rules"
                break
            result.source, result.fallback_mode = "llm", False
            record_latency_ms((time.monotonic() - started) * 1000)
            return _finalize(result, rules, safe_prompt, reference_now, normalized.profanity_found)
    except (httpx.TimeoutException, QueueWaitTimeout) as exc:
        category, reason = "TIMEOUT", f"{type(exc).__name__}: {exc}"
    except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
        category, reason = "INFRA_CRASH", f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        if client is None:
            http.close()

    record = log_ai_failure(category, safe_prompt, reason, retrieved_context=context, raw_output=raw_output,
                            user_id=user_id, retry_count=retries)
    log_ai_error(db, user_id, safe_prompt, raw_output, AiErrorType(record["db_error_type"]), retries)
    record_latency_ms((time.monotonic() - started) * 1000)
    rules.fallback_mode = True
    rules.fallback_reason = f"{category}: {reason}"[:300]
    return rules
