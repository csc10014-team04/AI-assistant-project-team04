"""
QA: accuracy of services.search_engine.find_free_slots (sort-and-sweep free-time engine).

Standard / method : ISO/IEC 25010 Functional correctness; ISO/IEC/IEEE 29119-4 (boundary value, equivalence classes);
                    differential testing against an independent brute-force oracle; metamorphic relations.
Run               : cd sourceCode/BE && .venv\\Scripts\\python -m pytest "../../QA  docs/test_free_slots_accuracy.py" -v -s
No MySQL / FastAPI / LLM needed. (find_user_free_slots reads UserPreference from the DB: not covered here.)

Quantities are chosen > 10% above the planned minimum (plan: >= 20 hand cases, >= 1000 random cases, >= 100 timing runs).
"""
import random
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

import pytest

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from database import UTC_TZ, VN_TZ  # noqa: E402
from models import EventDomain, EventKind, EventSource  # noqa: E402
from services.search_engine import find_free_slots  # noqa: E402

DAY = datetime(2026, 10, 19, 0, 0, tzinfo=VN_TZ)  # Monday 00:00 +07:00
N_RANDOM = 2000  # plan minimum 1000
TIMING_RUNS = 220  # plan minimum 100 (and >10% above the 200 quoted in the report)


def at(h: int, m: int = 0, s: int = 0, day: int = 0) -> datetime:
    return DAY + timedelta(days=day, hours=h, minutes=m, seconds=s)


def ev(start: datetime, end: datetime, kind=EventKind.CLASS, i: int = 1) -> EventDomain:
    return EventDomain(id=i, owner_id=1, title=f"e{i}", start_time=start, end_time=end, kind=kind,
                       source=EventSource.IMPORTED, is_hard=kind in (EventKind.CLASS, EventKind.EXAM))


def run(events, ws, we, dur=60, **kw):
    return [(s.start, s.end) for s in find_free_slots(events, ws, we, dur, **kw)]


W = (at(8), at(18))  # default window 08:00-18:00


