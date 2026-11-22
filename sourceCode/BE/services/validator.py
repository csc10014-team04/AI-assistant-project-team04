# [pic: khoi] p1-6 hard constraint validator & import commit (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import calendar
from datetime import date, datetime, time, timedelta
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, active_courses_stmt, active_events_stmt, from_db_to_vn, to_db_utc
from models import (
    Course,
    CsvRowKind,
    Event,
    EventDomain,
    EventKind,
    EventSource,
    ParsedCsvRow,
    PriorityLevel,
    TimeSlot,
    Weekday,
)

WEEKDAY_TO_INDEX: dict[Weekday, int] = {
    Weekday.MON: 0,
    Weekday.TUE: 1,
    Weekday.WED: 2,
    Weekday.THU: 3,
    Weekday.FRI: 4,
    Weekday.SAT: 5,
    Weekday.SUN: 6,
}

INDEX_TO_WEEKDAY: dict[int, Weekday] = {v: k for k, v in WEEKDAY_TO_INDEX.items()}

# các mẫu regex nhận diện chu kỳ lặp mở rộng (2 tuần/lần, k tuần/lần, hàng tháng) trong title/room/course_code
_BIWEEKLY_RE = re.compile(
    r"(?:\b(?:cách\s+tuần|cach\s+tuan|hai\s+tuần\s+một\s+lần|biweekly|every\s+other\s+week)\b|\[2w\])",
    re.IGNORECASE,
)
_NWEEKLY_RE = re.compile(
    r"(?:(?<!\d)([2-9]|\d{2,})\s*tuần\s*(?:/|\s*một\s*|\s*1\s*)lần"
    r"|\bmỗi\s*([2-9]|\d{2,})\s*tuần\b"
    r"|\bevery\s*([2-9]|\d{2,})\s*weeks?\b"
    r"|\[([2-9]|\d{2,})w\])",
    re.IGNORECASE,
)
_NMONTHLY_RE = re.compile(
    r"(?:(?<!\d)([1-9]\d*)\s*tháng\s*(?:/|\s*một\s*|\s*1\s*)lần"
    r"|\bmỗi\s*([1-9]\d*)\s*tháng\b"
    r"|\bevery\s*([1-9]\d*)\s*months?\b"
    r"|\[([1-9]\d*)m\])",
    re.IGNORECASE,
)
_MONTHLY_RE = re.compile(
    r"\b(?:hàng\s+tháng|hằng\s+tháng|hang\s+thang|mỗi\s+tháng|moi\s+thang|một\s+tháng\s+một\s+lần|monthly|every\s+month)\b",
    re.IGNORECASE,
)


def _resolve_row_weekday(row: ParsedCsvRow) -> Weekday:
    """
    input: row (ParsedCsvRow) with optional weekday enum and mandatory first_date.
    core logic: return row.weekday when present, otherwise map row.first_date.weekday() to Weekday.
    output: Weekday enum (MON..SUN).
    typical flow: CLASS row uses explicit weekday; single-day EXAM/EVENT falls back to first_date.
    """
    if row.weekday is not None:
        return row.weekday
    return INDEX_TO_WEEKDAY[row.first_date.weekday()]  # infer weekday from calendar date


def _parse_recurrence_spec(row: ParsedCsvRow) -> tuple[str, int]:
    """
    input: row (ParsedCsvRow) containing title, room, and course_code.
    core logic: detect multi-week ('WEEKLY', k) or monthly ('MONTHLY', k) markers; default ('WEEKLY', 1).
    output: tuple[str, int] of (mode, interval) where mode in {'WEEKLY', 'MONTHLY'} and interval >= 1.
    typical flow: normal row -> ('WEEKLY', 1); 'Lab [2w]' -> ('WEEKLY', 2); 'Họp CLB hàng tháng' -> ('MONTHLY', 1).
    """
    # xem file validator_FUNC_iter_row_dates.txt (sourceCode/BE/learning/)
    # ghép title, room và course_code để dò xem người dùng có ghi chú chu kỳ lặp đặc biệt hay không
    combined = f"{row.title or ''} {row.room or ''} {row.course_code or ''}"
    m_nmonth = _NMONTHLY_RE.search(combined)
    if m_nmonth:
        step = next(int(g) for g in m_nmonth.groups() if g is not None)
        return ("MONTHLY", max(1, step))
    if _MONTHLY_RE.search(combined):
        return ("MONTHLY", 1)
    m_nweek = _NWEEKLY_RE.search(combined)
    if m_nweek:
        step = next(int(g) for g in m_nweek.groups() if g is not None)
        return ("WEEKLY", max(1, step))
    if _BIWEEKLY_RE.search(combined):
        return ("WEEKLY", 2)
    return ("WEEKLY", 1)


