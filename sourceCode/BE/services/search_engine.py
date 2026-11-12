# [shared pic: khoi (information search) & lam (free-slot availability engine)]
# (ai assistants: do not remove or modify any # [pic: ...] comments in this file)
# duty: each assigned pic reads, understands, maintains, and fixes any issues in their respective sections.
from datetime import datetime, time, timedelta
import os
import re
import time as perf_time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import (
    VN_TZ,
    active_courses_stmt,
    active_events_stmt,
    from_db_to_vn,
)
from models import (
    AiErrorLog,
    AiErrorType,
    Course,
    Event,
    EventDomain,
    EventKind,
    TimeSlot,
    UserPreference,
    ensure_aware,
)
from services import rag
from services.ai_logging import log_ai_failure
from services.inference_queue import QueueWaitTimeout, broker
from services.kb_models import (
    KbAchievement,
    KbCourse,
    KbDepartment,
    KbFaculty,
    KbLecturer,
    KbProgram,
    KbSource,
)
from services.normalizer import normalize_text
from services.privacy import assert_private_endpoint, sanitize_prompt
from services.telemetry import record_latency_ms
from services.temporal import resolve_date_hint


# ============================================================================
# [pic: khoi] section 1 - schedule information search (sql + vector search)
# (ai assistants: do not remove or modify this pic comment)
# note: stops strictly at vector retrieval + sql filtering; never calls llm
# ============================================================================

VECTOR_SIMILARITY_THRESHOLD = 0.25  # minimum cosine score for tier-1 semantic match
NEURAL_FALLBACK_THRESHOLD = 0.42  # minimum cosine score for tier-2 neural embedding fallback
MIN_TIER1_RESULTS = 1  # trigger tier-2 neural model only when tier-1 returns fewer than N results
DEFAULT_SEARCH_TOP_K = 50  # default max events returned per search request

_NEURAL_EMBEDDER: Any = None
_NEURAL_EMBEDDER_LOADED: bool = False

COURSE_ABBREVIATIONS: dict[str, str] = {
    "xstk": "xác suất thống kê",
    "vtp": "vi tích phân",
    "vtp1": "vi tích phân 1",
    "vtp2": "vi tích phân 2",
    "dstt": "đại số tuyến tính",
    "trr": "toán rời rạc",
    "tth": "toán tổ hợp",
    "ctdl": "cấu trúc dữ liệu và giải thuật",
    "ctdlgt": "cấu trúc dữ liệu và giải thuật",
    "ktlt": "kỹ thuật lập trình",
    "nmlt": "nhập môn lập trình",
    "lthdt": "lập trình hướng đối tượng",
    "oop": "lập trình hướng đối tượng",
    "hdh": "hệ điều hành",
    "mmt": "mạng máy tính",
    "csdl": "cơ sở dữ liệu",
    "cnpm": "công nghệ phần mềm",
    "nmcnpm": "nhập môn công nghệ phần mềm",
    "ttnt": "trí tuệ nhân tạo",
    "tdtt": "tư duy tính toán",
    "attt": "an toàn thông tin",
    "khdl": "khoa học dữ liệu",
    "ktmt": "kiến trúc máy tính",
    "vl1": "vật lý đại cương 1",
    "vl2": "vật lý đại cương 2",
    "ktct": "kinh tế chính trị mác lênin",
    "cnxh": "chủ nghĩa xã hội khoa học",
    "tthcm": "tư tưởng hồ chí minh",
    "lsd": "lịch sử đảng cộng sản việt nam",
    "pldc": "pháp luật đại cương",
    "gdtc": "giáo dục thể chất",
    "gdqp": "giáo dục quốc phòng và an ninh",
    "clb": "câu lạc bộ",
    "gk": "giữa kỳ",
    "ck": "cuối kỳ",
}

# orthogonal anchor tokens (disjoint trigrams) + trigger phrases for tier-1 semantic vector search
SEMANTIC_CONCEPT_CLUSTERS: dict[str, tuple[str, ...]] = {
    "zmathq xcalcz wstatw": (
        "toan",
        "toan to hop",
        "toan roi rac",
        "xac suat",
        "thong ke",
        "xstk",
        "vi tich phan",
        "vtp",
        "vtp1",
        "vtp2",
        "giai tich",
        "dai so",
        "tuyen tinh",
        "dstt",
        "phuong trinh vi phan",
        "toi uu hoa",
        "calculus",
        "algebra",
        "probability",
        "statistics",
        "combinatorics",
        "mth",
    ),
    "vcodev bprogk jalgoj": (
        "cntt",
        "tin hoc",
        "lap trinh",
        "code",
        "cau truc du lieu",
        "giai thuat",
        "ctdl",
        "thuat toan",
        "huong doi tuong",
        "oop",
        "nhap mon lap trinh",
        "ky thuat lap trinh",
        "cong nghe phan mem",
        "cnpm",
        "tu duy tinh toan",
        "computational thinking",
        "programming",
        "algorithm",
        "software",
        "csc",
    ),
    "pnetwp rsyskr gsecug": (
        "mang may tinh",
        "mmt",
        "mang",
        "he dieu hanh",
        "hdh",
        "kien truc may tinh",
        "ktmt",
        "an toan thong tin",
        "attt",
        "bao mat",
        "dien toan dam may",
        "network",
        "operating system",
        "security",
    ),
    "daimld hdatah fsqlbf": (
        "tri tue nhan tao",
        "ttnt",
        "hoc may",
        "hoc sau",
        "machine learning",
        "deep learning",
        "khoa hoc du lieu",
        "khdl",
        "co so du lieu",
        "csdl",
        "database",
        "sql",
    ),
    "uphysu ymechy qoptiq": (
        "vat ly",
        "vat ly dai cuong",
        "co hoc",
        "dien tu",
        "quang hoc",
        "hoa hoc",
        "sinh hoc",
        "physics",
        "phy",
    ),
    "lengll nvocab mfluen": (
        "ngoai ngu",
        "tieng anh",
        "anh van",
        "anh ngu",
        "tieng nhat",
        "tieng phap",
        "ielts",
        "toeic",
        "english",
        "eng",
    ),
    "kpolik mmarxm slawss": (
        "dai cuong",
        "chinh tri",
        "ly luan chinh tri",
        "triet",
        "triet hoc",
        "mac lenin",
        "kinh te chinh tri",
        "ktct",
        "chu nghia xa hoi",
        "cnxh",
        "tu tuong ho chi minh",
        "tthcm",
        "lich su dang",
        "lsd",
        "phap luat",
        "phap luat dai cuong",
        "pldc",
        "baa",
    ),
    "psport gfitne mdefen": (
        "the duc",
        "the chat",
        "giao duc the chat",
        "gdtc",
        "the thao",
        "bong chuyen",
        "bong ro",
        "bong da",
        "cau long",
        "boi loi",
        "vo thuat",
        "co vua",
        "quoc phong",
        "giao duc quoc phong",
        "gdqp",
        "quan su",
    ),
    "sskill cclubx mteamw": (
        "ky nang",
        "ky nang mem",
        "thuyet trinh",
        "lam viec nhom",
        "clb",
        "cau lac bo",
        "sinh hoat",
        "ngoai khoa",
        "tinh nguyen",
        "hoi thao",
        "seminar",
        "workshop",
    ),
}