# ====================================================================== hand-made cases with known answers (>= 30)
class TestKnownAnswers:
    def test_01_no_events_whole_window(self):
        assert run([], *W) == [(at(8), at(18))]

    def test_02_one_event_in_the_middle(self):
        assert run([ev(at(10), at(11))], *W) == [(at(8), at(10)), (at(11), at(18))]

    def test_03_event_at_window_start(self):
        assert run([ev(at(8), at(9))], *W) == [(at(9), at(18))]

    def test_04_event_at_window_end(self):
        assert run([ev(at(17), at(18))], *W) == [(at(8), at(17))]

    def test_05_event_covers_whole_window(self):
        assert run([ev(at(7), at(19))], *W) == []

    def test_06_event_ends_off_grid_start_rounds_up(self):
        assert run([ev(at(8), at(9, 7))], *W) == [(at(9, 15), at(18))]

    def test_07_event_starts_off_grid_end_rounds_down(self):
        assert run([ev(at(12, 50), at(14))], *W) == [(at(8), at(12, 45)), (at(14), at(18))]

    def test_08_min_break_extends_both_sides(self):
        assert run([ev(at(10), at(11))], *W, min_break_minutes=15) == [(at(8), at(9, 45)), (at(11, 15), at(18))]

    def test_09_overlapping_events_merge(self):
        assert run([ev(at(10), at(11, 30), i=1), ev(at(11), at(12), i=2)], *W) == [(at(8), at(10)), (at(12), at(18))]

    def test_10_touching_events_merge(self):
        assert run([ev(at(10), at(11), i=1), ev(at(11), at(12), i=2)], *W) == [(at(8), at(10)), (at(12), at(18))]

    def test_11_deadline_does_not_block(self):
        assert run([ev(at(12), at(12), EventKind.DEADLINE)], *W) == [(at(8), at(18))]

    @pytest.mark.parametrize("kind", [EventKind.CLASS, EventKind.EXAM, EventKind.EVENT, EventKind.TASK])
    def test_12_every_timed_kind_blocks(self, kind):
        assert run([ev(at(10), at(11), kind)], *W) == [(at(8), at(10)), (at(11), at(18))]

    def test_13_gap_exactly_duration_is_kept(self):
        assert run([ev(at(8), at(9), i=1), ev(at(10), at(18), i=2)], *W, dur=60) == [(at(9), at(10))]

    def test_14_gap_shorter_than_duration_is_dropped(self):
        assert run([ev(at(8), at(9), i=1), ev(at(9, 45), at(18), i=2)], *W, dur=60) == []

    def test_15_sleep_blocks_early_morning(self):
        assert run([], at(5), at(12), sleep_start=dtime(23, 30), sleep_end=dtime(6, 30)) == [(at(6, 30), at(12))]

    def test_16_sleep_across_midnight_window(self):
        got = run([], at(20), at(8, day=1), sleep_start=dtime(23, 30), sleep_end=dtime(6, 30))
        assert got == [(at(20), at(23, 30)), (at(6, 30, day=1), at(8, day=1))]

    def test_17_equal_sleep_times_disable_blocking(self):
        assert run([], *W, sleep_start=dtime(6, 0), sleep_end=dtime(6, 0)) == [(at(8), at(18))]

    def test_18_only_one_sleep_bound_means_no_sleep(self):
        assert run([], *W, sleep_start=dtime(23, 0)) == [(at(8), at(18))]

    @pytest.mark.parametrize("ws,we", [(at(10), at(10)), (at(11), at(10))])
    def test_19_empty_or_inverted_window(self, ws, we):
        assert run([], ws, we) == []

    @pytest.mark.parametrize("dur", [0, -15])
    def test_20_non_positive_duration_raises(self, dur):
        with pytest.raises(ValueError):
            find_free_slots([], *W, dur)

    def test_21_naive_datetime_raises(self):
        with pytest.raises(ValueError):
            find_free_slots([], datetime(2026, 10, 19, 8, 0), at(18), 60)

    def test_22_event_in_utc_window_in_vn(self):
        utc_event = ev(datetime(2026, 10, 19, 3, 0, tzinfo=UTC_TZ), datetime(2026, 10, 19, 4, 0, tzinfo=UTC_TZ))  # 10:00-11:00 VN
        assert run([utc_event], *W) == [(at(8), at(10)), (at(11), at(18))]

    def test_23_event_overlapping_window_start(self):
        assert run([ev(at(7), at(9))], *W) == [(at(9), at(18))]

    def test_24_event_outside_window_ignored(self):
        assert run([ev(at(19), at(20)), ev(at(5), at(6), i=2)], *W) == [(at(8), at(18))]

    def test_25_window_start_off_grid(self):
        assert run([], at(8, 7), at(18)) == [(at(8, 15), at(18))]

    def test_26_window_end_off_grid(self):
        assert run([], at(8), at(17, 55)) == [(at(8), at(17, 45))]

    def test_27_step_30_minutes(self):
        assert run([ev(at(10), at(10, 10))], *W, slot_step_minutes=30) == [(at(8), at(10)), (at(10, 30), at(18))]

    def test_28_break_and_sleep_together(self):
        got = run([ev(at(10), at(11))], at(5), at(12), dur=30, min_break_minutes=15, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30))
        assert got == [(at(6, 30), at(9, 45)), (at(11, 15), at(12))]
        # same calendar with dur=60: the 45-minute tail (11:15-12:00) is too short and must be dropped
        assert run([ev(at(10), at(11))], at(5), at(12), dur=60, min_break_minutes=15, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30)) == [(at(6, 30), at(9, 45))]

    def test_29_duration_longer_than_window(self):
        assert run([], *W, dur=11 * 60) == []

    def test_30_input_order_does_not_matter(self):
        a, b, c = ev(at(9), at(10), i=1), ev(at(12), at(13), i=2), ev(at(15), at(16), i=3)
        assert run([c, a, b], *W) == run([a, b, c], *W)

    def test_31_seconds_on_event_end_round_start_up(self):
        assert run([ev(at(8), at(9, 0, 30))], *W) == [(at(9, 15), at(18))]

    def test_32_zero_length_non_deadline_event_does_not_block(self):
        assert run([ev(at(12), at(12), EventKind.EVENT)], *W) == [(at(8), at(18))]

    def test_33_two_day_window_events_on_both_days(self):
        got = run([ev(at(9), at(10), i=1), ev(at(9, day=1), at(10, day=1), i=2)], at(8), at(12, day=1), dur=60)
        assert got == [(at(8), at(9)), (at(10), at(9, day=1)), (at(10, day=1), at(12, day=1))]

    def test_34_many_back_to_back_events_leave_no_gap(self):
        events = [ev(at(8 + i), at(9 + i), i=i + 1) for i in range(10)]
        assert run(events, *W) == []

    def test_35_big_break_swallows_small_gap(self):
        events = [ev(at(9), at(10), i=1), ev(at(10, 30), at(11), i=2)]
        assert run(events, *W, min_break_minutes=15, dur=15)[0] == (at(8), at(8, 45))


