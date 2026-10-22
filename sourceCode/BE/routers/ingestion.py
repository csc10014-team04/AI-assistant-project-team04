# owners: Lam (step 1: upload & preview parsing) + Khoi (step 2: conflict resolution & db commit)
import sys
from datetime import date, time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator

# Ensure the BE directory is in sys.path so 'models' and 'services' can be imported
CURRENT_DIR = Path(__file__).resolve().parent
BE_DIR = CURRENT_DIR.parent
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from models import CsvRowKind, InvalidCsvRow, ParsedCsvRow, Weekday
from services.parser import export_valid_rows_to_csv, parse_timetable_content

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


# ============================================================================
# PYDANTIC SCHEMAS
# Separate from models.py dataclasses — these are JSON input/output schemas only
# ============================================================================


class ParsedCsvRowSchema(BaseModel):
    """
    JSON-serializable representation of a single validated schedule row.
    Mirrors ParsedCsvRow dataclass from models.py, but uses str for date/time
    so FastAPI can serialize and deserialize them easily.
    """
    line_number: int
    course_code: str
    title: str
    kind: str  # One of: CLASS, EXAM, DEADLINE, EVENT
    start_time: str = Field(description="24-hour format HH:MM")
    end_time: str = Field(description="24-hour format HH:MM")
    first_date: str = Field(description="YYYY-MM-DD")
    last_date: str = Field(description="YYYY-MM-DD")
    weekday: Optional[str] = None  # MON, TUE, WED, THU, FRI, SAT, SUN — or empty
    room: Optional[str] = None


class InvalidCsvRowSchema(BaseModel):
    """
    JSON-serializable representation of an isolated malformed row.
    The frontend uses line_number to highlight the row, error_code for logic,
    and error_message to display a human-readable hint to the user.
    """
    line_number: int
    raw_text: str
    error_code: str
    error_message: str


class ParsePreviewTextRequest(BaseModel):
    """
    Optional JSON body alternative for parse-preview when the client sends raw
    text instead of uploading a binary file.
    """
    raw_content: str = Field(description="The full text content of the timetable file")
    filename: str = Field(default="", description="Optional original filename for format hints")


class ParsePreviewResponse(BaseModel):
    """
    Response contract for the parse-preview endpoint.
    import_batch_id is the session key that must be echoed back in resolve-preview.
    """
    import_batch_id: str
    valid_count: int
    invalid_count: int
    valid_rows: list[ParsedCsvRowSchema]
    invalid_rows: list[InvalidCsvRowSchema]


class CorrectedRowPayload(BaseModel):
    """
    A single row the user has manually corrected in the app's preview UI.
    All fields are plain strings so the router re-validates them through
    the same parser logic to guarantee correctness before accepting.
    """
    line_number: int = Field(description="Must match the original line_number from the parse-preview response")
    course_code: str
    title: str
    kind: str = Field(description="One of: CLASS, EXAM, DEADLINE, EVENT")
    start_time: str = Field(description="24-hour format HH:MM")
    end_time: str = Field(description="24-hour format HH:MM")
    first_date: str = Field(description="YYYY-MM-DD")
    last_date: str = Field(description="YYYY-MM-DD")
    weekday: Optional[str] = None
    room: Optional[str] = None


class ResolvePreviewRequest(BaseModel):
    """
    Request body for the resolve-preview endpoint.
    The client sends back the original batch ID, the confirmed valid rows,
    any user-corrected rows, and the line numbers the user chose to skip.
    """
    import_batch_id: str = Field(description="The batch ID returned by parse-preview")
    valid_rows: list[ParsedCsvRowSchema] = Field(
        description="The original valid rows from parse-preview that the user confirmed without changes"
    )
    corrected_rows: list[CorrectedRowPayload] = Field(
        default_factory=list,
        description="Rows the user edited on the preview screen — will be re-validated"
    )
    skipped_line_numbers: list[int] = Field(
        default_factory=list,
        description="Line numbers the user explicitly chose to discard (e.g. garbage comment rows)"
    )