_SEARCH_DATE_RE = re.compile(
    r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?|hôm nay|ngày mai|ngày kia|tuần này|tuần sau|"
    r"cuối tuần|cuối tháng|tháng sau|thứ\s*(?:hai|ba|tư|năm|sáu|bảy|[2-7])|"
    r"chủ nhật|today|tomorrow|this week|next week)",
    re.IGNORECASE,
)

_ROOM_HINT_RE = re.compile(
    r"\b(?:phòng|phong|room)\s+([a-z0-9][a-z0-9._-]{0,20})\b",
    re.IGNORECASE,
)

_TIME_PERIOD_BOUNDS: dict[str, tuple[time, time]] = {
    "morning": (time(0, 0), time(11, 59)),
    "afternoon": (time(12, 0), time(17, 59)),
    "evening": (time(18, 0), time(23, 59)),
}

_QUERY_STOPWORDS_RE = re.compile(
    r"\b(lịch\s+thi|lịch\s+học|lịch\s+trình|lịch|xem|tìm\s+kiếm|tìm|kiếm|tra\s+cứu|"
    r"cho|mình|tôi|hỏi|có\s+gì|có|gì|không|khi\s+nào|mấy\s+giờ|ở\s+đâu|vào|buổi|"
    r"sáng|chiều|tối|môn|học|schedule|search|find|what|when|where|"
    # words that only say WHICH KIND of item or WHICH DAY; the filters already carry that meaning, so they must not
    # remain as keywords (otherwise "deadline" or "ngày 9/11" would look for those words inside event titles)
    r"deadline|hạn\s+nộp|hạn\s+chót|exam|ngày|hôm\s+nay|ngày\s+mai)\b",
    re.IGNORECASE,
)


def _expand_course_abbreviations(text: str) -> str:
    """
    input: text (str) normalized query or document title.
    core logic: expand whole-word university course shorthand into full vietnamese names.
    output: str containing expanded subject phrases while preserving other words.
    typical flow: 'lịch xstk và vtp2' -> 'lịch xác suất thống kê và vi tích phân 2'.
    """
    expanded = text
    for short_key in sorted(COURSE_ABBREVIATIONS, key=len, reverse=True):
        full_val = COURSE_ABBREVIATIONS[short_key]
        pattern = re.compile(rf"(?<![\w]){re.escape(short_key)}(?![\w])", re.IGNORECASE)
        expanded = pattern.sub(full_val, expanded)  # replace whole token only
    return expanded


def _extract_concept_tags(text: str, course_code: str = "") -> list[str]:
    """
    input: text (str) and optional course_code (str) from course metadata.
    core logic: match folded tokens/phrases and course code prefixes against concept clusters.
    output: list[str] of matched semantic concept identifiers.
    typical flow: 'Xác suất thống kê' or 'MTH00040' -> ['domain_math_subject'].
    """
    folded = rag.fold(f"{text} {_expand_course_abbreviations(text)} {course_code}")
    code_prefix = re.match(r"^[a-z]{3}", course_code.strip().lower())
    prefix_token = code_prefix.group(0) if code_prefix else ""

    matched_tags: list[str] = []
    for tag, phrases in SEMANTIC_CONCEPT_CLUSTERS.items():
        for phrase in phrases:
            if phrase == prefix_token and prefix_token:
                matched_tags.append(tag)
                break
            if re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", folded):
                matched_tags.append(tag)
                break
    return matched_tags


