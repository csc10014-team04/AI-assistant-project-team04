"""
QA: accuracy of services.proposals.split_task (greedy recursive task splitting, P2-4).

Standard / method : ISO/IEC/IEEE 29119-4 (boundary value + equivalence partitioning) and property-based testing
                    (fixed-seed random instances, so every run is reproducible).
Run               : cd sourceCode/BE && .venv\\Scripts\\python -m pytest "../../QA  docs/test_split_task.py" -v -s
No MySQL / FastAPI / LLM needed: split_task is a pure function over TimeSlot lists.

Parameter mapping: remaining = task duration (minutes), cap = max_block (minutes per piece), gaps = free gaps.
"""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from database import VN_TZ  # noqa: E402
from models import TimeSlot  # noqa: E402
from services.proposals import MAX_PIECES, MIN_BLOCK_MIN, split_task  # noqa: E402

BASE = datetime(2026, 10, 19, 8, 0, tzinfo=VN_TZ)  # a Monday, on the 15-minute grid
N_RANDOM = 3000  # random instances per property (cap of the statistical claim: 0 failures in 3000 => rate < 0.1%)


def gap(start_min: int, length_min: int) -> TimeSlot:
    s = BASE + timedelta(minutes=start_min)
    return TimeSlot(s, s + timedelta(minutes=length_min))


def minutes(slots: list[TimeSlot]) -> list[int]:
    return [s.duration_minutes() for s in slots]


def random_instance(rng: random.Random) -> tuple[list[TimeSlot], int, int]:
    """1-6 disjoint gaps on the 15-minute grid, remaining 15..720, cap 30..240 (all multiples of 15)."""
    cursor, gaps = 0, []
    for _ in range(rng.randint(1, 6)):
        cursor += rng.randint(1, 16) * 15  # busy time before the gap
        length = rng.randint(1, 24) * 15
        gaps.append(gap(cursor, length))
        cursor += length
    return gaps, rng.randint(1, 48) * 15, rng.randint(2, 16) * 15


def inside_a_gap(piece: TimeSlot, gaps: list[TimeSlot]) -> bool:
    return any(g.start <= piece.start and piece.end <= g.end for g in gaps)


# ---------------------------------------------------------------- hand-made cases with known answers
class TestKnownAnswers:
    def test_zero_remaining_returns_empty(self):
        assert split_task([gap(0, 120)], 0, 120) == []

    def test_fits_in_one_gap_single_piece(self):
        out = split_task([gap(0, 180)], 120, 240)
        assert out is not None and minutes(out) == [120] and out[0].start == BASE

    def test_cap_forces_two_pieces_from_one_gap(self):
        out = split_task([gap(0, 240)], 180, 90)
        assert out is not None and sum(minutes(out)) == 180 and max(minutes(out)) <= 90

    def test_two_small_gaps_are_combined(self):
        out = split_task([gap(0, 60), gap(120, 60)], 120, 120)
        assert out is not None and minutes(out) == [60, 60]

    def test_pieces_come_back_in_time_order(self):
        out = split_task([gap(300, 60), gap(0, 60), gap(120, 60)], 180, 60)
        assert out is not None and [p.start for p in out] == sorted(p.start for p in out)

    def test_not_enough_free_time_returns_none(self):
        assert split_task([gap(0, 60), gap(120, 30)], 120, 120) is None

    def test_no_gaps_returns_none(self):
        assert split_task([], 60, 120) is None

    def test_gap_shorter_than_min_block_is_unusable(self):
        assert split_task([gap(0, 15)], 60, 120) is None

    def test_gap_length_not_multiple_of_15_is_floored(self):
        out = split_task([gap(0, 50)], 45, 120)  # 50 minutes -> room 45
        assert out is not None and sum(minutes(out)) == 45

    def test_exactly_max_pieces_is_allowed(self):
        gaps = [gap(i * 120, 30) for i in range(MAX_PIECES)]
        out = split_task(gaps, 30 * MAX_PIECES, 30)
        assert out is not None and len(out) == MAX_PIECES

    def test_more_than_max_pieces_returns_none(self):
        gaps = [gap(i * 120, 30) for i in range(MAX_PIECES + 1)]
        assert split_task(gaps, 30 * (MAX_PIECES + 1), 30) is None

    def test_does_not_mutate_input(self):
        gaps = [gap(0, 60), gap(120, 60)]
        before = list(gaps)
        split_task(gaps, 90, 60)
        assert gaps == before

    def test_deterministic(self):
        gaps = [gap(0, 120), gap(180, 90)]
        assert split_task(gaps, 150, 60) == split_task(gaps, 150, 60)

    def test_leaves_usable_last_piece_instead_of_sliver(self):
        # 105 = 90 + 15 would leave a 15-minute sliver; the algorithm shortens the first piece to 75 -> 75 + 30
        out = split_task([gap(0, 240)], 105, 90)
        assert out is not None and sorted(minutes(out)) == [30, 75]


