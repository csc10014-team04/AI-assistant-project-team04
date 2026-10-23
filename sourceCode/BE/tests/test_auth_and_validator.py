from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database import UTC_TZ, VN_TZ, active_courses_stmt, active_events_stmt, get_db, to_db_utc
from main import app
from models import (
    AuthIdentity,
    AuthProvider,
    Base,
    Course,
    CsvRowKind,
    Event,
    EventDomain,
    EventKind,
    EventSource,
    ParsedCsvRow,
    TimeSlot,
    User,
    UserPreference,
    Weekday,
)
from services.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from services.validator import (
    check_hard_conflict,
    commit_resolved_import,
    detect_import_conflicts,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """provide an isolated in-memory sqlite session for unit tests"""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """fastapi test client overriding get_db with in-memory session"""
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ============================================================================
# STAGE 1 TESTS: SECURITY & AUTHENTICATION
# ============================================================================


def test_password_hashing_and_verification() -> None:
    hashed = hash_password("S3cretP@ss!")
    assert hashed != "S3cretP@ss!"
    assert verify_password("S3cretP@ss!", hashed) is True
    assert verify_password("WrongPass", hashed) is False
    assert verify_password("S3cretP@ss!", "malformed-hash") is False


def test_jwt_create_and_decode(db_session: Session) -> None:
    user = User(display_name="Khoi")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_access_token(user.id)
    decoded_id = decode_access_token(token)
    assert decoded_id == user.id

    resolved_user = get_current_user(db=db_session, token=token)
    assert resolved_user.id == user.id

    expired_token = create_access_token(user.id, expires_delta=timedelta(seconds=-10))
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(expired_token)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException) as exc_info_invalid:
        decode_access_token("not.a.jwt")
    assert exc_info_invalid.value.status_code == 401


def test_register_and_login_endpoints(
    client: TestClient, db_session: Session
) -> None:
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "username": "khoi_student",
            "password": "StrongPassword123",
            "display_name": "Minh Khoi",
        },
    )
    assert reg_res.status_code == 201
    data = reg_res.json()
    user_id = data["user_id"]
    assert data["username"] == "khoi_student"
    assert data["display_name"] == "Minh Khoi"
    assert data["token_type"] == "bearer"
    assert decode_access_token(data["access_token"]) == user_id

    # verify User, AuthIdentity, and UserPreference were created in one transaction
    identity = db_session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.PASSWORD,
            AuthIdentity.provider_user_id == "khoi_student",
        )
    )
    pref = db_session.scalar(
        select(UserPreference).where(UserPreference.user_id == user_id)
    )
    assert identity is not None
    assert pref is not None
    assert pref.slot_step_minutes == 15

    # duplicate registration must return HTTP 409
    dup_res = client.post(
        "/api/v1/auth/register",
        json={
            "username": "khoi_student",
            "password": "AnotherPassword123",
            "display_name": "Duplicate",
        },
    )
    assert dup_res.status_code == 409

    # valid login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "khoi_student", "password": "StrongPassword123"},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["user_id"] == user_id
    assert login_data["token_type"] == "bearer"
    assert decode_access_token(login_data["access_token"]) == user_id

    # invalid password returns HTTP 401
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "khoi_student", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401


# ============================================================================
# STAGE 2 TESTS: VALIDATOR, SERIES CONFLICT GROUPING & DB COMMIT
# ============================================================================


def test_check_hard_conflict() -> None:
    base_day = date(2026, 10, 19)  # monday
    candidate = TimeSlot(
        start=datetime.combine(base_day, time(9, 0), tzinfo=VN_TZ),
        end=datetime.combine(base_day, time(11, 0), tzinfo=VN_TZ),
    )

    hard_class = EventDomain(
        id=1,
        owner_id=1,
        title="Software Engineering",
        start_time=datetime.combine(base_day, time(8, 0), tzinfo=VN_TZ),
        end_time=datetime.combine(base_day, time(10, 0), tzinfo=VN_TZ),
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        is_hard=True,
    )
    soft_task = EventDomain(
        id=2,
        owner_id=1,
        title="Study Group",
        start_time=datetime.combine(base_day, time(9, 30), tzinfo=VN_TZ),
        end_time=datetime.combine(base_day, time(10, 30), tzinfo=VN_TZ),
        kind=EventKind.TASK,
        source=EventSource.AI_CREATED,
        is_hard=False,
    )
    deadline_ev = EventDomain(
        id=3,
        owner_id=1,
        title="Assignment Due",
        start_time=datetime.combine(base_day, time(9, 30), tzinfo=VN_TZ),
        end_time=datetime.combine(base_day, time(9, 30), tzinfo=VN_TZ),
        kind=EventKind.DEADLINE,
        source=EventSource.IMPORTED,
        is_hard=True,
    )
    adjacent_hard = EventDomain(
        id=4,
        owner_id=1,
        title="Linear Algebra",
        start_time=datetime.combine(base_day, time(11, 0), tzinfo=VN_TZ),
        end_time=datetime.combine(base_day, time(13, 0), tzinfo=VN_TZ),
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        is_hard=True,
    )

    conflicts = check_hard_conflict(
        candidate, [hard_class, soft_task, deadline_ev, adjacent_hard]
    )
    assert len(conflicts) == 1
    assert conflicts[0].id == 1