def _nth_weekday_of_month(year: int, month: int, target_weekday: int, nth: int) -> date:
    """
    input: year (int), month (int 1..12), target_weekday (0=MON..6=SUN), and nth (1..5).
    core logic: find the nth occurrence of target_weekday in (year, month), clamping to last if nth=5 overflows.
    output: date in (year, month) whose weekday() == target_weekday.
    typical flow: (2026, 10, 0=MON, 1) -> 2026-10-05 (first Monday of October 2026).
    """
    first_of_month = date(year, month, 1)
    days_ahead = (target_weekday - first_of_month.weekday()) % 7
    first_occ_day = 1 + days_ahead
    candidate_day = first_occ_day + (nth - 1) * 7
    days_in_month = calendar.monthrange(year, month)[1]
    if candidate_day > days_in_month:
        candidate_day -= 7  # nếu tháng đó chỉ có 4 ngày thứ X mà nth=5 thì lùi về tuần thứ 4 cuối tháng
    return date(year, month, candidate_day)


def _iter_row_dates(row: ParsedCsvRow) -> list[date]:
    """
    input: row (ParsedCsvRow) describing either a recurring CLASS or a single-occurrence item.
    core logic: step by k weeks (+7*k days) or k months from first matching weekday up to last_date.
    output: list[date] of concrete occurrence dates in chronological order.
    typical flow: 15-week CLASS -> 15 dates; biweekly CLASS -> 8 dates; monthly CLASS -> 4 dates.
    """
    # xem file validator_FUNC_iter_row_dates.txt (sourceCode/BE/learning/)
    if row.kind == CsvRowKind.CLASS:
        target_idx = WEEKDAY_TO_INDEX[_resolve_row_weekday(row)]
        # tính độ lệch ngày để dời từ first_date tới đúng ngày thứ trong tuần (weekday) đầu tiên
        days_ahead = (target_idx - row.first_date.weekday()) % 7
        first_occ = row.first_date + timedelta(days=days_ahead)
        if first_occ > row.last_date:
            return []

        mode, step = _parse_recurrence_spec(row)
        dates: list[date] = []

        if mode == "MONTHLY":
            # xác định buổi đầu tiên rơi vào tuần thứ mấy (nth: 1..5) của tháng đầu tiên
            # để các tháng tiếp theo vẫn giữ nguyên đúng thứ trong tuần (weekday) đó
            nth = ((first_occ.day - 1) // 7) + 1
            cur_year, cur_month = first_occ.year, first_occ.month
            while True:
                occ = _nth_weekday_of_month(cur_year, cur_month, target_idx, nth)
                if occ > row.last_date:
                    break
                if occ >= first_occ:
                    dates.append(occ)
                # cộng thêm step tháng (ví dụ: step=1 là mỗi tháng 1 lần)
                total_months = (cur_year * 12 + (cur_month - 1)) + step
                cur_year, cur_month = total_months // 12, (total_months % 12) + 1
            return dates

        # mặc định mode == 'WEEKLY': bước nhảy là 7 * step ngày (step=1: hàng tuần, step=2: 2 tuần/lần, step=3: 3 tuần/lần)
        current = first_occ
        delta = timedelta(days=7 * step)
        while current <= row.last_date:
            dates.append(current)
            current += delta
        return dates
    return [row.first_date]


def _expand_row_slots(row: ParsedCsvRow) -> list[TimeSlot]:
    """
    input: row (ParsedCsvRow) validated from timetable preview step.
    core logic: skip zero-duration deadlines and combine each occurrence date with VN_TZ times.
    output: list[TimeSlot] of timezone-aware intervals in +07:00.
    typical flow: DEADLINE -> []; CLASS/EXAM/EVENT -> 1 or N TimeSlot objects for overlap checks.
    """
    if row.kind == CsvRowKind.DEADLINE or row.start_time == row.end_time:
        return []  # deadlines have zero duration and never block availability
    slots: list[TimeSlot] = []
    for occ_date in _iter_row_dates(row):
        start_dt = datetime.combine(occ_date, row.start_time, tzinfo=VN_TZ)
        end_dt = datetime.combine(occ_date, row.end_time, tzinfo=VN_TZ)
        if end_dt > start_dt:
            slots.append(TimeSlot(start=start_dt, end=end_dt))
    return slots


def _format_time_range(start_t: time, end_t: time) -> str:
    """
    input: start_t (time) and end_t (time).
    core logic: format start and end clock times as 24-hour HH:MM strings joined by a hyphen.
    output: str in 'HH:MM-HH:MM' format for human-readable conflict cards.
    typical flow: time(8, 0), time(9, 30) -> '08:00-09:30'.
    """
    return f"{start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}"


def check_hard_conflict(
    candidate_slot: TimeSlot, existing_events: list[EventDomain]
) -> list[EventDomain]:
    """
    input: candidate_slot (TimeSlot) and existing_events (list[EventDomain]) of current user.
    core logic: scan active events where is_hard and blocks_availability are True for interval overlap.
    output: list[EventDomain] containing all hard-constraint events intersecting candidate_slot.
    typical flow: overlaps CLASS/EXAM -> non-empty list; touches boundary or hits TASK/DEADLINE -> [].
    """
    conflicts: list[EventDomain] = []
    for event in existing_events:
        if (
            event.is_hard is True
            and event.blocks_availability is True
            and candidate_slot.overlaps(event.to_slot())
        ):
            conflicts.append(event)  # record hard collision to enforce zero-overlap guarantee
    return conflicts


def _bucket_slots_by_vn_date(
    slot_groups: list[list[TimeSlot]],
) -> dict[date, list[tuple[datetime, datetime, int]]]:
    """group time intervals by local VN calendar date for sweep-line conflict detection."""
    buckets: dict[date, list[tuple[datetime, datetime, int]]] = {}
    for item_idx, slots in enumerate(slot_groups):
        for slot in slots:
            cur_day = slot.start.astimezone(VN_TZ).date()
            end_day = slot.end.astimezone(VN_TZ).date()
            while cur_day <= end_day:
                buckets.setdefault(cur_day, []).append((slot.start, slot.end, item_idx))
                cur_day += timedelta(days=1)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: (item[0], item[1], item[2]))
    return buckets


