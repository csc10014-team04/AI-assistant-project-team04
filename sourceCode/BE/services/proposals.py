# owner: Backend (P1-8 server side: proposal lifecycle PROPOSED -> CONFIRMED / REJECTED / RESCHEDULED, AGENTS.md section 4)
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import VN_TZ, active_events_stmt, from_db_to_vn, round_up_to_15m, to_db_utc
from models import (
    Event,
    EventKind,
    EventSource,
    PrioritySource,
    Proposal,
    ProposalStatus,
    Reminder,
    Task,
    TaskStatus,
    TimeSlot,
    UserPreference,
)
from services.nlu import NluResult
from services.search_engine import find_user_free_slots
from services.validator import check_hard_conflict

DEFAULT_REMINDER_OFFSET_MIN = 30
DEFAULT_WINDOW_DAYS = 7  # when the user gave no date, search one week ahead
STEP = timedelta(minutes=15)
MIN_BLOCK_MIN = 30  # smallest piece a split task may be cut into
MAX_PIECES = 6  # a task split into more pieces than this is not a useful schedule
# preferred / avoided part of the day, as [start_hour, end_hour) in Vietnam time
TIME_OF_DAY = {"morning": (6, 12), "afternoon": (12, 18), "evening": (18, 23)}


class ProposalError(Exception):
    """business-rule failure; the router maps `status_code` to the HTTP response."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


@dataclass
class ConfirmResult:
    proposal: Proposal
    events: list[Event]
    reminders: list[Reminder]


def _slots_of(proposal: Proposal) -> list[TimeSlot]:
    """main block + any blocks stored in extra_slots_json (task splitting storage rule)."""
    slots = [TimeSlot(from_db_to_vn(proposal.start_time), from_db_to_vn(proposal.end_time))]
    for extra in proposal.extra_slots_json or []:
        slots.append(TimeSlot(datetime.fromisoformat(extra["start_time"]), datetime.fromisoformat(extra["end_time"])))
    return slots


def _search_window(nlu: NluResult, now_vn: datetime, fallback_start: date | None = None) -> tuple[datetime, datetime]:
    """convert the NLU date window into aware datetimes; never search the past."""
    start_day = nlu.window_start or fallback_start or now_vn.date()
    end_day = nlu.window_end or (start_day + timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    ws = datetime.combine(start_day, time(0), tzinfo=VN_TZ)
    we = datetime.combine(end_day + timedelta(days=1), time(0), tzinfo=VN_TZ)
    return max(ws, round_up_to_15m(now_vn)), we


def _score(candidate: TimeSlot, prefer: str | None, avoid: str | None) -> float:
    """lower is better: preferred part of day < normal waking hours < early/late < avoided part of day."""
    hour = candidate.start.hour
    if prefer in TIME_OF_DAY:
        a, b = TIME_OF_DAY[prefer]
        same_day = candidate.end.date() == candidate.start.date()
        if a <= hour < b and same_day and candidate.end.hour * 60 + candidate.end.minute <= b * 60:
            return 0.0
    if avoid in TIME_OF_DAY:
        a, b = TIME_OF_DAY[avoid]
        if a <= hour < b:
            return 3.0
    return 1.0 if 8 <= hour < 21 else 2.0


def _pick_slot(
    gaps: list[TimeSlot], duration: int, prefer: str | None, avoid: str | None, excluded: list[TimeSlot]
) -> TimeSlot | None:
    """best duration-long block inside the free gaps, skipping blocks the user already rejected."""
    best: tuple[float, datetime, TimeSlot] | None = None
    length = timedelta(minutes=duration)
    for gap in gaps:
        start = gap.start
        while start + length <= gap.end:
            cand = TimeSlot(start, start + length)
            if not any(cand.overlaps(x) for x in excluded):
                key = (_score(cand, prefer, avoid), cand.start)
                if best is None or key < best[:2]:
                    best = (*key, cand)
            start += STEP
    return best[2] if best else None


def _subtract(gaps: list[TimeSlot], excluded: list[TimeSlot]) -> list[TimeSlot]:
    """cut every excluded interval out of the free gaps (used to avoid previously rejected blocks)."""
    out = list(gaps)
    for ex in excluded:
        nxt: list[TimeSlot] = []
        for g in out:
            if not g.overlaps(ex):
                nxt.append(g)
                continue
            if g.start < ex.start:
                nxt.append(TimeSlot(g.start, ex.start))
            if ex.end < g.end:
                nxt.append(TimeSlot(ex.end, g.end))
        out = nxt
    return out


def split_task(gaps: list[TimeSlot], remaining: int, cap: int, min_block: int = MIN_BLOCK_MIN, depth: int = 0) -> list[TimeSlot] | None:
    """
    recursive task splitting (P2-4): when no single free gap can hold the task, cut it into smaller pieces.
    Each level places the biggest piece (<= cap minutes, on the 15-minute grid) at the start of the gap that
    allows it, shrinks that gap, and recurses on the minutes still missing. A trailing piece smaller than
    `min_block` is avoided by shortening the previous piece. Returns the pieces in time order, or None
    when the free time cannot hold the task within MAX_PIECES pieces.
    """
    if remaining <= 0:
        return []
    if depth >= MAX_PIECES:
        return None
    best: tuple[int, int] | None = None  # (piece minutes, gap index)
    for i, gap in enumerate(gaps):
        room = gap.duration_minutes() // 15 * 15
        size = min(remaining, cap, room)
        left = remaining - size
        if 0 < left < min_block and size - (min_block - left) >= min_block:
            size -= min_block - left  # leave a usable last piece instead of a sliver
        if size >= min(min_block, remaining) and (
            best is None or size > best[0] or (size == best[0] and gap.start < gaps[best[1]].start)
        ):
            best = (size, i)
    if best is None:
        return None
    size, i = best
    gap = gaps[i]
    piece = TimeSlot(gap.start, gap.start + timedelta(minutes=size))
    rest = gaps[:i] + [TimeSlot(piece.end, gap.end)] + gaps[i + 1 :]
    tail = split_task(rest, remaining - size, cap, min_block, depth + 1)
    if tail is None:
        return None
    return sorted([piece, *tail], key=lambda t: t.start)


def _ancestor_slots(db: Session, owner_id: int, proposal: Proposal) -> list[TimeSlot]:
    """slots of the proposal and of every proposal it was rescheduled from (all rejected by the user)."""
    out: list[TimeSlot] = []
    current: Proposal | None = proposal
    seen: set[int] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        out.extend(_slots_of(current))
        current = (
            db.scalar(select(Proposal).where(Proposal.id == current.parent_id, Proposal.owner_id == owner_id))
            if current.parent_id
            else None
        )
    return out


def get_proposal(db: Session, owner_id: int, proposal_id: int) -> Proposal:
    """owner-scoped lookup (anti-IDOR): another user's id behaves exactly like a missing one."""
    proposal = db.scalar(select(Proposal).where(Proposal.id == proposal_id, Proposal.owner_id == owner_id))
    if proposal is None:
        raise ProposalError(404, "proposal not found")
    return proposal


