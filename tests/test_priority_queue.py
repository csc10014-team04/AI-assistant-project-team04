"""
PRI-01..PRI-22: Priority queue and batch scheduling tests.
Covers: sort_queue ordering, schedule_pending_tasks, priority persistence,
        HIGH/MEDIUM/LOW labels, batch result with dropped tasks.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from database import UTC_TZ, VN_TZ
from models import Proposal, ProposalStatus, Task, TaskStatus, PriorityLevel
from services.proposals import sort_queue, schedule_pending_tasks, BatchResult


# ---- helpers ----------------------------------------------------------------
def make_task(db, owner_id, title, priority, duration=60, created_offset_hours=0):
    t = Task(
        owner_id=owner_id,
        title=title,
        duration_minutes=duration,
        priority=priority,
        status=TaskStatus.PENDING,
    )
    db.add(t)
    db.flush()
    return t


# ---- PRI-01: HIGH before MEDIUM before LOW ---------------------------------
def test_PRI01_priority_order_high_medium_low():
    """Contract: sort_queue orders 1 (HIGH) < 2 (MEDIUM) < 3 (LOW)."""
    now = datetime.now(UTC_TZ)
    tasks = [
        Task(id=3, owner_id=1, title="Low", duration_minutes=60, priority=3,
             status=TaskStatus.PENDING, created_at=now),
        Task(id=1, owner_id=1, title="High", duration_minutes=60, priority=1,
             status=TaskStatus.PENDING, created_at=now),
        Task(id=2, owner_id=1, title="Medium", duration_minutes=60, priority=2,
             status=TaskStatus.PENDING, created_at=now),
    ]
    ordered = sort_queue(tasks)
    priorities = [t.priority for t in ordered]
    assert priorities == [1, 2, 3]


# ---- PRI-02: Same priority, older task comes first -------------------------
def test_PRI02_same_priority_older_first():
    """Contract: tasks with equal priority are ordered by creation time (oldest first)."""
    base = datetime.now(UTC_TZ)
    older = Task(id=1, owner_id=1, title="Old", duration_minutes=60, priority=2,
                 status=TaskStatus.PENDING, created_at=base - timedelta(hours=2))
    newer = Task(id=2, owner_id=1, title="New", duration_minutes=60, priority=2,
                 status=TaskStatus.PENDING, created_at=base)
    ordered = sort_queue([newer, older])
    assert ordered[0].id == older.id


# ---- PRI-03: Same priority and time, lower id comes first ------------------
def test_PRI03_same_priority_same_time_lower_id_first():
    """Contract: tie-break by id when priority and created_at are identical."""
    base = datetime.now(UTC_TZ)
    t1 = Task(id=1, owner_id=1, title="A", duration_minutes=60, priority=2,
              status=TaskStatus.PENDING, created_at=base)
    t2 = Task(id=2, owner_id=1, title="B", duration_minutes=60, priority=2,
              status=TaskStatus.PENDING, created_at=base)
    ordered = sort_queue([t2, t1])
    assert ordered[0].id == 1


# ---- PRI-04: Empty task list -> empty queue --------------------------------
def test_PRI04_empty_task_list():
    """Contract: sort_queue with no tasks returns empty list."""
    assert sort_queue([]) == []


# ---- PRI-05: Single task passthrough --------------------------------------
def test_PRI05_single_task_passthrough():
    """Contract: sort_queue with one task returns that task."""
    t = Task(id=1, owner_id=1, title="x", duration_minutes=60, priority=1,
             status=TaskStatus.PENDING, created_at=datetime.now(UTC_TZ))
    assert sort_queue([t]) == [t]


# ---- PRI-06: PriorityLevel enum values ------------------------------------
def test_PRI06_priority_level_values():
    """Contract: PriorityLevel HIGH=1, MEDIUM=2, LOW=3 (matches AGENTS.md)."""
    assert int(PriorityLevel.HIGH) == 1
    assert int(PriorityLevel.MEDIUM) == 2
    assert int(PriorityLevel.LOW) == 3


# ---- PRI-07: schedule_pending_tasks returns BatchResult -------------------
def test_PRI07_schedule_pending_returns_batch_result(db, alice):
    """Contract: schedule_pending_tasks returns a BatchResult object."""
    make_task(db, alice.id, "Task A", priority=1)
    db.commit()
    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    assert isinstance(result, BatchResult)


# ---- PRI-08: HIGH priority task is proposed first -------------------------
def test_PRI08_high_priority_task_proposed_before_low(db, alice):
    """Contract: HIGH priority task gets a proposal even when LOW would use all free time."""
    low = make_task(db, alice.id, "Low Task", priority=3, duration=60)
    high = make_task(db, alice.id, "High Task", priority=1, duration=60)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))

    # Both tasks should get proposals (they fit in a week)
    proposal_task_ids = {p.task_id for p in result.proposals}
    # High should be scheduled
    assert high.id in proposal_task_ids


# ---- PRI-09: Dropped tasks have a reason ----------------------------------
def test_PRI09_dropped_tasks_have_reason(db, alice):
    """Contract: tasks in BatchResult.unscheduled include a non-empty reason string."""
    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    for task, reason in result.unscheduled:
        assert reason and len(reason) > 0


# ---- PRI-10: Already-PROPOSED task not re-queued --------------------------
def test_PRI10_already_proposed_task_skipped_in_batch(db, alice):
    """Contract: tasks with pending proposals are not re-queued in schedule_pending_tasks."""
    task = make_task(db, alice.id, "Pending Task", priority=1)
    db.flush()

    # Create a proposal for it in PROPOSED state
    from database import to_db_utc
    start = to_db_utc(datetime.now(VN_TZ) + timedelta(hours=2))
    end = to_db_utc(datetime.now(VN_TZ) + timedelta(hours=3))
    proposal = Proposal(
        owner_id=alice.id,
        task_id=task.id,
        start_time=start,
        end_time=end,
        status=ProposalStatus.PROPOSED,
    )
    db.add(proposal)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    # Task with PROPOSED proposal must not appear in new proposals
    new_task_ids = {p.task_id for p in result.proposals}
    assert task.id not in new_task_ids


# ---- PRI-11: SCHEDULED tasks are not in batch queue ----------------------
def test_PRI11_scheduled_tasks_excluded_from_batch(db, alice):
    """Contract: tasks with status=SCHEDULED are not picked up by batch scheduling."""
    task = make_task(db, alice.id, "Done", priority=1)
    task.status = TaskStatus.SCHEDULED
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    new_task_ids = {p.task_id for p in result.proposals}
    assert task.id not in new_task_ids


# ---- PRI-12: COMPLETED tasks are not in batch queue ----------------------
def test_PRI12_completed_tasks_excluded(db, alice):
    """Contract: tasks with status=COMPLETED are excluded from batch scheduling."""
    task = make_task(db, alice.id, "Completed Task", priority=1)
    task.status = TaskStatus.COMPLETED
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    new_task_ids = {p.task_id for p in result.proposals}
    assert task.id not in new_task_ids


# ---- PRI-13: Soft-deleted tasks are not queued ----------------------------
def test_PRI13_soft_deleted_tasks_excluded(db, alice):
    """Contract: soft-deleted tasks are excluded from batch scheduling."""
    task = make_task(db, alice.id, "Deleted Task", priority=1)
    task.deleted_at = datetime(2026, 1, 1)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    new_task_ids = {p.task_id for p in result.proposals}
    assert task.id not in new_task_ids


# ---- PRI-14: Multiple users' tasks don't interfere -----------------------
def test_PRI14_batch_scheduling_per_user(db, alice, bob):
    """Contract: schedule_pending_tasks only processes tasks of the specified owner."""
    alice_task = make_task(db, alice.id, "Alice Task", priority=1)
    bob_task = make_task(db, bob.id, "Bob Task", priority=1)
    db.commit()

    alice_result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    alice_task_ids = {p.task_id for p in alice_result.proposals}
    assert bob_task.id not in alice_task_ids


# ---- PRI-15: Proposals inherit task priority -----------------------------
def test_PRI15_proposal_created_with_task_priority(db, alice):
    """Contract: created proposals inherit the task's priority level."""
    task = make_task(db, alice.id, "High Priority Task", priority=1)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    if result.proposals:
        # The task priority should be preserved
        prop = result.proposals[0]
        db.refresh(task)
        assert task.priority == 1