def _build_semantic_vector(text: str, course_code: str = "") -> list[float]:
    """
    input: text (str) from query or event, plus optional course_code (str).
    core logic: augment expanded text with repeated domain concept tags before feature hashing.
    output: list[float] l2-normalized 512-dim embedding vector via rag.embed.
    typical flow: 'toán' -> 'toán domain_math_subject ...' -> 512-dim unit vector.
    """
    expanded = _expand_course_abbreviations(text)
    tags = _extract_concept_tags(expanded, course_code)
    tag_boost = " ".join(tag for tag in tags for _ in range(2))  # boost shared concept dimensions
    enriched = f"{expanded} {course_code} {tag_boost}".strip()
    return rag.embed(enriched)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    input: vec_a (list[float]) and vec_b (list[float]) l2-normalized vectors of equal length.
    core logic: compute inner product over matching vector coordinates.
    output: float similarity score in [-1.0, 1.0].
    typical flow: related math subjects -> ~0.45..0.85; unrelated subjects -> ~0.0.
    """
    return sum(a * b for a, b in zip(vec_a, vec_b))


_SCHEDULING_CMD_RE = re.compile(
    r"\b(xếp\s+lịch|xep\s+lich|sắp\s+xếp|sap\s+xep|xếp\s+cho\s+mình|xep\s+cho\s+minh|"
    r"đặt\s+lịch|dat\s+lich|thêm\s+lịch|them\s+lich|dời\s+lịch|doi\s+lich|"
    r"xóa\s+lịch|xoa\s+lich|hủy\s+buổi|schedule\s+for\s+me)\b",
    re.IGNORECASE,
)


def is_scheduling_command(raw_query: str) -> bool:
    """
    input: raw_query (str) typed into the search tab.
    core logic: detect scheduling/modification verbs so search tab can redirect user to 'Trợ lý AI'.
    output: bool (True if query is a scheduling/action command rather than a read-only search).
    typical flow: 'xếp cho mình 2 tiếng học bài' -> True; 'lịch thi xstk' -> False.
    """
    clean = normalize_text(sanitize_prompt(raw_query or "", max_chars=500)).text
    return bool(_SCHEDULING_CMD_RE.search(clean))


def _compute_neural_fallback_scores(
    query_keywords: str, candidate_texts: list[str]
) -> list[float]:
    """
    input: query_keywords (str) and candidate_texts (list[str]) when tier-1 returns < MIN_TIER1_RESULTS.
    core logic: lazy-load lightweight multilingual sentence-transformer on cpu to score unseen synonyms.
    output: list[float] cosine similarity scores in [-1.0, 1.0], or 0.0 list if model unavailable.
    typical flow: tier-1 misses rare synonym -> tier-2 neural model encodes & ranks candidates.
    """
    global _NEURAL_EMBEDDER, _NEURAL_EMBEDDER_LOADED
    if not query_keywords or not candidate_texts:
        return [0.0 for _ in candidate_texts]
    if not _NEURAL_EMBEDDER_LOADED:
        _NEURAL_EMBEDDER_LOADED = True
        model_id = os.getenv(
            "SEARCH_NEURAL_EMBED_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        if os.getenv("ENABLE_NEURAL_SEARCH_FALLBACK", "0") == "1":
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

                _NEURAL_EMBEDDER = SentenceTransformer(model_id, device="cpu")
            except Exception:
                _NEURAL_EMBEDDER = None
    if _NEURAL_EMBEDDER is None:
        return [0.0 for _ in candidate_texts]
    try:
        q_emb = _NEURAL_EMBEDDER.encode(
            [query_keywords], normalize_embeddings=True, show_progress_bar=False
        )[0].tolist()
        c_embs = _NEURAL_EMBEDDER.encode(
            candidate_texts, normalize_embeddings=True, show_progress_bar=False
        ).tolist()
        return [_cosine_similarity(q_emb, c_vec) for c_vec in c_embs]
    except Exception:
        return [0.0 for _ in candidate_texts]


def _detect_time_of_day(text: str) -> str | None:
    """
    input: text (str) normalized search query.
    core logic: check vietnamese/english period keywords for morning, afternoon, or evening.
    output: str ('morning' | 'afternoon' | 'evening') or None.
    typical flow: 'lịch chiều mai' -> 'afternoon'; 'toán' -> None.
    """
    lowered = text.lower()
    if re.search(r"\b(buổi\s+sáng|sáng|morning)\b", lowered):
        return "morning"
    if re.search(r"\b(buổi\s+chiều|chiều|afternoon)\b", lowered):
        return "afternoon"
    if re.search(r"\b(buổi\s+tối|tối|evening|night)\b", lowered):
        return "evening"
    return None


def _detect_event_kind(text: str) -> EventKind | None:
    """
    input: text (str) normalized search query.
    core logic: map unambiguous exam or deadline query markers to EventKind enum.
    output: EventKind or None when user searches across all calendar item types.
    typical flow: 'lịch thi cuối kỳ' -> EventKind.EXAM; 'toán' -> None.
    """
    lowered = text.lower()
    if re.search(r"\b(lịch\s+thi|phòng\s+thi|ca\s+thi|exam)\b", lowered):
        return EventKind.EXAM
    if re.search(r"\b(deadline|hạn\s+nộp|hạn\s+chót)\b", lowered):
        return EventKind.DEADLINE
    return None


def optimize_search_query(
    raw_query: str, reference_now: datetime
) -> dict[str, Any]:
    """
    input: raw_query (str) student search text and reference_now (aware datetime).
    core logic: normalize teencode/diacritics, expand abbreviations, extract date/room/kind filters.
    output: dict containing normalized_query, keywords, window_start, window_end, kind, room_hint, top_k.
    typical flow: 'lich thi xstk tuan sau' -> kind=EXAM, keywords='xác suất thống kê', next-week bounds.
    """
    ensure_aware(reference_now, "reference_now")
    clean_raw = sanitize_prompt(raw_query or "", max_chars=500)
    normalized = normalize_text(clean_raw).text
    expanded = _expand_course_abbreviations(normalized)

    room_match = _ROOM_HINT_RE.search(expanded)
    room_hint = room_match.group(1) if room_match else None

    date_match = _SEARCH_DATE_RE.search(expanded)
    date_hint = date_match.group(0) if date_match else None
    period = _detect_time_of_day(expanded)
    kind_filter = _detect_event_kind(expanded)

    window_start: datetime | None = None
    window_end: datetime | None = None
    if date_hint is not None:
        resolved = resolve_date_hint(date_hint, reference_now)
        start_clock, end_clock = _TIME_PERIOD_BOUNDS.get(
            period or "", (time(0, 0), time(23, 59))
        )
        window_start = datetime.combine(resolved.start, start_clock, tzinfo=VN_TZ)
        window_end = datetime.combine(resolved.end, end_clock, tzinfo=VN_TZ)

    # strip date, room, and query boilerplate so only semantic subject keywords remain
    stripped = expanded
    if date_hint:
        stripped = _SEARCH_DATE_RE.sub(" ", stripped)
    if room_match:
        stripped = _ROOM_HINT_RE.sub(" ", stripped)
    stripped = _QUERY_STOPWORDS_RE.sub(" ", stripped)
    stripped = re.sub(r"[^\w\s]", " ", stripped)
    keywords = re.sub(r"\s+", " ", stripped).strip()

    return {
        "raw_query": raw_query,
        "normalized_query": expanded,
        "keywords": keywords,
        "date_hint": date_hint,
        "time_of_day": period,
        "window_start": window_start,
        "window_end": window_end,
        "kind": kind_filter,
        "room_hint": room_hint,
        "top_k": DEFAULT_SEARCH_TOP_K,
    }


def _compute_lexical_score(query_keywords: str, candidate_text: str) -> float:
    """
    input: query_keywords (str) and candidate_text (str) combining event title, code, and room.
    core logic: check exact folded substring match first, then compute token overlap ratio.
    output: float score in [0.0, 1.0] reflecting sql-like exact/token precision.
    typical flow: 'toan' in 'toan to hop' -> 1.0; 'xac suat' in 'xac suat thong ke' -> 1.0.
    """
    q_fold = rag.fold(_expand_course_abbreviations(query_keywords)).strip()
    c_fold = rag.fold(_expand_course_abbreviations(candidate_text)).strip()
    if not q_fold or not c_fold:
        return 0.0
    if re.search(rf"(?<![\w]){re.escape(q_fold)}(?![\w])", c_fold):
        return 1.0  # exact whole-phrase match inside candidate text
    q_tokens = [tok for tok in re.findall(r"\w+", q_fold) if len(tok) >= 2]
    c_tokens = set(re.findall(r"\w+", c_fold))
    if not q_tokens or not c_tokens:
        return 0.0
    hits = sum(1 for tok in q_tokens if tok in c_tokens)
    return 0.85 * (hits / len(q_tokens))


def execute_local_search(
    db: Session, owner_id: int, structured_filters: dict[str, Any]
) -> list[EventDomain]:
    """
    input: db (Session), owner_id (int), and structured_filters (dict) from optimize_search_query.
    core logic: run anti-idor sql filter on events, then rank by hybrid lexical + vector similarity.
    output: list[EventDomain] of matching user schedule items (stops at vector top-k, zero llm).
    typical flow: sql filters owner/date/kind/room -> embed query & events -> return ranked top-k.
    """
    window_start: datetime | None = structured_filters.get("window_start")
    window_end: datetime | None = structured_filters.get("window_end")
    kind_filter: EventKind | None = structured_filters.get("kind")
    room_hint: str | None = structured_filters.get("room_hint")
    keywords: str = (structured_filters.get("keywords") or "").strip()
    top_k: int = int(structured_filters.get("top_k") or DEFAULT_SEARCH_TOP_K)

    stmt = active_events_stmt(
        owner_id=owner_id,
        start_from=window_start,
        end_until=window_end,
    )
    if kind_filter is not None:
        stmt = stmt.where(Event.kind == kind_filter)  # exact sql enum filter
    if room_hint:
        stmt = stmt.where(Event.room.ilike(f"%{room_hint}%"))  # sql case-insensitive room match

    orm_events = list(db.scalars(stmt).all())
    if not orm_events:
        structured_filters["_scores"] = {}
        return []

    domain_events = [ev.to_domain() for ev in orm_events]

    # pure sql filter query (e.g., 'lịch ngày mai' with no subject keywords)
    if not keywords:
        selected = domain_events[:top_k]
        structured_filters["_scores"] = {
            ev.id: 1.0 for ev in selected if ev.id is not None
        }
        return selected

    course_rows = list(db.scalars(active_courses_stmt(owner_id)).all())
    course_map: dict[int, Course] = {c.id: c for c in course_rows}

    query_vec = _build_semantic_vector(keywords)  # step 1 (tier 1): embed query into concept-enriched vector
    scored_items: list[tuple[float, EventDomain]] = []
    candidate_texts: list[str] = []

    # step 2 (tier 1 core): scan sql-filtered candidate events for lexical + concept-hashed vector similarity
    for ev in domain_events:
        course = course_map.get(ev.course_id) if ev.course_id is not None else None
        course_code = course.course_code if course is not None else ""
        searchable_text = f"{ev.title} {course_code} {ev.room or ''}".strip()
        candidate_texts.append(searchable_text)

        lex_score = _compute_lexical_score(keywords, searchable_text)
        doc_vec = _build_semantic_vector(ev.title, course_code)
        vec_score = _cosine_similarity(query_vec, doc_vec)

        if lex_score >= 0.5 or vec_score >= VECTOR_SIMILARITY_THRESHOLD:
            hybrid_score = (
                max(lex_score, 0.5 * lex_score + 0.5 * vec_score)
                if lex_score > 0
                else vec_score
            )
            scored_items.append((hybrid_score, ev))

    # step 2b (tier 2 fallback): if tier 1 returned fewer than MIN_TIER1_RESULTS, invoke neural embedding fallback
    min_tier1 = int(structured_filters.get("min_tier1_results") or MIN_TIER1_RESULTS)
    if len(scored_items) < min_tier1 and domain_events:
        matched_ids = {ev.id for _, ev in scored_items if ev.id is not None}
        neural_scores = _compute_neural_fallback_scores(keywords, candidate_texts)
        for ev, n_score in zip(domain_events, neural_scores):
            if ev.id not in matched_ids and n_score >= NEURAL_FALLBACK_THRESHOLD:
                scored_items.append((n_score, ev))

    # step 3: sort top-k results by similarity descending, then start_time ascending
    scored_items.sort(key=lambda pair: (-round(pair[0], 4), pair[1].start_time))
    top_matches = scored_items[:top_k]
    structured_filters["_scores"] = {
        ev.id: round(score, 4) for score, ev in top_matches if ev.id is not None
    }
    return [ev for _, ev in top_matches]


def verify_and_format_search_results(
    results: list[EventDomain], structured_filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    input: results (list[EventDomain]) and structured_filters (dict) used during search.
    core logic: re-verify window/kind/room invariants and format timestamps in +07:00 iso8601.
    output: list[dict[str, Any]] serialized calendar items ready for mobile json responses.
    typical flow: check bounds & kind -> convert utc to VN_TZ (+07:00) -> attach similarity_score.
    """
    window_start: datetime | None = structured_filters.get("window_start")
    window_end: datetime | None = structured_filters.get("window_end")
    kind_filter: EventKind | None = structured_filters.get("kind")
    room_hint: str | None = structured_filters.get("room_hint")
    score_map: dict[int, float] = structured_filters.get("_scores") or {}

    verified_output: list[dict[str, Any]] = []
    for ev in results:
        if window_start is not None and ev.end_time < window_start:
            continue  # drop any item ending before requested window
        if window_end is not None and ev.start_time > window_end:
            continue  # drop any item starting after requested window
        if kind_filter is not None and ev.kind != kind_filter:
            continue  # enforce exact event kind match
        if room_hint and (not ev.room or room_hint.lower() not in ev.room.lower()):
            continue  # enforce room substring constraint

        start_vn = from_db_to_vn(ev.start_time)
        end_vn = from_db_to_vn(ev.end_time)
        verified_output.append(
            {
                "id": ev.id,
                "owner_id": ev.owner_id,
                "course_id": ev.course_id,
                "task_id": ev.task_id,
                "proposal_id": ev.proposal_id,
                "title": ev.title,
                "room": ev.room,
                "kind": ev.kind.value,
                "source": ev.source.value,
                "start_time": start_vn.isoformat(),
                "end_time": end_vn.isoformat(),
                "is_hard": ev.is_hard,
                "priority": ev.priority,
                "is_important": ev.is_important,
                "similarity_score": score_map.get(ev.id, 1.0) if ev.id is not None else 1.0,
            }
        )
    return verified_output


