# owner: Backend (P1-8 server side: Accept / Reject buttons and the manual slot picker)
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import from_db_to_vn, get_db
from models import Event, Proposal, Reminder, User
from services import proposals as svc
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])


class ProposalOut(BaseModel):
    id: int
    task_id: int
    parent_id: int | None
    task_title: str
    duration_minutes: int
    start_time: str  # ISO 8601 +07:00
    end_time: str
    rationale: str | None
    status: str
    extra_slots: list[dict[str, str]] = []  # further blocks when a long task was split (first block is start/end)


class EventOut(BaseModel):
    event_id: int
    title: str
    start_time: str
    end_time: str


class ReminderOut(BaseModel):
    event_id: int
    offset_minutes: int
    fire_at: str  # the phone schedules its local alarm at this time


class ConfirmResponse(BaseModel):
    proposal: ProposalOut
    events: list[EventOut]
    reminders: list[ReminderOut]


class ManualEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(ge=15, le=720)
    slot_start: datetime
    slot_end: datetime


def proposal_out(p: Proposal) -> ProposalOut:
    """serialize a proposal in +07:00 for the mobile client."""
    return ProposalOut(
        id=p.id, task_id=p.task_id, parent_id=p.parent_id, task_title=p.task.title,
        duration_minutes=p.task.duration_minutes,
        start_time=from_db_to_vn(p.start_time).isoformat(), end_time=from_db_to_vn(p.end_time).isoformat(),
        rationale=p.rationale, status=p.status.value, extra_slots=p.extra_slots_json or [],
    )


def _confirm_out(result: svc.ConfirmResult) -> ConfirmResponse:
    def ev(e: Event) -> EventOut:
        return EventOut(event_id=e.id, title=e.title, start_time=from_db_to_vn(e.start_time).isoformat(),
                        end_time=from_db_to_vn(e.end_time).isoformat())

    def rem(r: Reminder, e: Event) -> ReminderOut:
        fire = from_db_to_vn(e.start_time) - timedelta(minutes=r.offset_minutes)
        return ReminderOut(event_id=e.id, offset_minutes=r.offset_minutes, fire_at=fire.isoformat())

    return ConfirmResponse(
        proposal=proposal_out(result.proposal),
        events=[ev(e) for e in result.events],
        reminders=[rem(r, e) for r, e in zip(result.reminders, result.events)],
    )


def _run(db: Session, fn, *args):
    """call a service function; commit on success, roll back and map ProposalError to an HTTP error."""
    try:
        out = fn(db, *args)
        db.commit()
        return out
    except svc.ProposalError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/{proposal_id}", response_model=ProposalOut)
def read_proposal(proposal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return proposal_out(_run(db, svc.get_proposal, user.id, proposal_id))


@router.post("/{proposal_id}/confirm", response_model=ConfirmResponse)
def confirm(proposal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Accept button: re-validates conflicts, creates the TASK event(s) and default reminder(s). 409 on conflict."""
    return _confirm_out(_run(db, svc.confirm_proposal, user.id, proposal_id))


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
def reject(proposal_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Reject button: marks the proposal REJECTED; the calendar is untouched."""
    return proposal_out(_run(db, svc.reject_proposal, user.id, proposal_id))


@router.post("/manual", response_model=ConfirmResponse, status_code=201)
def manual(body: ManualEventRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """manual slot picker (AI unavailable): places the task at the start of the gap the user selected."""
    return _confirm_out(
        _run(db, svc.create_manual_event, user.id, body.title, body.duration_minutes, body.slot_start, body.slot_end)
    )
