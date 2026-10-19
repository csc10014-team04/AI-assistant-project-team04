# owner: Khoi (P1-6 hard constraint validator + P1-4 second half: conflict detection & db commit)
from sqlalchemy.orm import Session
from models import EventDomain, ParsedCsvRow, TimeSlot


def check_hard_conflict(
    candidate_slot: TimeSlot, existing_events: list[EventDomain]
) -> list[EventDomain]:
    """return list of hard-constraint events that overlap with candidate_slot"""
    raise NotImplementedError


def detect_import_conflicts(
    incoming_rows: list[ParsedCsvRow], existing_events: list[EventDomain]
) -> dict:
    """group series-level conflicts and separate non-conflicting rows"""
    raise NotImplementedError


def commit_resolved_import(
    db: Session,
    owner_id: int,
    import_batch_id: str,
    resolved_rows: list[ParsedCsvRow],
    replace_previous_imports: bool = False,
) -> list[EventDomain]:
    """expand recurring CLASS rows into weekly events and persist to mysql"""
    raise NotImplementedError
