# owner: Lam (P1-4 first half: multi-format timetable parser & staging error isolation)
import csv
import io
import re
import sys
import uuid
from datetime import date, time
from pathlib import Path
from typing import Optional

# Ensure parent directory is in sys.path so 'models' can be imported when running standalone
CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from models import (
    CsvRowKind,
    InvalidCsvRow,
    ParseBatchResult,
    ParsedCsvRow,
    Weekday,
)

# Standard mapping to normalize weekday names across various input styles
WEEKDAY_LOOKUP: dict[str, Weekday] = {
    "MON": Weekday.MON,
    "MONDAY": Weekday.MON,
    "T2": Weekday.MON,
    "THU 2": Weekday.MON,
    "THỨ 2": Weekday.MON,
    "TUE": Weekday.TUE,
    "TUESDAY": Weekday.TUE,
    "T3": Weekday.TUE,
    "THU 3": Weekday.TUE,
    "THỨ 3": Weekday.TUE,
    "WED": Weekday.WED,
    "WEDNESDAY": Weekday.WED,
    "T4": Weekday.WED,
    "THU 4": Weekday.WED,
    "THỨ 4": Weekday.WED,
    "THU": Weekday.THU,
    "THURSDAY": Weekday.THU,
    "T5": Weekday.THU,
    "THU 5": Weekday.THU,
    "THỨ 5": Weekday.THU,
    "FRI": Weekday.FRI,
    "FRIDAY": Weekday.FRI,
    "T6": Weekday.FRI,
    "THU 6": Weekday.FRI,
    "THỨ 6": Weekday.FRI,
    "SAT": Weekday.SAT,
    "SATURDAY": Weekday.SAT,
    "T7": Weekday.SAT,
    "THU 7": Weekday.SAT,
    "THỨ 7": Weekday.SAT,
    "SUN": Weekday.SUN,
    "SUNDAY": Weekday.SUN,
    "CN": Weekday.SUN,
    "CHU NHAT": Weekday.SUN,
    "CHỦ NHẬT": Weekday.SUN,
}


def _split_line_into_cells(raw_line: str) -> Optional[list[str]]:
    """
    Input:
        raw_line (str): A single line of text from the uploaded timetable file.
    Output:
        Optional[list[str]]: List of cell values stripped of leading/trailing spaces,
                             or None if the line is empty or is a Markdown divider.
    Edge Cases Handled:
        - Completely blank lines or whitespace-only lines (returns None to skip).
        - Markdown table divider rows like '| --- | :---: |' (returns None to skip).
        - Markdown rows enclosed in '|' pipes.
        - Tab-separated and semicolon-separated lines.
        - Standard comma-separated lines (properly handles quotes via csv.reader).
    """
    stripped_line = raw_line.strip()
    if not stripped_line:
        # Ignore blank lines silently
        return None

    # Check if this line is a Markdown table row or divider
    if stripped_line.startswith("|") and stripped_line.endswith("|"):
        # Split by pipe and remove outermost empty elements caused by leading/trailing pipes
        raw_cells = stripped_line[1:-1].split("|")
        cleaned_cells = [cell.strip() for cell in raw_cells]

        # Check if the row is a markdown separator (e.g., '---' or ':---:')
        is_separator = True
        for cell in cleaned_cells:
            # A valid separator cell only has dashes, colons, or whitespace
            non_marker_chars = cell.replace("-", "").replace(":", "").strip()
            if non_marker_chars != "" or len(cell) == 0:
                is_separator = False
                break

        if is_separator:
            # Markdown table divider row, safe to skip
            return None

        return cleaned_cells

    # Check if tab-delimited (and has no commas)
    if "\t" in raw_line and "," not in raw_line:
        return [cell.strip() for cell in raw_line.split("\t")]

    # Check if semicolon-delimited (and has no commas)
    if ";" in raw_line and "," not in raw_line:
        reader = csv.reader([raw_line], delimiter=";")
        return [cell.strip() for cell in next(reader)]

    # Default to standard CSV parsing with comma delimiter
    try:
        reader = csv.reader([raw_line])
        return [cell.strip() for cell in next(reader)]
    except csv.Error as csv_err:
        # Raise ValueError to be caught and recorded as an InvalidCsvRow
        raise ValueError(f"Malformed CSV formatting: {str(csv_err)}")


