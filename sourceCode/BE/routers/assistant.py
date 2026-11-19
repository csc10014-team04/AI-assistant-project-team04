# [pic: khoi] p1-7 conversational scheduling entry & cross-tab redirect (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import re
import threading
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, abandon_pending_proposals, from_db_to_vn, get_db
from models import PendingClarification, ProposalStatus, User
from routers.proposals import ProposalOut, proposal_out
from services import proposals as proposal_svc
from services import rag
from services.nlu import _DATE_HINT_RE, NluResult, understand_prompt
from services.search_engine import find_user_free_slots
from services.security import get_current_user
from services.temporal import resolve_date_hint

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])
_clarification_table_lock = threading.Lock()
_clarification_table_ready = False


def _ensure_clarification_table(db: Session) -> None:
    """ensure pending_clarifications exists even on pre-initialized MySQL volumes."""
    global _clarification_table_ready
    if _clarification_table_ready:
        return
    with _clarification_table_lock:
        if _clarification_table_ready:
            return
        PendingClarification.__table__.create(bind=db.get_bind(), checkfirst=True)
        _clarification_table_ready = True


class UnderstandRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    reschedule_proposal_id: int | None = None  # set when the user taps "Reschedule" on a proposal


class FallbackSlotOut(BaseModel):
    start_time: str
    end_time: str
    duration_minutes: int


def _slice_fallback_slots(
    raw_slots,
    duration_minutes: int,
    requested_start: str | None = None,
    requested_end: str | None = None,
    limit: int = 20,
) -> list[FallbackSlotOut]:
    """slice whole-day free gaps into concrete blocks matching requested duration (and optional clock window)."""
    dur = max(15, int(duration_minutes or 60))
    dur_td = timedelta(minutes=dur)
    out: list[FallbackSlotOut] = []

    if requested_start and requested_end:
        try:
            sh, sm = map(int, requested_start.split(":"))
            eh, em = map(int, requested_end.split(":"))
            for slot in raw_slots:
                gs, ge = from_db_to_vn(slot.start), from_db_to_vn(slot.end)
                ws = gs.replace(hour=sh, minute=sm, second=0, microsecond=0)
                we = gs.replace(hour=eh, minute=em, second=0, microsecond=0)
                if we <= ws:
                    we += timedelta(days=1)
                cur, bound = max(gs, ws), min(ge, we)
                while cur + dur_td <= bound and len(out) < limit:
                    out.append(
                        FallbackSlotOut(
                            start_time=cur.isoformat(),
                            end_time=(cur + dur_td).isoformat(),
                            duration_minutes=dur,
                        )
                    )
                    cur += dur_td
        except (ValueError, TypeError):
            out = []
        if out:
            return out

    for slot in raw_slots:
        cur, ge = from_db_to_vn(slot.start), from_db_to_vn(slot.end)
        while cur + dur_td <= ge and len(out) < limit:
            out.append(
                FallbackSlotOut(
                    start_time=cur.isoformat(),
                    end_time=(cur + dur_td).isoformat(),
                    duration_minutes=dur,
                )
            )
            cur += dur_td
    return out


