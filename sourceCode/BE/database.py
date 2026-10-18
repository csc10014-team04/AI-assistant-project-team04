import os
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Select, create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from models import Course, Event, Proposal, ProposalStatus, Task

# ============================================================================
# 1. MYSQL ENGINE & SESSION CONFIGURATION
# ============================================================================

# default local mysql connection string with utf8mb4 for vietnamese text
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:password@localhost:3306/university_assistant?charset=utf8mb4",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # verify mysql connection before each checkout
    pool_recycle=3600,   # recycle connections hourly to prevent mysql timeout
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """fastapi dependency yielding a database session per request"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# 2. TIMEZONE & 15-MINUTE GRID UTILITIES
# ============================================================================

UTC_TZ = timezone.utc
VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def to_db_utc(dt: datetime) -> datetime:
    """convert a timezone-aware datetime to naive utc for mysql storage"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("refusing naive datetime; all timestamps must be timezone-aware")
    return dt.astimezone(UTC_TZ).replace(second=0, microsecond=0, tzinfo=None)


def from_db_to_vn(dt: datetime) -> datetime:
    """convert a utc datetime read from mysql into an aware +07:00 datetime for json"""
    utc_aware = dt.replace(tzinfo=UTC_TZ) if dt.tzinfo is None else dt.astimezone(UTC_TZ)
    return utc_aware.astimezone(VN_TZ)


def round_up_to_15m(dt: datetime) -> datetime:
    """round a timezone-aware datetime up to the nearest 15-minute boundary"""
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("datetime must be timezone-aware")
    dt_clean = dt.replace(second=0, microsecond=0)
    remainder = dt_clean.minute % 15
    if remainder == 0:
        return dt_clean
    return dt_clean + timedelta(minutes=(15 - remainder))


# ============================================================================
# 3. SAFE QUERY HELPERS (ENFORCING OWNER ISOLATION & SOFT DELETE FILTERING)
# ============================================================================


def active_events_stmt(
    owner_id: int,
    start_from: Optional[datetime] = None,
    end_until: Optional[datetime] = None,
) -> Select[tuple[Event]]:
    """build a select statement for active non-deleted events of a specific user"""
    stmt = select(Event).where(
        Event.owner_id == owner_id,
        Event.deleted_at.is_(None),
    )
    if start_from is not None:
        stmt = stmt.where(Event.end_time >= to_db_utc(start_from))
    if end_until is not None:
        stmt = stmt.where(Event.start_time <= to_db_utc(end_until))
    return stmt.order_by(Event.start_time.asc())


def active_courses_stmt(owner_id: int) -> Select[tuple[Course]]:
    """build a select statement for non-deleted courses of a specific user"""
    return select(Course).where(
        Course.owner_id == owner_id,
        Course.deleted_at.is_(None),
    )


def active_tasks_stmt(owner_id: int) -> Select[tuple[Task]]:
    """build a select statement for non-deleted tasks of a specific user"""
    return select(Task).where(
        Task.owner_id == owner_id,
        Task.deleted_at.is_(None),
    )


def abandon_pending_proposals(db: Session, owner_id: int) -> int:
    """mark all pending proposals of user as ABANDONED when conversation topic changes"""
    result = db.execute(
        update(Proposal)
        .where(
            Proposal.owner_id == owner_id,
            Proposal.status == ProposalStatus.PROPOSED,
        )
        .values(status=ProposalStatus.ABANDONED)
    )
    return result.rowcount or 0
