# shared api router: khoi (information search) & lam (free-slot availability endpoints)
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, from_db_to_vn, get_db
from models import EventKind, User
from services.search_engine import (
    ask_academic_knowledge_base,
    execute_local_search,
    find_user_free_slots,
    ingest_academic_document,
    optimize_search_query,
    verify_and_format_search_results,
)
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["search"])

MAX_ACADEMIC_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 mb upload cap for academic documents


def _coerce_vn_aware(dt: datetime | None) -> datetime | None:
    """
    input: dt (datetime | None) parsed from query string or json request payload.
    core logic: attach VN_TZ if caller omitted offset, else shift aware timestamp to VN_TZ.
    output: timezone-aware datetime in +07:00 or None.
    typical flow: '2026-09-07T07:00:00' -> 07:00+07:00; aware utc -> +07:00.
    """
    if dt is None:
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=VN_TZ)  # treat naive client filter timestamps as local +07:00
    return dt.astimezone(VN_TZ)


# ============================================================================
# [pic: khoi] section 1 - information search endpoints
# 1.1 schedule search: hybrid sql + semantic vector search (no llm generation)
# 1.2 academic knowledge base: document indexing + full 6-step rag q&a
# ============================================================================


class ScheduleSearchEventOut(BaseModel):
    id: int | None
    owner_id: int
    course_id: int | None = None
    task_id: int | None = None
    proposal_id: int | None = None
    title: str
    room: str | None = None
    kind: str
    source: str
    start_time: str
    end_time: str
    is_hard: bool
    priority: int
    is_important: bool
    similarity_score: float = 1.0


class ScheduleSearchResponse(BaseModel):
    query: str
    normalized_query: str
    keywords: str
    total: int
    events: list[ScheduleSearchEventOut]


class AcademicDocumentIndexResponse(BaseModel):
    filename: str
    chunks_indexed: int


class AcademicRagRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=10)


class AcademicCitationOut(BaseModel):
    source: str
    text: str
    score: float


class AcademicRagResponse(BaseModel):
    query: str
    normalized_query: str
    answer: str
    citations: list[AcademicCitationOut]
    fallback_mode: bool


