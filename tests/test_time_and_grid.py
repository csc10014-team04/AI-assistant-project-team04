"""
TIME-01..TIME-30: Timezone and 15-minute grid contract tests.
Covers: UTC/VN_TZ conversions, round_up_to_15m, naive datetime rejection,
        to_db_utc, from_db_to_vn, resolve_date_hint.
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from database import UTC_TZ, VN_TZ, from_db_to_vn, round_up_to_15m, to_db_utc
from models import EventDomain, EventKind, EventSource, TimeSlot, ensure_aware
from services.temporal import ResolvedWindow, resolve_date_hint


# --------------- helpers -----------------------------------------------------
def vn(h, m=0, d=7, month=9, year=2026):
    return datetime(year, month, d, h, m, tzinfo=VN_TZ)


def utc(h, m=0, d=7, month=9, year=2026):
    return datetime(year, month, d, h, m, tzinfo=UTC_TZ)


def naive(h, m=0):
    return datetime(2026, 9, 7, h, m)


NOW_VN = vn(10, 0)


# ---- TIME-01: naive datetime raises ValueError in ensure_aware -------------
def test_TIME01_ensure_aware_rejects_naive():
    """Contract: ensure_aware raises ValueError for naive datetimes."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ensure_aware(naive(8), "start")


# ---- TIME-02: aware datetime passes ensure_aware ---------------------------
def test_TIME02_ensure_aware_accepts_aware():
    """Contract: ensure_aware does not raise for aware datetimes."""
    ensure_aware(vn(8), "start")  # must not raise


# ---- TIME-03: to_db_utc converts VN to UTC and strips tzinfo ---------------
def test_TIME03_vn_to_db_utc_gives_naive_utc():
    """Contract: 07:30+07 -> 00:30 UTC naive (MySQL DATETIME format)."""
    result = to_db_utc(vn(7, 30))
    assert result == datetime(2026, 9, 7, 0, 30)
    assert result.tzinfo is None


# ---- TIME-04: to_db_utc rejects naive datetimes ----------------------------
def test_TIME04_to_db_utc_rejects_naive():
    """Contract: to_db_utc raises ValueError for naive datetime."""
    with pytest.raises(ValueError):
        to_db_utc(naive(8))


# ---- TIME-05: to_db_utc truncates seconds ----------------------------------
def test_TIME05_to_db_utc_truncates_seconds():
    """Contract: seconds and microseconds are zeroed in DB output."""
    dt = datetime(2026, 9, 7, 7, 30, 45, 123456, tzinfo=VN_TZ)
    result = to_db_utc(dt)
    assert result.second == 0 and result.microsecond == 0


# ---- TIME-06: from_db_to_vn attaches VN_TZ to naive UTC -------------------
def test_TIME06_from_db_to_vn_naive_utc_gives_vn_time():
    """Contract: naive 00:30 UTC -> 07:30+07:00."""
    result = from_db_to_vn(datetime(2026, 9, 7, 0, 30))
    assert result.hour == 7 and result.minute == 30
    assert result.utcoffset() == timedelta(hours=7)


# ---- TIME-07: from_db_to_vn with aware UTC input ---------------------------
def test_TIME07_from_db_to_vn_aware_utc_input():
    """Contract: aware UTC datetime is correctly shifted to VN_TZ."""
    result = from_db_to_vn(datetime(2026, 9, 7, 0, 30, tzinfo=UTC_TZ))
    assert result.isoformat() == "2026-09-07T07:30:00+07:00"


# ---- TIME-08: roundtrip VN -> UTC -> VN is identity -----------------------
def test_TIME08_roundtrip_vn_utc_vn():
    """Contract: converting VN->UTC->VN recovers the original time."""
    original = vn(7, 30)
    stored = to_db_utc(original)
    recovered = from_db_to_vn(stored)
    assert recovered.hour == 7 and recovered.minute == 30


# ---- TIME-09: round_up_to_15m at boundary points --------------------------
@pytest.mark.parametrize("minute,expected_minute,expected_hour_offset", [
    (0, 0, 0),
    (1, 15, 0),
    (14, 15, 0),
    (15, 15, 0),
    (16, 30, 0),
    (29, 30, 0),
    (30, 30, 0),
    (31, 45, 0),
    (44, 45, 0),
    (45, 45, 0),
    (46, 0, 1),   # wraps to next hour
    (59, 0, 1),   # wraps to next hour
])
def test_TIME09_round_up_to_15m_parametrize(minute, expected_minute, expected_hour_offset):
    """Contract: round_up_to_15m advances to next 15-min boundary."""
    base = vn(8, minute)
    result = round_up_to_15m(base)
    expected_hour = (8 + expected_hour_offset) % 24
    assert result.minute == expected_minute
    assert result.hour == expected_hour
    assert result.second == 0


