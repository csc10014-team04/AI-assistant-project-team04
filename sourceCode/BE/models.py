from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from enum import Enum, IntEnum
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ============================================================================
# 1. STANDARDIZED ENUMERATIONS (SHARED ACROSS ALL MODULES)
# ============================================================================


class AuthProvider(str, Enum):
    PASSWORD = "password"  # local username and hashed password authentication
    GOOGLE = "google"      # google oauth2 authentication
    GITHUB = "github"      # github oauth2 authentication


class EventKind(str, Enum):
    CLASS = "CLASS"        # recurring weekly university class session
    EXAM = "EXAM"          # one-off exam session
    DEADLINE = "DEADLINE"  # point-in-time deadline where start_time == end_time
    EVENT = "EVENT"        # fixed one-off school or personal event
    TASK = "TASK"          # time block allocated from a flexible user task


class CsvRowKind(str, Enum):
    CLASS = "CLASS"        # recurring class row in intermediate timetable csv
    EXAM = "EXAM"          # exam row in intermediate timetable csv
    DEADLINE = "DEADLINE"  # deadline row in intermediate timetable csv
    EVENT = "EVENT"        # fixed event row in intermediate timetable csv


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class EventSource(str, Enum):
    IMPORTED = "IMPORTED"      # parsed from uploaded timetable file
    AI_CREATED = "AI_CREATED"  # created via chatbot proposal confirmation
    MANUAL = "MANUAL"          # created via manual fallback ui


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"          # awaiting user action (confirm, reject, reschedule)
    CONFIRMED = "CONFIRMED"        # user clicked confirm -> generates event row(s)
    REJECTED = "REJECTED"          # user clicked reject
    RESCHEDULED = "RESCHEDULED"    # closed after user clicked reschedule to create a new proposal
    ABANDONED = "ABANDONED"        # auto-closed when user switched to a new conversation topic


class TaskStatus(str, Enum):
    PENDING = "PENDING"      # created, not yet confirmed into events
    SCHEDULED = "SCHEDULED"  # proposal confirmed and events generated
    COMPLETED = "COMPLETED"  # finished by user


class PriorityLevel(IntEnum):
    HIGH = 1    # highest priority (e.g., final exam)
    MEDIUM = 2  # medium priority (e.g., university coursework)
    LOW = 3     # default priority when unspecified


class PrioritySource(str, Enum):
    USER = "USER"        # explicitly set by student
    AI = "AI"            # inferred by rule or llm from keywords
    DEFAULT = "DEFAULT"  # fallback default value of 3


class AiErrorType(str, Enum):
    TIMEOUT = "TIMEOUT"                      # llm inference exceeded timeout threshold
    INFRA_CRASH = "INFRA_CRASH"              # llm server process down or out-of-memory
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"  # malformed json or missing required keys
    SEMANTIC_FAILURE = "SEMANTIC_FAILURE"    # unresolvable intent or invalid values


class QueueStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


# ============================================================================
# 2. PURE PYTHON DOMAIN DATACLASSES (FOR PARSER, ENGINE, AND VALIDATOR)
# ============================================================================