def _is_header_row(cells: list[str]) -> bool:
    """
    Input:
        cells (list[str]): Parsed column cells from a line.
    Output:
        bool: True if the row represents the schema header, False otherwise.
    Edge Cases Handled:
        - Case insensitivity (e.g. 'Course_Code', 'COURSE_CODE').
        - Header with spaces or markdown artifacts.
    """
    if len(cells) >= 2:
        first_cell = cells[0].lower().replace(" ", "_").strip("#")
        second_cell = cells[1].lower().replace(" ", "_")
        if first_cell == "course_code" and "title" in second_cell:
            return True
    return False


def _parse_and_validate_row(
    line_number: int,
    raw_text: str,
    cells: list[str],
) -> tuple[Optional[ParsedCsvRow], Optional[InvalidCsvRow]]:
    """
    Input:
        line_number (int): 1-indexed line number in the source file.
        raw_text (str): The original line text for diagnostic logging.
        cells (list[str]): The extracted cell strings.
    Output:
        tuple[Optional[ParsedCsvRow], Optional[InvalidCsvRow]]: Exactly one of the two will be non-None.
    Edge Cases Handled:
        - Incorrect column counts (must be exactly 9 columns).
        - Missing mandatory fields (course_code, title, kind, dates, times).
        - Invalid enum kinds (must be CLASS, EXAM, DEADLINE, EVENT).
        - DEADLINE rows with empty start_time (auto-copied from end_time).
        - DEADLINE rows with non-matching start/end time or differing dates.
        - CLASS rows with missing weekday or reversed times/dates.
        - EXAM and EVENT rows spanning multiple days or with reversed times.
        - Invalid time (HH:MM) or date (YYYY-MM-DD) formatting.
    """
    # Expected 9-column schema:
    # 0: course_code, 1: title, 2: weekday, 3: start_time, 4: end_time,
    # 5: room, 6: first_date, 7: last_date, 8: kind
    if len(cells) != 9:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_COLUMN_COUNT",
            error_message=f"Expected exactly 9 columns, found {len(cells)}",
        )

    course_code = cells[0].strip()
    title = cells[1].strip()
    weekday_raw = cells[2].strip().upper()
    start_time_raw = cells[3].strip()
    end_time_raw = cells[4].strip()
    room_raw = cells[5].strip()
    first_date_raw = cells[6].strip()
    last_date_raw = cells[7].strip()
    kind_raw = cells[8].strip().upper()

    # 1. Validate mandatory course_code and title
    if not course_code:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_COURSE_CODE",
            error_message="Course code cannot be empty",
        )

    if not title:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_TITLE",
            error_message="Title cannot be empty",
        )

    # 2. Validate kind against CsvRowKind
    if not kind_raw:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_KIND",
            error_message="Kind cannot be empty",
        )

    try:
        row_kind = CsvRowKind(kind_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_KIND",
            error_message=f"Invalid kind '{cells[8]}'. Must be one of CLASS, EXAM, DEADLINE, EVENT",
        )

    # 3. Validate weekday
    parsed_weekday: Optional[Weekday] = None
    if weekday_raw:
        if weekday_raw in WEEKDAY_LOOKUP:
            parsed_weekday = WEEKDAY_LOOKUP[weekday_raw]
        else:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="INVALID_WEEKDAY",
                error_message=f"Invalid weekday '{cells[2]}'. Expected one of MON, TUE, WED, THU, FRI, SAT, SUN",
            )

    # CLASS requires a valid weekday because it recurs weekly on that day
    if row_kind == CsvRowKind.CLASS and parsed_weekday is None:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="MISSING_WEEKDAY",
            error_message="CLASS row requires a valid weekday (e.g. MON, TUE, WED, THU, FRI, SAT, SUN)",
        )

    # 4. Handle DEADLINE special rule: set start_time = end_time if start_time is omitted
    # Why: Deadlines are point-in-time milestones with 0 duration in our unified events table
    if row_kind == CsvRowKind.DEADLINE:
        if not start_time_raw and end_time_raw:
            start_time_raw = end_time_raw
        elif start_time_raw and not end_time_raw:
            end_time_raw = start_time_raw

    # 5. Validate presence of time values
    if not start_time_raw:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_START_TIME",
            error_message="Start time cannot be empty",
        )

    if not end_time_raw:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_END_TIME",
            error_message="End time cannot be empty",
        )

    # Parse 24-hour HH:MM time
    try:
        parsed_start_time = time.fromisoformat(start_time_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_START_TIME",
            error_message=f"Invalid start_time '{start_time_raw}'. Expected 24-hour format HH:MM",
        )

    try:
        parsed_end_time = time.fromisoformat(end_time_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_END_TIME",
            error_message=f"Invalid end_time '{end_time_raw}'. Expected 24-hour format HH:MM",
        )

    # 6. Validate presence of date values
    if not first_date_raw:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_FIRST_DATE",
            error_message="First date cannot be empty",
        )

    if not last_date_raw:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="EMPTY_LAST_DATE",
            error_message="Last date cannot be empty",
        )

    # Parse YYYY-MM-DD date
    try:
        parsed_first_date = date.fromisoformat(first_date_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_FIRST_DATE",
            error_message=f"Invalid first_date '{first_date_raw}'. Expected format YYYY-MM-DD",
        )

    try:
        parsed_last_date = date.fromisoformat(last_date_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_LAST_DATE",
            error_message=f"Invalid last_date '{last_date_raw}'. Expected format YYYY-MM-DD",
        )

    # Room is optional; store None if empty
    parsed_room: Optional[str] = room_raw if room_raw else None

    # 7. Cross-field semantic validation according to system architecture
    if row_kind == CsvRowKind.DEADLINE:
        # Deadlines must represent a point-in-time: start == end and on a single date
        if parsed_start_time != parsed_end_time:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="DEADLINE_TIME_MISMATCH",
                error_message=f"DEADLINE requires start_time == end_time (found {start_time_raw} vs {end_time_raw})",
            )
        if parsed_first_date != parsed_last_date:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="DEADLINE_DATE_MISMATCH",
                error_message=f"DEADLINE requires first_date == last_date (found {first_date_raw} vs {last_date_raw})",
            )

    elif row_kind == CsvRowKind.CLASS:
        # Recurring weekly class sessions must have positive duration and valid date range
        if parsed_start_time >= parsed_end_time:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="INVALID_TIME_RANGE",
                error_message=f"CLASS start_time ({start_time_raw}) must be strictly earlier than end_time ({end_time_raw})",
            )
        if parsed_first_date > parsed_last_date:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="INVALID_DATE_RANGE",
                error_message=f"CLASS first_date ({first_date_raw}) cannot be after last_date ({last_date_raw})",
            )

    elif row_kind in (CsvRowKind.EXAM, CsvRowKind.EVENT):
        # One-off exams and fixed events must have positive duration and occur on a single date
        if parsed_start_time >= parsed_end_time:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="INVALID_TIME_RANGE",
                error_message=f"{row_kind.value} start_time ({start_time_raw}) must be strictly earlier than end_time ({end_time_raw})",
            )
        if parsed_first_date != parsed_last_date:
            return None, InvalidCsvRow(
                line_number=line_number,
                raw_text=raw_text,
                error_code="INVALID_DATE_RANGE",
                error_message=f"{row_kind.value} is a single-day event and requires first_date == last_date (found {first_date_raw} vs {last_date_raw})",
            )

    # All validations passed: construct clean ParsedCsvRow
    valid_row = ParsedCsvRow(
        line_number=line_number,
        course_code=course_code,
        title=title,
        kind=row_kind,
        start_time=parsed_start_time,
        end_time=parsed_end_time,
        first_date=parsed_first_date,
        last_date=parsed_last_date,
        weekday=parsed_weekday,
        room=parsed_room,
    )
    return valid_row, None