# ---- TIME-10: round_up_to_15m rejects naive datetime ----------------------
def test_TIME10_round_up_to_15m_rejects_naive():
    """Contract: round_up_to_15m raises ValueError for naive datetime."""
    with pytest.raises(ValueError):
        round_up_to_15m(naive(8))


# ---- TIME-11: TimeSlot raises for reversed start/end ----------------------
def test_TIME11_timeslot_reversed_raises():
    """Contract: TimeSlot with end < start raises ValueError."""
    with pytest.raises(ValueError):
        TimeSlot(vn(10), vn(8))


# ---- TIME-12: TimeSlot with naive times raises ----------------------------
def test_TIME12_timeslot_naive_raises():
    """Contract: TimeSlot with naive datetime raises ValueError."""
    with pytest.raises(ValueError):
        TimeSlot(naive(8), naive(10))


# ---- TIME-13: TimeSlot equality and duration ------------------------------
def test_TIME13_timeslot_duration():
    """Contract: duration_minutes() returns correct minutes between start and end."""
    slot = TimeSlot(vn(8, 0), vn(10, 30))
    assert slot.duration_minutes() == 150


# ---- TIME-14: TimeSlot overlap semantics (open interval) ------------------
@pytest.mark.parametrize("a_start,a_end,b_start,b_end,overlaps", [
    (8, 10, 9, 11, True),   # partial overlap
    (8, 10, 10, 12, False), # touching boundary: not overlap
    (8, 10, 6, 8, False),   # adjacent before
    (8, 10, 8, 10, True),   # identical
    (8, 10, 7, 11, True),   # B contains A
    (8, 10, 9, 9.5, True),  # A contains B  -- skip half-hour representation
])
def test_TIME14_timeslot_overlap_parametrize(a_start, a_end, b_start, b_end, overlaps):
    """Contract: TimeSlot.overlaps uses open-interval semantics (touching = no overlap)."""
    # Build datetime from hour values
    def h(hh):
        full = int(hh)
        mins = int((hh - full) * 60)
        return vn(full, mins)
    a = TimeSlot(h(a_start), h(a_end))
    b = TimeSlot(h(b_start), h(b_end))
    assert a.overlaps(b) == overlaps


# ---- TIME-15: TimeSlot.is_aligned_to_step ---------------------------------
@pytest.mark.parametrize("h,m,aligned", [
    (8, 0, True),
    (8, 15, True),
    (8, 30, True),
    (8, 45, True),
    (8, 1, False),
    (8, 16, False),
    (8, 59, False),
])
def test_TIME15_timeslot_grid_alignment(h, m, aligned):
    """Contract: is_aligned_to_step(15) detects 15-min grid boundaries."""
    slot = TimeSlot(vn(h, m), vn(h + 1, m))
    assert slot.is_aligned_to_step(15) == aligned


# ---- TIME-16: resolve_date_hint "hôm nay" ---------------------------------
def test_TIME16_resolve_today(monkeypatch):
    """Contract: 'hôm nay' resolves to today's date."""
    result = resolve_date_hint("hôm nay", NOW_VN)
    assert result.start == result.end == NOW_VN.astimezone(VN_TZ).date()
    assert not result.assumed


# ---- TIME-17: resolve_date_hint "ngày mai" --------------------------------
def test_TIME17_resolve_tomorrow():
    """Contract: 'ngày mai' resolves to today + 1 day."""
    today = NOW_VN.astimezone(VN_TZ).date()
    result = resolve_date_hint("ngày mai", NOW_VN)
    assert result.start == today + timedelta(days=1)


# ---- TIME-18: resolve_date_hint "ngày kia" --------------------------------
def test_TIME18_resolve_day_after_tomorrow():
    """Contract: 'ngày kia' resolves to today + 2 days."""
    today = NOW_VN.astimezone(VN_TZ).date()
    result = resolve_date_hint("ngày kia", NOW_VN)
    assert result.start == today + timedelta(days=2)


# ---- TIME-19: resolve_date_hint "tuần này" --------------------------------
def test_TIME19_resolve_this_week():
    """Contract: 'tuần này' window includes today and ends on Sunday."""
    today = NOW_VN.astimezone(VN_TZ).date()
    result = resolve_date_hint("tuần này", NOW_VN)
    assert result.start <= today <= result.end
    # end should be Sunday of this week (weekday 6)
    assert result.end.weekday() == 6


# ---- TIME-20: resolve_date_hint "tuần sau" --------------------------------
def test_TIME20_resolve_next_week():
    """Contract: 'tuần sau' starts on next Monday."""
    today = NOW_VN.astimezone(VN_TZ).date()
    result = resolve_date_hint("tuần sau", NOW_VN)
    assert result.start > today
    assert result.start.weekday() == 0  # Monday