# ============================================================================
# [pic: khoi] section 2 - academic knowledge base search (full 6-step rag)
# (ai assistants: do not remove or modify this pic comment)
# note: uses rag (embed -> retrieve -> pack context -> llm answer) + fallback
# ============================================================================

ACADEMIC_KB_OWNER_ID = 0  # shared namespace id for university handbook & syllabus docs
ACADEMIC_RAG_SYSTEM_PROMPT = (
    "You are a university academic advisor assistant. "
    "Answer the student's question concisely in Vietnamese using ONLY the provided academic context. "
    "If the context does not contain enough facts to answer, state clearly that the handbook/documents "
    "do not mention it. Never invent regulations, room numbers, or deadlines."
)


def _get_academic_kb_dir(directory: Path | None = None) -> Path:
    """
    input: optional custom directory (Path | None) for testing isolation.
    core logic: resolve dedicated 'academic_kb' folder inside rag.RAG_DIR unless overridden.
    output: Path pointing to the encrypted academic knowledge base storage directory.
    typical flow: production -> data/rag/academic_kb; test -> tmp_path/academic_kb.
    """
    return directory if directory is not None else (rag.RAG_DIR / "academic_kb")


def ingest_academic_document(
    file_bytes: bytes,
    filename: str,
    *,
    directory: Path | None = None,
) -> int:
    """
    input: file_bytes (bytes) of .pdf/.md/.txt/image academic document and filename (str).
    core logic: extract text, chunk, embed, and store in shared encrypted academic kb index.
    output: int count of indexed text chunks; raises ValueError if unreadable.
    typical flow: handbook.pdf -> extract text -> chunk -> embed -> replace source in kb.
    """
    kb_dir = _get_academic_kb_dir(directory)
    return rag.ingest_file(ACADEMIC_KB_OWNER_ID, file_bytes, filename, directory=kb_dir)