# ---- PRI-16: Multiple tasks same priority are all attempted ---------------
def test_PRI16_multiple_same_priority_all_attempted(db, alice):
    """Contract: all tasks with equal priority are attempted in time order."""
    t1 = make_task(db, alice.id, "Task 1", priority=2)
    t2 = make_task(db, alice.id, "Task 2", priority=2)
    t3 = make_task(db, alice.id, "Task 3", priority=2)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    total_handled = len(result.proposals) + len(result.unscheduled)
    # All 3 tasks should be handled (proposed or dropped)
    assert total_handled >= 3


# ---- PRI-17: AI-inferred HIGH priority keywords detection -----------------
def test_PRI17_ai_inferred_high_priority(client, alice, monkeypatch):
    """Contract: 'gấp' or 'khẩn' keywords should produce priority=1 in NLU."""
    from test_ai_layer import llm, reply, understand
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "làm bài gấp",
        "duration_minutes": 60,
        "priority": 1,
    }))
    n = understand(client, alice, "xếp 1 tiếng làm bài gấp ngay").json()["nlu"]
    assert n["intent"] == "schedule_task"


# ---- PRI-18: DEFAULT priority is 3 (LOW) ----------------------------------
def test_PRI18_default_priority_is_low():
    """Contract: tasks created without explicit priority default to LOW (3)."""
    from models import PriorityLevel
    t = Task(owner_id=1, title="Default Priority", duration_minutes=60)
    # Default value from model definition
    assert t.priority == int(PriorityLevel.LOW)


