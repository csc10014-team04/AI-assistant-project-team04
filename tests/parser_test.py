import parser
# ============================================================================
# SELF-VERIFICATION & EDGE-CASE TESTING SNIPPET
# ============================================================================

if __name__ == "__main__":
    print("--- Running Timetable Parser Self-Verification Suite ---\n")

    # 1. Happy Path: Standard timetable with CSV and Markdown rows for all 4 kinds
    happy_path_input = """course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
CSC10001,Nhap mon lap trinh,MON,07:30,11:00,C32,2026-09-01,2026-12-15,CLASS
CSC10002,Thi Giua Ky CTDL,,08:00,10:00,F201,2026-10-25,2026-10-25,EXAM
EVT00001,Hoi thao Khoa hoc,,14:00,16:30,Auditorium,2026-11-10,2026-11-10,EVENT
DL000001,Nop bai tap lon,,23:59,23:59,,2026-11-20,2026-11-20,DEADLINE
"""
    result_happy = parse_timetable_content(happy_path_input, "schedule_sample.csv")
    print(f"[Happy Path] Valid rows: {len(result_happy.valid_rows)}, Invalid rows: {len(result_happy.invalid_rows)}")
    assert len(result_happy.valid_rows) == 4, f"Expected 4 valid rows, got {len(result_happy.valid_rows)}"
    assert len(result_happy.invalid_rows) == 0, f"Expected 0 invalid rows, got {len(result_happy.invalid_rows)}"

    # Verify CSV export round-trip
    exported_csv = export_valid_rows_to_csv(result_happy.valid_rows)
    assert "CSC10001" in exported_csv and "DL000001" in exported_csv
    print("[Happy Path] Exported CSV successfully verified.")

    # 2. Boundary Case:
    # - DEADLINE with empty start_time (should auto-copy end_time)
    # - Single-day CLASS (first_date == last_date)
    # - Day boundaries (00:00 start or 23:59 end)
    boundary_markdown_input = """| course_code | title | weekday | start_time | end_time | room | first_date | last_date | kind |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| MAT101 | Dai so tuyen tinh | TUE | 00:00 | 02:00 | B11 | 2026-10-01 | 2026-10-01 | CLASS |
| DL_AUTO | Nop bao cao tuan 1 | | | 23:59 | | 2026-10-05 | 2026-10-05 | DEADLINE |
"""
    result_boundary = parse_timetable_content(boundary_markdown_input, "boundary.md")
    print(f"\n[Boundary Case] Valid rows: {len(result_boundary.valid_rows)}, Invalid rows: {len(result_boundary.invalid_rows)}")
    assert len(result_boundary.valid_rows) == 2, f"Expected 2 valid rows, got {len(result_boundary.valid_rows)}"
    assert len(result_boundary.invalid_rows) == 0, f"Expected 0 invalid rows, got {len(result_boundary.invalid_rows)}"

    deadline_row = result_boundary.valid_rows[1]
    assert deadline_row.start_time == time(23, 59), "DEADLINE empty start_time was not auto-copied from end_time"
    assert deadline_row.start_time == deadline_row.end_time, "DEADLINE start_time must equal end_time"
    print("[Boundary Case] DEADLINE auto-copy and single-day CLASS verified.")

    # 3. Conflict/Failure Case: Malformed rows isolated without crashing valid rows
    failure_input = """course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
CSC20001,Kien truc may tinh,WED,07:30,10:30,E105,2026-09-01,2026-12-15,CLASS
ERR_COL,Thieu cot bi loi,MON,08:00,10:00
ERR_TIME,Sai gio ket thuc som hon,THU,10:00,08:00,A12,2026-09-01,2026-12-15,CLASS
ERR_DATE,Ngay bat dau sau ngay ket thuc,FRI,07:30,09:30,A12,2026-12-15,2026-09-01,CLASS
ERR_KIND,Loai khong ton tai,SAT,08:00,10:00,B10,2026-10-10,2026-10-10,UNKNOWN_KIND
ERR_EXAM_MULTI,Thi 2 ngay,SUN,08:00,10:00,C12,2026-10-10,2026-10-11,EXAM
"""
    result_failure = parse_timetable_content(failure_input, "mixed_errors.csv")
    print(f"\n[Failure/Isolation Case] Valid rows: {len(result_failure.valid_rows)}, Invalid rows: {len(result_failure.invalid_rows)}")
    assert len(result_failure.valid_rows) == 1, f"Expected 1 valid row, got {len(result_failure.valid_rows)}"
    assert len(result_failure.invalid_rows) == 5, f"Expected 5 invalid rows, got {len(result_failure.invalid_rows)}"
    assert result_failure.valid_rows[0].course_code == "CSC20001"

    # Confirm distinct error codes are isolated
    error_codes = [err.error_code for err in result_failure.invalid_rows]
    print(f"[Failure/Isolation Case] Isolated error codes: {error_codes}")
    assert "INVALID_COLUMN_COUNT" in error_codes
    assert "INVALID_TIME_RANGE" in error_codes
    assert "INVALID_DATE_RANGE" in error_codes
    assert "INVALID_KIND" in error_codes
    print("\n[SUCCESS] All 3 verification test cases passed with zero errors!")