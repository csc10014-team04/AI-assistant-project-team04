"""DB-01..DB-20: schema parity (init.sql vs ORM), constraints, soft-delete helpers, Docker/deploy configuration."""
import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from conftest import DEPLOY_DIR
from database import UTC_TZ, abandon_pending_proposals, active_courses_stmt, active_events_stmt, active_tasks_stmt, to_db_utc
from models import (AiErrorType, AuthIdentity, AuthProvider, Base, Course, Event, EventKind, EventSource, Proposal,
                    ProposalStatus, QueueStatus, Reminder, Task, User)

INIT_SQL = (DEPLOY_DIR / "init.sql").read_text(encoding="utf-8")
COMPOSE = (DEPLOY_DIR / "docker-compose.yml").read_text(encoding="utf-8")


def sql_tables() -> dict[str, dict[str, str]]:
    """{table: {column: definition}} parsed from CREATE TABLE blocks in init.sql."""
    tables = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", INIT_SQL, re.S):
        cols = {}
        for line in body.splitlines():
            m = re.match(r"\s+(\w+)\s+(.+?),?\s*$", line)
            if m and m.group(1).upper() not in {"CONSTRAINT", "INDEX", "PRIMARY", "UNIQUE", "FOREIGN", "KEY"}:
                cols[m.group(1)] = m.group(2)
        tables[name] = cols
    return tables


def sql_enum(table: str, column: str) -> set[str]:
    m = re.search(rf"{column} ENUM\(([^)]*)\)", sql_tables()[table][column] and
                  re.search(rf"CREATE TABLE {table} \(.*?\n\) ENGINE", INIT_SQL, re.S).group(0))
    return set(re.findall(r"'(\w+)'", m.group(1)))


# ---------------- schema parity -----------------------------------------------------------------
def test_DB01_every_orm_table_exists_in_init_sql_and_vice_versa():
    assert set(sql_tables()) == set(Base.metadata.tables), "init.sql and models.py describe different tables"


def test_DB02_every_column_matches_between_init_sql_and_orm():
    sql = sql_tables()
    for name, table in Base.metadata.tables.items():
        assert set(sql[name]) == {c.name for c in table.columns}, f"column mismatch in {name}"


def test_DB03_enum_values_match_between_init_sql_and_orm():
    from models import AuthProvider, EventKind, EventSource, ProposalStatus, TaskStatus, PrioritySource
    pairs = [("auth_identities", "provider", {e.value for e in AuthProvider}),
             ("events", "kind", {e.value for e in EventKind}),
             ("events", "source", {e.value for e in EventSource}),
             ("proposals", "status", {e.value for e in ProposalStatus}),
             ("tasks", "status", {e.value for e in TaskStatus}),
             ("tasks", "priority_source", {e.value for e in PrioritySource}),
             ("ai_error_logs", "error_type", {e.value for e in AiErrorType}),
             ("inference_queue_logs", "status", {e.value for e in QueueStatus})]
    for table, col, expected in pairs:
        # ORM enums persist the *name*; names equal values in this project, so compare against both
        assert sql_enum(table, col) == expected, f"{table}.{col}"


def test_DB04_all_tables_use_utf8mb4_for_vietnamese_text():
    assert INIT_SQL.count("utf8mb4_unicode_ci") >= len(sql_tables())
    assert "CHARACTER SET utf8mb4" in INIT_SQL


def test_DB05_owned_tables_have_owner_id_and_indexes():
    for t in ("courses", "tasks", "proposals", "events", "reminders"):
        assert "owner_id" in sql_tables()[t], f"{t} lacks owner_id (anti-IDOR)"
    assert "idx_event_lookup (owner_id, deleted_at, start_time, end_time)" in INIT_SQL


def test_DB06_soft_delete_tables_and_state_tracked_proposals():
    for t in ("courses", "events", "tasks"):
        assert "deleted_at" in sql_tables()[t]
    assert "deleted_at" not in sql_tables()["proposals"], "proposals are never deleted (AGENTS.md section 7)"


# ---------------- constraints (enforced by the ORM CHECKs; MySQL enforces the same in init.sql) -
def _user(db, name="u"):
    u = User(display_name=name)
    db.add(u)
    db.flush()
    return u


def test_DB07_priority_outside_1_to_3_is_rejected(db):
    u = _user(db)
    db.add(Task(owner_id=u.id, title="t", duration_minutes=30, priority=4))
    with pytest.raises(IntegrityError):
        db.flush()


def test_DB08_non_positive_task_duration_rejected(db):
    u = _user(db)
    db.add(Task(owner_id=u.id, title="t", duration_minutes=0))
    with pytest.raises(IntegrityError):
        db.flush()