def detect_import_conflicts(
    incoming_rows: list[ParsedCsvRow], existing_events: list[EventDomain]
) -> dict[str, Any]:
    """
    input: incoming_rows (list[ParsedCsvRow]) from preview and existing_events (list[EventDomain]).
    core logic: detect intra-batch and vs-existing overlaps, deduplicating weekly repeats into 1 card.
    output: dict with 'non_conflicting_rows' (list[ParsedCsvRow]) and 'conflict_cards' (list[dict]).
    typical flow: expand slots -> check incoming pairs & existing events -> group by series_key -> return.
    """
    expanded_incoming: list[list[TimeSlot]] = [
        _expand_row_slots(row) for row in incoming_rows
    ]
    conflicting_row_indices: set[int] = set()
    conflict_cards: list[dict[str, Any]] = []
    seen_series_pairs: set[tuple[Any, ...]] = set()  # prevent 15 duplicate cards for 15-week classes

    # 1. detect conflicts within incoming_rows grouped at series level

    # expanded_incoming là list mà mỗi phần tử expanded_incoming[i] là ds con: các event đã được bung ra theo occurrence.
    incoming_by_date = _bucket_slots_by_vn_date(expanded_incoming)
    overlapping_incoming_pairs: set[tuple[int, int]] = set()
    for bucket in incoming_by_date.values():
        if len(bucket) < 2:
            continue
        for pos, (_start_a, end_a, idx_a) in enumerate(bucket):
            scan = pos + 1
            while scan < len(bucket) and bucket[scan][0] < end_a:
                idx_b = bucket[scan][2]
                if idx_a != idx_b:
                    overlapping_incoming_pairs.add((min(idx_a, idx_b), max(idx_a, idx_b)))
                scan += 1

    """
    event0 kiểm trùng lắp với event1 và event1 kiểm trùng lắp với event0 là như nhau
    tức ta chỉ cần xét cặp (event0, event1) ra kiểm trùng lắp là đủ
    nên 0 so với {1,2,3,...,n}
    1 so với {2,3,...,n}
    2 so với {3,...,n}
    là sẽ tạo ra các cặp không trùng
    nên j chạy từ i+1.
    """
    for i, j in sorted(overlapping_incoming_pairs):
        row_a = incoming_rows[i]  # dòng này để lấy dòng csv gốc (chưa được bung ra event theo quy luật)
        weekday_a = _resolve_row_weekday(row_a)  # dòng này để lấy thứ trong tuần
        row_b = incoming_rows[j]
        weekday_b = _resolve_row_weekday(row_b)

        conflicting_row_indices.add(i)
        conflicting_row_indices.add(j)

        # signature_a: do trong ParsedCsvRow có thể có một môn với buổi cố định hàng tuần giống nhau nhưng nửa đầu kỳ học phòng A rồi nửa sau học phòng B (do nửa đầu phòng B sửa chẳng hạn)
        # thì nó vẫn là môn đó, buổi học đó, khung giờ đó hàng tuần nên sig_a là gom những attrib tối thiểu để xác định một buổi học
        # ta lưu dạng set vì đảo vị trí các attrib thì bộ đó vẫn xác định buổi học y hệt bộ trước khi đảo
        sig_a = (
            "ROW",
            row_a.course_code or "",
            row_a.title,
            weekday_a.value,
            row_a.start_time,
            row_a.end_time,
        )
        sig_b = (
            "ROW",
            row_b.course_code or "",
            row_b.title,
            weekday_b.value,
            row_b.start_time,
            row_b.end_time,
        )

        # xem file validator_FUNC_detect_import_conflicts.txt (sourceCode/BE/learning/)
        pair_key = ("INCOMING", min(sig_a, sig_b), max(sig_a, sig_b))
        if pair_key in seen_series_pairs:  # ta kiểm cặp này đã được xét chưa (không quan tâm có trùng lịch hay không, ta quan tâm đã được xét chưa, xét rồi thì continue)
            continue
        seen_series_pairs.add(pair_key)  # nếu chưa thì ghi nhận rồi đem đi xét

        # 2 biến này để xác định khoảng thời gian bị trùng
        overlap_start = max(row_a.start_time, row_b.start_time)
        overlap_end = min(row_a.end_time, row_b.end_time)
        conflict_cards.append(
            {
                "conflict_id": f"conflict_{len(conflict_cards) + 1}",
                "option_a": row_a,
                "option_b": row_b,
                "overlap_description": (
                    f"{weekday_a.value} {_format_time_range(overlap_start, overlap_end)}: "
                    f"'{row_a.title}' overlaps with '{row_b.title}'"
                ),
            }
        )

    # 2. detect conflicts between incoming_rows and existing_events grouped at series level
    blocking_existing = [ev for ev in existing_events if ev.blocks_availability]
    existing_by_date = _bucket_slots_by_vn_date([[ev.to_slot()] for ev in blocking_existing])
    matched_existing_by_row: dict[int, set[int]] = {}
    for day, inc_bucket in incoming_by_date.items():
        ex_bucket = existing_by_date.get(day)
        if not ex_bucket:
            continue
        active_existing: list[tuple[datetime, datetime, int]] = []
        ex_pos = 0
        for inc_start, inc_end, row_idx in inc_bucket:
            while ex_pos < len(ex_bucket) and ex_bucket[ex_pos][0] < inc_end:
                if ex_bucket[ex_pos][1] > inc_start:
                    active_existing.append(ex_bucket[ex_pos])
                ex_pos += 1
            active_existing = [ex for ex in active_existing if ex[1] > inc_start]
            for ex_start, _ex_end, ev_idx in active_existing:
                if ex_start < inc_end:
                    matched_existing_by_row.setdefault(row_idx, set()).add(ev_idx)

    for i, ev_indices in sorted(matched_existing_by_row.items()):
        row = incoming_rows[i]
        weekday_a = _resolve_row_weekday(row)
        conflicting_row_indices.add(i)

        for ev_idx in sorted(ev_indices):
            event = blocking_existing[ev_idx]
            ev_start_vn = event.start_time.astimezone(VN_TZ)
            ev_end_vn = event.end_time.astimezone(VN_TZ)
            ev_weekday = INDEX_TO_WEEKDAY[ev_start_vn.weekday()]
            ev_start_t = ev_start_vn.timetz().replace(tzinfo=None)
            ev_end_t = ev_end_vn.timetz().replace(tzinfo=None)

            series_key = (
                "EXISTING",
                row.course_code,
                row.title,
                weekday_a.value,
                row.start_time,
                row.end_time,
                event.course_id,
                event.title,
                event.kind.value,
                ev_weekday.value,
                ev_start_t,
                ev_end_t,
            )
            if series_key in seen_series_pairs:
                continue
            seen_series_pairs.add(series_key)

            overlap_start = max(row.start_time, ev_start_t)
            overlap_end = min(row.end_time, ev_end_t)
            conflict_cards.append(
                {
                    "conflict_id": f"conflict_{len(conflict_cards) + 1}",
                    "option_a": row,
                    "option_b": event,
                    "overlap_description": (
                        f"{ev_weekday.value} {_format_time_range(overlap_start, overlap_end)}: "
                        f"incoming '{row.title}' overlaps with existing '{event.title}'"
                    ),
                }
            )

    non_conflicting_rows = [
        row
        for idx, row in enumerate(incoming_rows)
        if idx not in conflicting_row_indices
    ]
    return {
        "non_conflicting_rows": non_conflicting_rows,
        "conflict_cards": conflict_cards,
    }

