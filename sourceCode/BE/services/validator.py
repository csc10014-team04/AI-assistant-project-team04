# owner: Khoi (P1-6 hard constraint validator + P1-4 second half: conflict detection & db commit)
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, to_db_utc
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


def _resolve_row_weekday(row: ParsedCsvRow) -> Weekday:
    """return explicit weekday on row or infer from first_date"""
    if row.weekday is not None:
        return row.weekday
    return INDEX_TO_WEEKDAY[row.first_date.weekday()]


def _iter_row_dates(row: ParsedCsvRow) -> list[date]:
    """expand a parsed csv row into concrete calendar dates"""
    if row.kind == CsvRowKind.CLASS:
        target_idx = WEEKDAY_TO_INDEX[_resolve_row_weekday(row)]
        days_ahead = (target_idx - row.first_date.weekday()) % 7
        current = row.first_date + timedelta(days=days_ahead)
        dates: list[date] = []
        while current <= row.last_date:
            dates.append(current)
            current += timedelta(days=7)
        return dates
    return [row.first_date]


def _expand_row_slots(row: ParsedCsvRow) -> list[TimeSlot]:
    """convert a non-deadline parsed csv row into timezone-aware time slots in vn_tz"""
    if row.kind == CsvRowKind.DEADLINE or row.start_time == row.end_time:
        return []
    slots: list[TimeSlot] = []
    for occ_date in _iter_row_dates(row):
        start_dt = datetime.combine(occ_date, row.start_time, tzinfo=VN_TZ)
        end_dt = datetime.combine(occ_date, row.end_time, tzinfo=VN_TZ)
        if end_dt > start_dt:
            slots.append(TimeSlot(start=start_dt, end=end_dt))
    return slots


def _format_time_range(start_t: time, end_t: time) -> str:
    """format a time interval as HH:MM-HH:MM"""
    return f"{start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}"


def check_hard_conflict(
    candidate_slot: TimeSlot, existing_events: list[EventDomain]
) -> list[EventDomain]:
    """return list of hard-constraint events that overlap with candidate_slot"""
    conflicts: list[EventDomain] = []
    for event in existing_events:
        if (
            event.is_hard is True
            and event.blocks_availability is True
            and candidate_slot.overlaps(event.to_slot())
        ):
            conflicts.append(event)
    return conflicts


def detect_import_conflicts(
    incoming_rows: list[ParsedCsvRow], existing_events: list[EventDomain]
) -> dict[str, Any]:
    """group series-level conflicts and separate non-conflicting rows"""
    expanded_incoming: list[list[TimeSlot]] = [
        _expand_row_slots(row) for row in incoming_rows
    ]
    conflicting_row_indices: set[int] = set()
    conflict_cards: list[dict[str, Any]] = []
    seen_series_pairs: set[tuple[Any, ...]] = set()

    # 1. detect conflicts within incoming_rows grouped at series level
    for i in range(len(incoming_rows)):
        slots_a = expanded_incoming[i]
        if not slots_a:
            continue
        row_a = incoming_rows[i]
        weekday_a = _resolve_row_weekday(row_a)

        for j in range(i + 1, len(incoming_rows)):
            slots_b = expanded_incoming[j]
            if not slots_b:
                continue
            row_b = incoming_rows[j]
            weekday_b = _resolve_row_weekday(row_b)

            has_overlap = any(
                slot_a.overlaps(slot_b) for slot_a in slots_a for slot_b in slots_b
            )
            if not has_overlap:
                continue

            conflicting_row_indices.add(i)
            conflicting_row_indices.add(j)

            sig_a = (
                "ROW",
                row_a.course_code,
                row_a.title,
                weekday_a.value,
                row_a.start_time,
                row_a.end_time,
            )
            sig_b = (
                "ROW",
                row_b.course_code,
                row_b.title,
                weekday_b.value,
                row_b.start_time,
                row_b.end_time,
            )
            pair_key = ("INCOMING", min(sig_a, sig_b), max(sig_a, sig_b))
            if pair_key in seen_series_pairs:
                continue
            seen_series_pairs.add(pair_key)

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
    for i, row in enumerate(incoming_rows):
        slots_a = expanded_incoming[i]
        if not slots_a:
            continue
        weekday_a = _resolve_row_weekday(row)

        for event in blocking_existing:
            event_slot = event.to_slot()
            if not any(slot_a.overlaps(event_slot) for slot_a in slots_a):
                continue

            conflicting_row_indices.add(i)

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