# ---------------------------------------------------------------- behaviour that does NOT match the docstring literally
class TestCharacterization:
    def test_trailing_sliver_below_min_block_can_remain(self):
        """
        Documented finding: the docstring says a trailing piece smaller than min_block is avoided, but when the
        first piece cannot be shortened (size - shortfall < min_block) a 15-minute piece is still returned.
        remaining=45, cap=30 -> [30, 15]. Decide with the PIC whether this is accepted behaviour.
        """
        out = split_task([gap(0, 240)], 45, 30)
        assert out is not None
        assert sorted(minutes(out)) == [15, 30]
        assert min(minutes(out)) < MIN_BLOCK_MIN


# ---------------------------------------------------------------- property tests on random instances
@pytest.fixture(scope="module")
def cases():
    rng = random.Random(20261117)
    out = []
    for _ in range(N_RANDOM):
        gaps, remaining, cap = random_instance(rng)
        out.append((gaps, remaining, cap, split_task(gaps, remaining, cap)))
    return out


class TestInvariants:
    def test_total_duration_equals_task_duration(self, cases):
        bad = [c for c in cases if c[3] is not None and sum(minutes(c[3])) != c[1]]
        assert not bad, f"{len(bad)} instances: total != remaining"

    def test_no_piece_exceeds_max_block(self, cases):
        bad = [c for c in cases if c[3] is not None and max(minutes(c[3]), default=0) > c[2]]
        assert not bad, f"{len(bad)} instances: piece > cap"

    def test_every_piece_lies_inside_a_free_gap(self, cases):
        bad = [c for c in cases if c[3] is not None and not all(inside_a_gap(p, c[0]) for p in c[3])]
        assert not bad, f"{len(bad)} instances: piece outside free time"

    def test_pieces_never_overlap_each_other(self, cases):
        for gaps, _, _, out in cases:
            if out:
                for a, b in zip(out, out[1:]):
                    assert a.end <= b.start

    def test_pieces_sorted_and_at_most_max_pieces(self, cases):
        for _, _, _, out in cases:
            if out:
                assert len(out) <= MAX_PIECES
                assert [p.start for p in out] == sorted(p.start for p in out)

    def test_pieces_on_15_minute_grid(self, cases):
        for _, _, _, out in cases:
            for p in out or []:
                assert p.is_aligned_to_step(15)

    def test_at_most_one_piece_below_min_block(self, cases):
        for _, _, _, out in cases:
            if out:
                assert sum(1 for m in minutes(out) if m < MIN_BLOCK_MIN) <= 1

    def test_failure_report(self, cases):
        """always passes; prints the share of instances where no schedule was returned (see completeness below)."""
        none_rate = sum(1 for c in cases if c[3] is None) / len(cases)
        print(f"\n[split_task] instances={len(cases)}  returned None={none_rate:.1%}")


# ---------------------------------------------------------------- completeness against an exhaustive oracle
def oracle_feasible(gaps: list[TimeSlot], remaining: int, cap: int) -> bool:
    """
    exact feasibility ignoring min_block: dynamic programming over gaps (units of 15 min).
    placing x units in one gap costs ceil(x / cap_units) pieces; feasible when remaining can be placed with <= MAX_PIECES.
    """
    u, cap_u = remaining // 15, max(1, cap // 15)
    INF = 10**9
    best = [0] + [INF] * u  # best[r] = fewest pieces to place r units so far
    for g in gaps:
        room = g.duration_minutes() // 15
        nxt = best[:]
        for r in range(u + 1):
            if best[r] >= INF:
                continue
            for x in range(1, min(room, u - r) + 1):
                cost = best[r] + -(-x // cap_u)
                if cost < nxt[r + x]:
                    nxt[r + x] = cost
        best = nxt
    return best[u] <= MAX_PIECES


class TestCompleteness:
    def test_never_invents_a_schedule_when_infeasible(self):
        rng = random.Random(7)
        for _ in range(N_RANDOM):
            gaps, remaining, cap = random_instance(rng)
            if split_task(gaps, remaining, cap) is not None:
                assert oracle_feasible(gaps, remaining, cap)

    def test_completeness_rate_is_reported_and_high(self):
        """
        share of feasible instances for which the greedy algorithm finds a schedule. The greedy algorithm is not
        guaranteed to be optimal (it also honours min_block, which the oracle ignores), so we report the rate and
        only fail below 90%. Quote the printed number with its Wilson interval in the report.
        """
        rng = random.Random(11)
        feasible = found = 0
        for _ in range(N_RANDOM):
            gaps, remaining, cap = random_instance(rng)
            if oracle_feasible(gaps, remaining, cap):
                feasible += 1
                found += split_task(gaps, remaining, cap) is not None
        rate = found / feasible
        print(f"\n[split_task] completeness: {found}/{feasible} = {rate:.1%} of feasible instances solved")
        assert feasible > 500, "random generator produced too few feasible instances"
        assert rate >= 0.90
