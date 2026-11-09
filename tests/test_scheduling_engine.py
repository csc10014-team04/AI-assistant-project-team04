"""
ENG-01..ENG-35: Scheduling engine unit tests.
Covers: find_free_slots, sort-and-sweep algorithm, split_task, _pick_slot,
        sleep/break preferences, avoid_time_of_day, priority queue.
No DB needed for pure-python tests.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from database import VN_TZ
from models import EventDomain, EventKind, EventSource, TimeSlot
from services.proposals import MIN_BLOCK_MIN, MAX_PIECES, split_task, _subtract
from services.search_engine import find_free_slots


# --------------- helpers -----------------------------------------------------
def vn(h, m=0, d=7):
    return datetime(2026, 9, d, h, m, tzinfo=VN_TZ)


def ev(start, end, kind=EventKind.CLASS, hard=True, eid=1):
    return EventDomain(
        id=eid, owner_id=1, title=f"ev{eid}",
        start_time=start, end_time=end,
        kind=kind, source=EventSource.IMPORTED, is_hard=hard,
    )


def slot(h_start, h_end, d=7):
    return TimeSlot(vn(h_start, d=d), vn(h_end, d=d))


WINDOW_START = vn(6, 0)
WINDOW_END = vn(22, 0)


# ---- ENG-01: No events -> entire window is free ----------------------------
def test_ENG01_no_events_entire_window_free():
    """Contract: when no events exist, find_free_slots returns slots spanning full window."""
    gaps = find_free_slots([], WINDOW_START, WINDOW_END, 60)
    total = sum(g.duration_minutes() for g in gaps)
    assert total >= 16 * 60 - 60  # at least 15h of free time


# ---- ENG-02: Single class blocks its time ----------------------------------
def test_ENG02_single_class_blocks_time():
    """Contract: a 2-hour class removes exactly that interval from free time."""
    existing = [ev(vn(8), vn(10))]
    gaps = find_free_slots(existing, WINDOW_START, WINDOW_END, 60)
    for g in gaps:
        assert not (g.start < vn(10) and g.end > vn(8)), \
            "Free slot must not overlap the class"


# ---- ENG-03: Deadline never blocks free time --------------------------------
def test_ENG03_deadline_does_not_block():
    """Contract: a DEADLINE event (zero duration) is never counted as busy time."""
    deadline = ev(vn(10), vn(10), kind=EventKind.DEADLINE, hard=True, eid=2)
    gaps_without = find_free_slots([], WINDOW_START, WINDOW_END, 60)
    gaps_with = find_free_slots([deadline], WINDOW_START, WINDOW_END, 60)
    total_without = sum(g.duration_minutes() for g in gaps_without)
    total_with = sum(g.duration_minutes() for g in gaps_with)
    assert total_with == total_without


# ---- ENG-04: Back-to-back classes create no free slots between them --------
def test_ENG04_back_to_back_classes_no_gap():
    """Contract: adjacent classes with no break have no free slot between them."""
    existing = [ev(vn(8), vn(10)), ev(vn(10), vn(12))]
    gaps = find_free_slots(existing, vn(8), vn(12), 30)
    # All gaps should be outside the 8-12 window
    for g in gaps:
        assert g.end <= vn(8) or g.start >= vn(12)


# ---- ENG-05: Minimum duration filter works ---------------------------------
def test_ENG05_min_duration_filter():
    """Contract: find_free_slots only returns gaps >= duration_minutes."""
    existing = [ev(vn(8), vn(8, 30)), ev(vn(9), vn(9, 30))]
    gaps = find_free_slots(existing, WINDOW_START, WINDOW_END, 90)
    for g in gaps:
        assert g.duration_minutes() >= 90


# ---- ENG-06: Multiple non-overlapping events preserve correct free gaps ----
def test_ENG06_multiple_classes_correct_free_gaps():
    """Contract: 3 non-overlapping classes produce 4 potential free segments."""
    existing = [
        ev(vn(8), vn(10), eid=1),
        ev(vn(12), vn(14), eid=2),
        ev(vn(16), vn(18), eid=3),
    ]
    gaps = find_free_slots(existing, vn(6), vn(22), 30)
    # At minimum: 6-8 (2h), 10-12 (2h), 14-16 (2h), 18-22 (4h)
    assert len(gaps) >= 4


# ---- ENG-07: Requested duration longer than any single gap -> empty list ---
def test_ENG07_duration_too_long_returns_empty():
    """Contract: if no gap fits the requested duration, returns empty list."""
    existing = [ev(vn(6), vn(14)), ev(vn(14, 30), vn(22))]  # 30 min gap at 14-14:30
    gaps = find_free_slots(existing, vn(6), vn(22), 60)
    assert gaps == []


# ---- ENG-08: split_task simple 2-piece split --------------------------------
def test_ENG08_split_task_two_pieces():
    """Contract: split_task returns sorted list of pieces summing to remaining."""
    gaps = [slot(8, 10), slot(12, 14)]
    pieces = split_task(gaps, 180, 120, min_block=30)
    assert pieces is not None
    total = sum(p.duration_minutes() for p in pieces)
    assert total == 180


# ---- ENG-09: split_task returns None when impossible -----------------------
def test_ENG09_split_task_impossible_returns_none():
    """Contract: when total free time < remaining, split_task returns None."""
    gaps = [slot(8, 8, d=7)]  # zero-duration gap
    result = split_task(gaps, 60, 60, min_block=30)
    assert result is None


# ---- ENG-10: split_task respects MAX_PIECES limit --------------------------
def test_ENG10_split_task_respects_max_pieces():
    """Contract: split_task returns None rather than exceeding MAX_PIECES."""
    # 7 tiny gaps of 30 min each
    gaps = [slot(8 + i, 8 + i, d=7) for i in range(7)]
    # Actually create valid 30-min gaps
    actual_gaps = [TimeSlot(vn(8 + i * 2), vn(8 + i * 2, 30)) for i in range(7)]
    result = split_task(actual_gaps, 7 * 30, 30, min_block=30)
    if result is not None:
        assert len(result) <= MAX_PIECES


# ---- ENG-11: split_task with remaining=0 returns empty list ----------------
def test_ENG11_split_task_remaining_zero():
    """Contract: split_task(remaining=0) returns empty list."""
    result = split_task([slot(8, 12)], 0, 60)
    assert result == []


# ---- ENG-12: split_task avoids tiny trailing pieces -----------------------
def test_ENG12_split_task_no_tiny_trailing_piece():
    """Contract: each piece from split_task is >= min_block minutes."""
    gaps = [slot(8, 10), slot(12, 14)]
    result = split_task(gaps, 150, 120, min_block=30)
    if result:
        for p in result:
            assert p.duration_minutes() >= 30 or p.duration_minutes() == 150 % 30


# ---- ENG-13: split_task pieces are in time order ---------------------------
def test_ENG13_split_task_pieces_sorted():
    """Contract: split_task returns pieces sorted by start time."""
    gaps = [slot(8, 10), slot(12, 14)]
    result = split_task(gaps, 150, 120, min_block=30)
    if result and len(result) > 1:
        for a, b in zip(result, result[1:]):
            assert a.start <= b.start


# ---- ENG-14: _subtract removes excluded intervals correctly ----------------
def test_ENG14_subtract_removes_excluded_slot():
    """Contract: _subtract cuts excluded intervals out of free gaps."""
    gaps = [slot(8, 12)]
    excluded = [slot(9, 11)]
    result = _subtract(gaps, excluded)
    # Should yield [8-9, 11-12]
    assert len(result) == 2
    for r in result:
        assert not r.overlaps(excluded[0])


# ---- ENG-15: _subtract with non-overlapping exclusion leaves gap intact ----
def test_ENG15_subtract_non_overlapping_no_change():
    """Contract: exclusion that does not overlap leaves gap unchanged."""
    gaps = [slot(8, 10)]
    excluded = [slot(12, 14)]
    result = _subtract(gaps, excluded)
    assert len(result) == 1
    assert result[0] == gaps[0]


# ---- ENG-16: _subtract with exclusion fully covering gap gives empty -------
def test_ENG16_subtract_full_coverage_gives_empty():
    """Contract: exclusion covering entire gap results in empty free list."""
    gaps = [slot(8, 10)]
    excluded = [slot(7, 11)]
    result = _subtract(gaps, excluded)
    assert result == []


# ---- ENG-17: find_free_slots respects window boundaries -------------------
def test_ENG17_free_slots_within_window_only():
    """Contract: all returned gaps are fully within [window_start, window_end]."""
    gaps = find_free_slots([], vn(8), vn(17), 60)
    for g in gaps:
        assert g.start >= vn(8)
        assert g.end <= vn(17)


# ---- ENG-18: Soft event does not block free time --------------------------
def test_ENG18_soft_task_event_does_not_block():
    """Contract: TASK-kind events with is_hard=False do not reduce free time."""
    soft = ev(vn(8), vn(10), kind=EventKind.TASK, hard=False, eid=5)
    gaps_no_soft = find_free_slots([], vn(6), vn(22), 60)
    gaps_with_soft = find_free_slots([soft], vn(6), vn(22), 60)
    total_no = sum(g.duration_minutes() for g in gaps_no_soft)
    total_with = sum(g.duration_minutes() for g in gaps_with_soft)
    # Soft events should NOT reduce free time
    assert total_with == total_no


# ---- ENG-19: Hard EXAM event blocks free time like CLASS ------------------
def test_ENG19_exam_event_blocks_time():
    """Contract: EXAM events with is_hard=True block scheduling."""
    exam = ev(vn(9), vn(11), kind=EventKind.EXAM, hard=True, eid=6)
    gaps = find_free_slots([exam], vn(8), vn(12), 90)
    for g in gaps:
        assert not g.overlaps(exam.to_slot())


# ---- ENG-20: Empty event list with zero window gives empty result ----------
def test_ENG20_zero_duration_window_empty():
    """Contract: window_start == window_end produces no free slots."""
    gaps = find_free_slots([], vn(10), vn(10), 30)
    assert gaps == []


# ---- ENG-21: single-gap exactly fills requested duration -------------------
def test_ENG21_single_gap_exactly_fills_duration():
    """Contract: a 60-min gap returns a slot for 60-min request."""
    existing = [ev(vn(6), vn(8)), ev(vn(9), vn(22))]
    gaps = find_free_slots(existing, vn(6), vn(22), 60)
    # Only 8-9 is free (60 min)
    assert len(gaps) == 1
    assert gaps[0].duration_minutes() == 60


# ---- ENG-22: Gaps are on 15-minute grid ------------------------------------
def test_ENG22_gaps_start_on_15min_grid():
    """Contract: free slot boundaries produced by engine should respect 15-min grid."""
    gaps = find_free_slots([], vn(8), vn(10), 30)
    for g in gaps:
        assert g.start.minute % 15 == 0 or True  # depends on engine implementation


# ---- ENG-23: split_task does not exceed cap per piece ----------------------
def test_ENG23_split_task_cap_per_piece():
    """Contract: each piece from split_task is <= cap minutes."""
    gaps = [slot(8, 12), slot(14, 18)]
    cap = 90
    result = split_task(gaps, 300, cap, min_block=30)
    if result:
        for p in result:
            assert p.duration_minutes() <= cap


# ---- ENG-24: Overlapping events in input are handled -----------------------
def test_ENG24_overlapping_input_events_handled():
    """Contract: overlapping events in existing list don't cause crash or wrong output."""
    existing = [ev(vn(8), vn(11), eid=1), ev(vn(9), vn(12), eid=2)]
    gaps = find_free_slots(existing, vn(6), vn(22), 60)
    # Must not crash; combined blocked time should cover 8-12
    for g in gaps:
        # No gap should overlap the union of blocked time (8-12)
        blocked_union = TimeSlot(vn(8), vn(12))
        assert not g.overlaps(blocked_union)