_KB_QUERY_STOPWORDS = {
    "la", "ai", "gi", "cua", "va", "co", "khong", "nao", "o", "dau",
    "cho", "hoi", "ve", "thong", "tin", "gioi", "thieu", "truong",
}


def _retrieve_structured_kb_hits(
    db: Session | None,
    normalized_query: str,
    top_k: int = 3,
) -> list[rag.Hit]:
    """
    input: db (Session | None), normalized_query (str), and top_k (int).
    core logic: query structured kb_* tables (lecturers, departments, programs, courses, achievements)
                using folded token matching and format matching rows as rag.Hit records.
    output: list[rag.Hit] sorted by relevance score; safely returns [] if kb_* tables are absent.
    typical flow: fold query -> match KbLecturer/KbDepartment/KbProgram/KbCourse -> return top-k hits.
    """
    if db is None or not normalized_query:
        return []
    q_fold = rag.fold(normalized_query).strip()
    q_tokens = [
        tok for tok in re.findall(r"\w+", q_fold)
        if len(tok) >= 2 and tok not in _KB_QUERY_STOPWORDS
    ]
    if not q_tokens:
        return []

    hits: list[rag.Hit] = []
    try:
        faculties = {f.id: f for f in db.scalars(select(KbFaculty)).all()}
        departments = {d.id: d for d in db.scalars(select(KbDepartment)).all()}
        sources = {s.id: s for s in db.scalars(select(KbSource)).all()}

        # 1. check active lecturers (preferring APPROVED rows, falling back to non-REJECTED)
        lecturers = list(
            db.scalars(
                select(KbLecturer).where(
                    KbLecturer.is_active.is_(True),
                    KbLecturer.review_status != "REJECTED",
                )
            ).all()
        )
        achievements = list(
            db.scalars(
                select(KbAchievement).where(KbAchievement.review_status != "REJECTED")
            ).all()
        )
        ach_by_lecturer: dict[int, list[KbAchievement]] = {}
        for ach in achievements:
            if ach.lecturer_id is not None:
                ach_by_lecturer.setdefault(ach.lecturer_id, []).append(ach)

        for lec in lecturers:
            dept = departments.get(lec.department_id) if lec.department_id else None
            fac = faculties.get(lec.faculty_id)
            candidate_fold = rag.fold(
                f"{lec.full_name} {lec.name_folded} {lec.academic_title or ''} "
                f"{lec.position or ''} {dept.name if dept else ''} "
                f"{fac.name if fac else ''} {lec.bio or ''}"
            )
            matched = sum(1 for tok in q_tokens if tok in candidate_fold)
            if matched == 0 and q_fold not in candidate_fold:
                continue
            score = 0.95 if lec.name_folded and lec.name_folded in q_fold else 0.85 * (matched / len(q_tokens))
            if score < 0.35:
                continue
            title_prefix = f"{lec.academic_title} " if lec.academic_title else ""
            parts = [f"Giảng viên: {title_prefix}{lec.full_name}".strip()]
            if lec.position:
                parts.append(f"Chức vụ: {lec.position}")
            if dept is not None:
                parts.append(f"Bộ môn: {dept.name}")
            if fac is not None:
                parts.append(f"Khoa: {fac.name}")
            if lec.bio:
                parts.append(f"Thông tin: {lec.bio[:240]}")
            lec_achs = ach_by_lecturer.get(lec.id, [])
            if lec_achs:
                ach_titles = "; ".join(
                    f"{a.title} ({a.year})" if a.year else a.title for a in lec_achs[:3]
                )
                parts.append(f"Thành tựu/Công bố: {ach_titles}")
            src = sources.get(lec.source_id) if lec.source_id else None
            src_label = (src.url if src else None) or lec.profile_url or "kb_lecturers"
            hits.append(rag.Hit(text=" | ".join(parts), score=round(score, 4), source=src_label))

        # 2. check departments, programs, and kb courses
        for dept in departments.values():
            if dept.review_status == "REJECTED":
                continue
            fac = faculties.get(dept.faculty_id)
            cand = rag.fold(f"{dept.name} {dept.name_folded} {dept.description or ''} {fac.name if fac else ''}")
            matched = sum(1 for tok in q_tokens if tok in cand)
            if matched == 0:
                continue
            score = 0.82 * (matched / len(q_tokens))
            if score >= 0.4:
                src = sources.get(dept.source_id) if dept.source_id else None
                text = f"Bộ môn: {dept.name}"
                if fac is not None:
                    text += f" | Khoa: {fac.name}"
                if dept.description:
                    text += f" | Mô tả: {dept.description[:240]}"
                hits.append(rag.Hit(text=text, score=round(score, 4), source=src.url if src else "kb_departments"))

        programs = list(
            db.scalars(select(KbProgram).where(KbProgram.review_status != "REJECTED")).all()
        )
        for prog in programs:
            fac = faculties.get(prog.faculty_id)
            cand = rag.fold(f"{prog.name} {prog.name_folded} {prog.level or ''} {prog.description or ''}")
            matched = sum(1 for tok in q_tokens if tok in cand)
            if matched == 0:
                continue
            score = 0.82 * (matched / len(q_tokens))
            if score >= 0.4:
                src = sources.get(prog.source_id) if prog.source_id else None
                text = f"Chương trình đào tạo: {prog.name}"
                if prog.level:
                    text += f" ({prog.level})"
                if fac is not None:
                    text += f" | Khoa: {fac.name}"
                if prog.description:
                    text += f" | Mô tả: {prog.description[:240]}"
                hits.append(rag.Hit(text=text, score=round(score, 4), source=src.url if src else "kb_programs"))

        kb_courses = list(
            db.scalars(select(KbCourse).where(KbCourse.review_status != "REJECTED")).all()
        )
        for crs in kb_courses:
            cand = rag.fold(f"{crs.course_code or ''} {crs.name} {crs.name_folded} {crs.description or ''}")
            matched = sum(1 for tok in q_tokens if tok in cand)
            if matched == 0:
                continue
            score = 0.85 * (matched / len(q_tokens))
            if score >= 0.4:
                src = sources.get(crs.source_id) if crs.source_id else None
                code_str = f"[{crs.course_code}] " if crs.course_code else ""
                credits_str = f" ({crs.credits} tín chỉ)" if crs.credits is not None else ""
                text = f"Học phần: {code_str}{crs.name}{credits_str}"
                if crs.description:
                    text += f" | Mô tả: {crs.description[:240]}"
                hits.append(rag.Hit(text=text, score=round(score, 4), source=src.url if src else "kb_courses"))
    except Exception:
        return []

    hits.sort(key=lambda item: item.score, reverse=True)
    return hits[:top_k]