# ---- TIME-21: resolve_date_hint "cuối tuần" --------------------------------
def test_TIME21_resolve_weekend():
    """Contract: 'cuối tuần' window includes Saturday and/or Sunday."""
    result = resolve_date_hint("cuối tuần", NOW_VN)
    # weekend: Saturday (5) and Sunday (6)
    assert result.start.weekday() in (5, 6) or result.end.weekday() in (5, 6)


# ---- TIME-22: vague date triggers clarification ----------------------------
@pytest.mark.parametrize("hint", ["sớm", "lúc nào đó", "sắp tới", "dạo này"])
def test_TIME22_vague_date_triggers_clarification(hint):
    """Contract: vague date hints set clarification_question and assumed=True."""
    result = resolve_date_hint(hint, NOW_VN)
    assert result.assumed is True
    assert result.clarification_question is not None


# ---- TIME-23: None hint gives 7-day default window -------------------------
def test_TIME23_none_hint_gives_7_day_default():
    """Contract: resolve_date_hint(None) returns assumed 7-day window."""
    today = NOW_VN.astimezone(VN_TZ).date()
    result = resolve_date_hint(None, NOW_VN)
    assert result.assumed is True
    assert result.end == today + timedelta(days=6)


# ---- TIME-24: Numeric date parsing (DD/MM) --------------------------------
def test_TIME24_numeric_date_dd_mm():
    """Contract: '15/9' parses to September 15 of the current/next year."""
    result = resolve_date_hint("15/9", NOW_VN)
    assert result.start.day == 15 and result.start.month == 9


# ---- TIME-25: resolve_date_hint requires aware reference_now ---------------
def test_TIME25_naive_reference_now_raises():
    """Contract: resolve_date_hint raises ValueError if reference_now is naive."""
    with pytest.raises(ValueError):
        resolve_date_hint("hôm nay", datetime(2026, 9, 7, 10, 0))


# ---- TIME-26: EventDomain raises for DEADLINE with non-zero duration -------
def test_TIME26_deadline_nonzero_duration_raises():
    """Contract: DEADLINE EventDomain with start != end raises ValueError."""
    t = vn(10)
    with pytest.raises(ValueError, match="DEADLINE"):
        EventDomain(
            id=1, owner_id=1, title="x",
            start_time=t, end_time=t + timedelta(hours=1),
            kind=EventKind.DEADLINE, source=EventSource.IMPORTED,
        )


# ---- TIME-27: EventDomain DEADLINE blocks_availability is False ------------
def test_TIME27_deadline_does_not_block_availability():
    """Contract: DEADLINE EventDomain.blocks_availability returns False."""
    t = vn(23, 59)
    d = EventDomain(
        id=1, owner_id=1, title="deadline",
        start_time=t, end_time=t,
        kind=EventKind.DEADLINE, source=EventSource.IMPORTED,
    )
    assert not d.blocks_availability
    assert d.is_deadline


# ---- TIME-28: Non-deadline event with duration blocks availability ---------
def test_TIME28_class_event_blocks_availability():
    """Contract: CLASS event with positive duration blocks_availability=True."""
    ev = EventDomain(
        id=1, owner_id=1, title="Math",
        start_time=vn(8), end_time=vn(10),
        kind=EventKind.CLASS, source=EventSource.IMPORTED,
        is_hard=True,
    )
    assert ev.blocks_availability is True


# ---- TIME-29: DB timestamps in ISO 8601 +07:00 format in API responses ----
def test_TIME29_api_timestamps_in_vn_tz(client, alice):
    """Contract: event timestamps in API responses end with +07:00."""
    from conftest import class_row
    res = client.post(
        "/api/v1/ingestion/commit",
        headers=alice.h,
        json={"import_batch_id": "tz_test",
              "resolved_rows": [class_row(first="2026-09-07", last="2026-09-07")]},
    )
    events = res.json().get("events", [])
    for ev in events:
        assert ev["start_time"].endswith("+07:00"), f"Bad TZ: {ev['start_time']}"
        assert ev["end_time"].endswith("+07:00"), f"Bad TZ: {ev['end_time']}"


# ---- TIME-30: 15-min grid checked on manual event creation ----------------
def test_TIME30_manual_event_non_grid_start_rejected(client, alice):
    """Contract: slot_start not on 15-min grid returns 422 from /proposals/manual."""
    start = datetime(2026, 11, 20, 14, 7, tzinfo=VN_TZ)  # :07 is not on grid
    end = datetime(2026, 11, 20, 16, 0, tzinfo=VN_TZ)
    res = client.post(
        "/api/v1/proposals/manual",
        headers=alice.h,
        json={
            "title": "Invalid Grid Event",
            "duration_minutes": 60,
            "slot_start": start.isoformat(),
            "slot_end": end.isoformat(),
        },
    )
    assert res.status_code == 422