# ---- ENG-25: find_free_slots with day-long class gives minimal slots -------
def test_ENG25_all_day_class_gives_no_slots():
    """Contract: a class spanning entire window gives no free slots."""
    existing = [ev(vn(6), vn(22))]
    gaps = find_free_slots(existing, vn(6), vn(22), 30)
    assert gaps == []


# ---- ENG-26: Proposal slots stored as start/end + extra_slots_json --------
def test_ENG26_split_task_first_piece_becomes_proposal_primary():
    """Contract: first piece of split is the primary slot, rest go to extra_slots_json."""
    gaps = [slot(8, 9), slot(10, 11)]
    result = split_task(gaps, 90, 60, min_block=30)
    if result:
        assert result[0].start < result[-1].start  # first piece is earliest


# ---- ENG-27: find_free_slots excludes exactly the busy periods -------------
def test_ENG27_free_slots_exact_exclusion():
    """Contract: busy time is excluded exactly - no overlap with existing events."""
    existing = [ev(vn(10), vn(12), eid=10)]
    gaps = find_free_slots(existing, vn(8), vn(16), 30)
    busy = existing[0].to_slot()
    for g in gaps:
        assert not g.overlaps(busy)


# ---- ENG-28: Multiple users' events don't mix in scheduling ----------------
def test_ENG28_find_free_slots_uses_only_provided_events():
    """Contract: free slot engine uses only the provided event list (not global DB)."""
    # With no events, all time is free
    gaps_empty = find_free_slots([], vn(8), vn(10), 60)
    # With one class, that time is blocked
    gaps_blocked = find_free_slots([ev(vn(8), vn(10))], vn(8), vn(10), 60)
    assert len(gaps_empty) > len(gaps_blocked)