def parse_timetable_content(raw_content: str, filename: str = "") -> ParseBatchResult:
    """
    Input:
        raw_content (str): The raw text, CSV, or Markdown content of a student timetable file.
        filename (str, optional): The original filename of the uploaded schedule.
    Output:
        ParseBatchResult: Object containing a unique import_batch_id, a list of valid_rows (ParsedCsvRow),
                          and a list of isolated invalid_rows (InvalidCsvRow).
    Edge Cases Handled:
        - Completely empty or whitespace-only files (returns empty lists with generated batch_id).
        - Markdown tables with header rows and divider lines (| --- | --- |).
        - CSV files with or without standard header row.
        - Malformed rows (bad column count, invalid time HH:MM, invalid date YYYY-MM-DD).
        - DEADLINE rows with missing start_time (automatically matched to end_time).
        - Never crashes the entire batch when encountering malformed lines (error isolation).
    """
    # Generate unique 16-character hex identifier for this import batch
    import_batch_id: str = uuid.uuid4().hex[:16]

    valid_rows: list[ParsedCsvRow] = []
    invalid_rows: list[InvalidCsvRow] = []

    # Split into lines and iterate with 1-indexed line numbers
    lines = raw_content.splitlines()

    for line_idx, line in enumerate(lines, start=1):
        # 1. Attempt to extract cell values from the line
        try:
            cells = _split_line_into_cells(line)
        except ValueError as err:
            # Catch formatting syntax errors (e.g. unclosed quotes) and isolate
            invalid_rows.append(
                InvalidCsvRow(
                    line_number=line_idx,
                    raw_text=line,
                    error_code="MALFORMED_LINE_SYNTAX",
                    error_message=str(err),
                )
            )
            continue

        # 2. Skip non-data lines (blank lines or markdown dividers)
        if cells is None:
            continue

        # 3. Skip header lines (e.g., 'course_code,title,...')
        if _is_header_row(cells):
            continue

        # 4. Parse and validate the data cells
        valid_row, invalid_row = _parse_and_validate_row(line_idx, line, cells)

        if valid_row is not None:
            valid_rows.append(valid_row)
        elif invalid_row is not None:
            invalid_rows.append(invalid_row)

    return ParseBatchResult(
        import_batch_id=import_batch_id,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )


