# owner: Database & AI (P1-7 conversational scheduling entry point; authenticated only)
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import UTC_TZ, abandon_pending_proposals, get_db
from models import ProposalStatus, User
from routers.proposals import ProposalOut, proposal_out
from services import proposals as proposal_svc
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
    proposal: ProposalOut | None = None  # set when a free slot was found; the chat renders Accept / Reject / Reschedule
    # optional ui navigation metadata so kivy ChatBubble can render a one-tap redirect button
    redirect_target: str | None = None
    redirect_button_label: str | None = None


@router.post("/understand", response_model=UnderstandResponse)
def understand(
    body: UnderstandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnderstandResponse:
    """
    input: authenticated user's free-text prompt (optionally a reschedule follow-up).
    core logic: a new root prompt abandons the user's pending proposals (AGENTS.md section 4), then NLU runs;
                if user asks a schedule/academic question in the AI scheduling chat, return a redirect notice
                pointing to 'search_home'; AI failures are logged and returned as fallback_mode=True.
    output: extracted intent/entities, optional redirect_target/redirect_button_label for UI tab switching.
    """
    parent = None
    abandoned = 0
    if body.reschedule_proposal_id is None:
        abandoned = abandon_pending_proposals(db, current_user.id)
    else:  # reschedule follow-up: the old proposal must still be waiting for the user
        try:
            parent = proposal_svc.get_proposal(db, current_user.id, body.reschedule_proposal_id)
        except proposal_svc.ProposalError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        if parent.status != ProposalStatus.PROPOSED:
            raise HTTPException(409, f"proposal is already {parent.status.value}")
    now = datetime.now(UTC_TZ)
    result = understand_prompt(body.prompt, now, db=db, user_id=current_user.id)

    proposal = None
    message = None
    if result.fallback_mode:
        message = "Trợ lý AI đang bận. Chuyển sang chế độ chọn lịch trực tiếp."
    elif not result.needs_clarification and (result.intent == "schedule_task" or (parent and result.intent != "unknown")):
        created = proposal_svc.create_proposal(db, current_user.id, result, body.prompt, now, parent)
        if created is None:
            message = "Không tìm thấy khung giờ trống phù hợp trong khoảng thời gian này. Bạn thử chọn ngày khác nhé."
        else:
            if parent is not None:
                parent.status = ProposalStatus.RESCHEDULED
            db.flush()
            proposal = proposal_out(created)
            message = "Mình đề xuất khung giờ này, bạn xác nhận nhé."
    db.commit()

    redirect_target: str | None = None
    redirect_button_label: str | None = None
    if result.intent == "query_schedule":  # a calendar / academic question belongs in the search tab
        message = (
            "It seems bạn đang muốn tra cứu lịch trình hoặc hỏi đáp học vụ. "
            "Khung 'Trợ lý AI' chỉ dùng để xếp lịch công việc mới; bạn hãy bấm nút 'Tìm kiếm' để chuyển sang trang Tra cứu nhé."
        )
        redirect_target = "search_home"
        redirect_button_label = "Tìm kiếm"

    return UnderstandResponse(
        nlu=result,
        abandoned_proposals=abandoned,
        message=message,
        proposal=proposal,
        redirect_target=redirect_target,
        redirect_button_label=redirect_button_label,
    )


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