def commit_resolved_import(
    db: Session,
    owner_id: int,
    import_batch_id: str,
    resolved_rows: list[ParsedCsvRow],
    replace_previous_imports: bool = False,
) -> list[EventDomain]:
    """expand recurring CLASS rows into weekly events and persist to mysql"""
    if replace_previous_imports:
        now_naive_utc = datetime.now(UTC_TZ).replace(tzinfo=None)
        db.execute(
            update(Event)
            .where(
                Event.owner_id == owner_id,
                Event.source == EventSource.IMPORTED,
                Event.deleted_at.is_(None),
            )
            .values(deleted_at=now_naive_utc)
        )
        db.execute(
            update(Course)
            .where(
                Course.owner_id == owner_id,
                Course.deleted_at.is_(None),
            )
            .values(deleted_at=now_naive_utc)
        )

    created_events: list[Event] = []

    for row in resolved_rows:
        if row.kind == CsvRowKind.CLASS:
            course = Course(
                owner_id=owner_id,
                course_code=row.course_code,
                title=row.title,
                default_room=row.room,
                import_batch_id=import_batch_id,
            )
            db.add(course)
            db.flush()  # populate course.id for child events

            for occ_date in _iter_row_dates(row):
                start_vn = datetime.combine(occ_date, row.start_time, tzinfo=VN_TZ)
                end_vn = datetime.combine(occ_date, row.end_time, tzinfo=VN_TZ)
                ev = Event(
                    owner_id=owner_id,
                    course_id=course.id,
                    title=row.title,
                    room=row.room,
                    kind=EventKind.CLASS,
                    source=EventSource.IMPORTED,
                    import_batch_id=import_batch_id,
                    start_time=to_db_utc(start_vn),
                    end_time=to_db_utc(end_vn),
                    is_hard=True,
                    priority=int(PriorityLevel.MEDIUM),
                )
                db.add(ev)
                created_events.append(ev)

        elif row.kind in (CsvRowKind.EXAM, CsvRowKind.EVENT):
            is_exam = row.kind == CsvRowKind.EXAM
            start_vn = datetime.combine(row.first_date, row.start_time, tzinfo=VN_TZ)
            end_vn = datetime.combine(row.first_date, row.end_time, tzinfo=VN_TZ)
            ev = Event(
                owner_id=owner_id,
                course_id=None,
                title=row.title,
                room=row.room,
                kind=EventKind.EXAM if is_exam else EventKind.EVENT,
                source=EventSource.IMPORTED,
                import_batch_id=import_batch_id,
                start_time=to_db_utc(start_vn),
                end_time=to_db_utc(end_vn),
                is_hard=is_exam,
                priority=int(PriorityLevel.HIGH if is_exam else PriorityLevel.LOW),
            )
            db.add(ev)
            created_events.append(ev)

        elif row.kind == CsvRowKind.DEADLINE:
            deadline_vn = datetime.combine(row.first_date, row.start_time, tzinfo=VN_TZ)
            deadline_utc = to_db_utc(deadline_vn)
            ev = Event(
                owner_id=owner_id,
                course_id=None,
                title=row.title,
                room=row.room,
                kind=EventKind.DEADLINE,
                source=EventSource.IMPORTED,
                import_batch_id=import_batch_id,
                start_time=deadline_utc,
                end_time=deadline_utc,
                is_hard=False,
                priority=int(PriorityLevel.HIGH),
            )
            db.add(ev)
            created_events.append(ev)

    db.commit()
    for ev in created_events:
        db.refresh(ev)

    return [ev.to_domain() for ev in created_events]