def test_DB09_event_end_before_start_rejected(db):
    u = _user(db)
    now = datetime(2026, 9, 7, 8)
    db.add(Event(owner_id=u.id, title="e", kind=EventKind.EVENT, source=EventSource.MANUAL,
                 start_time=now, end_time=now - timedelta(hours=1)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_DB10_one_reminder_per_event(db):
    u = _user(db)
    t = datetime(2026, 9, 7, 8)
    e = Event(owner_id=u.id, title="e", kind=EventKind.EVENT, source=EventSource.MANUAL, start_time=t, end_time=t)
    db.add(e)
    db.flush()
    db.add_all([Reminder(owner_id=u.id, event_id=e.id), Reminder(owner_id=u.id, event_id=e.id)])
    with pytest.raises(IntegrityError):
        db.flush()


def test_DB11_same_username_cannot_register_twice_per_provider(db):
    a, b = _user(db, "a"), _user(db, "b")
    db.add_all([AuthIdentity(user_id=a.id, provider=AuthProvider.PASSWORD, provider_user_id="x", hashed_password="h"),
                AuthIdentity(user_id=b.id, provider=AuthProvider.PASSWORD, provider_user_id="x", hashed_password="h")])
    with pytest.raises(IntegrityError):
        db.flush()


def test_DB12_oauth_identity_may_have_no_password(db):
    u = _user(db)
    db.add(AuthIdentity(user_id=u.id, provider=AuthProvider.GOOGLE, provider_user_id="g-1", hashed_password=None))
    db.flush()  # P2-8 readiness: no schema change needed for OAuth


# ---------------- query helpers ---------------------------------------------------------------
def test_DB13_active_helpers_hide_soft_deleted_rows_and_other_owners(db):
    a, b = _user(db, "a"), _user(db, "b")
    t = datetime(2026, 9, 7, 8)
    keep = Event(owner_id=a.id, title="keep", kind=EventKind.EVENT, source=EventSource.MANUAL, start_time=t, end_time=t + timedelta(hours=1))
    gone = Event(owner_id=a.id, title="gone", kind=EventKind.EVENT, source=EventSource.MANUAL, start_time=t, end_time=t + timedelta(hours=1), deleted_at=t)
    other = Event(owner_id=b.id, title="other", kind=EventKind.EVENT, source=EventSource.MANUAL, start_time=t, end_time=t + timedelta(hours=1))
    db.add_all([keep, gone, other, Course(owner_id=a.id, course_code="C", title="c", deleted_at=t),
                Task(owner_id=a.id, title="t", duration_minutes=30, deleted_at=t)])
    db.flush()
    assert [e.title for e in db.scalars(active_events_stmt(a.id))] == ["keep"]
    assert list(db.scalars(active_courses_stmt(a.id))) == [] and list(db.scalars(active_tasks_stmt(a.id))) == []


def test_DB14_active_events_window_filter_is_inclusive_and_ordered(db):
    u = _user(db)
    for i, h in enumerate((14, 8, 11)):
        s = datetime(2026, 9, 7, h)
        db.add(Event(owner_id=u.id, title=str(h), kind=EventKind.EVENT, source=EventSource.MANUAL, start_time=s, end_time=s + timedelta(hours=1)))
    db.flush()
    win = db.scalars(active_events_stmt(u.id, datetime(2026, 9, 7, 9, tzinfo=UTC_TZ), datetime(2026, 9, 7, 12, tzinfo=UTC_TZ))).all()
    # boundary is inclusive by design (end_time >= window start), so the 08:00-09:00 event is returned; 14:00 is not
    assert [e.title for e in win] == ["8", "11"]  # ordered ascending by start_time


def test_DB15_abandon_pending_proposals_only_touches_owner_and_proposed(db):
    a, b = _user(db, "a"), _user(db, "b")
    ta, tb = Task(owner_id=a.id, title="t", duration_minutes=30), Task(owner_id=b.id, title="t", duration_minutes=30)
    db.add_all([ta, tb])
    db.flush()
    now = to_db_utc(datetime.now(UTC_TZ))
    mk = lambda owner, task, st: Proposal(owner_id=owner.id, task_id=task.id, start_time=now, end_time=now, status=st)
    ps = [mk(a, ta, ProposalStatus.PROPOSED), mk(a, ta, ProposalStatus.PROPOSED), mk(a, ta, ProposalStatus.CONFIRMED), mk(b, tb, ProposalStatus.PROPOSED)]
    db.add_all(ps)
    db.flush()
    assert abandon_pending_proposals(db, a.id) == 2
    db.expire_all()
    assert [p.status for p in ps] == [ProposalStatus.ABANDONED, ProposalStatus.ABANDONED, ProposalStatus.CONFIRMED, ProposalStatus.PROPOSED]


# ---------------- deployment configuration (P1-2 privacy, README contract) -------------------
def test_DB16_compose_publishes_documented_ports():
    for mapping in ('"3307:3306"', '"8000:8000"', '"8080:8080"', '"80:80"'):
        assert mapping in COMPOSE, f"{mapping} missing (README section 1)"


def test_DB17_compose_has_no_hardcoded_secrets():
    assert re.search(r"MYSQL_ROOT_PASSWORD:\s*\$\{DB_ROOT_PASSWORD\}", COMPOSE)
    assert not re.search(r"(PASSWORD|TOKEN)\s*[:=]\s*(?!\$\{)\S+", COMPOSE.replace("MYSQL_PASSWORD: ${DB_PASSWORD}", "")), \
        "secret literal found in docker-compose.yml"


def test_DB18_llm_context_window_and_db_volume_settings():
    assert "--max-model-len 2048" in COMPOSE  # README rule: 2048-token context
    assert "db_data:/var/lib/mysql" in COMPOSE and "./init.sql:/docker-entrypoint-initdb.d/init.sql" in COMPOSE


def test_DB19_env_example_lists_required_variables_and_real_env_is_ignored():
    env = (DEPLOY_DIR / ".env.example").read_text(encoding="utf-8")
    for key in ("DB_ROOT_PASSWORD", "DB_USER", "DB_PASSWORD", "HF_TOKEN"):
        assert re.search(rf"^{key}=", env, re.M), key
    assert ".env" in (DEPLOY_DIR / ".gitignore").read_text(encoding="utf-8-sig").split()


def test_DB20_deploy_backend_stub_has_no_embedded_credentials_or_sql_echo():
    src = (DEPLOY_DIR / "backend" / "main.py").read_text(encoding="utf-8")
    assert not re.search(r"mysql\+\w+://\w+:[^@$\s{]+@", src), "database credentials hard-coded in stub backend"
    code = "\n".join(line.split("#")[0] for line in src.splitlines())  # ignore comments
    assert not re.search(r"echo\s*=\s*True", code), "echo=True logs every SQL statement including schedule data"
