"""
QA: latency benchmark of the pure functions (no MySQL, no FastAPI, no LLM).

Measures p50 / p95 / p99 (nearest-rank percentiles) at several input sizes, and the growth exponent
(slope of log(time) vs log(n); ~1 = linear, ~2 = quadratic).

Standard / method : ISO/IEC 25010 "Performance efficiency / Time behaviour", ISO/IEC 25023 measures.
                    Warm-up runs are discarded; the mean is NOT used as the headline figure.
Target            : find_free_slots p95 < 200 ms on 300 events (tests/README.md section 2.4); others are informational.

Run (from sourceCode/BE):
    .venv\\Scripts\\python "../../QA  docs/bench_pure.py"                 # all groups, 100 runs each
    .venv\\Scripts\\python "../../QA  docs/bench_pure.py" --runs 300 --only free_slots crypto
    .venv\\Scripts\\python "../../QA  docs/bench_pure.py" --json bench_results.json
Close other programs and plug the laptop in before measuring; record the hardware printed in the header.
"""
import argparse
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from database import VN_TZ  # noqa: E402
from models import EventDomain, EventKind, EventSource  # noqa: E402
from services.normalizer import normalize_text  # noqa: E402
from services.parser import parse_timetable_content  # noqa: E402
from services.privacy import decrypt_text, encrypt_text  # noqa: E402
from services.search_engine import find_free_slots  # noqa: E402
from services.temporal import resolve_date_hint  # noqa: E402
from services.validator import detect_import_conflicts  # noqa: E402

SLO_FREE_SLOTS_MS = 200.0
BASE = datetime(2026, 9, 7, 0, 0, tzinfo=VN_TZ)  # a Monday
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ)
SLOW_STOP_S = 3.0  # stop growing the input once one call takes longer than this


# ------------------------------------------------------------------ measurement helpers
def percentile(sorted_ms: list[float], p: float) -> float:
    """nearest-rank percentile."""
    k = max(1, math.ceil(p / 100 * len(sorted_ms)))
    return sorted_ms[k - 1]


def measure(fn, runs: int, warmup: int = 5) -> dict:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - t0) / 1e6)
    samples.sort()
    return {"runs": runs, "p50": percentile(samples, 50), "p95": percentile(samples, 95),
            "p99": percentile(samples, 99), "max": samples[-1], "mean": sum(samples) / len(samples)}


def slope(points: list[tuple[int, float]]) -> float | None:
    """least-squares slope of log(p50) vs log(n)."""
    pts = [(math.log(n), math.log(max(t, 1e-6))) for n, t in points if n > 0]
    if len(pts) < 2:
        return None
    mx, my = sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
    den = sum((x - mx) ** 2 for x, _ in pts)
    return sum((x - mx) * (y - my) for x, y in pts) / den if den else None


def hardware() -> dict:
    cpu = platform.processor()
    try:
        cpu = subprocess.run(["wmic", "cpu", "get", "name"], capture_output=True, text=True, timeout=5).stdout.split("\n")[1].strip() or cpu
    except Exception:
        pass
    return {"python": platform.python_version(), "os": platform.platform(), "cpu": cpu, "cores": os.cpu_count()}


# ------------------------------------------------------------------ input generators (fixed seed => reproducible)
def make_events(n: int, seed: int = 1) -> tuple[list[EventDomain], datetime, datetime]:
    """n CLASS events, ~3 per day, so the density stays constant as n grows."""
    rng = random.Random(seed)
    days = max(7, n // 3)
    events = []
    for i in range(n):
        start = BASE + timedelta(days=rng.randrange(days), hours=rng.randint(7, 19), minutes=rng.choice([0, 15, 30, 45]))
        end = start + timedelta(minutes=rng.choice([60, 90, 120, 180]))
        events.append(EventDomain(id=i + 1, owner_id=1, title=f"Mon {i}", start_time=start, end_time=end,
                                  kind=EventKind.CLASS, source=EventSource.IMPORTED, is_hard=True))
    return events, BASE, BASE + timedelta(days=days)


def make_csv(n_rows: int, seed: int = 2) -> str:
    rng = random.Random(seed)
    lines = ["course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind"]
    for i in range(n_rows):
        h = rng.randint(7, 17)
        wd = rng.choice(["MON", "TUE", "WED", "THU", "FRI", "SAT"])
        lines.append(f"CS{i:04d},Mon hoc {i},{wd},{h:02d}:00,{h + 2:02d}:00,A{i % 9}.{i % 20:02d},2026-09-07,2026-12-21,CLASS")
    return "\n".join(lines)


PROMPT_PARTS = ["xếp", "3 tiếng", "làm đồ án CTDL", "tuần này", "không làm buổi tối", "nhé", "😀", "vcl", "gấp", "ngày mai"]


def make_prompt(n_chars: int, seed: int = 3) -> str:
    rng, out = random.Random(seed), ""
    while len(out) < n_chars:
        out += rng.choice(PROMPT_PARTS) + " "
    return out[:n_chars]


# ------------------------------------------------------------------ benchmark groups: name -> (label, sizes, build(n) -> callable)
def build_free_slots(n):
    events, ws, we = make_events(n)
    return lambda: find_free_slots(events, ws, we, 120, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30), min_break_minutes=15)