class ResolvePreviewResponse(BaseModel):
    """
    Response contract for resolve-preview.
    all_valid_rows is the unified, 100% clean list that Khoi's module
    (detect_import_conflicts) will consume in Step 2.3.
    exported_csv is the normalized CSV string ready for any downstream processing.
    """
    import_batch_id: str
    total_accepted: int
    all_valid_rows: list[ParsedCsvRowSchema]
    exported_csv: str


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _domain_to_schema(row: ParsedCsvRow) -> ParsedCsvRowSchema:
    """
    Input:
        row (ParsedCsvRow): A validated domain dataclass from the parser.
    Output:
        ParsedCsvRowSchema: A Pydantic schema with date/time serialized to strings.
    Edge Cases Handled:
        - weekday and room are Optional — written as None if missing.
    """
    return ParsedCsvRowSchema(
        line_number=row.line_number,
        course_code=row.course_code,
        title=row.title,
        kind=row.kind.value,
        start_time=row.start_time.strftime("%H:%M"),
        end_time=row.end_time.strftime("%H:%M"),
        first_date=row.first_date.isoformat(),
        last_date=row.last_date.isoformat(),
        weekday=row.weekday.value if row.weekday else None,
        room=row.room,
    )


def _invalid_to_schema(row: InvalidCsvRow) -> InvalidCsvRowSchema:
    """
    Input:
        row (InvalidCsvRow): An isolated malformed row from the parser.
    Output:
        InvalidCsvRowSchema: The same data wrapped in a Pydantic schema for JSON output.
    Edge Cases Handled: None — all fields are plain strings.
    """
    return InvalidCsvRowSchema(
        line_number=row.line_number,
        raw_text=row.raw_text,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _corrected_payload_to_csv_line(payload: CorrectedRowPayload) -> str:
    """
    Input:
        payload (CorrectedRowPayload): A user-edited row submitted by the Android app.
    Output:
        str: A single CSV-formatted line with 9 fields, ready to be re-parsed
             by parse_timetable_content to enforce the same validation rules.
    Edge Cases Handled:
        - weekday and room are optional: written as empty string when None.
        - Uses csv.writer to safely quote values containing commas or special chars.
    """
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        payload.course_code,
        payload.title,
        payload.weekday if payload.weekday else "",
        payload.start_time,
        payload.end_time,
        payload.room if payload.room else "",
        payload.first_date,
        payload.last_date,
        payload.kind,
    ])
    # csv.writer adds a trailing newline — strip it before returning
    return buffer.getvalue().strip()


def _revalidate_corrected_rows(
    corrected_rows: list[CorrectedRowPayload],
) -> tuple[list[ParsedCsvRow], list[InvalidCsvRowSchema]]:
    """
    Input:
        corrected_rows (list[CorrectedRowPayload]): User-edited rows from the resolve request.
    Output:
        tuple:
            - list[ParsedCsvRow]: Rows that passed re-validation.
            - list[InvalidCsvRowSchema]: Rows that still failed after the user's edit,
              returned to the caller so the API can report them clearly.
    Edge Cases Handled:
        - If the user corrects a row but still enters an invalid time format, the row
          is re-isolated and returned in the still_invalid list rather than silently dropped.
        - Each corrected row is rebuilt as a single CSV line and fed back through
          parse_timetable_content to reuse all existing validation logic.
    """
    from services.parser import _parse_and_validate_row, _split_line_into_cells

    accepted: list[ParsedCsvRow] = []
    still_invalid: list[InvalidCsvRowSchema] = []

    for corrected in corrected_rows:
        csv_line = _corrected_payload_to_csv_line(corrected)
        try:
            cells = _split_line_into_cells(csv_line)
        except ValueError as err:
            still_invalid.append(InvalidCsvRowSchema(
                line_number=corrected.line_number,
                raw_text=csv_line,
                error_code="MALFORMED_LINE_SYNTAX",
                error_message=str(err),
            ))
            continue

        if cells is None:
            # Should never happen for a user-submitted row, but guard anyway
            still_invalid.append(InvalidCsvRowSchema(
                line_number=corrected.line_number,
                raw_text=csv_line,
                error_code="EMPTY_CORRECTED_ROW",
                error_message="The corrected row appears to be empty after parsing",
            ))
            continue

        valid_row, invalid_row = _parse_and_validate_row(corrected.line_number, csv_line, cells)

        if valid_row is not None:
            accepted.append(valid_row)
        else:
            still_invalid.append(InvalidCsvRowSchema(
                line_number=invalid_row.line_number,
                raw_text=invalid_row.raw_text,
                error_code=invalid_row.error_code,
                error_message=invalid_row.error_message,
            ))

    return accepted, still_invalid


