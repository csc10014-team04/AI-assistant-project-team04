import csv
import io
import sys
from dataclasses import asdict
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# ensure be root directory is in sys.path so models, database, and services can be imported
CURRENT_DIR = Path(__file__).resolve().parent
BE_DIR = CURRENT_DIR.parent
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from database import active_events_stmt, from_db_to_vn, get_db  # noqa: E402
from models import (  # noqa: E402
    CsvRowKind,
    EventDomain,
    EventKind,
    EventSource,
    InvalidCsvRow,
    ParsedCsvRow,
    User,
    Weekday,
)
from services.parser import (  # noqa: E402
    _parse_and_validate_row,
    _split_line_into_cells,
    export_valid_rows_to_csv,
    parse_timetable_content,
)
from services.security import get_current_user  # noqa: E402
from services.validator import commit_resolved_import, detect_import_conflicts  # noqa: E402

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


# ============================================================================
# PART 1: PYDANTIC SCHEMAS FOR STEP 1 (parse-preview) & STEP 2 (resolve-preview)
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
    all_valid_rows is the unified, 100% clean list that detect_import_conflicts
    will consume in Step 3.
    exported_csv is the normalized CSV string ready for any downstream processing.
    """
    import_batch_id: str
    total_accepted: int
    all_valid_rows: list[ParsedCsvRowSchema]
    exported_csv: str


# ============================================================================
# PART 2: PYDANTIC SCHEMAS FOR STEP 3 (check-conflicts) & STEP 4 (commit)
# ============================================================================


class CsvRowPayload(BaseModel):
    line_number: int = Field(default=1, ge=1)
    course_code: str
    title: str
    kind: CsvRowKind
    start_time: time
    end_time: time
    first_date: date
    last_date: date
    weekday: Weekday | None = None
    room: str | None = None

    def to_domain(self) -> ParsedCsvRow:
        """convert request payload item into ParsedCsvRow dataclass"""
        return ParsedCsvRow(
            line_number=self.line_number,
            course_code=self.course_code,
            title=self.title,
            kind=self.kind,
            start_time=self.start_time,
            end_time=self.end_time,
            first_date=self.first_date,
            last_date=self.last_date,
            weekday=self.weekday,
            room=self.room,
        )


class CheckConflictsRequest(BaseModel):
    incoming_rows: list[CsvRowPayload]
    replace_previous_imports: bool = False


class CommitImportRequest(BaseModel):
    import_batch_id: str = Field(..., min_length=1, max_length=64)
    resolved_rows: list[CsvRowPayload]
    replace_previous_imports: bool = False


class EventResponseItem(BaseModel):
    id: int | None
    owner_id: int
    title: str
    start_time: datetime
    end_time: datetime
    kind: EventKind
    source: EventSource
    is_hard: bool
    priority: int
    room: str | None = None
    course_id: int | None = None
    task_id: int | None = None
    proposal_id: int | None = None
    import_batch_id: str | None = None
    is_important: bool = False


class CommitImportResponse(BaseModel):
    import_batch_id: str
    created_count: int
    events: list[EventResponseItem]


# ============================================================================
# PART 3: HELPER FUNCTIONS
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
        payload (CorrectedRowPayload): A user-edited row submitted by the frontend app.
    Output:
        str: A single CSV-formatted line with 9 fields, ready to be re-parsed
             by parse_timetable_content to enforce the same validation rules.
    Edge Cases Handled:
        - weekday and room are optional: written as empty string when None.
        - Uses csv.writer to safely quote values containing commas or special chars.
    """
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
    """
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
        elif invalid_row is not None:
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


def _serialize_conflict_option(option: ParsedCsvRow | EventDomain) -> dict[str, Any]:
    """serialize either a ParsedCsvRow or EventDomain with vn_tz timestamps"""
    if isinstance(option, ParsedCsvRow):
        data = asdict(option)
        data["option_type"] = "incoming_row"
        return data
    return {
        "option_type": "existing_event",
        "id": option.id,
        "owner_id": option.owner_id,
        "title": option.title,
        "start_time": from_db_to_vn(option.start_time).isoformat(),
        "end_time": from_db_to_vn(option.end_time).isoformat(),
        "kind": option.kind,
        "source": option.source,
        "is_hard": option.is_hard,
        "priority": option.priority,
        "room": option.room,
        "course_id": option.course_id,
    }


# ============================================================================
# PART 4: ENDPOINTS 1 & 2 (PARSE-PREVIEW & RESOLVE-PREVIEW)
# ============================================================================


@router.post(
    "/parse-preview",
    response_model=ParsePreviewResponse,
    summary="Upload a timetable file and get a preview with valid and invalid rows",
    description=(
        "Accepts either a file upload (multipart/form-data) or a raw text form field. "
        "Returns valid rows (green) and invalid rows (yellow) for the student to review "
        "before confirming import. Never crashes on malformed lines."
    ),
)
async def parse_preview(
    file: Optional[UploadFile] = File(default=None, description="Upload a .csv, .md, or .txt timetable file"),
    raw_content: Optional[str] = Form(default=None, description="Alternative: paste raw timetable text"),
) -> ParsePreviewResponse:
    # 1. Resolve content source: file upload takes priority over raw_content form field
    if file is not None:
        file_bytes = await file.read()

        MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
        if len(file_bytes) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds the 10 MB limit. Please split the timetable into smaller files.",
            )

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
        "parser logic. Returns a unified list[ParsedCsvRow] and exported CSV ready for "
        "conflict detection (Step 3)."
    ),
)
async def resolve_preview(body: ResolvePreviewRequest) -> ResolvePreviewResponse:
    skip_set: set[int] = set(body.skipped_line_numbers)

    corrected_non_skipped = [row for row in body.corrected_rows if row.line_number not in skip_set]
    revalidated_rows, still_invalid = _revalidate_corrected_rows(corrected_non_skipped)

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

    corrected_line_numbers: set[int] = {row.line_number for row in revalidated_rows}

    confirmed_original: list[ParsedCsvRow] = []
    for schema_row in body.valid_rows:
        if schema_row.line_number in skip_set:
            continue
        if schema_row.line_number in corrected_line_numbers:
            continue
        confirmed_original.append(_schema_to_domain(schema_row))

    all_clean_rows = confirmed_original + revalidated_rows
    all_clean_rows.sort(key=lambda row: row.line_number)

    exported_csv = export_valid_rows_to_csv(all_clean_rows)
    all_schemas = [_domain_to_schema(row) for row in all_clean_rows]

    return ResolvePreviewResponse(
        import_batch_id=body.import_batch_id,
        total_accepted=len(all_clean_rows),
        all_valid_rows=all_schemas,
        exported_csv=exported_csv,
    )


# ============================================================================
# PART 5: ENDPOINTS 3 & 4 (CHECK-CONFLICTS & COMMIT TO MYSQL)
# ============================================================================


@router.post("/check-conflicts")
def check_conflicts_endpoint(
    payload: CheckConflictsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """detect series-level time conflicts among incoming rows and existing user events"""
    db_events = db.scalars(active_events_stmt(current_user.id)).all()
    existing_domains = [
        ev.to_domain()
        for ev in db_events
        if not (payload.replace_previous_imports and ev.source == EventSource.IMPORTED)
    ]
    incoming_domains = [row.to_domain() for row in payload.incoming_rows]
    result = detect_import_conflicts(incoming_domains, existing_domains)

    serialized_cards = [
        {
            "conflict_id": card["conflict_id"],
            "option_a": _serialize_conflict_option(card["option_a"]),
            "option_b": _serialize_conflict_option(card["option_b"]),
            "overlap_description": card["overlap_description"],
        }
        for card in result["conflict_cards"]
    ]
    return {
        "non_conflicting_rows": [asdict(r) for r in result["non_conflicting_rows"]],
        "conflict_cards": serialized_cards,
    }


@router.post("/commit", response_model=CommitImportResponse)
def commit_import_endpoint(
    payload: CommitImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CommitImportResponse:
    """persist resolved timetable rows into courses and events in a single transaction"""
    resolved_domains = [row.to_domain() for row in payload.resolved_rows]
    created_domains = commit_resolved_import(
        db=db,
        owner_id=current_user.id,
        import_batch_id=payload.import_batch_id,
        resolved_rows=resolved_domains,
        replace_previous_imports=payload.replace_previous_imports,
    )
    items = [
        EventResponseItem(
            id=ev.id,
            owner_id=ev.owner_id,
            title=ev.title,
            start_time=from_db_to_vn(ev.start_time),
            end_time=from_db_to_vn(ev.end_time),
            kind=ev.kind,
            source=ev.source,
            is_hard=ev.is_hard,
            priority=ev.priority,
            room=ev.room,
            course_id=ev.course_id,
            task_id=ev.task_id,
            proposal_id=ev.proposal_id,
            import_batch_id=ev.import_batch_id,
            is_important=ev.is_important,
        )
        for ev in created_domains
    ]
    return CommitImportResponse(
        import_batch_id=payload.import_batch_id,
        created_count=len(items),
        events=items,
    )