def test_detect_import_conflicts_series_grouping() -> None:
    first_monday = date(2026, 9, 7)
    last_monday = first_monday + timedelta(weeks=14)  # 15 weeks total

    # two overlapping incoming recurring rows + one non-conflicting row
    school_class = ParsedCsvRow(
        line_number=1,
        course_code="CO3001",
        title="Software Engineering",
        kind=CsvRowKind.CLASS,
        weekday=Weekday.MON,
        start_time=time(7, 0),
        end_time=time(9, 0),
        room="H1-101",
        first_date=first_monday,
        last_date=last_monday,
    )
    part_time_job = ParsedCsvRow(
        line_number=2,
        course_code="JOB01",
        title="Barista Shift",
        kind=CsvRowKind.CLASS,
        weekday=Weekday.MON,
        start_time=time(8, 30),
        end_time=time(11, 30),
        room="Cafe",
        first_date=first_monday,
        last_date=last_monday,
    )
    tuesday_class = ParsedCsvRow(
        line_number=3,
        course_code="CO3005",
        title="Principles of Programming Languages",
        kind=CsvRowKind.CLASS,
        weekday=Weekday.TUE,
        start_time=time(7, 0),
        end_time=time(9, 0),
        room="H6-202",
        first_date=first_monday,
        last_date=last_monday,
    )

    # 15 weekly existing events on Friday 13:00-15:00
    existing_friday_events: list[EventDomain] = []
    first_friday = date(2026, 9, 11)
    for w in range(15):
        occ = first_friday + timedelta(weeks=w)
        existing_friday_events.append(
            EventDomain(
                id=100 + w,
                owner_id=1,
                title="Computer Networks",
                start_time=datetime.combine(occ, time(13, 0), tzinfo=VN_TZ).astimezone(
                    UTC_TZ
                ),
                end_time=datetime.combine(occ, time(15, 0), tzinfo=VN_TZ).astimezone(
                    UTC_TZ
                ),
                kind=EventKind.CLASS,
                source=EventSource.IMPORTED,
                is_hard=True,
                course_id=10,
            )
        )

    incoming_friday_clash = ParsedCsvRow(
        line_number=4,
        course_code="AI101",
        title="AI Lab",
        kind=CsvRowKind.CLASS,
        weekday=Weekday.FRI,
        start_time=time(14, 0),
        end_time=time(16, 0),
        room="B4-303",
        first_date=first_monday,
        last_date=last_monday,
    )

    result = detect_import_conflicts(
        [school_class, part_time_job, tuesday_class, incoming_friday_clash],
        existing_friday_events,
    )

    assert len(result["non_conflicting_rows"]) == 1
    assert result["non_conflicting_rows"][0].course_code == "CO3005"
    # 1 conflict card for Monday incoming-vs-incoming + 1 grouped card for Friday incoming-vs-existing (NOT 15)
    assert len(result["conflict_cards"]) == 2