def _schema_to_domain(schema: ParsedCsvRowSchema) -> ParsedCsvRow:
    """
    Input:
        schema (ParsedCsvRowSchema): A validated Pydantic row schema from the request body.
    Output:
        ParsedCsvRow: Domain dataclass used by export_valid_rows_to_csv.
    Edge Cases Handled:
        - Parses time strings ("HH:MM") and date strings ("YYYY-MM-DD") safely.
        - Converts weekday string to Weekday enum or None.
        - Raises HTTPException 422 if any field is malformed (should not happen
          since client echoes back what the server sent, but guards against tampering).
    """
    try:
        parsed_start = time.fromisoformat(schema.start_time)
        parsed_end = time.fromisoformat(schema.end_time)
        parsed_first = date.fromisoformat(schema.first_date)
        parsed_last = date.fromisoformat(schema.last_date)
        parsed_kind = CsvRowKind(schema.kind.upper())
    except (ValueError, KeyError) as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tampered or invalid field in valid_rows at line {schema.line_number}: {str(err)}",
        )

    parsed_weekday: Optional[Weekday] = None
    if schema.weekday:
        try:
            parsed_weekday = Weekday(schema.weekday.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid weekday '{schema.weekday}' in valid_rows at line {schema.line_number}",
            )

    return ParsedCsvRow(
        line_number=schema.line_number,
        course_code=schema.course_code,
        title=schema.title,
        kind=parsed_kind,
        start_time=parsed_start,
        end_time=parsed_end,
        first_date=parsed_first,
        last_date=parsed_last,
        weekday=parsed_weekday,
        room=schema.room if schema.room else None,
    )


# ============================================================================
# LAM'S ENDPOINTS: STEP 2.1 (parse-preview) & STEP 2.2 (resolve-preview)
# ============================================================================


@router.post(
    "/parse-preview",
    response_model=ParsePreviewResponse,
    summary="Upload a timetable file and get a preview with valid and invalid rows",
    description=(
        "Accepts either a file upload (multipart/form-data) or a raw text JSON body. "
        "Returns valid rows (green) and invalid rows (yellow) for the student to review "
        "before confirming import. Never crashes on malformed lines."
    ),
)
async def parse_preview(
    file: Optional[UploadFile] = File(default=None, description="Upload a .csv, .md, or .txt timetable file"),
    raw_content: Optional[str] = Form(default=None, description="Alternative: paste raw timetable text"),
) -> ParsePreviewResponse:
    """
    Input:
        file (UploadFile, optional): Uploaded timetable file (.csv, .md, .txt).
        raw_content (str, optional): Raw timetable text sent as a form field.
        Exactly one of these two must be provided.
    Output:
        ParsePreviewResponse: Contains import_batch_id, valid_rows, and invalid_rows.
    Edge Cases Handled:
        - Both file and raw_content absent: returns HTTP 422.
        - File too large to read: returns HTTP 413 with a clear message.
        - File encoding other than UTF-8: attempts latin-1 fallback before failing.
        - Completely empty file or content: returns valid/invalid lists both empty,
          still with a valid import_batch_id (so the client can render an empty preview).
    """
    # 1. Resolve content source: file upload takes priority over raw_content form field
    if file is not None:
        file_bytes = await file.read()

        # Guard against suspiciously large files (10 MB limit)
        MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
        if len(file_bytes) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds the 10 MB limit. Please split the timetable into smaller files.",
            )

        # Attempt UTF-8 decoding first, then fall back to latin-1 for older exports
        try:
            content_str = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content_str = file_bytes.decode("latin-1")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Could not decode file. Please save the file as UTF-8 and re-upload.",
                )

        filename = file.filename or ""

    elif raw_content is not None and raw_content.strip():
        content_str = raw_content
        filename = ""

    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No timetable content provided. "
                "Send either a file upload via 'file' or paste text via 'raw_content'."
            ),
        )

    # 2. Run the parser — never raises exceptions, always returns ParseBatchResult
    batch_result = parse_timetable_content(content_str, filename)

    # 3. Convert domain dataclasses to JSON-serializable Pydantic schemas
    valid_schemas = [_domain_to_schema(row) for row in batch_result.valid_rows]
    invalid_schemas = [_invalid_to_schema(row) for row in batch_result.invalid_rows]

    return ParsePreviewResponse(
        import_batch_id=batch_result.import_batch_id,
        valid_count=len(valid_schemas),
        invalid_count=len(invalid_schemas),
        valid_rows=valid_schemas,
        invalid_rows=invalid_schemas,
    )


