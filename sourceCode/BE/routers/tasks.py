# owner: Backend (P2-5 priority classification + queue, P2-4 batch scheduling with dropped low-priority items)
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import UTC_TZ, abandon_pending_proposals, active_tasks_stmt, get_db
from models import PrioritySource, Task, TaskStatus, User
from routers.proposals import ProposalOut, proposal_out
from services import proposals as svc
from services.nlu import rule_based_understand
from services.security import get_current_user

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(ge=15, le=720)
    priority: int | None = Field(default=None, ge=1, le=3, description="1 = highest; omit to let the server infer it")
    description: str | None = Field(default=None, max_length=2000)


class PriorityUpdate(BaseModel):
    priority: int = Field(ge=1, le=3)


class TaskOut(BaseModel):
    id: int
    title: str
    duration_minutes: int
    priority: int
    priority_source: str
    status: str


class ScheduleRequest(BaseModel):
    window_start: date | None = None
    window_end: date | None = None


class UnscheduledOut(BaseModel):
    task: TaskOut
    reason: str


class ScheduleResponse(BaseModel):
    proposals: list[ProposalOut]  # in priority order
    unscheduled: list[UnscheduledOut]


def task_out(t: Task) -> TaskOut:
    return TaskOut(id=t.id, title=t.title, duration_minutes=t.duration_minutes, priority=t.priority,
                   priority_source=t.priority_source.value, status=t.status.value)


def _own_task(db: Session, user_id: int, task_id: int) -> Task:
    task = db.scalar(active_tasks_stmt(user_id).where(Task.id == task_id))  # owner + soft-delete filtered
    if task is None:
        raise HTTPException(404, "task not found")
    return task


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """create a flexible task. Priority: the user's value, else inferred from words like 'gấp'/'thi', else 3."""
    if body.priority is not None:
        priority, source = body.priority, PrioritySource.USER
    else:
        inferred = rule_based_understand(body.title).priority
        priority, source = (inferred, PrioritySource.AI) if inferred else (3, PrioritySource.DEFAULT)
    task = Task(owner_id=user.id, title=body.title.strip(), description=body.description,
                duration_minutes=body.duration_minutes, priority=priority, priority_source=source,
                status=TaskStatus.PENDING)
    db.add(task)
    db.commit()
    return task_out(task)


@router.get("", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """the user's active tasks in scheduling-queue order (priority first)."""
    return [task_out(t) for t in svc.sort_queue(list(db.scalars(active_tasks_stmt(user.id)).all()))]


@router.patch("/{task_id}", response_model=TaskOut)
def set_priority(task_id: int, body: PriorityUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _own_task(db, user.id, task_id)
    task.priority, task.priority_source = body.priority, PrioritySource.USER
    db.commit()
    return task_out(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """soft delete (AGENTS.md section 7)."""
    task = _own_task(db, user.id, task_id)
    task.deleted_at = datetime.now(UTC_TZ).replace(tzinfo=None)
    db.commit()


@router.post("/schedule", response_model=ScheduleResponse)
def schedule(body: ScheduleRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    allocate time to all pending tasks, most important first. Earlier pending proposals are abandoned (a new
    scheduling round is a new topic). Tasks that cannot fit are listed in `unscheduled`, lowest priority last.
    """
    abandon_pending_proposals(db, user.id)
    result = svc.schedule_pending_tasks(db, user.id, datetime.now(UTC_TZ), body.window_start, body.window_end)
    db.commit()
    return ScheduleResponse(
        proposals=[proposal_out(p) for p in result.proposals],
        unscheduled=[UnscheduledOut(task=task_out(t), reason=r) for t, r in result.unscheduled],
    )
