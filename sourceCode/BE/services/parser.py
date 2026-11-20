# [pic: lam] p1-4 multi-format timetable parser & error isolation (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import csv
import io
import re
import sys
import unicodedata
import uuid
from datetime import date, time
from pathlib import Path
from typing import Any, Optional

# Third-party imports for PDF and image extraction (installed via pip)
# pdfplumber: structured PDF table + text extraction
# pytesseract + Pillow: OCR for scanned images
try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    import os
    from PIL import Image
    import pytesseract
    _OCR_AVAILABLE = True

    # Check common Tesseract installation paths on Windows and Linux
    _tess_candidates = [
        os.getenv("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for _path in _tess_candidates:
        if _path and Path(_path).exists():
            pytesseract.pytesseract.tesseract_cmd = str(_path)
            break
except ImportError:
    _OCR_AVAILABLE = False

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

# Header aliases used by common university timetable exports. These aliases
# are only used to map a table into the existing ParsedCsvRow contract.
_TABLE_HEADER_ALIASES: dict[str, str] = {
    "ma mh": "course_code",
    "mamh": "course_code",
    "ma mon": "course_code",
    "mamon": "course_code",
    "ma mon hoc": "course_code",
    "mamonhoc": "course_code",
    "ma hp": "course_code",
    "mahp": "course_code",
    "ma hoc phan": "course_code",
    "mahocphan": "course_code",
    "course code": "course_code",
    "coursecode": "course_code",
    "course id": "course_code",
    "courseid": "course_code",
    "subject code": "course_code",
    "subjectcode": "course_code",
    "ten mh": "title",
    "tenmh": "title",
    "ten mon": "title",
    "tenmon": "title",
    "ten mon hoc": "title",
    "tenmonhoc": "title",
    "ten hoc phan": "title",
    "tenhocphan": "title",
    "ten hoc phan hoc": "title",
    "course name": "title",
    "coursename": "title",
    "subject name": "title",
    "subjectname": "title",
    "title": "title",
    "thu": "weekday",
    "thu hoc": "weekday",
    "ngay trong tuan": "weekday",
    "weekday": "weekday",
    "day of week": "weekday",
    "day": "weekday",
    "gio bat dau": "start_time",
    "start time": "start_time",
    "gio ket thuc": "end_time",
    "end time": "end_time",
    "phong": "room",
    "phong hoc": "room",
    "room": "room",
    "classroom": "room",
    "ngay bat dau": "first_date",
    "tu ngay": "first_date",
    "first date": "first_date",
    "start date": "first_date",
    "ngay ket thuc": "last_date",
    "den ngay": "last_date",
    "last date": "last_date",
    "end date": "last_date",
    "kind": "kind",
    "loai": "kind",
    "loai lich": "kind",
    "loai su kien": "kind",
    "event type": "kind",
    "hoc ky": "semester",
    "hocky": "semester",
    "semester": "semester",
    "term": "semester",
    "lich lt": "lecture_schedule",
    "lichlt": "lecture_schedule",
    "lich ly thuyet": "lecture_schedule",
    "ly thuyet": "lecture_schedule",
    "lecture schedule": "lecture_schedule",
    "theory schedule": "lecture_schedule",
    "lich th": "practice_schedule",
    "lichth": "practice_schedule",
    "lich thuc hanh": "practice_schedule",
    "thuc hanh": "practice_schedule",
    "practice schedule": "practice_schedule",
    "lab schedule": "practice_schedule",
    "lich hoc": "schedule",
    "lichhoc": "schedule",
    "thoi khoa bieu": "schedule",
    "schedule": "schedule",
    "timetable": "schedule",
}

_SCHEDULE_WEEKDAY_RE = re.compile(
    r"(?<![A-Z0-9])(?:THỨ\s*[2-7]|THU\s*[2-7]|T\s*[2-7]|CN|CHỦ\s*NHẬT|CHU\s*NHAT|"
    r"MONDAY|MON|TUESDAY|TUE|WEDNESDAY|WED|THURSDAY|THU|FRIDAY|FRI|"
    r"SATURDAY|SAT|SUNDAY|SUN)(?![A-Z0-9])",
    re.IGNORECASE,
)
_TIME_RANGE_RE = re.compile(
    r"(?<!\d)(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})(?!\d)"
)


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


def _parse_time_cell(value: str) -> time:
    """Parse an HH:MM cell, accepting and discarding an ISO timezone suffix.

    Input: a time cell such as '08:00', '8:00Z', or '08:00+07:00'.
    Output: a naive time preserving the displayed wall-clock hour and minute.
    Edge Cases Handled: Invalid offsets still fail; the legacy no-suffix format stays unchanged.
    """
    timezone_match = re.fullmatch(
        r"(\d{1,2}:\d{2})(Z|[+-]\d{2}:\d{2})",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if timezone_match is None:
        return time.fromisoformat(value)

    clock_text, timezone_suffix = timezone_match.groups()
    hour_text, minute_text = clock_text.split(":", maxsplit=1)
    normalized_clock = f"{int(hour_text):02d}:{minute_text}"
    iso_offset = "+00:00" if timezone_suffix.upper() == "Z" else timezone_suffix
    parsed_time = time.fromisoformat(f"{normalized_clock}{iso_offset}")
    return parsed_time.replace(tzinfo=None)


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
        - course_code is optional — an empty string is accepted and stored as "".
        - Missing mandatory fields (title, kind, dates, times).
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
   
    # 1. Validate title against CsvRowKind
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
        parsed_start_time = _parse_time_cell(start_time_raw)
    except ValueError:
        return None, InvalidCsvRow(
            line_number=line_number,
            raw_text=raw_text,
            error_code="INVALID_START_TIME",
            error_message=f"Invalid start_time '{start_time_raw}'. Expected 24-hour format HH:MM",
        )

    try:
        parsed_end_time = _parse_time_cell(end_time_raw)
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


def _normalize_header_label(label: str) -> str:
    """Normalize a table heading before matching known timetable aliases.

    Input: label, one heading cell from a CSV, Markdown, PDF, or OCR table.
    Output: lowercase ASCII words with accents and punctuation removed.
    Edge Cases Handled: Vietnamese accents, the letter đ, extra spaces, and punctuation.
    """
    normalized = unicodedata.normalize("NFKD", label.lower().replace("đ", "d"))
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    words = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return " ".join(words.split())


def _map_table_headers(header_cells: list[str]) -> dict[str, int]:
    """Map recognized table headings to fields supported by ParsedCsvRow.

    Input: header_cells, cells from one candidate header row.
    Output: semantic field names mapped to their zero-based column positions.
    Edge Cases Handled: Unknown columns are ignored and duplicate aliases keep the first match.
    """
    mapped: dict[str, int] = {}
    for column_index, header in enumerate(header_cells):
        normalized_header = _normalize_header_label(header)
        field_name = _TABLE_HEADER_ALIASES.get(normalized_header)
        if field_name is not None and field_name not in mapped:
            mapped[field_name] = column_index
    return mapped


def _is_canonical_nine_column_header(header_cells: list[str]) -> bool:
    """Identify the original locked CSV header that must keep the old parser path.

    Input: header_cells, one candidate header row.
    Output: True only when all nine fields are in the original canonical order.
    Edge Cases Handled: Header case, spaces, and a UTF-8 BOM.
    """
    expected_fields = [
        "course code",
        "title",
        "weekday",
        "start time",
        "end time",
        "room",
        "first date",
        "last date",
        "kind",
    ]
    normalized_fields = [_normalize_header_label(cell) for cell in header_cells]
    return normalized_fields == expected_fields


def _table_header_is_supported(header_map: dict[str, int]) -> bool:
    """Check whether a header has enough fields to describe timetable sessions.

    Input: header_map, semantic column positions produced by _map_table_headers.
    Output: True for a course title plus schedule columns or weekday/time columns.
    Edge Cases Handled: Course code stays optional as required by the existing parser contract.
    """
    has_schedule_cell = any(
        field_name in header_map
        for field_name in ("lecture_schedule", "practice_schedule", "schedule")
    )
    has_split_time = all(
        field_name in header_map for field_name in ("weekday", "start_time", "end_time")
    )
    return "title" in header_map and (has_schedule_cell or has_split_time)


def _table_cell(row: list[str], header_map: dict[str, int], field_name: str) -> str:
    """Read a table cell by semantic field name without indexing past short rows.

    Input: row, the current data row; header_map, semantic positions; field_name, requested field.
    Output: trimmed cell text, or an empty string when that field is absent.
    Edge Cases Handled: Short/ragged rows and optional columns.
    """
    column_index = header_map.get(field_name)
    if column_index is None or column_index >= len(row):
        return ""
    return row[column_index].strip()


def _parse_weekday_token(token: str) -> Optional[Weekday]:
    """Convert one recognized weekday token into the existing Weekday enum.

    Input: token, a Vietnamese or English weekday abbreviation/name.
    Output: Weekday enum value, or None when the token is not recognized.
    Edge Cases Handled: T 2 spacing, accented Vietnamese names, and common abbreviations.
    """
    normalized = re.sub(r"\s+", " ", token.strip().upper())
    if re.fullmatch(r"T\s*[2-7]", normalized):
        normalized = normalized.replace(" ", "")
    return WEEKDAY_LOOKUP.get(normalized)


def _schedule_entries_from_text(
    schedule_text: str,
) -> list[tuple[Optional[Weekday], str, str, Optional[str], Optional[str]]]:
    """Split one schedule cell into individual weekday/time/room entries.

    Input: schedule_text, for example 'T4 07:30-09:10 (C.45) T6 07:30-09:10 (I.44)'.
    Output: tuples of weekday, start, end, room, and an optional parse error.
    Edge Cases Handled: Multiple sessions in one cell, multiline OCR text, dotted times,
    missing time ranges, and cells containing no recognizable weekday.
    """
    entries: list[tuple[Optional[Weekday], str, str, Optional[str], Optional[str]]] = []
    weekday_matches = list(_SCHEDULE_WEEKDAY_RE.finditer(schedule_text.upper()))

    if not weekday_matches:
        if schedule_text.strip():
            entries.append((None, "", "", None, "No weekday marker was found in this schedule cell."))
        return entries

    for match_index, weekday_match in enumerate(weekday_matches):
        segment_end = len(schedule_text)
        if match_index + 1 < len(weekday_matches):
            segment_end = weekday_matches[match_index + 1].start()
        segment = schedule_text[weekday_match.start():segment_end]

        weekday = _parse_weekday_token(weekday_match.group(0))
        time_match = _TIME_RANGE_RE.search(segment)
        room_match = re.search(r"\(([^()]*)\)", segment)
        room = room_match.group(1).strip() if room_match else None

        if time_match is None:
            entries.append((weekday, "", "", room, "No HH:MM-HH:MM time range was found for this weekday."))
            continue

        raw_start = time_match.group(1).replace(".", ":")
        raw_end = time_match.group(2).replace(".", ":")
        start_hour, start_minute = raw_start.split(":", maxsplit=1)
        end_hour, end_minute = raw_end.split(":", maxsplit=1)
        start_text = f"{int(start_hour):02d}:{start_minute}"
        end_text = f"{int(end_hour):02d}:{end_minute}"
        entries.append((weekday, start_text, end_text, room, None))

    return entries


def _parse_timetable_table_rows(
    table_rows: list[list[str]],
    import_batch_id: str,
    line_number_start: int = 1,
    low_confidence_cells: Optional[set[tuple[int, int]]] = None,
) -> Optional[ParseBatchResult]:
    """Convert an aliased timetable table into the existing parser result contract.

    Input: table_rows, extracted row/cell strings; import_batch_id, the current batch ID;
    line_number_start, first unique output line number for expanded sessions;
    low_confidence_cells, optional OCR cells that need human confirmation.
    Output: ParseBatchResult when a supported header is found, otherwise None.
    Edge Cases Handled: Repeated headers, merged course cells, multiple schedule cells,
    empty schedules, missing semester dates, and ragged rows.
    """
    header_position: Optional[int] = None
    header_map: dict[str, int] = {}

    for candidate_index, candidate_row in enumerate(table_rows[:6]):
        candidate_map = _map_table_headers(candidate_row)
        if _table_header_is_supported(candidate_map):
            header_position = candidate_index
            header_map = candidate_map
            break

    if header_position is None:
        return None

    if _is_canonical_nine_column_header(table_rows[header_position]):
        return None

    has_schedule_columns = any(
        field_name in header_map
        for field_name in ("lecture_schedule", "practice_schedule", "schedule")
    )
    valid_rows: list[ParsedCsvRow] = []
    invalid_rows: list[InvalidCsvRow] = []
    next_line_number = line_number_start
    previous_course_code = ""
    previous_title = ""
    previous_semester = ""
    low_confidence_cells = low_confidence_cells or set()

    for table_row_index, table_row in enumerate(
        table_rows[header_position + 1:],
        start=header_position + 1,
    ):
        if not any(cell.strip() for cell in table_row):
            continue

        repeated_header_map = _map_table_headers(table_row)
        if _table_header_is_supported(repeated_header_map):
            continue

        course_code = _table_cell(table_row, header_map, "course_code")
        title = _table_cell(table_row, header_map, "title")
        semester = _table_cell(table_row, header_map, "semester")

        if has_schedule_columns:
            if not course_code:
                course_code = previous_course_code
            if not title:
                title = previous_title
            if not semester:
                semester = previous_semester

        if course_code:
            previous_course_code = course_code
        if title:
            previous_title = title
        if semester:
            previous_semester = semester

        first_date = _table_cell(table_row, header_map, "first_date")
        last_date = _table_cell(table_row, header_map, "last_date")
        room = _table_cell(table_row, header_map, "room") or None
        kind = _table_cell(table_row, header_map, "kind") or "CLASS"
        raw_text = " | ".join(cell.strip() for cell in table_row)

        schedule_entries: list[
            tuple[Optional[Weekday], str, str, Optional[str], Optional[str]]
        ] = []
        if has_schedule_columns:
            for field_name in ("lecture_schedule", "practice_schedule", "schedule"):
                schedule_cell = _table_cell(table_row, header_map, field_name)
                if schedule_cell:
                    schedule_entries.extend(_schedule_entries_from_text(schedule_cell))
        else:
            weekday_text = _table_cell(table_row, header_map, "weekday")
            start_text = _table_cell(table_row, header_map, "start_time")
            end_text = _table_cell(table_row, header_map, "end_time")
            row_kind_text = _table_cell(table_row, header_map, "kind").upper() or "CLASS"
            if row_kind_text in ("EXAM", "EVENT", "DEADLINE") and not weekday_text:
                if start_text or end_text:
                    schedule_entries.append((None, start_text, end_text, room, None))
            elif weekday_text or start_text or end_text:
                combined_schedule = f"{weekday_text} {start_text}-{end_text}".strip()
                schedule_entries.extend(_schedule_entries_from_text(combined_schedule))

        important_fields = (
            "course_code",
            "title",
            "weekday",
            "start_time",
            "end_time",
            "room",
            "first_date",
            "last_date",
            "semester",
            "lecture_schedule",
            "practice_schedule",
            "schedule",
        )
        important_columns = {
            header_map[field_name]
            for field_name in important_fields
            if field_name in header_map
        }
        row_has_low_confidence = any(
            (table_row_index, column_index) in low_confidence_cells
            for column_index in important_columns
        )

        if not schedule_entries:
            invalid_rows.append(InvalidCsvRow(
                line_number=next_line_number,
                raw_text=raw_text,
                error_code="NO_SCHEDULE_DETECTED",
                error_message=(
                    "This course row has no recognizable weekday and time. "
                    "Check the schedule cells or skip the row if the course has no published time."
                ),
            ))
            next_line_number += 1
            continue

        for weekday, start_text, end_text, room_from_schedule, schedule_error in schedule_entries:
            row_line_number = next_line_number
            next_line_number += 1
            if row_has_low_confidence:
                invalid_rows.append(InvalidCsvRow(
                    line_number=row_line_number,
                    raw_text=raw_text,
                    error_code="OCR_LOW_CONFIDENCE",
                    error_message=(
                        "OCR confidence is low in a course or schedule cell. "
                        "Review and correct this session before importing it."
                    ),
                ))
                continue
            if schedule_error is not None:
                invalid_rows.append(InvalidCsvRow(
                    line_number=row_line_number,
                    raw_text=raw_text,
                    error_code="UNPARSEABLE_SCHEDULE",
                    error_message=schedule_error,
                ))
                continue

            normalized_cells = [
                course_code,
                title,
                weekday.value if weekday is not None else "",
                start_text,
                end_text,
                room_from_schedule or room or "",
                first_date,
                last_date,
                kind,
            ]
            valid_row, invalid_row = _parse_and_validate_row(
                row_line_number,
                raw_text,
                normalized_cells,
            )

            if invalid_row is not None:
                if semester and invalid_row.error_code in ("EMPTY_FIRST_DATE", "EMPTY_LAST_DATE"):
                    invalid_row.error_message = (
                        f"Academic term '{semester}' does not provide exact recurrence dates. "
                        "Enter first_date and last_date as YYYY-MM-DD before importing this class."
                    )
                invalid_rows.append(invalid_row)
            elif valid_row is not None:
                valid_rows.append(valid_row)

    return ParseBatchResult(
        import_batch_id=import_batch_id,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )


def _table_rows_from_text(raw_content: str) -> Optional[list[list[str]]]:
    """Split text or Markdown into table rows for aliased-header detection.

    Input: raw_content, decoded timetable text.
    Output: parsed rows, or None when malformed syntax needs the legacy line error path.
    Edge Cases Handled: Quoted CSV fields, Markdown divider rows, empty files, and malformed lines.
    """
    has_markdown_rows = re.search(r"(?m)^\s*\|", raw_content) is not None
    if not has_markdown_rows:
        delimited_rows = _read_delimited_table(raw_content)
        if delimited_rows or not raw_content.strip():
            return delimited_rows
        return None

    rows: list[list[str]] = []
    for line in raw_content.splitlines():
        try:
            cells = _split_line_into_cells(line)
        except ValueError:
            return None
        if cells is not None:
            rows.append(cells)
    return rows


def _parse_positional_table_rows(
    table_rows: list[list[str]],
    import_batch_id: str,
) -> ParseBatchResult:
    """Validate already-parsed rows using the locked nine-column field order.

    Input: table_rows from one CSV/Markdown read and an import batch ID.
    Output: ParseBatchResult with the same row validation used by the legacy parser.
    Edge Cases Handled: Headered/headerless canonical rows, malformed column counts, and empty rows.
    """
    valid_rows: list[ParsedCsvRow] = []
    invalid_rows: list[InvalidCsvRow] = []

    for row_number, cells in enumerate(table_rows, start=1):
        if not any(cell.strip() for cell in cells):
            continue
        if _is_header_row(cells):
            continue

        raw_text = _table_rows_to_csv([cells]).rstrip("\r\n")
        valid_row, invalid_row = _parse_and_validate_row(
            row_number,
            raw_text,
            cells,
        )
        if valid_row is not None:
            valid_rows.append(valid_row)
        elif invalid_row is not None:
            invalid_rows.append(invalid_row)

    return ParseBatchResult(
        import_batch_id=import_batch_id,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )


def _parse_headered_text_table(
    raw_content: str,
    import_batch_id: str,
) -> Optional[ParseBatchResult]:
    """Recognize common non-canonical CSV/Markdown headers before line parsing.

    Input: raw_content and an import batch ID.
    Output: a normalized ParseBatchResult, or None when no supported table header exists.
    Edge Cases Handled: Vietnamese headings, extra columns, and multi-session schedule cells.
    """
    table_rows = _table_rows_from_text(raw_content)
    if table_rows is None:
        return None

    for candidate_row in table_rows[:6]:
        if _is_canonical_nine_column_header(candidate_row):
            # Keep legacy semantics while reusing cells already read by csv.reader.
            return _parse_positional_table_rows(table_rows, import_batch_id)

    structured_result = _parse_timetable_table_rows(table_rows, import_batch_id)
    if structured_result is not None:
        return structured_result

    return _parse_positional_table_rows(table_rows, import_batch_id)


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

    structured_result = _parse_headered_text_table(raw_content, import_batch_id)
    if structured_result is not None:
        return structured_result

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


# ============================================================================
# FILE-FORMAT EXTRACTION HELPERS (PDF, IMAGE OCR, PLAIN TEXT)
# ============================================================================


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Input:
        file_bytes (bytes): Raw bytes of a PDF file.
    Output:
        str: Concatenated text extracted from all pages of the PDF.
             For pages that contain a structured table, each row is joined
             by commas (CSV-style) so downstream parsing can recognize columns.
             For pages without a table, raw text is used as a fallback.
    Edge Cases Handled:
        - pdfplumber not installed on server: raises ImportError with a clear message.
        - Password-protected / encrypted PDFs: raises ValueError.
        - PDFs where every page yields no text AND no table: raises ValueError.
        - Partial pages: pages with no content are silently skipped, not crashed on.
    """
    if not _PDFPLUMBER_AVAILABLE:
        raise ImportError(
            "pdfplumber is not installed on the server. "
            "Ask the administrator to run: pip install pdfplumber"
        )

    page_texts: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                # Try structured table extraction first (handles bordered/ruled tables)
                table = page.extract_table()
                if table:
                    # Each table row is a list of cells (may contain None for empty cells)
                    row_lines: list[str] = []
                    for table_row in table:
                        # Replace None cells with empty string, then join as CSV line
                        cleaned_cells = [
                            (cell.strip() if cell else "") for cell in table_row
                        ]
                        row_lines.append(",".join(cleaned_cells))
                    page_texts.append("\n".join(row_lines))
                else:
                    # Fallback: plain text extraction for pages without a drawn table
                    plain = page.extract_text()
                    if plain:
                        page_texts.append(plain.strip())
    except Exception as exc:
        exc_name = type(exc).__name__
        # pdfminer raises PDFPasswordIncorrect for encrypted files
        if "PDFPasswordIncorrect" in exc_name or "password" in str(exc).lower():
            raise ValueError(
                "PDF is password-protected. Please remove the password and re-upload."
            ) from exc
        # Re-raise unknown errors so the router can surface them
        raise ValueError(f"Failed to read PDF: {exc_name}: {exc}") from exc

    if not page_texts:
        raise ValueError(
            "No readable text found in PDF. "
            "The file may be scanned or image-only. Try uploading the image directly."
        )

    return "\n".join(page_texts)


def _extract_text_from_image(file_bytes: bytes) -> str:
    """
    Input:
        file_bytes (bytes): Raw bytes of an image file (PNG, JPEG, BMP, WEBP, TIFF).
    Output:
        str: Text extracted from the image via Tesseract OCR.
             Uses Vietnamese + English language models ('vie+eng') so that
             course names and labels in Vietnamese are recognized correctly.
    Edge Cases Handled:
        - Pillow or pytesseract not installed: raises ImportError.
        - Tesseract binary not found on the server: raises ValueError with admin guidance.
        - Image file is corrupt or unreadable: raises ValueError.
        - OCR finds no text (blank or non-text image): returns empty string
          (the caller / parse_timetable_content will produce 0 valid rows, not crash).
    """
    if not _OCR_AVAILABLE:
        raise ImportError(
            "Pillow and pytesseract are not installed on the server. "
            "Ask the administrator to run: pip install Pillow pytesseract"
        )

    try:
        image = Image.open(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(
            f"Cannot open image file: {type(exc).__name__}: {exc}"
        ) from exc

    try:
        extracted = pytesseract.image_to_string(image, lang="vie+eng")
    except pytesseract.TesseractNotFoundError as exc:
        raise ValueError(
            "Tesseract OCR engine is not installed on this server. "
            "Contact the system administrator to install Tesseract."
        ) from exc
    except Exception:
        try:
            extracted = pytesseract.image_to_string(image, lang="eng")
        except Exception:
            try:
                extracted = pytesseract.image_to_string(image)
            except Exception as exc:
                raise ValueError(
                    f"OCR failed on image: {type(exc).__name__}: {exc}"
                ) from exc

    return extracted


def _grid_line_positions(image: Any, horizontal: bool) -> list[int]:
    """Find long, dark table rules in a raster image using Pillow only.

    Input: image, a Pillow image; horizontal selects row rules, otherwise column rules.
    Output: sorted pixel positions for detected grid boundaries.
    Edge Cases Handled: Anti-aliased gray borders, shaded cells, and non-table images.
    """
    gray_image = image.convert("L")
    width, height = gray_image.size
    pixels = gray_image.load()
    axis_length = height if horizontal else width
    scan_length = width if horizontal else height
    # A real table rule spans most of the scan axis; this rejects ordinary text strokes.
    required_dark_pixels = int(scan_length * 0.72)
    candidate_positions: list[int] = []

    for axis_position in range(axis_length):
        dark_pixel_count = 0
        for scan_position in range(scan_length):
            x_position = scan_position if horizontal else axis_position
            y_position = axis_position if horizontal else scan_position
            if pixels[x_position, y_position] < 242:
                dark_pixel_count += 1
        if dark_pixel_count >= required_dark_pixels:
            candidate_positions.append(axis_position)

    grouped_positions: list[int] = []
    group_start: Optional[int] = None
    previous_position: Optional[int] = None

    for position in candidate_positions:
        if group_start is None:
            group_start = position
        elif previous_position is not None and position > previous_position + 2:
            # Collapse a slightly anti-aliased rule into one boundary coordinate.
            grouped_positions.append((group_start + previous_position) // 2)
            group_start = position
        previous_position = position

    if group_start is not None and previous_position is not None:
        grouped_positions.append((group_start + previous_position) // 2)

    if len(grouped_positions) < 2:
        return []

    if grouped_positions[0] > 2:
        grouped_positions.insert(0, 0)
    if grouped_positions[-1] < axis_length - 3:
        grouped_positions.append(axis_length - 1)
    return grouped_positions


def _coordinate_band_index(coordinate: float, boundaries: list[int]) -> Optional[int]:
    """Return the interval containing one OCR coordinate.

    Input: coordinate, a text-box center; boundaries, sorted table grid positions.
    Output: the zero-based cell interval, or None if the coordinate is outside the grid.
    Edge Cases Handled: Coordinates on outer borders and images with incomplete grids.
    """
    for band_index in range(len(boundaries) - 1):
        if boundaries[band_index] <= coordinate < boundaries[band_index + 1]:
            return band_index
    return None


def _extract_image_table_rows(
    image: Any,
) -> Optional[tuple[list[list[str]], set[tuple[int, int]]]]:
    """Use OCR word coordinates and detected grid lines to rebuild table cells.

    Input: image, a readable Pillow image.
    Output: table rows plus low-confidence cell coordinates, or None when no grid is found.
    Edge Cases Handled: Multiline cells, Vietnamese/English OCR, empty cells, low confidence,
    and OCR errors.
    """
    if not _OCR_AVAILABLE:
        raise ImportError(
            "Pillow and pytesseract are required to read timetable images."
        )

    horizontal_boundaries = _grid_line_positions(image, horizontal=True)
    vertical_boundaries = _grid_line_positions(image, horizontal=False)
    if len(horizontal_boundaries) < 2 or len(vertical_boundaries) < 2:
        return None

    try:
        ocr_data = pytesseract.image_to_data(
            image,
            lang="vie+eng",
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as error:
        raise ValueError(
            "Tesseract OCR engine is not installed on this server."
        ) from error
    except Exception as error:
        raise ValueError(
            f"OCR table extraction failed: {type(error).__name__}: {error}"
        ) from error

    row_count = len(horizontal_boundaries) - 1
    column_count = len(vertical_boundaries) - 1
    cell_words: list[list[list[tuple[int, int, str]]]] = [
        [[] for _ in range(column_count)] for _ in range(row_count)
    ]
    low_confidence_cells: set[tuple[int, int]] = set()

    word_count = len(ocr_data.get("text", []))
    for word_index in range(word_count):
        word = str(ocr_data["text"][word_index]).strip()
        if not word:
            continue

        try:
            left = int(ocr_data["left"][word_index])
            top = int(ocr_data["top"][word_index])
            word_width = int(ocr_data["width"][word_index])
            word_height = int(ocr_data["height"][word_index])
        except (KeyError, TypeError, ValueError, IndexError):
            continue

        column_index = _coordinate_band_index(
            left + (word_width / 2),
            vertical_boundaries,
        )
        row_index = _coordinate_band_index(
            top + (word_height / 2),
            horizontal_boundaries,
        )
        if column_index is None or row_index is None:
            continue

        cell_words[row_index][column_index].append((top, left, word))
        confidence_values = ocr_data.get("conf", [])
        confidence = 100.0
        if word_index < len(confidence_values):
            try:
                confidence = float(confidence_values[word_index])
            except (TypeError, ValueError):
                confidence = 0.0
        if confidence < 45:
            low_confidence_cells.add((row_index, column_index))

    table_rows: list[list[str]] = []
    for row in cell_words:
        table_cells: list[str] = []
        for words_in_cell in row:
            words_in_cell.sort(key=lambda item: (item[0], item[1]))
            table_cells.append(" ".join(word for _, _, word in words_in_cell))
        table_rows.append(table_cells)

    return table_rows, low_confidence_cells


def extract_raw_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    Public dispatcher: reads file_bytes according to the file extension inferred
    from filename and returns the raw text string for downstream timetable parsing.

    Input:
        file_bytes (bytes): Raw bytes of the uploaded file.
        filename   (str):   Original filename including extension (e.g. 'schedule.pdf').
                            Extension determines which extraction strategy is used.
    Output:
        str: Decoded/extracted text content of the file.
    Edge Cases Handled:
        - .pdf  → PDF table/text extraction via pdfplumber.
        - .png, .jpg, .jpeg, .webp, .bmp, .tiff, .tif → OCR via pytesseract + Pillow.
        - .csv, .txt, .md → UTF-8 decode with latin-1 fallback.
        - Unknown / unsupported extension → raises ValueError immediately.
        - Filename with no extension (or empty filename) → treated as plain text.
    """
    ext = Path(filename).suffix.lower()  # e.g. '' or '.pdf' or '.PNG'

    # --- PDF ---
    if ext == ".pdf":
        return _extract_text_from_pdf(file_bytes)

    # --- Image (OCR) ---
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
        return _extract_text_from_image(file_bytes)

    # --- Plain text formats: CSV, Markdown, plain text ---
    if ext in (".csv", ".txt", ".md", ""):
        # Try UTF-8 first (most common), fall back to latin-1 for legacy Windows files
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1")

    # --- Everything else is unsupported ---
    raise ValueError(
        f"Unsupported file type '{ext}'. "
        "Accepted formats: .csv, .txt, .md (plain text), .pdf, "
        ".png, .jpg, .jpeg, .webp, .bmp, .tiff, .tif (image OCR)."
    )


def _read_delimited_table(raw_content: str) -> list[list[str]]:
    """Read a complete delimited document so quoted cells may contain line breaks.

    Input: raw_content, decoded CSV/TSV/semicolon-delimited text.
    Output: trimmed rows from csv.reader using a detected common delimiter.
    Edge Cases Handled: UTF-8 BOM, quoted commas/newlines, and unknown dialects.
    """
    sample = raw_content[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    try:
        reader = csv.reader(io.StringIO(raw_content), dialect, strict=True)
        return [[cell.strip().lstrip("\ufeff") for cell in row] for row in reader]
    except csv.Error:
        # Let the established line parser isolate malformed quote syntax by source line.
        return []


def _table_rows_to_csv(table_rows: list[list[str]]) -> str:
    """Serialize extracted cells safely before passing them through the old row validator.

    Input: table_rows, extracted cells from PDF or image table recognition.
    Output: CSV text with quoted commas and empty cells preserved.
    Edge Cases Handled: Commas, quotes, and optional empty cells in table content.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(table_rows)
    return output.getvalue()


def _combine_parse_results(
    import_batch_id: str,
    results: list[ParseBatchResult],
) -> ParseBatchResult:
    """Merge page/table parse results while assigning unique preview line numbers.

    Input: import_batch_id and ordered parser results from one uploaded file.
    Output: one ParseBatchResult using the original model contract.
    Edge Cases Handled: Repeated page line numbers and multiple sessions expanded from one row.
    """
    valid_rows: list[ParsedCsvRow] = []
    invalid_rows: list[InvalidCsvRow] = []
    next_line_number = 1

    for result in results:
        combined_items: list[ParsedCsvRow | InvalidCsvRow] = []
        combined_items.extend(result.valid_rows)
        combined_items.extend(result.invalid_rows)
        combined_items.sort(key=lambda item: item.line_number)

        for item in combined_items:
            item.line_number = next_line_number
            next_line_number += 1
            if isinstance(item, ParsedCsvRow):
                valid_rows.append(item)
            else:
                invalid_rows.append(item)

    valid_rows.sort(key=lambda row: row.line_number)
    invalid_rows.sort(key=lambda row: row.line_number)
    return ParseBatchResult(
        import_batch_id=import_batch_id,
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
    )


def _result_has_rows(result: ParseBatchResult) -> bool:
    """Return whether parsing produced any valid or flagged row.

    Input: result, one ParseBatchResult.
    Output: True when a row is available for preview.
    Edge Cases Handled: Empty documents and documents containing only headers.
    """
    return bool(result.valid_rows or result.invalid_rows)


def _no_timetable_result(import_batch_id: str, filename: str) -> ParseBatchResult:
    """Create a visible parser error instead of silently accepting an unrelated image.

    Input: import_batch_id and uploaded filename.
    Output: ParseBatchResult with one NO_TIMETABLE_DETECTED invalid row.
    Edge Cases Handled: Blank or unrelated images that produce no text or table rows.
    """
    return ParseBatchResult(
        import_batch_id=import_batch_id,
        valid_rows=[],
        invalid_rows=[InvalidCsvRow(
            line_number=1,
            raw_text=filename,
            error_code="NO_TIMETABLE_DETECTED",
            error_message=(
                "No timetable table or recognizable weekday/time entries were detected. "
                "Upload a clearer timetable image or PDF."
            ),
        )],
    )


def _parse_pdf_timetable(file_bytes: bytes, filename: str) -> ParseBatchResult:
    """Parse PDF tables, text, or scanned pages into the existing row contract.

    Input: file_bytes and filename for one uploaded PDF.
    Output: one ParseBatchResult spanning all readable pages.
    Edge Cases Handled: Multiple tables/pages, repeated headers, scanned pages, and OCR failures.
    """
    if not _PDFPLUMBER_AVAILABLE:
        raise ImportError(
            "pdfplumber is not installed on the server. Install the backend PDF dependencies."
        )

    import_batch_id = uuid.uuid4().hex[:16]
    page_results: list[ParseBatchResult] = []

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_had_table = False
                try:
                    extracted_tables = page.extract_tables()
                except Exception as error:
                    extracted_tables = []
                    page_results.append(ParseBatchResult(
                        import_batch_id=import_batch_id,
                        invalid_rows=[InvalidCsvRow(
                            line_number=page_number,
                            raw_text=f"{filename} page {page_number}",
                            error_code="PDF_TABLE_EXTRACTION_FAILED",
                            error_message=(
                                f"Could not extract table structure: {type(error).__name__}: {error}"
                            ),
                        )],
                    ))

                for extracted_table in extracted_tables or []:
                    page_had_table = True
                    table_rows = [
                        [(cell or "").replace("\n", " ").strip() for cell in row]
                        for row in extracted_table
                    ]
                    parsed_table = _parse_timetable_table_rows(
                        table_rows,
                        import_batch_id,
                    )
                    if parsed_table is not None:
                        page_results.append(parsed_table)
                    else:
                        page_results.append(
                            _parse_positional_table_rows(table_rows, import_batch_id)
                        )

                if page_had_table:
                    continue

                page_text = page.extract_text() or ""
                if page_text.strip():
                    page_results.append(parse_timetable_content(page_text, filename))
                    continue

                if not _OCR_AVAILABLE:
                    page_results.append(ParseBatchResult(
                        import_batch_id=import_batch_id,
                        invalid_rows=[InvalidCsvRow(
                            line_number=page_number,
                            raw_text=f"{filename} page {page_number}",
                            error_code="PDF_PAGE_REQUIRES_OCR",
                            error_message=(
                                "This PDF page is image-only. Install Pillow and pytesseract "
                                "with the Vietnamese OCR language data to read it."
                            ),
                        )],
                    ))
                    continue

                try:
                    page_image = page.to_image(resolution=220).original
                    image_table = _extract_image_table_rows(page_image)
                    if image_table is not None:
                        table_rows, low_confidence_cells = image_table
                        parsed_table = _parse_timetable_table_rows(
                            table_rows,
                            import_batch_id,
                            low_confidence_cells=low_confidence_cells,
                        )
                        if parsed_table is not None:
                            page_results.append(parsed_table)
                            continue
                        table_result = _parse_positional_table_rows(
                            table_rows,
                            import_batch_id,
                        )
                        if _result_has_rows(table_result):
                            page_results.append(table_result)
                            continue

                    page_ocr_text = pytesseract.image_to_string(page_image, lang="vie+eng")
                    page_results.append(parse_timetable_content(page_ocr_text, filename))
                except Exception as error:
                    page_results.append(ParseBatchResult(
                        import_batch_id=import_batch_id,
                        invalid_rows=[InvalidCsvRow(
                            line_number=page_number,
                            raw_text=f"{filename} page {page_number}",
                            error_code="PDF_PAGE_OCR_FAILED",
                            error_message=f"Could not read this scanned page: {type(error).__name__}: {error}",
                        )],
                    ))
    except Exception as error:
        if "PDFPasswordIncorrect" in type(error).__name__ or "password" in str(error).lower():
            raise ValueError(
                "PDF is password-protected. Remove its password and upload it again."
            ) from error
        if isinstance(error, (ImportError, ValueError)):
            raise
        raise ValueError(
            f"Failed to read PDF: {type(error).__name__}: {error}"
        ) from error

    combined = _combine_parse_results(import_batch_id, page_results)
    if _result_has_rows(combined):
        has_only_unstructured_lines = bool(combined.invalid_rows) and all(
            row.error_code == "INVALID_COLUMN_COUNT" for row in combined.invalid_rows
        )
        if (
            not combined.valid_rows
            and has_only_unstructured_lines
            and not _SCHEDULE_WEEKDAY_RE.search(
                " ".join(row.raw_text.upper() for row in combined.invalid_rows)
            )
            and not _TIME_RANGE_RE.search(
                " ".join(row.raw_text for row in combined.invalid_rows)
            )
        ):
            return _no_timetable_result(import_batch_id, filename)
        return combined
    return _no_timetable_result(import_batch_id, filename)


def parse_timetable_file(file_bytes: bytes, filename: str) -> ParseBatchResult:
    """Parse one uploaded timetable file through its format-specific reader.

    Input: file_bytes and filename for one CSV, TXT, Markdown, PDF, or image file.
    Output: ParseBatchResult containing valid ParsedCsvRow values and isolated invalid rows.
    Edge Cases Handled: Aliased headers, multiline cells, multiple sessions per course,
    scanned PDFs, empty images, unsupported extensions, and the existing canonical CSV format.
    """
    extension = Path(filename).suffix.lower()
    import_batch_id = uuid.uuid4().hex[:16]

    if extension == ".pdf":
        return _parse_pdf_timetable(file_bytes, filename)

    if extension in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
        if not _OCR_AVAILABLE:
            raise ImportError(
                "Pillow and pytesseract are required to read timetable images."
            )
        image_table: Optional[tuple[list[list[str]], set[tuple[int, int]]]] = None
        try:
            with Image.open(io.BytesIO(file_bytes)) as image:
                image_table = _extract_image_table_rows(image)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(
                f"Cannot read image file: {type(error).__name__}: {error}"
            ) from error

        if image_table is not None:
            table_rows, low_confidence_cells = image_table
            structured_result = _parse_timetable_table_rows(
                table_rows,
                import_batch_id,
                low_confidence_cells=low_confidence_cells,
            )
            if structured_result is not None:
                return structured_result
            table_result = _parse_positional_table_rows(table_rows, import_batch_id)
            if table_result.valid_rows:
                return table_result
            if any(row.error_code != "INVALID_COLUMN_COUNT" for row in table_result.invalid_rows):
                return table_result
            table_text = " ".join(cell for row in table_rows for cell in row).upper()
            if _SCHEDULE_WEEKDAY_RE.search(table_text) or _TIME_RANGE_RE.search(table_text):
                return table_result

        extracted_text = _extract_text_from_image(file_bytes)
        result = parse_timetable_content(extracted_text, filename)
        if result.valid_rows:
            return result
        if any(row.error_code != "INVALID_COLUMN_COUNT" for row in result.invalid_rows):
            return result
        if _SCHEDULE_WEEKDAY_RE.search(extracted_text.upper()) or _TIME_RANGE_RE.search(extracted_text):
            return result
        return _no_timetable_result(import_batch_id, filename)

    extracted_text = extract_raw_text_from_file(file_bytes, filename)
    return parse_timetable_content(extracted_text, filename)