def ensure_aware(dt: datetime, field_name: str = "datetime") -> None:
    """raise ValueError if datetime is naive; all timestamps in domain logic must be aware"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class TimeSlot:
    """immutable time window used by availability search engine and conflict validator"""
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        ensure_aware(self.start, "start")
        ensure_aware(self.end, "end")
        if self.end < self.start:
            raise ValueError("end time must be greater than or equal to start time")

    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    def overlaps(self, other: TimeSlot) -> bool:
        """true if two non-empty intervals share any positive time overlap"""
        return self.start < other.end and other.start < self.end

    def is_aligned_to_step(self, step_minutes: int = 15) -> bool:
        """check if start and end align to the 15-minute scheduling grid"""
        return (
            self.start.minute % step_minutes == 0
            and self.start.second == 0
            and self.end.minute % step_minutes == 0
            and self.end.second == 0
        )


@dataclass
class EventDomain:
    """pure domain representation of a calendar item for engine and validator"""
    id: Optional[int]
    owner_id: int
    title: str
    start_time: datetime
    end_time: datetime
    kind: EventKind
    source: EventSource
    is_hard: bool = False
    priority: int = int(PriorityLevel.LOW)
    room: Optional[str] = None
    course_id: Optional[int] = None
    task_id: Optional[int] = None
    proposal_id: Optional[int] = None
    import_batch_id: Optional[str] = None
    is_important: bool = False

    def __post_init__(self) -> None:
        ensure_aware(self.start_time, "start_time")
        ensure_aware(self.end_time, "end_time")
        if self.end_time < self.start_time:
            raise ValueError("end_time cannot be earlier than start_time")
        if self.kind == EventKind.DEADLINE and self.start_time != self.end_time:
            raise ValueError("DEADLINE event must have start_time == end_time (zero duration)")

    @property
    def is_deadline(self) -> bool:
        return self.kind == EventKind.DEADLINE or self.start_time == self.end_time

    @property
    def blocks_availability(self) -> bool:
        """deadlines have zero duration and never block the scheduling engine"""
        return not self.is_deadline and self.end_time > self.start_time

    def to_slot(self) -> TimeSlot:
        return TimeSlot(start=self.start_time, end=self.end_time)


@dataclass
class ParsedCsvRow:
    """a single validated row extracted by the timetable parser"""
    line_number: int
    course_code: Optional[str] = None
    title: str
    kind: CsvRowKind
    start_time: time
    end_time: time
    first_date: date
    last_date: date
    weekday: Optional[Weekday] = None
    room: Optional[str] = None


@dataclass
class InvalidCsvRow:
    """an isolated malformed row flagged for human-in-the-loop preview"""
    line_number: int
    raw_text: str
    error_code: str
    error_message: str


@dataclass
class ParseBatchResult:
    """complete output contract of the timetable parser module"""
    import_batch_id: str
    valid_rows: list[ParsedCsvRow] = field(default_factory=list)
    invalid_rows: list[InvalidCsvRow] = field(default_factory=list)


# ============================================================================
# 3. SQLALCHEMY 2.0 ORM MODELS (MAPPED TO MYSQL SCHEMA)
# ============================================================================


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preference: Mapped[Optional[UserPreference]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    courses: Mapped[list[Course]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    proposals: Mapped[list[Proposal]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_identity"),
        Index("idx_auth_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[AuthProvider] = mapped_column(
        SqlEnum(AuthProvider, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="identities")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sleep_start: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(23, 30)
    )
    sleep_end: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(6, 30)
    )
    min_break_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    max_block_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    slot_step_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="preference")


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        Index("idx_course_owner_active", "owner_id", "deleted_at"),
        Index("idx_course_batch", "owner_id", "import_batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    default_room: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship(back_populates="courses")
    events: Mapped[list[Event]] = relationship(back_populates="course")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 3", name="chk_task_priority"),
        CheckConstraint("duration_minutes > 0", name="chk_task_duration"),
        Index("idx_task_owner_active", "owner_id", "deleted_at", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=int(PriorityLevel.LOW)
    )
    priority_source: Mapped[PrioritySource] = mapped_column(
        SqlEnum(PrioritySource), nullable=False, default=PrioritySource.DEFAULT
    )
    status: Mapped[TaskStatus] = mapped_column(
        SqlEnum(TaskStatus), nullable=False, default=TaskStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship(back_populates="tasks")
    proposals: Mapped[list[Proposal]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(back_populates="task")


class Proposal(Base):
    """no deleted_at column; lifecycle tracked strictly by status"""
    __tablename__ = "proposals"
    __table_args__ = (
        Index("idx_proposal_owner_status", "owner_id", "status"),
        Index("idx_proposal_task", "task_id"),
        Index("idx_proposal_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    extra_slots_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSON, nullable=True, default=None
    )
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        SqlEnum(ProposalStatus), nullable=False, default=ProposalStatus.PROPOSED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="proposals")
    task: Mapped[Task] = relationship(back_populates="proposals")
    parent: Mapped[Optional[Proposal]] = relationship(remote_side=[id])
    events: Mapped[list[Event]] = relationship(back_populates="proposal")


class Event(Base):
    """unified calendar table storing CLASS, EXAM, DEADLINE, EVENT, and TASK blocks"""
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 3", name="chk_event_priority"),
        CheckConstraint("end_time >= start_time", name="chk_event_time"),
        Index("idx_event_lookup", "owner_id", "deleted_at", "start_time", "end_time"),
        Index("idx_event_source_batch", "owner_id", "source", "import_batch_id"),
        Index("idx_event_course", "course_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    proposal_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    room: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    kind: Mapped[EventKind] = mapped_column(SqlEnum(EventKind), nullable=False)
    source: Mapped[EventSource] = mapped_column(SqlEnum(EventSource), nullable=False)
    import_batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_hard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=int(PriorityLevel.LOW)
    )
    is_important: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    owner: Mapped[User] = relationship(back_populates="events")
    course: Mapped[Optional[Course]] = relationship(back_populates="events")
    task: Mapped[Optional[Task]] = relationship(back_populates="events")
    proposal: Mapped[Optional[Proposal]] = relationship(back_populates="events")
    reminder: Mapped[Optional[Reminder]] = relationship(
        back_populates="event", uselist=False, cascade="all, delete-orphan"
    )

    def to_domain(self) -> EventDomain:
        """convert orm row (stored in utc) into a timezone-aware domain object"""
        start_utc = (
            self.start_time.replace(tzinfo=timezone.utc)
            if self.start_time.tzinfo is None
            else self.start_time
        )
        end_utc = (
            self.end_time.replace(tzinfo=timezone.utc)
            if self.end_time.tzinfo is None
            else self.end_time
        )
        return EventDomain(
            id=self.id,
            owner_id=self.owner_id,
            title=self.title,
            start_time=start_utc,
            end_time=end_utc,
            kind=self.kind,
            source=self.source,
            is_hard=self.is_hard,
            priority=self.priority,
            room=self.room,
            course_id=self.course_id,
            task_id=self.task_id,
            proposal_id=self.proposal_id,
            import_batch_id=self.import_batch_id,
            is_important=self.is_important,
        )


class Reminder(Base):
    """at most 1 reminder per event/deadline enforced by unique event_id"""
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    scheduled_on_device_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    event: Mapped[Event] = relationship(back_populates="reminder")


# ============================================================================
# 4. OPERATIONAL & TELEMETRY LOG MODELS
# ============================================================================


class TelemetryMetricLog(Base):
    __tablename__ = "telemetry_metric_logs"
    __table_args__ = (Index("idx_telemetry_name_time", "metric_name", "recorded_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_value: Mapped[float] = mapped_column(Double, nullable=False)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class AiErrorLog(Base):
    __tablename__ = "ai_error_logs"
    __table_args__ = (Index("idx_ai_error_type_time", "error_type", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[AiErrorType] = mapped_column(SqlEnum(AiErrorType), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    triggered_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InferenceQueueLog(Base):
    __tablename__ = "inference_queue_logs"
    __table_args__ = (Index("idx_queue_status_time", "status", "enqueued_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[QueueStatus] = mapped_column(
        SqlEnum(QueueStatus), nullable=False, default=QueueStatus.QUEUED
    )