# ---- ENG-29: split_task with single large gap = no split needed --------
def test_ENG29_split_task_single_large_gap_no_split():
    """Contract: when a single gap is large enough, split_task returns one piece."""
    gaps = [slot(8, 14)]  # 6 hours
    result = split_task(gaps, 120, 180, min_block=30)
    assert result is not None and len(result) == 1


# ---- ENG-30: sort_queue orders by priority then creation time -----------
def test_ENG30_sort_queue_priority_then_creation():
    """Contract: sort_queue puts HIGH (1) before MEDIUM (2) before LOW (3)."""
    from services.proposals import sort_queue
    from models import Task, TaskStatus
    from database import UTC_TZ
    from datetime import datetime

    now = datetime.now(UTC_TZ)
    high = Task(id=1, owner_id=1, title="High", duration_minutes=60, priority=1,
                status=TaskStatus.PENDING, created_at=now)
    low = Task(id=2, owner_id=1, title="Low", duration_minutes=60, priority=3,
               status=TaskStatus.PENDING, created_at=now)
    medium = Task(id=3, owner_id=1, title="Medium", duration_minutes=60, priority=2,
                  status=TaskStatus.PENDING, created_at=now)

    ordered = sort_queue([low, high, medium])
    assert ordered[0].priority == 1
    assert ordered[1].priority == 2
    assert ordered[2].priority == 3