class UnderstandResponse(BaseModel):
    nlu: NluResult
    abandoned_proposals: int
    message: str | None = None
    proposal: ProposalOut | None = None  # set when a free slot was found; the chat renders Accept / Reject / Reschedule
    # candidate free slots returned when fallback_mode=True so the mobile UI can open the manual slot picker immediately
    available_slots: list[FallbackSlotOut] = Field(default_factory=list)
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
                pointing to 'search_home'; AI failures are logged and returned as fallback_mode=True along with
                deterministic available_slots so the mobile UI can open the manual slot picker immediately.
    output: extracted intent/entities, optional available_slots, optional redirect_target/redirect_button_label.
    """
    parent = None
    abandoned = 0
    now = datetime.now(UTC_TZ)

    _ensure_clarification_table(db)
    pending = db.get(PendingClarification, current_user.id)
    context = None

    if pending is not None:
        created_at = pending.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC_TZ)

        if now - created_at <= timedelta(minutes=10):
            context = pending.context_json
        else:
            db.delete(pending)
            pending = None

    prompt_lower = body.prompt.strip().lower()

    is_cancel = bool(
        re.fullmatch(
            r"(cancel|never mind|nevermind|stop|huy|huỷ|hủy|thôi|bỏ qua)[.!]?",
            prompt_lower,
        )
    )

    is_new_topic = bool(
        re.search(
            r"\b(delete|remove|what|when|show|find|check|"
            r"xóa|xoá|xem|tra cứu|có lịch gì|lịch gì)\b|"
            r"\b(xếp|xep|sắp xếp|sap xep|đặt|dat|lên|len)\s+"
            r"(?:lịch|lich|(?:giúp|giup|cho)\s+(?:mình|minh|tôi|toi))\b",
            prompt_lower,
        )
    )

    if body.reschedule_proposal_id is not None:
        try:
            parent = proposal_svc.get_proposal(
                db, current_user.id, body.reschedule_proposal_id
            )
        except proposal_svc.ProposalError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc

        if parent.status != ProposalStatus.PROPOSED:
            raise HTTPException(409, f"proposal is already {parent.status.value}")

        same_reschedule_ctx = (
            context is not None
            and context.get("reschedule_proposal_id") == body.reschedule_proposal_id
            and not is_cancel
            and not is_new_topic
        )
        if not same_reschedule_ctx:
            if pending is not None:
                db.delete(pending)
                db.flush()
                pending = None
            context = None

    if is_cancel:
        if pending is not None:
            db.delete(pending)
            db.flush()
            pending = None
        context = None

    elif context is not None and not is_new_topic:
        if parent is None:
            reschedule_pid = context.get("reschedule_proposal_id")
            if reschedule_pid is not None:
                try:
                    cand_parent = proposal_svc.get_proposal(db, current_user.id, int(reschedule_pid))
                    if cand_parent.status == ProposalStatus.PROPOSED:
                        parent = cand_parent
                except proposal_svc.ProposalError:
                    parent = None

        original_prompt = context["original_prompt"]
        if context.get("requested_start") and context.get("requested_end") and not context.get("title"):
            combined_prompt = f"Schedule {body.prompt.strip()} {original_prompt}"
        else:
            combined_prompt = f"{original_prompt} {body.prompt.strip()}".strip()

        result = understand_prompt(
            combined_prompt,
            now,
            db=db,
            user_id=current_user.id,
            parent_title=(parent.task.title if parent is not None else context.get("title")),
            parent_duration=(parent.task.duration_minutes if parent is not None else context.get("duration_minutes")),
        )

        if result.requested_start is None and context.get("requested_start"):
            result.requested_start = context["requested_start"]
        if result.requested_end is None and context.get("requested_end"):
            result.requested_end = context["requested_end"]
        if result.duration_minutes is None and context.get("duration_minutes") is not None:
            result.duration_minutes = context["duration_minutes"]
        if not result.title and context.get("title"):
            result.title = context["title"]

        if context.get("window_start") and (result.window_start is None or result.date_assumed):
            result.window_start = date.fromisoformat(context["window_start"])
            if context.get("window_end"):
                result.window_end = date.fromisoformat(context["window_end"])
            result.date_assumed = False

        if result.intent == "unknown" and (context.get("intent") in {"schedule_task", "reschedule"} or result.title):
            ctx_intent = context.get("intent")
            result.intent = ctx_intent if ctx_intent in {"schedule_task", "reschedule"} else "schedule_task"

        if result.intent in {"schedule_task", "reschedule"} and result.duration_minutes is not None and (result.title or parent is not None) and not result.date_assumed:
            result.needs_clarification = False
            result.clarification_question = None

    else:
        if pending is not None:
            db.delete(pending)
            db.flush()
            pending = None
        context = None

        if parent is None:
            abandoned = abandon_pending_proposals(db, current_user.id)

    if context is None and not is_cancel:
        result = understand_prompt(
            body.prompt,
            now,
            db=db,
            user_id=current_user.id,
            parent_title=parent.task.title if parent is not None else None,
            parent_duration=parent.task.duration_minutes if parent is not None else None,
        )

    if is_cancel:
        result = understand_prompt(
            body.prompt,
            now,
            db=db,
            user_id=current_user.id,
        )
        result.intent = "unknown"
        result.title = None
        result.needs_clarification = False
        result.clarification_question = None
        message = "Clarification cancelled."
    else:
        message = None

    should_save_clarification = bool(
        not is_cancel
        and result.needs_clarification
        and (
            (result.intent == "unknown" and result.requested_start and result.requested_end)
            or result.intent in {"schedule_task", "reschedule"}
        )
    )
    if should_save_clarification:
        base_prompt = context["original_prompt"] if context is not None else body.prompt
        if result.date_assumed and result.clarification_question:
            base_prompt = re.sub(r"\s+", " ", _DATE_HINT_RE.sub(" ", base_prompt)).strip()
        context_data = {
            "original_prompt": base_prompt,
            "intent": result.intent,
            "title": result.title,
            "requested_start": result.requested_start,
            "requested_end": result.requested_end,
            "duration_minutes": result.duration_minutes,
            "window_start": (
                None if result.date_assumed else (result.window_start.isoformat() if result.window_start else None)
            ),
            "window_end": (
                None if result.date_assumed else (result.window_end.isoformat() if result.window_end else None)
            ),
            "reschedule_proposal_id": (
                body.reschedule_proposal_id
                if body.reschedule_proposal_id is not None
                else (context.get("reschedule_proposal_id") if context is not None else None)
            ),
        }

        if pending is None:
            pending = PendingClarification(
                user_id=current_user.id,
                context_json=context_data,
            )
            db.add(pending)
        else:
            pending.context_json = context_data

    elif pending is not None:
        db.delete(pending)
        pending = None

    if (
        parent is not None
        and not is_cancel
        and not result.fallback_mode
        and result.intent == "unknown"
    ):
        has_date_cue = result.date_hint is not None or bool(_DATE_HINT_RE.search(body.prompt))
        if (
            result.preferred_time_of_day is not None
            or result.avoid_time_of_day is not None
            or result.requested_start is not None
            or has_date_cue
        ):
            result.intent = "reschedule"
            if result.date_hint is None:
                m = _DATE_HINT_RE.search(body.prompt)
                if m:
                    result.date_hint = m.group(0)
            if result.window_start is None and result.date_hint is not None:
                win = resolve_date_hint(result.date_hint, now)
                result.window_start, result.window_end = win.start, win.end
                result.date_assumed = win.assumed

    print("[DEBUG NLU]", result.model_dump())
    proposal = None
    if not is_cancel:
        message = None
    available_slots: list[FallbackSlotOut] = []
    if result.fallback_mode:
        message = "Trợ lý AI đang bận. Chuyển sang chế độ chọn lịch trực tiếp."
        if result.intent != "query_schedule":
            now_vn = now.astimezone(VN_TZ)
            start_date = result.window_start or now_vn.date()
            end_date = result.window_end or (start_date + timedelta(days=6))
            if end_date < start_date:
                end_date = start_date
            ws_vn = max(datetime.combine(start_date, time(0, 0), tzinfo=VN_TZ), now_vn)
            we_vn = datetime.combine(end_date, time(23, 59), tzinfo=VN_TZ)
            dur = result.duration_minutes or 60
            if we_vn > ws_vn:
                raw_slots = find_user_free_slots(
                    db=db,
                    owner_id=current_user.id,
                    window_start=ws_vn,
                    window_end=we_vn,
                    duration_minutes=dur,
                    respect_preferences=True,
                )
                available_slots = _slice_fallback_slots(
                    raw_slots,
                    dur,
                    requested_start=result.requested_start,
                    requested_end=result.requested_end,
                    limit=20,
                )
    elif not result.needs_clarification and (result.intent == "schedule_task" or (parent and result.intent != "unknown")):
        created = proposal_svc.create_proposal(db, current_user.id, result, body.prompt, now, parent)
        print("[DEBUG PROPOSAL]", None if created is None else {
            "start": from_db_to_vn(created.start_time).isoformat(),
            "end": from_db_to_vn(created.end_time).isoformat(),
            "title": created.task.title,
        })
        if created is None:
            message = "Không tìm thấy khung giờ trống phù hợp trong khoảng thời gian này. Bạn thử chọn ngày khác nhé."
        else:
            if parent is not None:
                parent.status = ProposalStatus.RESCHEDULED
            db.flush()
            proposal = proposal_out(created)
            message = "Mình đề xuất khung giờ này, bạn xác nhận nhé."
    print("[DEBUG CLARIFICATION]", {
        "user_id": current_user.id,
        "pending_exists": pending is not None,
        "context": pending.context_json if pending is not None else None,
        "new_or_dirty": pending in db.new or pending in db.dirty if pending is not None else False,
    })
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
        available_slots=available_slots,
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
