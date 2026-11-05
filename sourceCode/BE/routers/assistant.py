# owner: Database & AI (P1-7 conversational scheduling entry point; authenticated only)
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import UTC_TZ, abandon_pending_proposals, get_db
from models import User
from services import rag
from services.nlu import NluResult, understand_prompt
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class UnderstandRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    reschedule_proposal_id: int | None = None  # set when the user taps "Reschedule" on a proposal


class UnderstandResponse(BaseModel):
    nlu: NluResult
    abandoned_proposals: int
    message: str | None = None


@router.post("/understand", response_model=UnderstandResponse)
def understand(
    body: UnderstandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnderstandResponse:
    """
    input: authenticated user's free-text prompt (optionally a reschedule follow-up).
    core logic: a new root prompt abandons the user's pending proposals (AGENTS.md section 4), then NLU runs;
                AI failures are logged to ai_error_logs and returned as fallback_mode=True, never as HTTP 500.
    output: extracted intent/entities for the scheduling engine and the mobile manual picker.
    """
    abandoned = 0
    if body.reschedule_proposal_id is None:
        abandoned = abandon_pending_proposals(db, current_user.id)
    result = understand_prompt(
        body.prompt, datetime.now(UTC_TZ), db=db, user_id=current_user.id
    )
    db.commit()
    message = (
        "Trợ lý AI đang bận. Chuyển sang chế độ chọn lịch trực tiếp." if result.fallback_mode else None
    )
    return UnderstandResponse(nlu=result, abandoned_proposals=abandoned, message=message)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/index-file")
async def index_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    """
    input: authenticated upload of a timetable pdf / image / text file.
    core logic: extract text (pdf layer or OCR) -> chunk -> embed -> replace this file's chunks in the
                caller's own encrypted vector index (re-upload of the same filename replaces, never duplicates).
    output: number of chunks indexed; 422 when nothing readable was found.
    """
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 10 MB)")
    try:
        count = rag.ingest_file(current_user.id, data, file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"filename": file.filename or "upload", "chunks_indexed": count}
