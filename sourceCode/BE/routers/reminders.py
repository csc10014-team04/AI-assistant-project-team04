# owner: Database & AI (P2-13 reminder scheduler audit trail; notifications themselves fire locally on the phone)
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import UTC_TZ, active_events_stmt, from_db_to_vn, get_db, to_db_utc
from models import Event, Reminder, User
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])

AUDIT_LOG_PATH = Path(os.getenv("REMINDER_AUDIT_LOG_PATH", str(Path(__file__).resolve().parent.parent / "logs" / "reminder_audit.jsonl")))


class ReminderUpsert(BaseModel):
    offset_minutes: int = Field(default=30, ge=0, le=7 * 24 * 60)


class DeviceReport(BaseModel):
    at: datetime | None = None  # device-side timestamp (aware); defaults to server now


class ReminderOut(BaseModel):
    reminder_id: int
    event_id: int
    offset_minutes: int
    fire_at: str  # ISO 8601 +07:00; the phone schedules its local alarm here
    scheduled_on_device_at: str | None
    delivered_at: str | None


def _audit(action: str, reminder: Reminder, owner_id: int) -> None:
    """append one line to the audit file; a disk error must never fail the request."""
    record = {"ts": datetime.now(UTC_TZ).isoformat(), "action": action, "reminder_id": reminder.id,
              "event_id": reminder.event_id, "owner_id": owner_id, "offset_minutes": reminder.offset_minutes}
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _get_event(db: Session, owner_id: int, event_id: int) -> Event:
    event = db.scalar(active_events_stmt(owner_id).where(Event.id == event_id))  # owner + soft-delete filtered
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


def _get_reminder(db: Session, owner_id: int, event_id: int) -> Reminder:
    _get_event(db, owner_id, event_id)
    reminder = db.scalar(select(Reminder).where(Reminder.event_id == event_id, Reminder.owner_id == owner_id))
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return reminder


def _out(reminder: Reminder, event: Event) -> ReminderOut:
    fire = from_db_to_vn(event.start_time) - timedelta(minutes=reminder.offset_minutes)
    return ReminderOut(
        reminder_id=reminder.id, event_id=reminder.event_id, offset_minutes=reminder.offset_minutes,
        fire_at=fire.isoformat(),
        scheduled_on_device_at=from_db_to_vn(reminder.scheduled_on_device_at).isoformat() if reminder.scheduled_on_device_at else None,
        delivered_at=from_db_to_vn(reminder.delivered_at).isoformat() if reminder.delivered_at else None,
    )


@router.put("/{event_id}", response_model=ReminderOut)
def upsert_reminder(event_id: int, body: ReminderUpsert, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)) -> ReminderOut:
    """create or change the single reminder of an event; resets device timestamps so the phone must re-report."""
    event = _get_event(db, current_user.id, event_id)
    reminder = db.scalar(select(Reminder).where(Reminder.event_id == event_id, Reminder.owner_id == current_user.id))
    action = "updated"
    if reminder is None:
        reminder, action = Reminder(owner_id=current_user.id, event_id=event_id, offset_minutes=body.offset_minutes), "created"
        db.add(reminder)
    else:
        reminder.offset_minutes = body.offset_minutes
        reminder.scheduled_on_device_at = reminder.delivered_at = None
    db.commit()
    db.refresh(reminder)
    _audit(action, reminder, current_user.id)
    return _out(reminder, event)


def _report(field: str, action: str, event_id: int, body: DeviceReport, db: Session, user: User) -> ReminderOut:
    reminder = _get_reminder(db, user.id, event_id)
    setattr(reminder, field, to_db_utc(body.at or datetime.now(UTC_TZ)))
    db.commit()
    db.refresh(reminder)
    _audit(action, reminder, user.id)
    return _out(reminder, _get_event(db, user.id, event_id))


@router.post("/{event_id}/scheduled", response_model=ReminderOut)
def report_scheduled(event_id: int, body: DeviceReport, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)) -> ReminderOut:
    """the phone confirms its local alarm was registered (AlarmManager / WorkManager)."""
    return _report("scheduled_on_device_at", "scheduled", event_id, body, db, current_user)


@router.post("/{event_id}/delivered", response_model=ReminderOut)
def report_delivered(event_id: int, body: DeviceReport, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)) -> ReminderOut:
    """the phone confirms the notification was actually shown."""
    return _report("delivered_at", "delivered", event_id, body, db, current_user)


@router.get("/audit", response_model=list[ReminderOut])
def audit_trail(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[ReminderOut]:
    """the caller's reminders with scheduled/delivered timestamps; delivered_at None past fire_at = missed."""
    rows = db.execute(
        select(Reminder, Event).join(Event, Event.id == Reminder.event_id)
        .where(Reminder.owner_id == current_user.id, Event.owner_id == current_user.id, Event.deleted_at.is_(None))
        .order_by(Event.start_time)
    ).all()
    return [_out(r, e) for r, e in rows]
