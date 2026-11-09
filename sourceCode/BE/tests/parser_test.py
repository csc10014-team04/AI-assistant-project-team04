import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `services` importable
from services.parser import *  # noqa: F401,F403  (bare `import parser` hit the stdlib module Python 3.10 removed)
# ============================================================================
# SELF-VERIFICATION SUITE (run: python tests/parser_test.py)
# ============================================================================

if __name__ == "__main__":
    import traceback

    total = 0
    failed = 0

    def check(label: str, condition: bool) -> None:
        global total, failed
        total += 1
        if condition:
            print(f"[PASS] {label}")
        else:
            print(f"[FAIL] {label}")
            failed += 1

    # ------------------------------------------------------------------
    # Test 1: Happy-path CSV round-trip (existing test)
    # ------------------------------------------------------------------
    sample_csv = (
        "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
        "CSC101,Intro to CS,MON,08:00,10:00,A101,2024-01-08,2024-05-06,CLASS\n"
        "CSC102,Database,WED,13:00,15:00,B202,2024-01-10,2024-05-08,CLASS\n"
    )
    result1 = parse_timetable_content(sample_csv, "test.csv")
    check("Test 1a: valid_rows count == 2", len(result1.valid_rows) == 2)
    check("Test 1b: no invalid rows", len(result1.invalid_rows) == 0)
    check("Test 1c: batch_id generated", len(result1.import_batch_id) == 16)

    # ------------------------------------------------------------------
    # Test 2: Optional course_code (empty string is allowed)
    # ------------------------------------------------------------------
    no_code_csv = (
        ",Calculus Final,,,15:00,,2024-06-10,2024-06-10,EXAM\n"
        ",Math Final,,,16:00,,2024-07-01,2024-07-01,DEADLINE\n"
    )
    result2 = parse_timetable_content(no_code_csv, "test.csv")
    # EXAM row needs start_time and end_time; above EXAM row is missing start_time
    # so it will be INVALID — that's expected.  DEADLINE row start_time == end_time auto-copy.
    check("Test 2a: DEADLINE with empty course_code accepted",
          any(r.course_code == "" for r in result2.valid_rows))

    # ------------------------------------------------------------------
    # Test 3: Malformed / boundary rows
    # ------------------------------------------------------------------
    bad_csv = (
        "A,B,C\n"  # only 3 columns → INVALID_COLUMN_COUNT
        "CSC999,Valid Event,,,23:59,,2024-12-25,2024-12-25,EVENT\n"  # missing start_time
    )
    result3 = parse_timetable_content(bad_csv, "test.csv")
    check("Test 3a: short row isolated as invalid", len(result3.invalid_rows) >= 1)

    # ------------------------------------------------------------------
    # Test 4: extract_raw_text_from_file — .csv extension (happy path)
    # ------------------------------------------------------------------
    csv_bytes = b"course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
    decoded = extract_raw_text_from_file(csv_bytes, "schedule.csv")
    check("Test 4a: .csv bytes decoded correctly", "course_code" in decoded)

    # ------------------------------------------------------------------
    # Test 5: extract_raw_text_from_file — .txt extension with latin-1 content
    # ------------------------------------------------------------------
    latin1_bytes = "Lịch học – Môn Toán".encode("latin-1", errors="replace")
    decoded_txt = extract_raw_text_from_file(latin1_bytes, "schedule.txt")
    check("Test 5a: .txt with latin-1 bytes does not crash", isinstance(decoded_txt, str))

    # ------------------------------------------------------------------
    # Test 6: extract_raw_text_from_file — no extension treated as plain text
    # ------------------------------------------------------------------
    no_ext_bytes = b"CSC101,Intro,MON,08:00,10:00,A1,2024-01-01,2024-05-01,CLASS"
    decoded_noext = extract_raw_text_from_file(no_ext_bytes, "my_schedule")
    check("Test 6a: no-extension filename treated as plain text", "CSC101" in decoded_noext)

    # ------------------------------------------------------------------
    # Test 7: extract_raw_text_from_file — unsupported extension raises ValueError
    # ------------------------------------------------------------------
    try:
        extract_raw_text_from_file(b"dummy", "timetable.xlsx")
        check("Test 7a: .xlsx raises ValueError", False)  # should not reach here
    except ValueError as exc:
        check("Test 7a: .xlsx raises ValueError", "Unsupported file type" in str(exc))

    # ------------------------------------------------------------------
    # Test 8: extract_raw_text_from_file — .docx raises ValueError
    # ------------------------------------------------------------------
    try:
        extract_raw_text_from_file(b"dummy", "schedule.docx")
        check("Test 8a: .docx raises ValueError", False)
    except ValueError as exc:
        check("Test 8a: .docx raises ValueError", "Unsupported file type" in str(exc))

    # ------------------------------------------------------------------
    # Test 9: export_valid_rows_to_csv round-trip
    # ------------------------------------------------------------------
    if result1.valid_rows:
        csv_str = export_valid_rows_to_csv(result1.valid_rows)
        check("Test 9a: export produces CSV string", isinstance(csv_str, str))
        check("Test 9b: export contains header row", "course_code" in csv_str)
        check("Test 9c: export contains data row", "CSC101" in csv_str)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Results: {total - failed}/{total} passed, {failed} failed")
    if failed > 0:
        print("[FAIL] Some tests failed — check output above.")
        sys.exit(1)
    else:
        print("[SUCCESS] All tests passed.")