def build_normalizer(n_chars):
    text = make_prompt(n_chars)
    return lambda: normalize_text(text)


HINTS = ["hôm nay", "ngày mai", "tuần này", "tuần sau", "cuối tuần", "thứ sáu", "thứ 4", "chủ nhật", "25/11", "tháng sau", "sớm", None]


def build_temporal(n_calls):
    return lambda: [resolve_date_hint(HINTS[i % len(HINTS)], NOW) for i in range(n_calls)]


def build_validator(n_rows):
    rows = parse_timetable_content(make_csv(n_rows)).valid_rows
    existing, _, _ = make_events(max(50, n_rows), seed=5)
    return lambda: detect_import_conflicts(rows, existing)


def build_parser(n_rows):
    text = make_csv(n_rows)
    return lambda: parse_timetable_content(text, "bench.csv")


def build_crypto_roundtrip(n_bytes):
    text = "Tiếng Việt có dấu ắằẳẵặ " * (n_bytes // 30 + 1)
    text = text[:n_bytes]
    return lambda: decrypt_text(encrypt_text(text))


GROUPS = {
    "free_slots": ("find_free_slots (n = events)", [50, 300, 500, 5000], build_free_slots),
    "normalizer": ("normalize_text (n = characters)", [50, 200, 500], build_normalizer),
    "temporal": ("resolve_date_hint (n = calls per run)", [1, 50, 500], build_temporal),
    "validator": ("detect_import_conflicts (n = CSV rows, vs max(50,n) existing events)", [10, 50, 200], build_validator),
    "parser": ("parse_timetable_content (n = CSV rows)", [50, 500, 5000], build_parser),
    "crypto": ("encrypt+decrypt round-trip (n = bytes of text)", [1_000, 100_000, 1_000_000], build_crypto_roundtrip),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=100, help="measured runs per size (default 100)")
    ap.add_argument("--only", nargs="*", choices=list(GROUPS), help="run only these groups")
    ap.add_argument("--json", help="also write all results to this JSON file")
    args = ap.parse_args()

    hw = hardware()
    print(f"# bench_pure  {datetime.now():%Y-%m-%d %H:%M}  python={hw['python']}  cpu={hw['cpu']} ({hw['cores']} threads)\n  {hw['os']}")
    results: dict = {"hardware": hw, "runs": args.runs, "groups": {}}
    exit_code = 0

    for key, (label, sizes, build) in GROUPS.items():
        if args.only and key not in args.only:
            continue
        print(f"\n## {label}")
        print(f"{'n':>9} {'p50 ms':>10} {'p95 ms':>10} {'p99 ms':>10} {'max ms':>10}")
        rows, pts = [], []
        for n in sizes:
            try:
                fn = build(n)
                runs = args.runs if n <= 500 or key == "crypto" else max(20, args.runs // 5)
                m = measure(fn, runs)
            except Exception as exc:  # report and continue: a crash is itself a finding
                print(f"{n:>9}  ERROR {type(exc).__name__}: {str(exc)[:80]}")
                rows.append({"n": n, "error": f"{type(exc).__name__}: {exc}"})
                continue
            print(f"{n:>9} {m['p50']:>10.3f} {m['p95']:>10.3f} {m['p99']:>10.3f} {m['max']:>10.3f}")
            rows.append({"n": n, **m})
            pts.append((n, m["p50"]))
            if m["p50"] / 1000 > SLOW_STOP_S:
                print(f"{'':>9} (stopped growing: one call exceeds {SLOW_STOP_S:.0f} s)")
                break
        s = slope(pts)
        if s is not None:
            print(f"  growth exponent (log-log slope of p50): {s:.2f}")
        results["groups"][key] = {"label": label, "rows": rows, "growth_exponent": s}

        if key == "free_slots":
            r300 = next((r for r in rows if r.get("n") == 300 and "p95" in r), None)
            if r300:
                ok = r300["p95"] < SLO_FREE_SLOTS_MS
                print(f"  SLO check: p95 at 300 events = {r300['p95']:.2f} ms  (limit {SLO_FREE_SLOTS_MS:.0f} ms)  -> {'PASS' if ok else 'FAIL'}")
                results["groups"][key]["slo_pass"] = ok
                exit_code |= 0 if ok else 1
        if key == "crypto":
            big = next((r for r in rows if r.get("n") == 1_000_000 and "p50" in r), None)
            if big:
                print(f"  throughput at 1 MB: ~{(2 * 1_000_000 / 1e6) / (big['p50'] / 1000):.1f} MB/s (encrypt + decrypt, p50)")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nresults written to {args.json}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