# ====================================================================== brute-force oracle
def _sleeping(minute_of_day: int, s: dtime, e: dtime) -> bool:
    sm, em = s.hour * 60 + s.minute, e.hour * 60 + e.minute
    if sm == em:
        return False
    return (sm <= minute_of_day < em) if sm < em else (minute_of_day >= sm or minute_of_day < em)


def oracle(events, ws, we, dur, brk=0, sleep=None, step=15):
    """walk every grid cell [t, t+step) of the window; a cell is free if it overlaps no (break-extended) event and no sleep minute."""
    delta = timedelta(minutes=brk)
    busy = [(e.start_time - delta, e.end_time + delta) for e in events if e.blocks_availability]
    t = ws.replace(second=0, microsecond=0)
    while (t.minute % step != 0) or t < ws:
        t += timedelta(minutes=1)
    free_cells = []
    while t + timedelta(minutes=step) <= we:
        t2 = t + timedelta(minutes=step)
        free = not any(b0 < t2 and t < b1 for b0, b1 in busy)
        if free and sleep:
            free = not any(_sleeping(((t + timedelta(minutes=k)).astimezone(VN_TZ).hour * 60 + (t + timedelta(minutes=k)).astimezone(VN_TZ).minute), *sleep) for k in range(step))
        free_cells.append((t, t2, free))
        t = t2
    runs, cur = [], None
    for a, b, free in free_cells:
        if free:
            cur = (cur[0], b) if cur else (a, b)
        elif cur:
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    return [r for r in runs if r[1] - r[0] >= timedelta(minutes=dur)]