def create_proposal(
    db: Session,
    owner_id: int,
    nlu: NluResult,
    prompt: str,
    now: datetime,
    parent: Proposal | None = None,
    task: Task | None = None,
    extra_excluded: list[TimeSlot] | None = None,
) -> Proposal | None:
    """
    input: validated NLU result, the raw prompt, current time, optional parent proposal being rescheduled,
           optional existing `task` (batch scheduling) and slots already promised to other tasks.
    core logic: find free gaps in the NLU window (respecting sleep/break preferences), choose the best block for
                the requested part of the day, skip blocks of the parent chain, then store a PROPOSED row.
                The AI never writes to `events` - only a proposal is created.
    output: the new Proposal, or None when no free block exists in the window.
    """
    now_vn = now.astimezone(VN_TZ)
    if parent is not None:  # inherit the task context from the proposal being rescheduled
        task = parent.task
        title, duration = task.title, task.duration_minutes
        excluded = _ancestor_slots(db, owner_id, parent)
        fallback_start = from_db_to_vn(parent.start_time).date()
    elif task is not None:  # an existing pending task (priority queue)
        title, duration = task.title, task.duration_minutes
        excluded, fallback_start = [], None
    else:
        title = (nlu.title or "Công việc").strip()[:255]
        duration = nlu.duration_minutes or 60
        excluded, fallback_start = [], None
    excluded = excluded + list(extra_excluded or [])

    window_start, window_end = _search_window(nlu, now_vn, fallback_start)
    gaps = find_user_free_slots(db, owner_id, window_start, window_end, duration)
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == owner_id))
    cap = pref.max_block_minutes if pref else 180  # longest continuous work block the user accepts
    pieces: list[TimeSlot] | None = None
    if duration <= cap:  # a whole block is preferred whenever the task is short enough
        chosen = _pick_slot(gaps, duration, nlu.preferred_time_of_day, nlu.avoid_time_of_day, excluded)
        pieces = [chosen] if chosen else None
    if pieces is None:  # too long for one block, or no gap long enough: split it (P2-4)
        small = find_user_free_slots(db, owner_id, window_start, window_end, MIN_BLOCK_MIN)
        pieces = split_task(_subtract(small, excluded), duration, cap)
    if not pieces:
        return None
    chosen = pieces[0]
    extra = [{"start_time": p.start.isoformat(), "end_time": p.end.isoformat()} for p in pieces[1:]] or None

    if task is None:
        task = Task(
            owner_id=owner_id,
            title=title,
            duration_minutes=duration,
            priority=nlu.priority or 3,
            priority_source=PrioritySource.AI if nlu.priority else PrioritySource.DEFAULT,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.flush()

    rationale = (
        f"Khung trống {chosen.start:%H:%M}-{chosen.end:%H:%M} ngày {chosen.start:%d/%m}, "
        f"không trùng lịch học hay giờ ngủ."
    )
    if extra:
        rationale = f"Công việc {duration} phút được chia thành {len(pieces)} khối vì không có khoảng trống liên tục đủ dài. " + rationale
    proposal = Proposal(
        owner_id=owner_id,
        task_id=task.id,
        parent_id=parent.id if parent else None,
        start_time=to_db_utc(chosen.start),
        end_time=to_db_utc(chosen.end),
        extra_slots_json=extra,
        rationale=rationale,
        source_prompt=prompt[:2000],
        status=ProposalStatus.PROPOSED,
    )
    db.add(proposal)
    db.flush()
    return proposal


def _create_events(
    db: Session, owner_id: int, task: Task, slots: list[TimeSlot], source: EventSource, proposal_id: int | None
) -> tuple[list[Event], list[Reminder]]:
    """validate every block against the user's calendar, then insert Event + default Reminder rows."""
    lo = min(s.start for s in slots) - timedelta(hours=1)
    hi = max(s.end for s in slots) + timedelta(hours=1)
    existing = [e.to_domain() for e in db.scalars(active_events_stmt(owner_id, lo, hi)).all()]
    for slot in slots:
        hard = check_hard_conflict(slot, existing)
        blocking = [e for e in existing if e.blocks_availability and slot.overlaps(e.to_slot())]
        clash = hard or blocking
        if clash:
            raise ProposalError(409, f"time slot conflicts with: {', '.join(sorted({e.title for e in clash}))}")
    events, reminders = [], []
    for slot in slots:
        event = Event(
            owner_id=owner_id,
            task_id=task.id,
            proposal_id=proposal_id,
            title=task.title,
            kind=EventKind.TASK,
            source=source,
            start_time=to_db_utc(slot.start),
            end_time=to_db_utc(slot.end),
            is_hard=False,
            priority=task.priority,
        )
        db.add(event)
        db.flush()
        reminder = Reminder(owner_id=owner_id, event_id=event.id, offset_minutes=DEFAULT_REMINDER_OFFSET_MIN)
        db.add(reminder)
        events.append(event)
        reminders.append(reminder)
    db.flush()
    return events, reminders


def confirm_proposal(db: Session, owner_id: int, proposal_id: int) -> ConfirmResult:
    """PROPOSED -> CONFIRMED: re-run the conflict validator (the calendar may have changed), then create events."""
    proposal = get_proposal(db, owner_id, proposal_id)
    if proposal.status != ProposalStatus.PROPOSED:
        raise ProposalError(409, f"proposal is already {proposal.status.value}")
    events, reminders = _create_events(
        db, owner_id, proposal.task, _slots_of(proposal), EventSource.AI_CREATED, proposal.id
    )
    proposal.status = ProposalStatus.CONFIRMED
    proposal.task.status = TaskStatus.SCHEDULED
    db.flush()
    return ConfirmResult(proposal, events, reminders)


def reject_proposal(db: Session, owner_id: int, proposal_id: int) -> Proposal:
    """PROPOSED -> REJECTED. Nothing is written to the calendar."""
    proposal = get_proposal(db, owner_id, proposal_id)
    if proposal.status != ProposalStatus.PROPOSED:
        raise ProposalError(409, f"proposal is already {proposal.status.value}")
    proposal.status = ProposalStatus.REJECTED
    db.flush()
    return proposal


def create_manual_event(
    db: Session, owner_id: int, title: str, duration_minutes: int, slot_start: datetime, slot_end: datetime
) -> ConfirmResult:
    """
    manual fallback picker: the user picked a free gap themselves (no AI involved), so the proposal is created
    already CONFIRMED and its event is stored with source MANUAL. The task is placed at the start of the gap.
    """
    for label, value in (("slot_start", slot_start), ("slot_end", slot_end)):
        if value.tzinfo is None:
            raise ProposalError(422, f"{label} must be timezone-aware")
    start = slot_start.astimezone(VN_TZ).replace(second=0, microsecond=0)
    gap_end = slot_end.astimezone(VN_TZ)
    if start.minute % 15 != 0:
        raise ProposalError(422, "slot_start must be on the 15-minute grid")
    end = start + timedelta(minutes=duration_minutes)
    if end > gap_end:
        raise ProposalError(422, "the chosen slot is shorter than the task duration")
    task = Task(
        owner_id=owner_id, title=title.strip()[:255], duration_minutes=duration_minutes,
        priority=3, priority_source=PrioritySource.DEFAULT, status=TaskStatus.SCHEDULED,
    )
    db.add(task)
    db.flush()
    proposal = Proposal(
        owner_id=owner_id, task_id=task.id, start_time=to_db_utc(start), end_time=to_db_utc(end),
        rationale="Người dùng tự chọn khung giờ.", source_prompt=None, status=ProposalStatus.CONFIRMED,
    )
    db.add(proposal)
    db.flush()
    events, reminders = _create_events(db, owner_id, task, [TimeSlot(start, end)], EventSource.MANUAL, proposal.id)
    return ConfirmResult(proposal, events, reminders)


# ---------------------------------------------------------------------------------------------
# priority queue (P2-5) and edge-case handling for a batch of pending tasks (P2-4)
# ---------------------------------------------------------------------------------------------
PRIORITY_LABEL = {1: "cao", 2: "trung bình", 3: "thấp"}


def sort_queue(tasks: list[Task]) -> list[Task]:
    """scheduling order: priority weight first (1 = most important), then oldest task, then id."""
    return sorted(tasks, key=lambda t: (t.priority, t.created_at or datetime.min, t.id))


@dataclass
class BatchResult:
    proposals: list[Proposal]
    unscheduled: list[tuple[Task, str]]  # (task, reason) dropped because no time is left


def schedule_pending_tasks(
    db: Session, owner_id: int, now: datetime, window_start: date | None = None, window_end: date | None = None
) -> BatchResult:
    """
    allocate time to every PENDING task of the user, highest priority first. A task gets the earliest good
    block (or a split) that does not overlap the classes, the sleep time or blocks already promised to a
    more important task of this batch. Tasks that no longer fit are returned as `unscheduled` with a reason
    instead of silently disappearing: the low-priority items are the ones dropped, never the urgent ones.
    """
    pending = db.scalars(
        select(Task).where(Task.owner_id == owner_id, Task.deleted_at.is_(None), Task.status == TaskStatus.PENDING)
    ).all()
    waiting = {
        pid for (pid,) in db.execute(
            select(Proposal.task_id).where(Proposal.owner_id == owner_id, Proposal.status == ProposalStatus.PROPOSED)
        )
    }
    queue = sort_queue([t for t in pending if t.id not in waiting])
    promised: list[TimeSlot] = []
    proposals: list[Proposal] = []
    dropped: list[tuple[Task, str]] = []
    for task in queue:
        nlu = NluResult(
            intent="schedule_task", title=task.title, duration_minutes=task.duration_minutes,
            priority=task.priority, window_start=window_start, window_end=window_end,
        )
        created = create_proposal(db, owner_id, nlu, task.title, now, task=task, extra_excluded=promised)
        if created is None:
            dropped.append((task, f"không còn khoảng trống cho công việc ưu tiên {PRIORITY_LABEL.get(task.priority, task.priority)}"))
            continue
        promised.extend(_slots_of(created))
        proposals.append(created)
    return BatchResult(proposals, dropped)