def _normalize_key_text(value: str | None) -> str:
    """
    input: value (str | None) such as course_code, title, or room.
    core logic: lowercase, strip leading/trailing spaces, and collapse internal whitespace.
    output: normalized str safe for case-insensitive subject and occurrence comparison.
    typical flow: '  Vi   Tích Phân 2 ' -> 'vi tích phân 2'; None -> ''.
    """
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _subject_keys_for_row(row: ParsedCsvRow) -> set[tuple[str, str]]:
    """
    input: row (ParsedCsvRow) from incoming timetable file.
    core logic: build normalized identity keys by (kind, course_code) and (kind, title).
    output: set[tuple[str, str]] representing the subject/activity identity of this row.
    typical flow: row with code='MTH10002', title='Vi tích phân 2' -> {('CLASS','code:mth10002'), ('CLASS','title:vi tích phân 2')}.
    """
    # xem file validator_FUNC_commit_resolved_import.txt (sourceCode/BE/learning/)
    # tạo tập khóa nhận diện môn học/hoạt động để nối được cả trường hợp file có mã môn lẫn file pdf/txt chỉ có tên môn
    keys: set[tuple[str, str]] = set()
    kind_val = row.kind.value
    norm_code = _normalize_key_text(row.course_code)
    norm_title = _normalize_key_text(row.title)
    if norm_code and norm_code != "general":
        keys.add((kind_val, f"code:{norm_code}"))
    if norm_title:
        keys.add((kind_val, f"title:{norm_title}"))
    return keys


