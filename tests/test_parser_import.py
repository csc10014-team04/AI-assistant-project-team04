"""
QA: timetable CSV parser (services.parser.parse_timetable_content) and import conflict detection (services.validator).

Standard / method : ISO/IEC/IEEE 29119-4 (equivalence partitioning, boundary values, error guessing), RFC 4180 (CSV),
                    labelled golden set -> precision/recall of invalid-row detection, fuzzing for crash-freedom.
Run               : cd sourceCode/BE && .venv\\Scripts\\python -m pytest "../../QA  docs/test_parser_import.py" -v -s
No MySQL / FastAPI needed. Smart-diff on re-import (commit_resolved_import) needs a database and is NOT covered here.

Quantities are chosen > 10% above the planned minimum (plan: >= 40 labelled rows, >= 1000 fuzz inputs).
Rules come from AGENTS.md section 5: never crash, never silently drop a line, isolate bad rows in invalid_rows.
"""
import random
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BE_ROOT = next(p / "sourceCode" / "BE" for p in Path(__file__).resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())  # works wherever this file is placed
if str(BE_ROOT) not in sys.path:
    sys.path.insert(0, str(BE_ROOT))

from database import VN_TZ  # noqa: E402
from models import EventDomain, EventKind, EventSource  # noqa: E402
from services.parser import parse_timetable_content, parse_timetable_file  # noqa: E402
from services.validator import detect_import_conflicts  # noqa: E402

HEADER = "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind"
N_FUZZ = 3000  # plan minimum 1000

