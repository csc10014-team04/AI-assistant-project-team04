# [pic: lam] p2-10 fifo inference request broker (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from database import UTC_TZ
from models import InferenceQueueLog, QueueStatus

T = TypeVar("T")

QUEUE_MAX_WAIT_SECONDS = 1.0  # + 3.0s llm timeout keeps worst-case end-to-end latency at 4s


class QueueWaitTimeout(Exception):
    """raised when a request waited longer than max_wait before reaching the model."""


class InferenceBroker:
    """
    strict first-in-first-out gate: exactly one inference runs at a time, the rest wait in arrival order.
    a ticket deque + condition variable (not a plain Lock) guarantees FIFO fairness.
    """

    def __init__(self, recorder: Callable[[dict], None] | None = None) -> None:
        self._cond = threading.Condition()
        self._waiting: deque[str] = deque()
        self._running: str | None = None
        self.recorder = recorder
        self.completed = 0

    @property
    def depth(self) -> int:
        """requests currently waiting or running."""
        with self._cond:
            return len(self._waiting) + (1 if self._running else 0)

    def run(self, fn: Callable[[], T], *, user_id: int | None = None, max_wait: float = QUEUE_MAX_WAIT_SECONDS) -> T:
        """
        input: fn (callable doing the model call), user_id for logging, max_wait seconds allowed in line.
        core logic: enqueue ticket -> wait until it is at the head and the model is idle -> run fn -> release.
        output: fn's return value; raises QueueWaitTimeout (status TIMEOUT) or re-raises fn's error (FAILED).
        """
        ticket = uuid.uuid4().hex
        enq = datetime.now(UTC_TZ)
        deadline = time.monotonic() + max_wait
        with self._cond:
            self._waiting.append(ticket)
            while not (self._running is None and self._waiting[0] == ticket):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._waiting.remove(ticket)
                    self._cond.notify_all()
                    self._record(ticket, user_id, enq, None, datetime.now(UTC_TZ), QueueStatus.TIMEOUT)
                    raise QueueWaitTimeout(f"waited more than {max_wait}s for the model")
                self._cond.wait(timeout=remaining)
            self._waiting.popleft()
            self._running = ticket
        started = datetime.now(UTC_TZ)
        status = QueueStatus.COMPLETED
        try:
            return fn()
        except BaseException:
            status = QueueStatus.FAILED
            raise
        finally:
            with self._cond:
                self._running = None
                self.completed += 1
                self._cond.notify_all()
            self._record(ticket, user_id, enq, started, datetime.now(UTC_TZ), status)

    def _record(self, ticket: str, user_id: int | None, enq: datetime, start: datetime | None,
                end: datetime, status: QueueStatus) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder({"request_id": ticket, "user_id": user_id, "enqueued_at": enq,
                           "started_at": start, "completed_at": end, "status": status})
        except Exception:
            pass  # telemetry must never break inference


def db_recorder(entry: dict) -> None:
    """persist one InferenceQueueLog row in its own short session (timestamps stored as naive utc)."""
    from database import SessionLocal  # local import: keeps unit tests free of a db connection

    with SessionLocal() as session:
        row = {k: (v.replace(tzinfo=None) if isinstance(v, datetime) else v) for k, v in entry.items()}
        session.add(InferenceQueueLog(**row))
        session.commit()


import os  # noqa: E402

broker = InferenceBroker(recorder=db_recorder if os.getenv("INFERENCE_QUEUE_LOGGING", "0") == "1" else None)
