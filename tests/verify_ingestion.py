"""
Standalone verification script for routers/ingestion.py
Tests the core logic functions WITHOUT needing a live FastAPI server.

Run from: sourceCode/BE/
    python tests/verify_ingestion.py
"""
import sys
from pathlib import Path

# Add the BE directory to sys.path
BE_DIR = Path(__file__).resolve().parent.parent / "sourceCode" / "BE"
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from datetime import date, time

from models import CsvRowKind, ParsedCsvRow, Weekday
from routers.ingestion import (
    CorrectedRowPayload,
    ParsedCsvRowSchema,
    ResolvePreviewRequest,
    _corrected_payload_to_csv_line,
    _domain_to_schema,
    _revalidate_corrected_rows,
    _schema_to_domain,
)
from services.parser import parse_timetable_content, export_valid_rows_to_csv

print("=" * 60)
print("  Ingestion Router Verification Suite")
print("=" * 60)

# ----------------------------------------------------------------
# Test 1: _domain_to_schema round-trip
# ----------------------------------------------------------------
print("\n[Test 1] _domain_to_schema: domain dataclass -> Pydantic schema")

sample_domain = ParsedCsvRow(
    line_number=2,
    course_code="CSC10001",
    title="Nhap mon lap trinh",
    kind=CsvRowKind.CLASS,
    start_time=time(7, 30),
    end_time=time(11, 0),
    first_date=date(2026, 9, 1),
    last_date=date(2026, 12, 15),
    weekday=Weekday.MON,
    room="C32",
)

schema = _domain_to_schema(sample_domain)
assert schema.course_code == "CSC10001"
assert schema.start_time == "07:30"
assert schema.weekday == "MON"
assert schema.kind == "CLASS"
print("  PASS: domain -> schema conversion correct")

# ----------------------------------------------------------------
# Test 2: _schema_to_domain round-trip
# ----------------------------------------------------------------
print("\n[Test 2] _schema_to_domain: Pydantic schema -> domain dataclass")

back_to_domain = _schema_to_domain(schema)
assert back_to_domain.course_code == "CSC10001"
assert back_to_domain.start_time == time(7, 30)
assert back_to_domain.weekday == Weekday.MON
assert back_to_domain.kind == CsvRowKind.CLASS
print("  PASS: schema -> domain conversion correct")

# ----------------------------------------------------------------
# Test 3: _corrected_payload_to_csv_line
# ----------------------------------------------------------------
print("\n[Test 3] _corrected_payload_to_csv_line: payload -> CSV line string")

corrected = CorrectedRowPayload(
    line_number=5,
    course_code="CSC10002",
    title="Cau truc du lieu",
    kind="CLASS",
    start_time="07:30",
    end_time="09:30",
    first_date="2026-09-01",
    last_date="2026-12-15",
    weekday="WED",
    room="A101",
)

csv_line = _corrected_payload_to_csv_line(corrected)
assert "CSC10002" in csv_line
assert "07:30" in csv_line
assert "WED" in csv_line
print(f"  PASS: Generated CSV line: {csv_line}")

# ----------------------------------------------------------------
# Test 4: _revalidate_corrected_rows — happy path
# ----------------------------------------------------------------
print("\n[Test 4] _revalidate_corrected_rows: valid corrections accepted")

valid_correction = CorrectedRowPayload(
    line_number=3,
    course_code="MAT101",
    title="Giai tich 1",
    kind="CLASS",
    start_time="07:30",
    end_time="09:30",
    first_date="2026-09-01",
    last_date="2026-12-15",
    weekday="THU",
    room="B202",
)

accepted, still_invalid = _revalidate_corrected_rows([valid_correction])
assert len(accepted) == 1
assert len(still_invalid) == 0
assert accepted[0].course_code == "MAT101"
print("  PASS: Valid corrected row accepted successfully")

# ----------------------------------------------------------------
# Test 5: _revalidate_corrected_rows — user corrects wrongly again
# ----------------------------------------------------------------
print("\n[Test 5] _revalidate_corrected_rows: still-invalid correction isolated")

bad_correction = CorrectedRowPayload(
    line_number=7,
    course_code="ERR001",
    title="Van con sai",
    kind="CLASS",        # CLASS requires weekday
    start_time="10:00",
    end_time="08:00",    # end < start — still invalid!
    first_date="2026-09-01",
    last_date="2026-12-15",
    weekday="MON",
    room="",
)

accepted_bad, still_invalid_bad = _revalidate_corrected_rows([bad_correction])
assert len(accepted_bad) == 0
assert len(still_invalid_bad) == 1
assert still_invalid_bad[0].error_code == "INVALID_TIME_RANGE"
print(f"  PASS: Still-invalid row isolated with code '{still_invalid_bad[0].error_code}'")

# ----------------------------------------------------------------
# Test 6: Full resolve-preview logic simulation (no HTTP server needed)
# ----------------------------------------------------------------
print("\n[Test 6] Full resolve-preview logic simulation")

# Simulate parse-preview output
raw_content = """course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
CSC10001,Nhap mon lap trinh,MON,07:30,11:00,C32,2026-09-01,2026-12-15,CLASS
ERR_TIME,Sai gio hoc,TUE,10:00,08:00,A01,2026-09-01,2026-12-15,CLASS
CSC10003,Thi cuoi ky,,09:00,11:00,F201,2026-12-20,2026-12-20,EXAM
DL000001,Nop bao cao,,23:59,23:59,,2026-11-30,2026-11-30,DEADLINE
GARBAGE_LINE,Ghi chu rac ruo,,,,,,,
"""
batch = parse_timetable_content(raw_content, "schedule.csv")
assert len(batch.valid_rows) == 3   # CSC10001, CSC10003, DL000001
assert len(batch.invalid_rows) == 2  # ERR_TIME, GARBAGE_LINE

# User confirms valid rows unchanged
valid_schemas = [_domain_to_schema(r) for r in batch.valid_rows]

# User corrects ERR_TIME: fixes end_time to 11:00
fixed_correction = CorrectedRowPayload(
    line_number=3,  # original line number from the file
    course_code="ERR_TIME",
    title="Sai gio hoc",
    kind="CLASS",
    start_time="08:00",
    end_time="10:00",   # now corrected
    first_date="2026-09-01",
    last_date="2026-12-15",
    weekday="TUE",
    room="A01",
)

# User skips the garbage line (line 6 = GARBAGE_LINE)
# Find the actual line number of the garbage row
garbage_line_number = batch.invalid_rows[1].line_number

reaccepted, still_bad = _revalidate_corrected_rows([fixed_correction])
assert len(reaccepted) == 1
assert len(still_bad) == 0
assert reaccepted[0].course_code == "ERR_TIME"

# Merge: original valid + re-validated corrected, skipping garbage
corrected_line_numbers = {r.line_number for r in reaccepted}
skip_set = {garbage_line_number}

confirmed_original = [
    _schema_to_domain(s) for s in valid_schemas
    if s.line_number not in skip_set and s.line_number not in corrected_line_numbers
]

all_clean = sorted(confirmed_original + reaccepted, key=lambda r: r.line_number)
exported = export_valid_rows_to_csv(all_clean)

assert len(all_clean) == 4   # CSC10001, ERR_TIME(fixed), CSC10003, DL000001
assert "ERR_TIME" in exported
assert "GARBAGE_LINE" not in exported
print(f"  PASS: Final clean rows = {len(all_clean)}, CSV exported ({len(exported)} chars)")
print(f"  Row order: {[r.course_code for r in all_clean]}")

print("\n" + "=" * 60)
print("  [SUCCESS] All 6 verification tests passed!")
print("=" * 60)
