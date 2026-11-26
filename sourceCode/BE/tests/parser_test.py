# [pic: lam] multi-format timetable parser test suite (ai assistants: do not remove this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `services` importable
from services import parser as parser_module
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

    # Confirm the uploaded CSV table is read once and then sent to the same validator.
    original_table_reader = parser_module._read_delimited_table
    table_read_count = {"count": 0}

    def counted_table_reader(raw_content: str) -> list[list[str]]:
        """Count calls to the parser's CSV table reader during one file upload.

        Input: one decoded source string.
        Output: parsed rows from the original CSV reader.
        Edge Cases Handled: The original reader is restored in the surrounding finally block.
        """
        table_read_count["count"] += 1
        return original_table_reader(raw_content)

    parser_module._read_delimited_table = counted_table_reader
    try:
        uploaded_result = parse_timetable_file(sample_csv.encode("utf-8"), "test.csv")
    finally:
        parser_module._read_delimited_table = original_table_reader
    check("Test 1d: uploaded CSV table read exactly once", table_read_count["count"] == 1)
    check("Test 1e: uploaded CSV still validates both rows", len(uploaded_result.valid_rows) == 2)

    # csv.reader must keep quoted commas and newlines inside one title cell.
    multiline_csv = (
        "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
        'CSC103,"Algorithms,\n'
        'and Data Structures",TUE,09:00,11:00,B101,2024-01-09,2024-05-07,CLASS\n'
    )
    multiline_result = parse_timetable_content(multiline_csv, "multiline.csv")
    check("Test 1f: quoted multiline record becomes one valid row",
          len(multiline_result.valid_rows) == 1
          and multiline_result.valid_rows[0].title == "Algorithms,\nand Data Structures")

    # Reordered alias headers still map into the established nine-column model.
    reordered_csv = (
        "Tên MH,Học kỳ,Mã MH,Lịch LT,Ngày bắt đầu,Ngày kết thúc,Phòng,Loại\n"
        "Đại số,2024-2025,MATH101,T2 08:00-10:00,2024-01-08,2024-05-06,A101,CLASS\n"
    )
    reordered_result = parse_timetable_content(reordered_csv, "reordered.csv")
    check("Test 1g: reordered headers still map and validate",
          len(reordered_result.valid_rows) == 1
          and reordered_result.valid_rows[0].course_code == "MATH101")

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
    # Test 10: Date formats, neutral date headers, and batch defaults
    # ------------------------------------------------------------------
    date_formats = [
        "2026-09-28", "2026/09/28", "28/09/2026", "5/9/2026",
        "28-09-2026", "5-9-2026", "28.09.2026", "5.9.2026",
    ]
    date_rows = [
        f"CSC{index},Math,MON,08:00,09:00,A1,{date_text},2026-12-12,CLASS"
        for index, date_text in enumerate(date_formats)
    ]
    date_format_result = parse_timetable_content("\n".join(date_rows), "dates.csv")
    check("Test 10a: all supported ISO and DMY date formats parse",
          len(date_format_result.valid_rows) == len(date_formats)
          and not date_format_result.invalid_rows)
    us_date_result = parse_timetable_content(
        "CSC900,No MDY,MON,08:00,09:00,A1,09/28/2026,12/12/2026,CLASS\n",
        "no_mdy.csv",
    )
    check("Test 10a2: ambiguous US month-first dates are not accepted",
          any(row.error_code == "INVALID_FIRST_DATE" for row in us_date_result.invalid_rows))

    neutral_dates = (
        "Mã MH,Tên MH,Lịch LT,date_1,date_2,Giảng viên\n"
        "CSC101,Math,T2 7h30-9h10 - Phòng C.45,12/12/2026,28/09/2026,Teacher\n"
    )
    neutral_result = parse_timetable_content(neutral_dates, "neutral_dates.csv")
    check("Test 10b: neutral date columns map by content and sort boundaries",
          len(neutral_result.valid_rows) == 1
          and neutral_result.valid_rows[0].first_date.isoformat() == "2026-09-28"
          and neutral_result.valid_rows[0].last_date.isoformat() == "2026-12-12")

    one_neutral_date = (
        "Mã MH,Tên MH,Lịch LT,date_1,date_2\n"
        "CSC102,Physics,T3 08:00-09:00,28/09/2026,\n"
    )
    one_date_result = parse_timetable_content(one_neutral_date, "one_date.csv")
    check("Test 10c: one unlabelled date is flagged as ambiguous",
          any(row.error_code == "AMBIGUOUS_SINGLE_DATE" for row in one_date_result.invalid_rows))

    date_range_table = (
        "Mã MH,Tên MH,Lịch LT,Khoảng ngày\n"
        "CSC103,History,T4 10:00-11:00,28.09.2026 - 12.12.2026\n"
    )
    date_range_result = parse_timetable_content(date_range_table, "date_range.csv")
    check("Test 10d: combined date range column is split",
          len(date_range_result.valid_rows) == 1)

    batch_defaults = parse_timetable_content(
        "A,Math,MON,08:00,09:00,A1,,,CLASS\n",
        "batch.csv",
        default_first_date="2026-09-01",
        default_last_date="2026-12-20",
    )
    check("Test 10e: batch dates fill missing positional date cells",
          len(batch_defaults.valid_rows) == 1
          and batch_defaults.valid_rows[0].first_date.isoformat() == "2026-09-01")

    # ------------------------------------------------------------------
    # Test 11: Time, weekday, kind, room, and published-schedule handling
    # ------------------------------------------------------------------
    flexible_values = (
        ",Discrete Math,T 2,7h30,9.10,P.C45,28/09/2026,12/12/2026,Lý thuyết\n"
        ",Final Exam,,8:00 AM,1:30 PM,@ I.44,2026-12-15,2026-12-15,Thi\n"
    )
    flexible_result = parse_timetable_content(flexible_values, "flexible.csv")
    check("Test 11a: tolerant weekday, time, kind, and room values parse",
          len(flexible_result.valid_rows) == 2
          and flexible_result.valid_rows[0].weekday == Weekday.MON
          and flexible_result.valid_rows[0].room == "C45"
          and flexible_result.valid_rows[1].kind == CsvRowKind.EXAM)

    inferred_weekday_kind = parse_timetable_content(
        ",Weekly Class,,07:30,09:00,A1,2026-09-07,2026-12-14,\n",
        "inferred.csv",
    )
    check("Test 11b: blank kind and weekday infer CLASS from recurring dates",
          len(inferred_weekday_kind.valid_rows) == 1
          and inferred_weekday_kind.valid_rows[0].kind == CsvRowKind.CLASS
          and inferred_weekday_kind.valid_rows[0].weekday == Weekday.MON)

    unscheduled = (
        "Mã MH,Tên MH,Lịch LT,Lịch TH\n"
        "BAA00030,Giáo dục quốc phòng - An ninh,,\n"
    )
    unscheduled_result = parse_timetable_content(unscheduled, "unscheduled.csv")
    check("Test 11c: course without a published schedule is marked for skip",
          any(row.error_code == "NO_SCHEDULE_PUBLISHED" for row in unscheduled_result.invalid_rows))

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