def test_commit_resolved_import_and_safe_reimport(
    client: TestClient, db_session: Session
) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "username": "importer_user",
            "password": "Password123!",
            "display_name": "Importer",
        },
    ).json()
    owner_id = reg["user_id"]
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    # seed an AI_CREATED event and a MANUAL event that must survive re-import replacement
    ai_event = Event(
        owner_id=owner_id,
        title="AI Study Block",
        kind=EventKind.TASK,
        source=EventSource.AI_CREATED,
        start_time=to_db_utc(datetime(2026, 9, 10, 19, 0, tzinfo=VN_TZ)),
        end_time=to_db_utc(datetime(2026, 9, 10, 21, 0, tzinfo=VN_TZ)),
        is_hard=False,
    )
    manual_event = Event(
        owner_id=owner_id,
        title="Dentist Appointment",
        kind=EventKind.EVENT,
        source=EventSource.MANUAL,
        start_time=to_db_utc(datetime(2026, 9, 12, 10, 0, tzinfo=VN_TZ)),
        end_time=to_db_utc(datetime(2026, 9, 12, 11, 0, tzinfo=VN_TZ)),
        is_hard=True,
    )
    db_session.add_all([ai_event, manual_event])
    db_session.commit()

    # initial import of 3 weeks of a Monday class, 1 exam, and 1 deadline
    rows_batch_1 = [
        ParsedCsvRow(
            line_number=1,
            course_code="CO2013",
            title="Database Systems",
            kind=CsvRowKind.CLASS,
            weekday=Weekday.MON,
            start_time=time(7, 0),
            end_time=time(9, 0),
            room="H1-201",
            first_date=date(2026, 9, 7),
            last_date=date(2026, 9, 21),
        ),
        ParsedCsvRow(
            line_number=2,
            course_code="CO2013",
            title="Database Midterm Exam",
            kind=CsvRowKind.EXAM,
            start_time=time(9, 0),
            end_time=time(10, 30),
            room="H2-105",
            first_date=date(2026, 10, 15),
            last_date=date(2026, 10, 15),
        ),
        ParsedCsvRow(
            line_number=3,
            course_code="CO2013",
            title="Milestone 1 Submission",
            kind=CsvRowKind.DEADLINE,
            start_time=time(23, 55),
            end_time=time(23, 55),
            first_date=date(2026, 9, 30),
            last_date=date(2026, 9, 30),
        ),
    ]

    created_batch_1 = commit_resolved_import(
        db=db_session,
        owner_id=owner_id,
        import_batch_id="batch_001",
        resolved_rows=rows_batch_1,
        replace_previous_imports=False,
    )
    assert len(created_batch_1) == 5  # 3 weekly classes + 1 exam + 1 deadline

    # verify UTC conversion (07:00 VN_TZ == 00:00 UTC) and deadline zero duration
    class_events = [e for e in created_batch_1 if e.kind == EventKind.CLASS]
    assert len(class_events) == 3
    assert class_events[0].start_time == datetime(2026, 9, 7, 0, 0, tzinfo=UTC_TZ)
    assert class_events[0].is_hard is True
    assert class_events[0].room == "H1-201"
    assert class_events[0].course_id is not None

    deadline_events = [e for e in created_batch_1 if e.kind == EventKind.DEADLINE]
    assert len(deadline_events) == 1
    assert deadline_events[0].start_time == deadline_events[0].end_time
    assert deadline_events[0].blocks_availability is False

    # test /api/v1/ingestion/check-conflicts and /api/v1/ingestion/commit with replace_previous_imports=True
    check_res = client.post(
        "/api/v1/ingestion/check-conflicts",
        headers=headers,
        json={
            "replace_previous_imports": True,
            "incoming_rows": [
                {
                    "line_number": 1,
                    "course_code": "CO3001",
                    "title": "Software Engineering",
                    "kind": "CLASS",
                    "weekday": "MON",
                    "start_time": "07:00:00",
                    "end_time": "09:00:00",
                    "room": "H6-301",
                    "first_date": "2026-09-07",
                    "last_date": "2026-09-14",
                }
            ],
        },
    )
    assert check_res.status_code == 200
    assert len(check_res.json()["conflict_cards"]) == 0

    commit_res = client.post(
        "/api/v1/ingestion/commit",
        headers=headers,
        json={
            "import_batch_id": "batch_002",
            "replace_previous_imports": True,
            "resolved_rows": [
                {
                    "line_number": 1,
                    "course_code": "CO3001",
                    "title": "Software Engineering",
                    "kind": "CLASS",
                    "weekday": "MON",
                    "start_time": "07:00:00",
                    "end_time": "09:00:00",
                    "room": "H6-301",
                    "first_date": "2026-09-07",
                    "last_date": "2026-09-14",
                }
            ],
        },
    )
    assert commit_res.status_code == 200
    commit_payload = commit_res.json()
    assert commit_payload["created_count"] == 2
    assert commit_payload["events"][0]["start_time"].endswith("+07:00")

    # verify batch_001 events & courses are soft-deleted, while AI_CREATED & MANUAL remain active
    active_evs = db_session.scalars(active_events_stmt(owner_id)).all()
    active_batches = {ev.import_batch_id for ev in active_evs}
    active_sources = {ev.source for ev in active_evs}
    assert "batch_001" not in active_batches
    assert "batch_002" in active_batches
    assert EventSource.AI_CREATED in active_sources
    assert EventSource.MANUAL in active_sources

    active_courses = db_session.scalars(active_courses_stmt(owner_id)).all()
    assert len(active_courses) == 1
    assert active_courses[0].course_code == "CO3001"
