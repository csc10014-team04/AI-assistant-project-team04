import os
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from sqlalchemy import Select, create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from models import Course, Event, Proposal, ProposalStatus, Task

# ============================================================================
# 1. MYSQL ENGINE & SESSION CONFIGURATION
# ============================================================================

BE_ROOT_DIR = Path(__file__).resolve().parent
DEPLOY_ENV_PATH = BE_ROOT_DIR.parent / "Database" / "assistant_deploy" / ".env"
LOCAL_ENV_PATH = BE_ROOT_DIR / ".env"


def _read_dotenv_file(env_path: Path) -> dict[str, str]:
    """
    input: env_path (Path) pointing to an optional .env configuration file.
    core logic: parse non-comment KEY=VALUE lines while stripping surrounding quotes.
    output: dict[str, str] mapping environment variable names to raw string values.
    typical flow: check file exists -> iterate lines -> split on first '=' -> return dict.
    """
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values  # return empty map when .env file is absent
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip("'").strip('"')
    return values


def resolve_database_url() -> str:
    """
    input: process env vars or local .env files in BE/ and Database/assistant_deploy/.
    core logic: prioritize DATABASE_URL, normalize driver to pymysql, or build 127.0.0.1:3307 url.
    output: str containing a valid sqlalchemy mysql+pymysql connection url with utf8mb4.
    typical flow: check os.environ -> check BE/.env -> check assistant_deploy/.env -> return url.
    """
    merged_env = {
        **_read_dotenv_file(DEPLOY_ENV_PATH),
        **_read_dotenv_file(LOCAL_ENV_PATH),
        **os.environ,
    }
    raw_url = merged_env.get("DATABASE_URL", "").strip()
    if raw_url:
        normalized = raw_url.replace("mysql+aiomysql://", "mysql+pymysql://")  # enforce sync driver
        if "mysql+pymysql://" in normalized and "charset=" not in normalized:
            sep = "&" if "?" in normalized else "?"
            normalized = f"{normalized}{sep}charset=utf8mb4"
        return normalized

    db_user = merged_env.get("DB_USER", "schedule_admin")
    db_password = quote_plus(merged_env.get("DB_PASSWORD", "password"))
    db_host = merged_env.get("DB_HOST", "localhost")
    db_port = merged_env.get("DB_PORT", "3307")  # docker exposes mysql on host port 3307
    db_name = merged_env.get("DB_NAME", "university_assistant")
    return (
        f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        "?charset=utf8mb4"
    )


DATABASE_URL = resolve_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # verify mysql connection health before each checkout
    pool_recycle=3600,   # recycle connections hourly to prevent mysql idle timeout
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    input: none (invoked automatically by fastapi Depends injection).
    core logic: open a synchronous sqlalchemy session and guarantee closure after request.
    output: generator yielding an active Session bound to the mysql engine.
    typical flow: open SessionLocal() -> yield session to route handler -> close in finally.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # always release connection back to pool


# ============================================================================
# 2. TIMEZONE & 15-MINUTE GRID UTILITIES
# ============================================================================