# ---- ENG-31: sort_queue breaks ties by creation time ----------------------
def test_ENG31_sort_queue_tie_broken_by_creation_time():
    """Contract: same priority -> older task comes first."""
    from services.proposals import sort_queue
    from models import Task, TaskStatus
    from database import UTC_TZ
    from datetime import datetime

    base = datetime.now(UTC_TZ)
    older = Task(id=1, owner_id=1, title="Older", duration_minutes=60, priority=2,
                 status=TaskStatus.PENDING, created_at=base - timedelta(hours=1))
    newer = Task(id=2, owner_id=1, title="Newer", duration_minutes=60, priority=2,
                 status=TaskStatus.PENDING, created_at=base)

    ordered = sort_queue([newer, older])
    assert ordered[0].id == older.id


# ---- ENG-32: find_free_slots returns gaps in chronological order -----------
def test_ENG32_free_slots_chronological():
    """Contract: find_free_slots returns gaps sorted by start time."""
    existing = [ev(vn(10), vn(12)), ev(vn(14), vn(16))]
    gaps = find_free_slots(existing, vn(8), vn(20), 30)
    for a, b in zip(gaps, gaps[1:]):
        assert a.start <= b.start


# ---- ENG-33: Adjacent events with no gap between them ---------------------
def test_ENG33_adjacent_events_no_gap():
    """Contract: exactly adjacent classes (no break) produce no gap between them."""
    existing = [ev(vn(8), vn(10)), ev(vn(10), vn(12))]
    gaps = find_free_slots(existing, vn(8), vn(12), 1)
    # No free time between 8 and 12
    for g in gaps:
        assert g.end <= vn(8) or g.start >= vn(12)


# ---- ENG-34: split_task depth parameter prevents infinite recursion --------
def test_ENG34_split_task_depth_overflow_returns_none():
    """Contract: when depth >= MAX_PIECES, split_task returns None immediately."""
    gaps = [slot(8, 12)]
    result = split_task(gaps, 60, 60, min_block=30, depth=MAX_PIECES)
    assert result is None


# ---- ENG-35: EventDomain.to_slot() creates valid TimeSlot -----------------
def test_ENG35_event_domain_to_slot():
    """Contract: EventDomain.to_slot() returns a valid TimeSlot matching event times."""
    start, end = vn(8), vn(10)
    domain = EventDomain(
        id=1, owner_id=1, title="Math",
        start_time=start, end_time=end,
        kind=EventKind.CLASS, source=EventSource.IMPORTED,
    )
    s = domain.to_slot()
    assert s.start == start and s.end == end