def _subject_keys_for_event(
    ev: Event | EventDomain, course_code_by_id: dict[int, str]
) -> set[tuple[str, str]]:
    """
    input: ev (Event | EventDomain) from database and course_code_by_id lookup map.
    core logic: build normalized identity keys matching _subject_keys_for_row format.
    output: set[tuple[str, str]] for comparing existing DB events against incoming rows.
    typical flow: CLASS event linked to Course('MTH10002') -> {('CLASS','code:mth10002'), ('CLASS','title:vi tích phân 2')}.
    """
    keys: set[tuple[str, str]] = set()
    kind_val = ev.kind.value
    norm_title = _normalize_key_text(ev.title)
    if norm_title:
        keys.add((kind_val, f"title:{norm_title}"))
    if ev.course_id is not None and ev.course_id in course_code_by_id:
        norm_code = _normalize_key_text(course_code_by_id[ev.course_id])
        if norm_code and norm_code != "general":
            keys.add((kind_val, f"code:{norm_code}"))
    return keys

    """
    2 hàm _subject_keys_for_row và _subject_keys_for_event nhìn đầu ra giống nhau vậy có hai hàm chi?
    -> Mấy cái được import mới thì gọi hàm _subject_keys_for_row, còn để so cái mới được import với cái đã có (có đụng độ hay không) thì cái đã có (lưu trong DB) thì gọi hàm _subject_keys_for_event.
    Vì mới được import sẽ là ParsedCsvRow, còn lưu trong DB thì data tổ chức kiểu khác, 2 kiểu data khác nhau nên logic xử lý khác nhau. (trong DB thì bảng events chỉ lưu fk: course_id chứ không lưu course_code, nên buộc phải tra cứu gián tiếp course_code thông qua từ điển course_code_by_id)
    Đầu ra giống nhau là do cái mới vào và cái đã có muốn check xem có conflict hay không thì phải đưa về một chuẩn chung.
    """

def _build_incoming_subject_windows(
    rows: list[ParsedCsvRow],
) -> dict[tuple[str, str], tuple[date, date]]:
    """
    input: rows (list[ParsedCsvRow]) from preview/commit request.
    core logic: compute [min_first_date, max_last_date] span for each subject key present in rows.
    output: dict mapping each subject_key -> (min_first_date, max_last_date).
    typical flow: 2 rows of same course -> merged date range covering both rows.
    """
    windows: dict[tuple[str, str], tuple[date, date]] = {} # key của dict windows là tuple(event_kind, normalized code) hay tuple(event_kind, normalized title), key dạng tuple được tạo ra ở dòng for skey in _subject_keys_for_row(row).
    for row in rows:
        for skey in _subject_keys_for_row(row):
            if skey not in windows: # toán tử 'in' trên một dict dùng để kiểm tra sự tồn tại của key
                windows[skey] = (row.first_date, row.last_date)
            else:
                cur_min, cur_max = windows[skey]
                windows[skey] = (min(cur_min, row.first_date), max(cur_max, row.last_date))
    return windows


def _is_event_covered_by_incoming_subjects(
    ev: Event | EventDomain,
    course_code_by_id: dict[int, str],
    subject_windows: dict[tuple[str, str], tuple[date, date]],
) -> bool:
    """
    input: ev (Event | EventDomain), course_code_by_id map, and subject_windows from incoming rows.
    core logic: return True if ev shares a subject key with incoming rows AND falls inside that subject's date window.
    [READ THIS] output: BOOL, indicating whether ev belongs to a subject+period being updated by the incoming file.
    [READ THIS] typical flow: updating 'Thể dục 1' from week 3 => True for week 3..15 of 'Thể dục 1', False for week 1..2 and other courses.
    """
    ev_keys = _subject_keys_for_event(ev, course_code_by_id)
    if not ev_keys:
        return False
    ev_date_vn = from_db_to_vn(ev.start_time).date()
    for ek in ev_keys:
        if ek in subject_windows:
            min_d, max_d = subject_windows[ek]
            if min_d <= ev_date_vn <= max_d:
                return True
    return False


def filter_existing_for_conflict_check(
    db: Session,
    owner_id: int,
    incoming_rows: list[ParsedCsvRow],
    db_events: list[Event],
    replace_previous_imports: bool = False,
) -> list[EventDomain]:
    """
    input: db, owner_id, incoming_rows, active db_events, and replace_previous_imports flag.
    core logic: exclude old IMPORTED events that will be replaced (all IMPORTED if replace=True, or only
                same-subject events within the updated date window if replace=False) so step 3 never raises
                false self-conflicts when updating a course's schedule while still catching collisions with other courses.
    output: list[EventDomain] of existing events that must be checked for hard overlaps.
    [READ THIS] typical flow: update 2 courses (total: 5 courses) -> skip old slots of those 2 courses (lịch sau replace lịch trước nên lịch ban đầu sẽ bị xóa, nếu không có func ignore sẽ bị báo conflict giả, nó lúc sau conflict với nó lúc trước, trong khi đang cập nhật nó), keep the other 3 courses for conflict check.
    """
    # xem file validator_FUNC_commit_resolved_import.txt (sourceCode/BE/learning/)
    if replace_previous_imports:
        return [
            ev.to_domain() 
            for ev in db_events
            if ev.source != EventSource.IMPORTED
        ]

    course_rows = db.scalars(active_courses_stmt(owner_id)).all()
    course_code_by_id = {c.id: c.course_code for c in course_rows}
    subject_windows = _build_incoming_subject_windows(incoming_rows)

    kept_domains: list[EventDomain] = []
    for ev in db_events:
        if ev.source == EventSource.IMPORTED and _is_event_covered_by_incoming_subjects(
            ev, course_code_by_id, subject_windows
        ):
            # bỏ qua lịch cũ của chính môn đang được cập nhật trong khung ngày mới để không báo xung đột giả với chính nó
            continue
        kept_domains.append(ev.to_domain())
    return kept_domains