def ask_academic_knowledge_base(
    raw_query: str,
    *,
    top_k: int = 3,
    db: Session | None = None,
    user_id: int | None = None,
    directory: Path | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """
    input: raw_query (str), top_k (int), optional db/user_id for ai error logging, optional httpx client.
    core logic: run 6-step rag (embed query -> retrieve structured kb_* + vector chunks -> pack prompt -> vllm -> answer).
    output: dict with query, normalized_query, answer, citations, and fallback_mode.
    typical flow: hits found -> vllm synthesizes grounded answer; vllm down -> fallback returns citations.
    """
    started = perf_time.monotonic()
    clean_query = sanitize_prompt(raw_query or "", max_chars=1000)
    normalized_query = _expand_course_abbreviations(normalize_text(clean_query).text)
    if not normalized_query:
        return {
            "query": raw_query,
            "normalized_query": "",
            "answer": "Vui lòng nhập nội dung câu hỏi học vụ.",
            "citations": [],
            "fallback_mode": False,
            "redirect_target": None,
            "redirect_button_label": None,
        }
    if is_scheduling_command(clean_query):
        return {
            "query": raw_query,
            "normalized_query": normalized_query,
            "answer": (
                "It seems bạn đang muốn yêu cầu xếp lịch công việc. "
                "Trang 'Tìm kiếm' chỉ dùng để tra cứu lịch trình và hỏi đáp học vụ; "
                "bạn hãy bấm nút 'Trợ lý AI' để chuyển sang khung xếp lịch thông minh nhé."
            ),
            "citations": [],
            "fallback_mode": False,
            "redirect_target": "chat_home",
            "redirect_button_label": "Trợ lý AI",
        }

    # steps 1, 2, 3: retrieve from structured kb_* sql tables + academic vector store, and collect top-k chunks
    kb_dir = _get_academic_kb_dir(directory)
    structured_hits = _retrieve_structured_kb_hits(db, normalized_query, top_k=top_k)
    vector_hits = rag.retrieve(ACADEMIC_KB_OWNER_ID, normalized_query, k=top_k, directory=kb_dir)
    combined_hits = sorted(structured_hits + vector_hits, key=lambda h: h.score, reverse=True)
    hits: list[rag.Hit] = []
    seen_texts: set[str] = set()
    for h in combined_hits:
        if h.text not in seen_texts:
            seen_texts.add(h.text)
            hits.append(h)
            if len(hits) >= top_k:
                break
    citations = [
        {"source": h.source, "text": h.text, "score": round(h.score, 4)}
        for h in hits
    ]
    if not hits:
        return {
            "query": raw_query,
            "normalized_query": normalized_query,
            "answer": "Không tìm thấy thông tin phù hợp trong cơ sở tri thức học vụ.",
            "citations": [],
            "fallback_mode": False,
        }

    # step 4: pack original question + retrieved chunks into grounded rag prompt
    context_block = "\n\n".join(
        f"[{idx + 1}] ({h.source}): {h.text}" for idx, h in enumerate(hits)
    )
    user_prompt = f"Ngữ cảnh học vụ:\n{context_block}\n\nCâu hỏi: {clean_query}"

    vllm_endpoint = os.getenv(
        "VLLM_ENDPOINT", "http://127.0.0.1:8000/v1/chat/completions"
    )
    model_name = os.getenv(
        "LLM_MODEL", "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"
    )
    timeout_sec = float(os.getenv("LLM_TIMEOUT_SECONDS", "3.0"))

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": ACADEMIC_RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 300,
        "temperature": 0.1,
    }

    # steps 5 & 6: dispatch prompt through fifo broker to vllm and read generated answer
    http = client or httpx.Client(timeout=timeout_sec)
    db_err_type = AiErrorType.INFRA_CRASH
    err_category = "INFRA_CRASH"
    err_reason = "llm unavailable"
    raw_output: str | None = None

    try:
        assert_private_endpoint(vllm_endpoint)
        response = broker.run(
            lambda: http.post(vllm_endpoint, json=payload, timeout=timeout_sec),
            user_id=user_id,
        )
        response.raise_for_status()
        raw_output = response.json()["choices"][0]["message"]["content"].strip()
        if raw_output:
            record_latency_ms((perf_time.monotonic() - started) * 1000)
            return {
                "query": raw_query,
                "normalized_query": normalized_query,
                "answer": raw_output,
                "citations": citations,
                "fallback_mode": False,
            }
        db_err_type = AiErrorType.SEMANTIC_FAILURE
        err_category = "SEMANTIC_FAILURE"
        err_reason = "empty llm answer"
    except (httpx.TimeoutException, QueueWaitTimeout) as exc:
        db_err_type = AiErrorType.TIMEOUT
        err_category = "TIMEOUT"
        err_reason = f"{type(exc).__name__}: {str(exc)[:200]}"
    except Exception as exc:
        db_err_type = AiErrorType.INFRA_CRASH
        err_category = "INFRA_CRASH"
        err_reason = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        if client is None:
            http.close()

    # graceful fallback (agents.md section 8): log failure and return retrieved excerpts directly
    if db is not None:
        db.add(
            AiErrorLog(
                user_id=user_id,
                prompt_text=clean_query,
                raw_output=(raw_output or "")[:4000] or None,
                error_type=db_err_type,
                retry_count=0,
                triggered_fallback=True,
            )
        )
        db.flush()

    log_ai_failure(
        err_category,
        clean_query,
        err_reason,
        retrieved_context=[h.text for h in hits],
        raw_output=raw_output,
        user_id=user_id,
    )
    fallback_excerpt = "\n".join(f"- ({h.source}) {h.text}" for h in hits)
    return {
        "query": raw_query,
        "normalized_query": normalized_query,
        "answer": f"Trợ lý AI đang bận. Dưới đây là trích đoạn tài liệu học vụ liên quan:\n{fallback_excerpt}",
        "citations": citations,
        "fallback_mode": True,
    }