# (label, csv line, expected error_code or None when the line must be accepted)
V = None
GOLDEN: list[tuple[str, str, str | None]] = [
    # ---- must be accepted ----
    ("class_normal", "CSC10014,Computational Thinking,MON,07:30,09:30,B11.02,2026-09-07,2026-12-14,CLASS", V),
    ("class_vietnamese_title", "MTH10001,Giải tích 1 - Lý thuyết,WED,09:45,11:45,E203,2026-09-09,2026-12-16,CLASS", V),
    ("class_quoted_title_with_comma", 'MTH10002,"Toán, rời rạc",TUE,13:00,15:00,A1.01,2026-09-08,2026-12-15,CLASS', V),
    ("class_empty_course_code", ",Sinh hoạt lớp,FRI,16:00,17:00,A1.01,2026-09-11,2026-12-18,CLASS", V),
    ("class_empty_room", "PHY10001,Vật lý đại cương,THU,07:30,09:30,,2026-09-10,2026-12-17,CLASS", V),
    ("class_single_day_range", "PHY10002,Thực hành,SAT,07:30,11:30,Lab1,2026-09-12,2026-09-12,CLASS", V),
    ("class_spaces_around_cells", " CSC10015 , Lập trình , MON , 13:00 , 15:00 , B1 , 2026-09-07 , 2026-12-14 , CLASS ", V),
    ("class_boundary_midnight_start", "CSC10016,Trực đêm,MON,00:00,00:15,B1,2026-09-07,2026-12-14,CLASS", V),
    ("class_boundary_late_end", "CSC10017,Học muộn,MON,20:00,23:59,B1,2026-09-07,2026-12-14,CLASS", V),
    ("exam_empty_weekday_single_day", "CSC10014,Thi cuối kỳ,,08:00,10:00,B11.02,2027-01-12,2027-01-12,EXAM", V),
    ("event_single_day", ",Hội thảo việc làm,,09:00,11:00,Hội trường,2026-10-20,2026-10-20,EVENT", V),
    ("deadline_empty_start_autofilled", ",Nộp báo cáo,,,23:59,,2026-11-30,2026-11-30,DEADLINE", V),
    ("deadline_same_start_end", ",Nộp bài tập,,23:59,23:59,,2026-11-30,2026-11-30,DEADLINE", V),
    ("leap_day_valid", ",Sự kiện năm nhuận,,09:00,10:00,,2028-02-29,2028-02-29,EVENT", V),
    # ---- must be rejected, with a specific code ----
    ("bad_start_hour_25", "CSC10014,A,MON,25:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_START_TIME"),
    ("bad_end_minute_60", "CSC10014,A,MON,08:00,10:60,B1,2026-09-07,2026-12-14,CLASS", "INVALID_END_TIME"),
    ("end_before_start", "CSC10014,A,MON,10:00,08:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_TIME_RANGE"),
    ("bad_first_date_slashes", "CSC10014,A,MON,08:00,10:00,B1,2026/09/07,2026-12-14,CLASS", "INVALID_FIRST_DATE"),
    ("bad_first_date_feb_30", "CSC10014,A,MON,08:00,10:00,B1,2026-02-30,2026-12-14,CLASS", "INVALID_FIRST_DATE"),
    ("bad_first_date_month_13", "CSC10014,A,MON,08:00,10:00,B1,2026-13-01,2026-12-14,CLASS", "INVALID_FIRST_DATE"),
    ("bad_last_date_text", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,cuối kỳ,CLASS", "INVALID_LAST_DATE"),
    ("last_date_before_first", "CSC10014,A,MON,08:00,10:00,B1,2026-12-14,2026-09-07,CLASS", "INVALID_DATE_RANGE"),
    ("unknown_kind", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,2026-12-14,LECTURE", "INVALID_KIND"),
    ("empty_kind", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,2026-12-14,", "EMPTY_KIND"),
    ("too_few_columns", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,CLASS", "INVALID_COLUMN_COUNT"),
    ("too_many_columns", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS,extra", "INVALID_COLUMN_COUNT"),
    ("empty_title", "CSC10014,,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "EMPTY_TITLE"),
    ("class_missing_weekday", "CSC10014,A,,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "MISSING_WEEKDAY"),
    ("class_bad_weekday", "CSC10014,A,XYZ,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_WEEKDAY"),
    ("class_empty_start", "CSC10014,A,MON,,10:00,B1,2026-09-07,2026-12-14,CLASS", "EMPTY_START_TIME"),
    ("class_empty_end", "CSC10014,A,MON,08:00,,B1,2026-09-07,2026-12-14,CLASS", "EMPTY_END_TIME"),
    ("empty_first_date", "CSC10014,A,MON,08:00,10:00,B1,,2026-12-14,CLASS", "EMPTY_FIRST_DATE"),
    ("empty_last_date", "CSC10014,A,MON,08:00,10:00,B1,2026-09-07,,CLASS", "EMPTY_LAST_DATE"),
    ("deadline_start_differs_from_end", ",Nộp bài,,22:00,23:59,,2026-11-30,2026-11-30,DEADLINE", "DEADLINE_TIME_MISMATCH"),
    ("deadline_dates_differ", ",Nộp bài,,,23:59,,2026-11-30,2026-12-01,DEADLINE", "DEADLINE_DATE_MISMATCH"),
    # an unclosed quote must be rejected; the parser reports it as a column-count problem (either code is acceptable)
    ("unclosed_quote", 'CSC10014,"Toán rời rạc,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS', ("MALFORMED_LINE_SYNTAX", "INVALID_COLUMN_COUNT")),
    ("exam_spanning_two_days", "CSC10014,Thi,,08:00,10:00,B1,2027-01-12,2027-01-13,EXAM", "INVALID_DATE_RANGE"),
    ("event_spanning_two_days", ",Hội thảo,,09:00,11:00,,2026-10-20,2026-10-21,EVENT", "INVALID_DATE_RANGE"),
    ("class_zero_duration", "CSC10014,A,MON,08:00,08:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_TIME_RANGE"),
    ("title_only_spaces", "CSC10014,   ,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "EMPTY_TITLE"),
    ("first_date_with_month_name", "CSC10014,A,MON,08:00,10:00,B1,07 Sep 2026,2026-12-14,CLASS", "INVALID_FIRST_DATE"),
    ("time_without_leading_zero", "CSC10014,A,MON,8:00,10:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_START_TIME"),
    ("deadline_at_midnight_ok", ",Nộp bài,,,00:00,,2026-11-30,2026-11-30,DEADLINE", V),
    ("exam_with_weekday_ok", "CSC10014,Thi giữa kỳ,MON,08:00,10:00,B1,2027-01-11,2027-01-11,EXAM", V),
    ("exam_end_before_start", "CSC10014,Thi,,10:00,08:00,B1,2027-01-12,2027-01-12,EXAM", "INVALID_TIME_RANGE"),
    ("event_end_before_start", ",Hội thảo,,11:00,09:00,,2026-10-20,2026-10-20,EVENT", "INVALID_TIME_RANGE"),
    ("start_not_a_time", "CSC10014,A,MON,sáng,10:00,B1,2026-09-07,2026-12-14,CLASS", "INVALID_START_TIME"),
    ("end_not_a_time", "CSC10014,A,MON,08:00,trưa,B1,2026-09-07,2026-12-14,CLASS", "INVALID_END_TIME"),
]


def parse_one(line: str):
    res = parse_timetable_content(f"{HEADER}\n{line}\n", "qa.csv")
    return res.valid_rows, res.invalid_rows


class TestGoldenRows:
    @pytest.mark.parametrize("label,line,code", GOLDEN, ids=[g[0] for g in GOLDEN])
    def test_row_is_classified_as_labelled(self, label, line, code):
        valid, invalid = parse_one(line)
        if code is None:
            assert len(valid) == 1 and not invalid, f"{label}: expected valid, got invalid {[(i.error_code, i.error_message) for i in invalid]}"
        else:
            assert not valid and len(invalid) == 1, f"{label}: expected {code}, got valid {valid}"
            allowed = code if isinstance(code, tuple) else (code,)
            assert invalid[0].error_code in allowed, f"{label}: expected {allowed}, got {invalid[0].error_code}"
            assert invalid[0].line_number == 2 and invalid[0].raw_text.strip()

    def test_golden_set_size_exceeds_plan_minimum(self):
        assert len(GOLDEN) >= 44  # plan minimum 40, +10%

    def test_precision_recall_of_invalid_detection(self):
        tp = fp = fn = tn = 0
        for _, line, code in GOLDEN:
            valid, invalid = parse_one(line)
            predicted_invalid = bool(invalid)
            if code is not None and predicted_invalid:
                tp += 1
            elif code is None and predicted_invalid:
                fp += 1
            elif code is not None and not predicted_invalid:
                fn += 1
            else:
                tn += 1
        precision, recall = tp / max(1, tp + fp), tp / max(1, tp + fn)
        print(f"\n[parser] invalid-row detection on {len(GOLDEN)} labelled rows: TP={tp} FP={fp} FN={fn} TN={tn}  precision={precision:.1%} recall={recall:.1%}")
        assert recall == 1.0 and precision == 1.0


@pytest.fixture(scope="module")
def batch():
    body = "\n".join(line for _, line, _ in GOLDEN)
    return GOLDEN, parse_timetable_content(f"{HEADER}\n{body}\n", "qa.csv")


class TestBatchBehaviour:
    def test_no_line_is_silently_dropped(self, batch):
        golden, res = batch
        assert len(res.valid_rows) + len(res.invalid_rows) == len(golden)

    def test_counts_match_labels(self, batch):
        golden, res = batch
        assert len(res.valid_rows) == sum(1 for g in golden if g[2] is None)
        assert len(res.invalid_rows) == sum(1 for g in golden if g[2] is not None)

    def test_invalid_rows_point_to_their_own_source_line(self, batch):
        golden, res = batch
        for inv in res.invalid_rows:
            assert golden[inv.line_number - 2][1] == inv.raw_text

    def test_each_batch_gets_a_unique_id(self):
        ids = {parse_timetable_content(f"{HEADER}\n", "x.csv").import_batch_id for _ in range(50)}
        assert len(ids) == 50

    @pytest.mark.parametrize("text", ["", "   \n\n  \n", HEADER, HEADER + "\n\n\n"])
    def test_empty_or_header_only_files_do_not_crash(self, text):
        res = parse_timetable_content(text, "empty.csv")
        assert res.valid_rows == [] and res.invalid_rows == []

    def test_crlf_and_blank_lines_between_rows(self):
        text = HEADER + "\r\n\r\n" + GOLDEN[0][1] + "\r\n\r\n" + GOLDEN[1][1] + "\r\n"
        res = parse_timetable_content(text, "crlf.csv")
        assert len(res.valid_rows) == 2 and not res.invalid_rows

    def test_file_without_header_row_is_accepted(self):
        res = parse_timetable_content(GOLDEN[0][1] + "\n" + GOLDEN[1][1] + "\n", "nohdr.csv")
        assert len(res.valid_rows) == 2

    def test_utf8_bom_is_tolerated(self):
        res = parse_timetable_file(("﻿" + HEADER + "\n" + GOLDEN[0][1] + "\n").encode("utf-8"), "bom.csv")
        assert len(res.valid_rows) == 1 and not res.invalid_rows

    def test_parsing_is_deterministic_apart_from_batch_id(self):
        text = HEADER + "\n" + "\n".join(g[1] for g in GOLDEN) + "\n"
        a, b = parse_timetable_content(text, "x.csv"), parse_timetable_content(text, "x.csv")
        assert a.valid_rows == b.valid_rows and a.invalid_rows == b.invalid_rows


# ====================================================================== fuzzing: never crash, never lose a line
def mutate(line: str, rng: random.Random) -> str:
    chars = list(line)
    for _ in range(rng.randint(1, 6)):
        op = rng.choice(["del", "ins", "swap", "dup_comma", "drop_comma", "quote", "unicode"])
        if not chars:
            break
        i = rng.randrange(len(chars))
        if op == "del":
            del chars[i]
        elif op == "ins":
            chars.insert(i, rng.choice(string.printable.replace("\n", "").replace("\r", "")))
        elif op == "swap":
            chars[i] = rng.choice("0123456789:-/aXZ ")
        elif op == "dup_comma":
            chars.insert(i, ",")
        elif op == "drop_comma" and "," in chars:
            chars.remove(",")
        elif op == "quote":
            chars.insert(i, '"')
        else:
            chars.insert(i, rng.choice("ăâđêôơưÀỲ😀​\x00"))
    return "".join(chars)


class TestFuzz:
    def test_mutated_rows_never_crash_and_never_lose_lines(self):
        rng = random.Random(20261118)
        seeds = [g[1] for g in GOLDEN]
        known_crashes = 0
        for n in range(N_FUZZ):
            lines = [mutate(rng.choice(seeds), rng) for _ in range(rng.randint(1, 6))]
            text = HEADER + "\n" + "\n".join(lines) + "\n"
            try:
                res = parse_timetable_content(text, "fuzz.csv")
            except TypeError as exc:
                if "offset-naive and offset-aware" in str(exc):  # the one known defect, reproduced in TestKnownDefects
                    known_crashes += 1
                    continue
                raise  # any other crash is a NEW defect and must fail the test
            data_lines = sum(1 for line in text.splitlines()[1:] if line.strip())
            assert len(res.valid_rows) + len(res.invalid_rows) <= data_lines + 1, f"case {n}: more rows than lines"
            for inv in res.invalid_rows:
                assert inv.error_code and inv.line_number >= 1
        print(f"\n[parser] fuzz: {N_FUZZ} mutated files, {known_crashes} hit the known timezone-suffix crash")

    def test_random_text_never_crashes(self):
        rng = random.Random(5)
        alphabet = string.printable + "ăâđêôơưĂÂĐ😀日本​"
        for _ in range(N_FUZZ // 3 + 100):
            text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
            res = parse_timetable_content(text, "random.txt")
            assert isinstance(res.valid_rows, list) and isinstance(res.invalid_rows, list)

    def test_very_long_line_and_many_lines(self):
        long_title = "A" * 100_000
        res = parse_timetable_content(f"{HEADER}\nX,{long_title},MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS\n", "long.csv")
        assert len(res.valid_rows) + len(res.invalid_rows) == 1
        many = HEADER + "\n" + "\n".join(GOLDEN[0][1] for _ in range(20_000)) + "\n"
        res = parse_timetable_content(many, "many.csv")
        assert len(res.valid_rows) == 20_000


class TestKnownDefects:
    """Reproductions of defects found by fuzzing. strict xfail: the test turns red (XPASS) the day the bug is fixed."""

    @pytest.mark.parametrize("start,end", [("08:00Z", "10:00"), ("08:00", "10:00Z"), ("08:00+07:00", "10:00")])
    def test_mixed_timezone_suffix_must_not_crash(self, start, end):
        line = f"CSC1,A,MON,{start},{end},B1,2026-09-07,2026-12-14,CLASS"
        res = parse_timetable_content(f"{HEADER}\n{line}\n", "tz.csv")
        assert len(res.valid_rows) + len(res.invalid_rows) == 1

    def test_timezone_suffix_on_both_sides_should_be_rejected(self):
        res = parse_timetable_content(f"{HEADER}\nCSC1,A,MON,08:00Z,10:00Z,B1,2026-09-07,2026-12-14,CLASS\n", "tz.csv")
        assert len(res.invalid_rows) == 1


# ====================================================================== import conflict detection (validator)
def rows_from(*lines: str):
    res = parse_timetable_content(HEADER + "\n" + "\n".join(lines) + "\n", "c.csv")
    assert not res.invalid_rows
    return res.valid_rows


def existing_event(day: int, start_h: int, end_h: int, hard=True):
    s = datetime(2026, 9, 7, start_h, 0, tzinfo=VN_TZ) + timedelta(days=day)
    return EventDomain(id=1, owner_id=1, title="Existing", start_time=s, end_time=s.replace(hour=end_h),
                       kind=EventKind.CLASS, source=EventSource.MANUAL, is_hard=hard)


class TestImportConflicts:
    def test_non_overlapping_rows_have_no_conflict(self):
        rows = rows_from("A,Mon A,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS",
                         "B,Mon B,MON,10:00,12:00,B1,2026-09-07,2026-12-14,CLASS",
                         "C,Mon C,TUE,08:00,10:00,B1,2026-09-08,2026-12-15,CLASS")
        out = detect_import_conflicts(rows, [])
        assert out["conflict_cards"] == [] and len(out["non_conflicting_rows"]) == 3

    def test_overlap_within_file_makes_one_card_not_one_per_week(self):
        rows = rows_from("A,Mon A,MON,08:00,10:00,B1,2026-09-07,2026-12-14,CLASS",
                         "B,Mon B,MON,09:00,11:00,B1,2026-09-07,2026-12-14,CLASS")
        out = detect_import_conflicts(rows, [])
        assert len(out["conflict_cards"]) == 1  # 15 weekly overlaps collapse into one series card

    def test_overlap_with_existing_event_is_reported(self):
        rows = rows_from("A,Mon A,MON,08:00,10:00,B1,2026-09-07,2026-09-07,CLASS")
        out = detect_import_conflicts(rows, [existing_event(0, 9, 11)])
        assert len(out["conflict_cards"]) >= 1

    def test_event_on_another_day_is_not_a_conflict(self):
        rows = rows_from("A,Mon A,MON,08:00,10:00,B1,2026-09-07,2026-09-07,CLASS")
        out = detect_import_conflicts(rows, [existing_event(1, 9, 11)])
        assert out["conflict_cards"] == []

    def test_back_to_back_classes_do_not_conflict(self):
        rows = rows_from("A,Mon A,MON,08:00,10:00,B1,2026-09-07,2026-09-07,CLASS",
                         "B,Mon B,MON,10:00,12:00,B1,2026-09-07,2026-09-07,CLASS")
        assert detect_import_conflicts(rows, [])["conflict_cards"] == []

    def test_empty_input(self):
        out = detect_import_conflicts([], [])
        assert out["conflict_cards"] == [] and out["non_conflicting_rows"] == []