def _event_occurrence_sig(
    kind_val: str,
    title: str | None,
    room: str | None,
    start_utc_naive: datetime,
    end_utc_naive: datetime,
) -> tuple[str, str, str, datetime, datetime]:
    """
    input: kind_val (str), title (str), room (str | None), and naive UTC start/end timestamps.
    core logic: build a canonical 5-tuple signature uniquely identifying one concrete calendar occurrence.
    output: tuple[str, str, str, datetime, datetime] hashable signature for O(1) diff lookup.
    typical flow: ('CLASS', 'tư duy tính toán', 'i42', datetime(2026,11,2,0,30), datetime(2026,11,2,2,30)).
    """
    return (
        kind_val,
        _normalize_key_text(title),
        _normalize_key_text(room),
        start_utc_naive.replace(tzinfo=None),
        end_utc_naive.replace(tzinfo=None),
    )


# LƯU Ý: hàm này thực hiện đồng bộ thông minh (Smart Diff & Subject-Scoped Upsert):
# - Giữ nguyên bản ghi không đổi (không xóa đi tạo lại gây lãng phí tài nguyên DB).
# - Chỉ xóa mềm (soft-del) những buổi học bị thay đổi hoặc bị hủy trong phạm vi cập nhật.
# xem file validator_FUNC_commit_resolved_import.txt (sourceCode/BE/learning/)
def commit_resolved_import(
    db: Session,
    owner_id: int,
    import_batch_id: str,
    resolved_rows: list[ParsedCsvRow], # các dòng bị lỗi định dạng đã được sửa hoặc bỏ qua và các lịch được giữ lại trong các cặp bị trùng giờ
    replace_previous_imports: bool = False,
) -> list[EventDomain]:
    """
    input: db (Session), owner_id (int), import_batch_id (str), resolved_rows, replace_previous_imports.
    core logic: reconcile (đối chiếu) incoming occurrences against existing IMPORTED events (preserving unchanged rows,
                soft-deleting only modified/removed rows in scope, and inserting only new/changed rows).
    output: list[EventDomain] of all active Event records resulting from resolved_rows.
    typical flow: expand incoming specs -> match unchanged DB rows -> soft-delete stale rows -> insert diff -> return.
    """
    now_naive_utc = datetime.now(UTC_TZ).replace(tzinfo=None)

    # lấy danh sách Course và Event còn active (chưa bị xóa mềm) của user để chuẩn bị đối chiếu (Diffing)
    active_courses = list(db.scalars(active_courses_stmt(owner_id)).all())
    course_code_by_id: dict[int, str] = {c.id: c.course_code for c in active_courses} 
    # course_code_by_id là từ điển được tạo bằng cách duyệt qua id của các event chưa bị xóa mềm (còn active) và truy xuất mã môn tương ứng với id (nếu event đó có id),
    # mỗi phần tử trong dict là cặp id và mã môn. 

    # từ điển này để tra Course theo (norm_code, norm_title), là khi import, đi qua bước normalize ta được cặp (norm_code, norm_title) là duy nhất, thì nếu file mới nhắc
    # đến một sự kiện đã có rồi sẽ tra ra, ta sẽ biết đó là cập nhật, xử lý như nào đó chứ không phải xóa cái cũ đi tạo cái mới vì 2 cái đều có code và title giống nhau, 
    # nếu file mới chứa 1 sự kiện đã có trong hệ thống mà khác thời gian thì cập nhật thời gian thôi chứ không xóa cả cái cũ đi tạo lại cái mới, hàm này là để truy xem cái được import vào có giống cái đã có không
    course_by_identity: dict[tuple[str, str], Course] = {
        (_normalize_key_text(c.course_code or "GENERAL"), _normalize_key_text(c.title)): c
        for c in active_courses
    }

    active_imported_events = list(
        db.scalars(
            select(Event).where(
                Event.owner_id == owner_id,
                Event.source == EventSource.IMPORTED,
                Event.deleted_at.is_(None),
            )
        ).all()
    )
    # active_courses ở đoạn đầu cũng dùng db.scalars nhưng là lấy hết mọi thứ chưa bị xóa, còn list active_imported_events này chỉ lấy những event được tạo bằng nút import (không phải tạo bởi AI hay tạo bởi user manually)

    # 2. xác định tập các Event IMPORTED cũ nằm trong phạm vi cần đối chiếu (candidate_old_events):
    # - nếu replace_previous_imports=True (chỉ dùng như nút Reset khi user lỡ nạp nhầm file sai hoàn toàn hoặc muốn xóa trắng lịch IMPORTED cũ):
    #   xét toàn bộ active_imported_events. (Lưu ý: khi sang học kỳ mới, các lớp kỳ cũ vốn đã kết thúc ở last_date của kỳ cũ nên không cần bật cờ này).
    # - nếu replace_previous_imports=False (mặc định cho cả sang kỳ mới, cập nhật lịch giữa kỳ, nạp tiếp nửa kỳ sau, hoặc nạp lịch làm thêm):
    #   chỉ xét các Event IMPORTED có cùng khóa môn (_subject_key) VÀ nằm trong khoảng [first_date, last_date] của môn đó ở file mới.
    #   nhờ vậy: các môn không có trong file sửa đổi, hoặc các tuần/học kỳ trước đã học, hoặc lịch học khi nạp lịch làm thêm được giữ lại toàn bộ.
    
    subject_windows = _build_incoming_subject_windows(resolved_rows) # resolved_rows là list
    # subject_windows này là 1 dict, một thành phần hợp lệ trong dict này có thể là {"(event_kind, normalized code)": (first_date, last_date)}
    candidate_old_events: list[Event] = []
    for ev in active_imported_events:
        if replace_previous_imports or _is_event_covered_by_incoming_subjects(ev, course_code_by_id, subject_windows):
            candidate_old_events.append(ev)
        """ 
        Biến cờ replace_previous_imports mặc định là False: khi user nạp file mới chỉ để sửa giờ vài môn hoặc nạp bổ sung (kể cả sửa 1-2 môn trong 5 môn cũ), không cần bật cờ này vì cơ chế Smart Diff đã tự cập nhật đúng các môn trong file mới và giữ nguyên các môn khác.
        Cờ replace_previous_imports chỉ được gửi là True (ở UI có checkbox "thay thế toàn bộ lịch đã import" và được user tích chọn) khi user muốn xóa sạch toàn bộ lịch IMPORTED trước đó và thay bằng file mới, có thể do nạp nhầm file chẳng hạn.

        * Ngay cả khi replace_previous_imports=True, hàm commit_resolved_import không xóa sạch mù quáng mọi dòng cũ rồi chèn lại từ đầu nếu file mới có những buổi không thay đổi (vẫn giữ nguyên bản ghi cũ nếu trùng chữ ký).
        * Chỉ với những buổi có thay đổi hoặc bị bỏ đi, hệ thống mới đánh dấu xóa mềm bản ghi cũ (deleted_at) rồi INSERT bản ghi mới chứ không UPDATE đè lên dòng cũ.
        Vì:
        - File nguồn không có event.id và số buổi cũ/mới có thể không khớp 1-1: ví dụ một môn từ 2 buổi/tuần (Thứ Hai, Thứ Tư) chuyển sang 1 buổi/tuần (Thứ Năm).
        - Hệ thống không có căn cứ chắc chắn để biết "buổi Thứ Năm mới" là bản sửa của "buổi Thứ Hai cũ" hay "buổi Thứ Tư cũ".
        - Nếu cố đoán ghép theo vị trí để UPDATE tại chỗ sẽ rất dễ ghi đè sai lên lịch các tuần đã qua, làm lệch dữ liệu hoặc kéo nhầm trạng thái Reminder cũ sang khung giờ mới.
        
        Còn hàm _is_event_covered...: vd trong các sự kiện trong file import, cái bắt đầu sớm nhất là ngày a, 
        cái sau cùng là kết thúc ngày b, thì hệ thống chỉ xét những event thuộc khoảng ngày a đến ngày b, 
        các sự kiện thuộc khoảng khác bỏ qua.
        """

    # gom các Event cũ theo chữ ký buổi học (_event_occurrence_sig) để tra cứu O(1)
    old_events_by_sig: dict[tuple[str, str, str, datetime, datetime], list[Event]] = {} # dict có key là chữ ký buổi học, value là tất cả event có chữ ký như key
    for ev in candidate_old_events:
        sig = _event_occurrence_sig(
            ev.kind.value, ev.title, ev.room, ev.start_time, ev.end_time # đóng gói lại thành 1 tuple
        )
        old_events_by_sig.setdefault(sig, []).append(ev)

    # 3. bung toàn bộ resolved_rows thành danh sách các buổi học cụ thể (incoming_specs)
    # mỗi phần tử lưu thông tin cần thiết để tái sử dụng bản ghi cũ hoặc INSERT bản ghi mới
    incoming_specs: list[dict[str, Any]] = []
    for row in resolved_rows:
        if row.kind == CsvRowKind.CLASS:
            code_val = row.course_code or "GENERAL"
            course_ident = (_normalize_key_text(code_val), _normalize_key_text(row.title))
            course = course_by_identity.get(course_ident) # trả về đối tượng môn học nếu đã tồn tại hoặc None
            if course is None:
                course = Course(
                    owner_id=owner_id,
                    course_code=code_val,
                    title=row.title,
                    default_room=row.room,
                    import_batch_id=import_batch_id,
                )
                db.add(course)
                db.flush()  # lấy course.id ngay để gán cho các buổi học bên dưới
                course_by_identity[course_ident] = course
                course_code_by_id[course.id] = course.course_code
            else:
                # nếu môn học đã tồn tại thì chỉ cập nhật lại phòng mặc định và mã lô mới nhất
                course.default_room = row.room
                course.import_batch_id = import_batch_id

            # hàm này bung lịch học ra từng buổi cụ thể, từ occurrence rule vd như lặp thứ hai hàng tuần
            for occ_date in _iter_row_dates(row):
                start_vn = datetime.combine(occ_date, row.start_time, tzinfo=VN_TZ)
                end_vn = datetime.combine(occ_date, row.end_time, tzinfo=VN_TZ)
                start_utc = to_db_utc(start_vn)
                end_utc = to_db_utc(end_vn)
                incoming_specs.append(
                    {
                        "course_id": course.id,
                        "title": row.title,
                        "room": row.room,
                        "kind": EventKind.CLASS,
                        "start_time": start_utc,
                        "end_time": end_utc,
                        "is_hard": True,
                        "priority": int(PriorityLevel.MEDIUM),
                        "sig": _event_occurrence_sig(
                            EventKind.CLASS.value, row.title, row.room, start_utc, end_utc
                        ),
                    }
                )

        elif row.kind in (CsvRowKind.EXAM, CsvRowKind.EVENT):
            is_exam = row.kind == CsvRowKind.EXAM
            ev_kind = EventKind.EXAM if is_exam else EventKind.EVENT
            start_vn = datetime.combine(row.first_date, row.start_time, tzinfo=VN_TZ)
            end_vn = datetime.combine(row.first_date, row.end_time, tzinfo=VN_TZ)
            start_utc = to_db_utc(start_vn)
            end_utc = to_db_utc(end_vn)
            incoming_specs.append(
                {
                    "course_id": None,
                    "title": row.title,
                    "room": row.room,
                    "kind": ev_kind,
                    "start_time": start_utc,
                    "end_time": end_utc,
                    "is_hard": is_exam,
                    "priority": int(PriorityLevel.HIGH if is_exam else PriorityLevel.LOW),
                    "sig": _event_occurrence_sig(
                        ev_kind.value, row.title, row.room, start_utc, end_utc
                    ),
                }
            )

        elif row.kind == CsvRowKind.DEADLINE:
            deadline_vn = datetime.combine(row.first_date, row.start_time, tzinfo=VN_TZ)
            deadline_utc = to_db_utc(deadline_vn)
            incoming_specs.append(
                {
                    "course_id": None,
                    "title": row.title,
                    "room": row.room,
                    "kind": EventKind.DEADLINE,
                    "start_time": deadline_utc,
                    "end_time": deadline_utc,
                    "is_hard": False,
                    "priority": int(PriorityLevel.HIGH),
                    "sig": _event_occurrence_sig(
                        EventKind.DEADLINE.value, row.title, row.room, deadline_utc, deadline_utc
                    ),
                }
            )

    # 4. đối chiếu từng buổi học trong incoming_specs với old_events_by_sig:
    # Nguyên tắc: giống hệt 100% thì giữ nguyên dòng cũ; có thay đổi dù nhỏ thì xóa mềm dòng cũ và tạo dòng mới với id mới.
    
    # - nếu chữ ký sig đã có sẵn trong DB -> giữ nguyên bản ghi cũ (reused_event_ids), KHÔNG xóa và KHÔNG tạo mới.
    # - nếu chữ ký sig chưa có trong DB -> tạo bản ghi Event mới (newly_created_events).
    reused_event_ids: set[int] = set()
    committed_events: list[Event] = []
    newly_created_events: list[Event] = []

    for spec in incoming_specs:
        matching_bucket = old_events_by_sig.get(spec["sig"])
        if matching_bucket:
            existing_ev = matching_bucket.pop(0)
            reused_event_ids.add(existing_ev.id)
            if spec["course_id"] is not None and existing_ev.course_id != spec["course_id"]:
                existing_ev.course_id = spec["course_id"]
            committed_events.append(existing_ev)
        else:
            new_ev = Event(
                owner_id=owner_id,
                course_id=spec["course_id"],
                title=spec["title"],
                room=spec["room"],
                kind=spec["kind"],
                source=EventSource.IMPORTED,
                import_batch_id=import_batch_id,
                start_time=spec["start_time"],
                end_time=spec["end_time"],
                is_hard=spec["is_hard"],
                priority=spec["priority"],
            )
            db.add(new_ev)
            committed_events.append(new_ev)
            newly_created_events.append(new_ev)

    # 5. những Event cũ nằm trong phạm vi đối chiếu (candidate_old_events) nhưng KHÔNG được tái sử dụng
    #    (tức là các buổi đã bị đổi khung giờ/phòng hoặc bị loại bỏ) mới bị đánh dấu xóa mềm (deleted_at = now_naive_utc)
    for old_ev in candidate_old_events:
        if old_ev.id not in reused_event_ids:
            old_ev.deleted_at = now_naive_utc

    db.flush()

    # 6. dọn dẹp bảng courses: nếu sau khi cập nhật mà một Course không còn bất kỳ Event active nào trỏ tới
    #    (ví dụ khi sang kỳ mới bật replace_previous_imports=True), đánh dấu xóa mềm Course mồ côi đó
    remaining_course_ids = set(
        db.scalars(
            select(Event.course_id).where(
                Event.owner_id == owner_id,
                Event.deleted_at.is_(None),
                Event.course_id.is_not(None),
            )
        ).all()
    )
    for c in active_courses:
        if c.id not in remaining_course_ids:
            c.deleted_at = now_naive_utc

    db.commit()
    for ev in newly_created_events:
        db.refresh(ev)

    return [ev.to_domain() for ev in committed_events]