def random_case(rng: random.Random):
    ws = at(0) + timedelta(days=rng.randint(0, 3), minutes=rng.choice([0, 0, 15, 30, 7, 45, 8 * 60 + 3, 600]))
    we = ws + timedelta(minutes=rng.choice([180, 480, 720, 1440, 2000, 3000]) + rng.choice([0, 0, 5, 11]))
    events = []
    for i in range(rng.randint(0, 25)):
        s = ws + timedelta(minutes=rng.randint(-120, int((we - ws).total_seconds() // 60) + 60), seconds=rng.choice([0, 0, 0, 30]))
        length = rng.choice([0, 15, 30, 45, 60, 90, 120, 180, 240, 20, 50])
        kind = rng.choice([EventKind.CLASS, EventKind.EXAM, EventKind.EVENT, EventKind.TASK, EventKind.DEADLINE])
        if kind == EventKind.DEADLINE:
            length = 0
        events.append(ev(s, s + timedelta(minutes=length), kind, i=i + 1))
    sleep = None
    if rng.random() < 0.4:
        sleep = (dtime(rng.choice([21, 22, 23, 0]), rng.choice([0, 15, 30])), dtime(rng.choice([5, 6, 7]), rng.choice([0, 15, 30, 10])))
    return {"events": events, "ws": ws, "we": we, "dur": rng.choice([15, 30, 60, 90, 120, 180]),
            "brk": rng.choice([0, 0, 5, 15, 30]), "sleep": sleep, "step": rng.choice([15, 15, 15, 30, 10])}


def engine(c):
    kw = {"min_break_minutes": c["brk"], "slot_step_minutes": c["step"]}
    if c["sleep"]:
        kw.update(sleep_start=c["sleep"][0], sleep_end=c["sleep"][1])
    return run(c["events"], c["ws"], c["we"], c["dur"], **kw)


@pytest.fixture(scope="module")
def cases():
    rng = random.Random(20261118)
    return [random_case(rng) for _ in range(N_RANDOM)]


# ====================================================================== differential test and invariants
class TestAgainstOracle:
    def test_engine_equals_brute_force_oracle(self, cases):
        bad = []
        for i, c in enumerate(cases):
            expected = oracle(c["events"], c["ws"], c["we"], c["dur"], c["brk"], c["sleep"], c["step"])
            got = engine(c)
            if got != expected:
                bad.append((i, got[:2], expected[:2]))
        print(f"\n[free_slots] differential: {len(cases) - len(bad)}/{len(cases)} cases identical to the oracle")
        assert not bad, f"{len(bad)} mismatches, first: {bad[0]}"

    def test_all_slots_on_the_step_grid(self, cases):
        for c in cases:
            for a, b in engine(c):
                assert a.second == 0 and b.second == 0
                assert a.minute % c["step"] == 0 and b.minute % c["step"] == 0

    def test_all_slots_inside_window_and_long_enough(self, cases):
        for c in cases:
            for a, b in engine(c):
                assert c["ws"] <= a and b <= c["we"]
                assert b - a >= timedelta(minutes=c["dur"])

    def test_slots_sorted_and_disjoint(self, cases):
        for c in cases:
            got = engine(c)
            for (a1, b1), (a2, b2) in zip(got, got[1:]):
                assert b1 <= a2

    def test_no_slot_overlaps_a_blocking_event(self, cases):
        for c in cases:
            delta = timedelta(minutes=c["brk"])
            for a, b in engine(c):
                for e in c["events"]:
                    if e.blocks_availability:
                        assert not (a < e.end_time + delta and e.start_time - delta < b)

    def test_no_slot_overlaps_sleep_time(self, cases):
        for c in cases:
            if not c["sleep"]:
                continue
            for a, b in engine(c):
                t = a
                while t < b:
                    local = t.astimezone(VN_TZ)
                    assert not _sleeping(local.hour * 60 + local.minute, *c["sleep"])
                    t += timedelta(minutes=1)


# ====================================================================== metamorphic relations
class TestMetamorphic:
    def test_shuffling_events_changes_nothing(self, cases):
        rng = random.Random(3)
        for c in cases[:600]:
            shuffled = dict(c, events=rng.sample(c["events"], len(c["events"])))
            assert engine(shuffled) == engine(c)

    def test_adding_a_deadline_changes_nothing(self, cases):
        for c in cases[:600]:
            mid = c["ws"] + (c["we"] - c["ws"]) / 2
            plus = dict(c, events=[*c["events"], ev(mid, mid, EventKind.DEADLINE, i=999)])
            assert engine(plus) == engine(c)

    def test_adding_an_event_never_adds_free_time(self, cases):
        rng = random.Random(4)
        total = lambda got: sum((b - a).total_seconds() for a, b in got)  # noqa: E731
        for c in cases[:600]:
            s = c["ws"] + timedelta(minutes=rng.randint(0, 600))
            plus = dict(c, events=[*c["events"], ev(s, s + timedelta(minutes=rng.choice([30, 60, 120])), i=998)])
            assert total(engine(plus)) <= total(engine(c))

    def test_duplicate_events_are_idempotent(self, cases):
        for c in cases[:600]:
            dup = dict(c, events=[*c["events"], *c["events"]])
            assert engine(dup) == engine(c)

    def test_longer_required_duration_gives_subset(self, cases):
        for c in cases[:600]:
            longer = dict(c, dur=c["dur"] + 60)
            kept = {s for s in engine(longer)}
            assert kept <= set(engine(c))

    def test_larger_break_never_adds_free_time(self, cases):
        total = lambda got: sum((b - a).total_seconds() for a, b in got)  # noqa: E731
        for c in cases[:600]:
            bigger = dict(c, brk=c["brk"] + 15)
            assert total(engine(bigger)) <= total(engine(c))


# ====================================================================== performance gate (README: < 200 ms on 300 events)
def test_p95_under_200ms_for_300_events():
    rng = random.Random(9)
    events = []
    for i in range(300):
        s = at(rng.randint(7, 19), rng.choice([0, 15, 30, 45]), day=rng.randrange(105))
        events.append(ev(s, s + timedelta(minutes=rng.choice([60, 90, 120])), i=i + 1))
    ws, we = at(0), at(0, day=105)
    for _ in range(10):
        find_free_slots(events, ws, we, 120, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30), min_break_minutes=15)
    samples = []
    for _ in range(TIMING_RUNS):
        t0 = time.perf_counter()
        find_free_slots(events, ws, we, 120, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30), min_break_minutes=15)
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * len(samples)) - 1]
    print(f"\n[free_slots] 300 events, {TIMING_RUNS} runs: p50={samples[len(samples) // 2]:.2f} ms  p95={p95:.2f} ms  max={samples[-1]:.2f} ms")
    assert p95 < 200