# ============================================================================
# [pic: lam] section 3 - deterministic free-slot availability engine (<200ms)
# (ai assistants: do not remove or modify this pic comment)
# ============================================================================


def _align_up_to_step(dt: datetime, step_minutes: int) -> datetime:
    """
    input: dt (aware datetime) and step_minutes (int) grid size (e.g., 15).
    core logic: advance sub-minute remainders, then round minute up to step_minutes boundary.
    output: aware datetime >= dt aligned cleanly on the scheduling grid.
    typical flow: 08:00 -> 08:00; 08:03 -> 08:15 when step_minutes=15.
    """
    clean = dt.replace(second=0, microsecond=0)
    if dt.second > 0 or dt.microsecond > 0:
        clean += timedelta(minutes=1)  # never round backward into a busy interval
    remainder = clean.minute % step_minutes
    if remainder == 0:
        return clean
    return clean + timedelta(minutes=(step_minutes - remainder))


def _align_down_to_step(dt: datetime, step_minutes: int) -> datetime:
    """
    input: dt (aware datetime) and step_minutes (int) grid size (e.g., 15).
    core logic: strip seconds and round minute down to nearest step_minutes boundary.
    output: aware datetime <= dt aligned cleanly on the scheduling grid.
    typical flow: 10:00 -> 10:00; 09:55 -> 09:45 when step_minutes=15.
    """
    clean = dt.replace(second=0, microsecond=0)
    remainder = clean.minute % step_minutes
    if remainder == 0:
        return clean
    return clean - timedelta(minutes=remainder)


