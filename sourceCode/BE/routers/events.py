# [pic: lam] event crud, patch time, soft-delete & reminder audit endpoints (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import re
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import UTC_TZ, active_events_stmt, from_db_to_vn, get_db, to_db_utc
from models import Event, Reminder, User, UserPreference
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/events", tags=["events"])
user_router = APIRouter(prefix="/api/v1/user", tags=["user"])


class EventPatchRequest(BaseModel):
    start_time: str | None = None  # ISO 8601
    end_time: str | None = None    # ISO 8601
    is_important: bool | None = None
    title: str | None = None
    room: str | None = None


class ReminderAuditRequest(BaseModel):
    offset_minutes: int = Field(default=30, ge=0, le=7 * 24 * 60)
    scheduled_on_device_at: datetime | None = None


class EventOut(BaseModel):
    id: int
    title: str
    room: str | None
    kind: str
    start_time: str  # ISO 8601 +07:00
    end_time: str
    is_hard: bool
    is_important: bool


def _event_out(e: Event) -> EventOut:
    return EventOut(
        id=e.id,
        title=e.title,
        room=e.room,
        kind=e.kind.value if hasattr(e.kind, "value") else str(e.kind),
        start_time=from_db_to_vn(e.start_time).isoformat(),
        end_time=from_db_to_vn(e.end_time).isoformat(),
        is_hard=e.is_hard,
        is_important=e.is_important,
    )


def _get_event(db: Session, owner_id: int, event_id: int) -> Event:
    event = db.scalar(active_events_stmt(owner_id).where(Event.id == event_id))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


@router.patch("/{event_id}", response_model=EventOut)
def patch_event(
    event_id: int,
    body: EventPatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventOut:
    event = _get_event(db, current_user.id, event_id)
    if body.start_time is not None or body.end_time is not None:
        if event.is_hard:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot edit time of hard events (CLASS/EXAM)")
        if body.start_time:
            event.start_time = to_db_utc(datetime.fromisoformat(body.start_time))
        if body.end_time:
            event.end_time = to_db_utc(datetime.fromisoformat(body.end_time))
        if event.end_time < event.start_time:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_time must be after start_time")

    if body.is_important is not None:
        event.is_important = body.is_important

    if body.title is not None and body.title.strip():
        event.title = body.title.strip()

    if body.room is not None:
        event.room = body.room.strip() or None

    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = _get_event(db, current_user.id, event_id)
    event.deleted_at = datetime.now(UTC_TZ).replace(tzinfo=None)
    db.commit()


@router.post("/{event_id}/reminder-audit")
def reminder_audit(
    event_id: int,
    body: ReminderAuditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = _get_event(db, current_user.id, event_id)
    event.is_important = True

    reminder = db.scalar(select(Reminder).where(Reminder.event_id == event_id, Reminder.owner_id == current_user.id))
    scheduled_at = to_db_utc(body.scheduled_on_device_at or datetime.now(UTC_TZ))
    if reminder is None:
        reminder = Reminder(
            owner_id=current_user.id,
            event_id=event_id,
            offset_minutes=body.offset_minutes,
            scheduled_on_device_at=scheduled_at,
        )
        db.add(reminder)
    else:
        reminder.offset_minutes = body.offset_minutes
        reminder.scheduled_on_device_at = scheduled_at

    db.commit()
    return {"status": "ok", "event_id": event_id, "offset_minutes": body.offset_minutes}


class UserPreferencesPayload(BaseModel):
    sleep_schedule: str | None = None
    sleep_start: str | None = None
    sleep_end: str | None = None
    min_break_minutes: int | str | None = None
    max_continuous_minutes: int | str | None = None
    max_block_minutes: int | str | None = None
    natural_language_preference: str | None = None


def _parse_time_str(val: str) -> time | None:
    if not val:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})", val)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return time(h, m)
    return None


@user_router.get("/preferences")
def get_user_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == current_user.id))
    if pref is None:
        pref = UserPreference(user_id=current_user.id)
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return {
        "user_id": pref.user_id,
        "sleep_start": pref.sleep_start.strftime("%H:%M") if pref.sleep_start else "23:30",
        "sleep_end": pref.sleep_end.strftime("%H:%M") if pref.sleep_end else "06:30",
        "min_break_minutes": pref.min_break_minutes,
        "max_block_minutes": pref.max_block_minutes,
        "slot_step_minutes": pref.slot_step_minutes,
    }


@user_router.post("/preferences")
def save_user_preferences(
    body: UserPreferencesPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == current_user.id))
    if pref is None:
        pref = UserPreference(user_id=current_user.id)
        db.add(pref)

    if body.sleep_schedule:
        # Format might be "Ngủ: 23:30 - Dậy: 06:30" or "23:30 - 06:30"
        times = re.findall(r"(\d{1,2}:\d{2})", body.sleep_schedule)
        if len(times) >= 2:
            t_start = _parse_time_str(times[0])
            t_end = _parse_time_str(times[1])
            if t_start:
                pref.sleep_start = t_start
            if t_end:
                pref.sleep_end = t_end

    if body.sleep_start:
        t = _parse_time_str(body.sleep_start)
        if t:
            pref.sleep_start = t

    if body.sleep_end:
        t = _parse_time_str(body.sleep_end)
        if t:
            pref.sleep_end = t

    if body.min_break_minutes is not None:
        try:
            pref.min_break_minutes = max(0, min(int(body.min_break_minutes), 360))
        except (ValueError, TypeError):
            pass

    max_block = body.max_block_minutes or body.max_continuous_minutes
    if max_block is not None:
        try:
            pref.max_block_minutes = max(15, min(int(max_block), 720))
        except (ValueError, TypeError):
            pass

    db.commit()
    db.refresh(pref)
    return {
        "status": "ok",
        "sleep_start": pref.sleep_start.strftime("%H:%M"),
        "sleep_end": pref.sleep_end.strftime("%H:%M"),
        "min_break_minutes": pref.min_break_minutes,
        "max_block_minutes": pref.max_block_minutes,
    }