@router.post(
    "/resolve-preview",
    response_model=ResolvePreviewResponse,
    summary="Confirm corrected rows and produce a final clean list for conflict detection",
    description=(
        "Accepts the batch ID from parse-preview, the unchanged valid rows, user-corrected rows, "
        "and line numbers the user chose to skip. Re-validates all corrected rows through the same "
        "parser logic. Returns a unified list[ParsedCsvRow] and exported CSV ready for Khoi's "
        "conflict detection step (Step 2.3)."
    ),
)
async def resolve_preview(body: ResolvePreviewRequest) -> ResolvePreviewResponse:
    """
    Input:
        body (ResolvePreviewRequest): JSON containing import_batch_id, valid_rows,
                                      corrected_rows, and skipped_line_numbers.
    Output:
        ResolvePreviewResponse: A unified 100% clean list of ParsedCsvRow objects
                                and their exported CSV string for Khoi's module.
    Edge Cases Handled:
        - corrected_rows that still fail validation after user's edit are rejected with
          a 422 error listing which specific lines are still invalid and why — never
          silently merges a bad row into the clean output.
        - skipped_line_numbers are filtered out of both valid_rows and corrected_rows,
          giving the user the ability to permanently discard garbage comment lines.
        - Duplicate line_numbers between valid_rows and corrected_rows: corrected row
          takes precedence (the user's edited version overrides the original).
        - Rows are sorted by line_number in the final output for predictable ordering.
        - Empty corrected_rows and empty skipped_line_numbers are valid inputs
          (user accepted everything or rejected everything).
    """
    # 1. Build a set of line numbers to skip — O(1) lookup
    skip_set: set[int] = set(body.skipped_line_numbers)

    # 2. Re-validate all corrected rows through the same parser validator
    corrected_non_skipped = [row for row in body.corrected_rows if row.line_number not in skip_set]
    revalidated_rows, still_invalid = _revalidate_corrected_rows(corrected_non_skipped)

    # If any corrected row is still invalid after the user's edit, reject the entire
    # resolve request and tell the user exactly which lines need more attention.
    # Why: We must guarantee 100% data quality at this handoff point to Khoi's module.
    if still_invalid:
        details = [
            f"Line {err.line_number}: [{err.error_code}] {err.error_message}"
            for err in still_invalid
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "Some corrected rows are still invalid. "
                    "Please fix them in the app before confirming."
                ),
                "still_invalid_rows": details,
            },
        )

    # 3. Collect line numbers provided by successfully re-validated corrected rows
    # These line numbers "override" any original valid row with the same line number
    corrected_line_numbers: set[int] = {row.line_number for row in revalidated_rows}

    # 4. Convert the unchanged valid_rows from Pydantic schema back to domain dataclasses,
    # but filter out: (a) skipped lines and (b) lines already replaced by a corrected row
    confirmed_original: list[ParsedCsvRow] = []
    for schema_row in body.valid_rows:
        if schema_row.line_number in skip_set:
            # User explicitly skipped this line — discard
            continue
        if schema_row.line_number in corrected_line_numbers:
            # This line was also submitted as a corrected row — let the corrected version win
            continue
        confirmed_original.append(_schema_to_domain(schema_row))

    # 5. Merge: original confirmed rows + re-validated corrected rows
    all_clean_rows = confirmed_original + revalidated_rows

    # 6. Sort by original line_number for deterministic, predictable output ordering
    all_clean_rows.sort(key=lambda row: row.line_number)

    # 7. Serialize to the standard 9-column CSV string for Khoi's module
    exported_csv = export_valid_rows_to_csv(all_clean_rows)

    # 8. Convert domain dataclasses back to Pydantic schema for JSON response
    all_schemas = [_domain_to_schema(row) for row in all_clean_rows]

    return ResolvePreviewResponse(
        import_batch_id=body.import_batch_id,
        total_accepted=len(all_clean_rows),
        all_valid_rows=all_schemas,
        exported_csv=exported_csv,
    )