@router.get("/events", response_model=ScheduleSearchResponse)
def search_schedule_events(
    q: str = Query(default="", max_length=500, description="search query (e.g. 'toán', 'xstk ngày mai')"),
    kind: EventKind | None = Query(default=None, description="optional exact EventKind filter"),
    start_from: datetime | None = Query(default=None, description="optional start bound in iso8601"),
    end_until: datetime | None = Query(default=None, description="optional end bound in iso8601"),
    room: str | None = Query(default=None, max_length=100, description="optional room substring filter"),
    top_k: int = Query(default=50, ge=1, le=200, description="maximum number of matching events"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScheduleSearchResponse:
    """
    input: query params (q, kind, start_from, end_until, room, top_k), db session, authenticated user.
    core logic: normalize query, merge explicit sql filters, run hybrid sql + vector search, verify output.
    output: ScheduleSearchResponse with +07:00 events ranked by semantic/exact relevance (no llm).
    typical flow: q='toán' -> returns 'Toán tổ hợp', 'Xác suất thống kê', 'Vi tích phân 2' of current_user.
    """
    aware_start = _coerce_vn_aware(start_from)
    aware_end = _coerce_vn_aware(end_until)
    if aware_start is not None and aware_end is not None and aware_end < aware_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_until must be greater than or equal to start_from",
        )

    filters: dict[str, Any] = optimize_search_query(q, datetime.now(UTC_TZ))
    if kind is not None:
        filters["kind"] = kind  # explicit query parameter overrides inferred kind
    if aware_start is not None:
        filters["window_start"] = aware_start
    if aware_end is not None:
        filters["window_end"] = aware_end
    if room is not None and room.strip():
        filters["room_hint"] = room.strip()
    filters["top_k"] = top_k

    matched_domains = execute_local_search(db, current_user.id, filters)
    formatted_events = verify_and_format_search_results(matched_domains, filters)

    return ScheduleSearchResponse(
        query=q,
        normalized_query=filters["normalized_query"],
        keywords=filters["keywords"],
        total=len(formatted_events),
        events=[ScheduleSearchEventOut(**item) for item in formatted_events],
    )


@router.post("/academic/documents", response_model=AcademicDocumentIndexResponse)
async def upload_academic_document(
    file: UploadFile = File(..., description="academic pdf, markdown, text, or image file"),
    current_user: User = Depends(get_current_user),
) -> AcademicDocumentIndexResponse:
    """
    input: authenticated multipart file upload (.pdf/.md/.txt/image) up to 10 mb.
    core logic: extract text, split into chunks, embed, and persist in shared academic kb vector store.
    output: AcademicDocumentIndexResponse reporting filename and number of indexed chunks.
    typical flow: upload handbook.pdf -> index chunks -> return 200; unreadable file -> raise 422.
    """
    _ = current_user  # enforce authentication before indexing into academic knowledge base
    file_bytes = await file.read(MAX_ACADEMIC_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_ACADEMIC_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file size exceeds the 10 mb limit",
        )
    filename = file.filename or "academic_document.txt"
    try:
        chunks_count = ingest_academic_document(file_bytes, filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return AcademicDocumentIndexResponse(
        filename=filename,
        chunks_indexed=chunks_count,
    )


@router.post("/academic/ask", response_model=AcademicRagResponse)
def ask_academic_kb_endpoint(
    body: AcademicRagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AcademicRagResponse:
    """
    input: body (AcademicRagRequest: query, top_k), db session, and authenticated current_user.
    core logic: execute full 6-step rag over academic kb; commit ai_error_logs if fallback triggered.
    output: AcademicRagResponse containing grounded answer, source citations, and fallback_mode flag.
    typical flow: retrieve handbook chunks -> vllm generates answer -> return 200 (or fallback excerpts).
    """
    rag_result = ask_academic_knowledge_base(
        body.query,
        top_k=body.top_k,
        db=db,
        user_id=current_user.id,
    )
    if rag_result["fallback_mode"]:
        db.commit()  # persist ai error log flushed during llm timeout or crash
    return AcademicRagResponse(**rag_result)


# ============================================================================
# [pic: lam] section 2 - free-slot availability endpoints
# ============================================================================


class FreeSlotsRequest(BaseModel):
    window_start: datetime
    window_end: datetime
    duration_minutes: int = Field(default=60, ge=15, le=720)
    respect_preferences: bool = True


class TimeSlotOut(BaseModel):
    start_time: str
    end_time: str
    duration_minutes: int


class FreeSlotsResponse(BaseModel):
    total: int
    available_slots: list[TimeSlotOut]


@router.post("/free-slots", response_model=FreeSlotsResponse)
def search_free_time_slots(
    body: FreeSlotsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FreeSlotsResponse:
    """
    input: body (FreeSlotsRequest: window_start, window_end, duration_minutes, respect_preferences).
    core logic: validate time bounds, load user's active events & preferences, run sort-and-sweep engine.
    output: FreeSlotsResponse listing 15m-aligned available TimeSlot items in +07:00 iso8601.
    typical flow: valid window -> find_user_free_slots (<200ms) -> serialize +07:00 slots -> return 200.
    """
    aware_start = _coerce_vn_aware(body.window_start)
    aware_end = _coerce_vn_aware(body.window_end)
    if aware_start is None or aware_end is None or aware_end <= aware_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="window_end must be strictly greater than window_start",
        )

    slots = find_user_free_slots(
        db=db,
        owner_id=current_user.id,
        window_start=aware_start,
        window_end=aware_end,
        duration_minutes=body.duration_minutes,
        respect_preferences=body.respect_preferences,
    )
    formatted_slots = [
        TimeSlotOut(
            start_time=from_db_to_vn(slot.start).isoformat(),
            end_time=from_db_to_vn(slot.end).isoformat(),
            duration_minutes=slot.duration_minutes(),
        )
        for slot in slots
    ]
    return FreeSlotsResponse(
        total=len(formatted_slots),
        available_slots=formatted_slots,
    )