def export_valid_rows_to_csv(rows: list[ParsedCsvRow]) -> str:
    """
    Input:
        rows (list[ParsedCsvRow]): A list of validated schedule rows ready for export or conflict detection.
    Output:
        str: A standardized UTF-8 CSV string with the locked 9-column schema.
    Edge Cases Handled:
        - Empty list of rows (returns CSV string containing only the header row).
        - Optional fields (weekday and room properly serialized as empty strings when None).
        - Special characters or commas in titles/rooms safely escaped by standard csv.writer.
    """
    output_buffer = io.StringIO()
    writer = csv.writer(output_buffer, lineterminator="\n")

    # Locked 9-column schema header
    writer.writerow([
        "course_code",
        "title",
        "weekday",
        "start_time",
        "end_time",
        "room",
        "first_date",
        "last_date",
        "kind",
    ])

    for row in rows:
        weekday_str = row.weekday.value if row.weekday is not None else ""
        room_str = row.room if row.room is not None else ""

        writer.writerow([
            row.course_code,
            row.title,
            weekday_str,
            row.start_time.strftime("%H:%M"),
            row.end_time.strftime("%H:%M"),
            room_str,
            row.first_date.isoformat(),
            row.last_date.isoformat(),
            row.kind.value,
        ])

    return output_buffer.getvalue()