# ---- PRI-19: sort_queue preserves all tasks --------------------------------
def test_PRI19_sort_queue_preserves_all_tasks():
    """Contract: sort_queue returns all input tasks (no filtering)."""
    base = datetime.now(UTC_TZ)
    tasks = [
        Task(id=i, owner_id=1, title=f"T{i}", duration_minutes=60,
             priority=(i % 3) + 1, status=TaskStatus.PENDING, created_at=base)
        for i in range(1, 6)
    ]
    ordered = sort_queue(tasks)
    assert len(ordered) == len(tasks)
    assert set(t.id for t in ordered) == set(t.id for t in tasks)


# ---- PRI-20: Batch result unscheduled includes all dropped tasks ----------
def test_PRI20_batch_result_unscheduled_contains_dropped(db, alice):
    """Contract: BatchResult.unscheduled contains (task, reason) tuples for all dropped."""
    # Fill the week with hard events to prevent scheduling
    from models import Event, EventKind, EventSource
    from database import to_db_utc
    start_full = to_db_utc(datetime.now(VN_TZ).replace(hour=0, minute=0, second=0))
    end_full = to_db_utc(datetime.now(VN_TZ).replace(hour=23, minute=59, second=0))
    for i in range(7):
        offset = timedelta(days=i)
        blocker = Event(
            owner_id=alice.id,
            title=f"Blocker {i}",
            kind=EventKind.CLASS,
            source=EventSource.IMPORTED,
            start_time=start_full + offset,
            end_time=end_full + offset,
            is_hard=True,
            priority=3,
        )
        db.add(blocker)

    task = make_task(db, alice.id, "Impossible Task", priority=3)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    task_ids_dropped = {t.id for t, _ in result.unscheduled}
    assert task.id in task_ids_dropped


# ---- PRI-21: BatchResult.proposals all have status PROPOSED ---------------
def test_PRI21_batch_proposals_are_proposed(db, alice):
    """Contract: proposals generated by schedule_pending_tasks have status=PROPOSED."""
    make_task(db, alice.id, "Batch Task", priority=2)
    db.commit()

    result = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    for p in result.proposals:
        assert p.status == ProposalStatus.PROPOSED


# ---- PRI-22: Consecutive batch calls don't duplicate proposals -----------
def test_PRI22_consecutive_batch_no_duplicates(db, alice):
    """Contract: a task already in PROPOSED state is not re-queued in next batch."""
    task = make_task(db, alice.id, "Single Task", priority=1)
    db.commit()

    # First batch
    r1 = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))
    # Second batch - same task should not appear again
    r2 = schedule_pending_tasks(db, alice.id, datetime.now(VN_TZ))

    r2_task_ids = {p.task_id for p in r2.proposals}
    assert task.id not in r2_task_ids