UTC_TZ = timezone.utc
VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def to_db_utc(dt: datetime) -> datetime:
    """
    input: dt (datetime) that must carry explicit timezone info (UTC_TZ or VN_TZ).
    core logic: reject naive datetimes, convert to utc, truncate seconds, strip tzinfo for mysql.
    output: naive datetime representing exact utc minute for mysql DATETIME columns.
    typical flow: aware +07:00 dt -> astimezone(UTC_TZ) -> zero seconds -> naive utc dt.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("refusing naive datetime; all timestamps must be timezone-aware")
    return dt.astimezone(UTC_TZ).replace(second=0, microsecond=0, tzinfo=None)


def from_db_to_vn(dt: datetime) -> datetime:
    """
    input: dt (datetime) read from mysql (naive utc) or an existing aware datetime.
    core logic: attach UTC_TZ if naive, then shift timezone offset to Vietnam +07:00.
    output: timezone-aware datetime in VN_TZ (+07:00) ready for iso8601 serialization.
    typical flow: mysql naive utc dt -> attach UTC_TZ -> astimezone(VN_TZ) -> return.
    """
    utc_aware = dt.replace(tzinfo=UTC_TZ) if dt.tzinfo is None else dt.astimezone(UTC_TZ)
    return utc_aware.astimezone(VN_TZ)


def round_up_to_15m(dt: datetime) -> datetime:
    """
    input: dt (datetime) with explicit timezone info.
    core logic: zero out seconds and advance minute up to next multiple of 15 if needed.
    output: timezone-aware datetime aligned to :00, :15, :30, or :45 grid boundary.
    typical flow: 08:00 stays 08:00; 08:03 advances +12m to 08:15; naive dt raises ValueError.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("datetime must be timezone-aware")
    dt_clean = dt.replace(second=0, microsecond=0)
    remainder = dt_clean.minute % 15
    if remainder == 0:
        return dt_clean  # already aligned on 15-minute boundary
    return dt_clean + timedelta(minutes=(15 - remainder))


# ============================================================================
# 3. SAFE QUERY HELPERS (ENFORCING OWNER ISOLATION & SOFT DELETE FILTERING)
# ============================================================================


def active_events_stmt(
    owner_id: int,
    start_from: Optional[datetime] = None,
    end_until: Optional[datetime] = None,
) -> Select[tuple[Event]]:
    """
    input: owner_id (int) and optional aware window bounds start_from, end_until.
    core logic: filter events by owner_id, deleted_at is null, and optional time intersection.
    output: sqlalchemy Select statement ordered chronologically by start_time.
    typical flow: apply owner & soft-delete predicates -> convert bounds via to_db_utc -> order asc.
    """
    stmt = select(Event).where(
        Event.owner_id == owner_id,
        Event.deleted_at.is_(None),
    )
    if start_from is not None:
        stmt = stmt.where(Event.end_time >= to_db_utc(start_from))  # keep events ending after window start
    if end_until is not None:
        stmt = stmt.where(Event.start_time <= to_db_utc(end_until))  # keep events starting before window end
    return stmt.order_by(Event.start_time.asc())


def active_courses_stmt(owner_id: int) -> Select[tuple[Course]]:
    """
    input: owner_id (int) of the authenticated user.
    core logic: build select query restricted to owner's non-soft-deleted course records.
    output: sqlalchemy Select[tuple[Course]] statement.
    typical flow: pass current_user.id -> execute via db.scalars(stmt) -> receive active courses.
    """
    return select(Course).where(
        Course.owner_id == owner_id,
        Course.deleted_at.is_(None),
    )


def active_tasks_stmt(owner_id: int) -> Select[tuple[Task]]:
    """
    input: owner_id (int) of the authenticated user.
    core logic: build select query restricted to owner's non-soft-deleted flexible tasks.
    output: sqlalchemy Select[tuple[Task]] statement.
    typical flow: pass current_user.id -> execute via db.scalars(stmt) -> receive active tasks.
    """
    return select(Task).where(
        Task.owner_id == owner_id,
        Task.deleted_at.is_(None),
    )


def abandon_pending_proposals(db: Session, owner_id: int) -> int:
    """
    input: db (Session) and owner_id (int) when user starts a new scheduling topic.
    core logic: bulk-update all PROPOSED rows of owner_id to ABANDONED status.
    output: int count of proposal rows transitioned to ABANDONED.
    typical flow: user sends new root prompt -> update PROPOSED to ABANDONED -> return affected count.
    """
    result = db.execute(
        update(Proposal)
        .where(
            Proposal.owner_id == owner_id,
            Proposal.status == ProposalStatus.PROPOSED,
        )
        .values(status=ProposalStatus.ABANDONED)
    )
    return result.rowcount or 0