def _build_sleep_intervals(
    window_start: datetime,
    window_end: datetime,
    sleep_start: time,
    sleep_end: time,
) -> list[tuple[datetime, datetime]]:
    """
    input: window bounds (aware datetimes) and user sleep_start, sleep_end clock times.
    core logic: generate daily sleep intervals in VN_TZ across the window, handling midnight wrap.
    output: list[tuple[datetime, datetime]] of blocked sleep windows clipped to [window_start, window_end].
    typical flow: sleep 23:30..06:30 -> one blocked interval per night across requested dates.
    """
    if sleep_start == sleep_end:
        return []  # equal start and end disables sleep blocking

    ws_vn = window_start.astimezone(VN_TZ)
    we_vn = window_end.astimezone(VN_TZ)
    tz_out = window_start.tzinfo or VN_TZ

    intervals: list[tuple[datetime, datetime]] = []
    overnight = sleep_start > sleep_end
    cur_date = ws_vn.date() - (timedelta(days=1) if overnight else timedelta(days=0))
    end_date = we_vn.date()

    while cur_date <= end_date:
        s_vn = datetime.combine(cur_date, sleep_start, tzinfo=VN_TZ)
        next_date = cur_date + timedelta(days=1) if overnight else cur_date
        e_vn = datetime.combine(next_date, sleep_end, tzinfo=VN_TZ)

        clipped_start = max(s_vn.astimezone(tz_out), window_start)
        clipped_end = min(e_vn.astimezone(tz_out), window_end)
        if clipped_end > clipped_start:
            intervals.append((clipped_start, clipped_end))
        cur_date += timedelta(days=1)

    return intervals


def find_free_slots(
    existing_events: list[EventDomain],
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    *,
    sleep_start: time | None = None,
    sleep_end: time | None = None,
    min_break_minutes: int = 0,
    slot_step_minutes: int = 15,
) -> list[TimeSlot]:
    """
    input: existing_events (list[EventDomain]), aware window bounds, duration_minutes, optional prefs.
    core logic: o(n log n) sort-and-sweep merges busy + sleep intervals, then extracts aligned free gaps.
    output: list[TimeSlot] of zero-overlap free windows each >= duration_minutes.
    typical flow: filter blocking events -> merge overlaps -> sweep gaps -> align 15m grid -> return slots.
    """
    ensure_aware(window_start, "window_start")
    ensure_aware(window_end, "window_end")
    if window_end <= window_start:
        return []  # empty or inverted search window yields no slots
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if slot_step_minutes <= 0:
        raise ValueError("slot_step_minutes must be positive")

    tz_ref = window_start.tzinfo or VN_TZ
    break_delta = timedelta(minutes=max(0, min_break_minutes))
    busy_intervals: list[tuple[datetime, datetime]] = []

    # collect blocking events (deadlines have blocks_availability false and are skipped)
    for ev in existing_events:
        if not ev.blocks_availability:
            continue
        ev_start = ev.start_time.astimezone(tz_ref) - break_delta
        ev_end = ev.end_time.astimezone(tz_ref) + break_delta
        if ev_end <= window_start or ev_start >= window_end:
            continue  # skip event completely outside search window
        busy_intervals.append((max(ev_start, window_start), min(ev_end, window_end)))

    if sleep_start is not None and sleep_end is not None:
        busy_intervals.extend(
            _build_sleep_intervals(window_start, window_end, sleep_start, sleep_end)
        )

    # sort-and-sweep merge of overlapping or contiguous busy intervals
    busy_intervals.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime]] = []
    for b_start, b_end in busy_intervals:
        if not merged or b_start > merged[-1][1]:
            merged.append((b_start, b_end))
        elif b_end > merged[-1][1]:
            merged[-1] = (merged[-1][0], b_end)

    min_duration = timedelta(minutes=duration_minutes)
    free_slots: list[TimeSlot] = []
    cursor = window_start

    for b_start, b_end in merged:
        if b_start > cursor:
            aligned_start = _align_up_to_step(cursor, slot_step_minutes)
            aligned_end = _align_down_to_step(b_start, slot_step_minutes)
            if aligned_end - aligned_start >= min_duration:
                free_slots.append(TimeSlot(start=aligned_start, end=aligned_end))
        if b_end > cursor:
            cursor = b_end

    # check trailing free gap after the last busy interval up to window_end
    if window_end > cursor:
        aligned_start = _align_up_to_step(cursor, slot_step_minutes)
        aligned_end = _align_down_to_step(window_end, slot_step_minutes)
        if aligned_end - aligned_start >= min_duration:
            free_slots.append(TimeSlot(start=aligned_start, end=aligned_end))

    return free_slots


def find_user_free_slots(
    db: Session,
    owner_id: int,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    *,
    respect_preferences: bool = True,
) -> list[TimeSlot]:
    """
    input: db (Session), owner_id (int), aware window_start/window_end, duration_minutes, respect_preferences.
    core logic: load owner's active events and optional UserPreference row, then invoke find_free_slots.
    output: list[TimeSlot] of available 15m-aligned windows in VN_TZ (+07:00).
    typical flow: query active_events_stmt -> read sleep & break prefs -> run sort-and-sweep -> return.
    """
    ensure_aware(window_start, "window_start")
    ensure_aware(window_end, "window_end")
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if window_end <= window_start:
        return []

    ws_vn = window_start.astimezone(VN_TZ)
    we_vn = window_end.astimezone(VN_TZ)

    sleep_start: time | None = None
    sleep_end: time | None = None
    min_break = 0
    slot_step = 15

    if respect_preferences:
        pref = db.scalar(
            select(UserPreference).where(UserPreference.user_id == owner_id)
        )
        if pref is not None:
            sleep_start = pref.sleep_start
            sleep_end = pref.sleep_end
            min_break = pref.min_break_minutes
            slot_step = pref.slot_step_minutes

    # Fetch exactly far enough beyond the window to include events whose break buffer overlaps it.
    buffer_minutes = max(0, min_break)
    fetch_start = ws_vn - timedelta(minutes=buffer_minutes)
    fetch_end = we_vn + timedelta(minutes=buffer_minutes)
    orm_events = list(
        db.scalars(active_events_stmt(owner_id, fetch_start, fetch_end)).all()
    )
    domain_events = [ev.to_domain() for ev in orm_events]

    return find_free_slots(
        existing_events=domain_events,
        window_start=ws_vn,
        window_end=we_vn,
        duration_minutes=duration_minutes,
        sleep_start=sleep_start,
        sleep_end=sleep_end,
        min_break_minutes=min_break,
        slot_step_minutes=slot_step,
    )
