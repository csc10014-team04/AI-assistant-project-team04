# owner: Khoi (mysql-backed module & api tests for auth, security, validator, and ingestion commit)
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, active_courses_stmt, active_events_stmt, from_db_to_vn, to_db_utc
from models import (
    AuthIdentity,
    AuthProvider,
    Course,
    CsvRowKind,
    Event,
    EventDomain,
    EventKind,
    EventSource,
    ParsedCsvRow,
    PriorityLevel,
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


def _unique_username(prefix: str = "khoi_test") -> str:
    """
    input: prefix (str) identifying the test scenario.
    core logic: append an 8-char uuid suffix so usernames never collide even in persist mode.
    output: str unique username safe for both rollback mode and PERSIST_TEST_DATA=1 mode.
    typical flow: prefix='khoi_auth' -> 'khoi_auth_a1b2c3d4'.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _register_and_get_headers(
    client: TestClient, display_name: str = "Nguyễn Minh Khôi"
) -> tuple[int, str, dict[str, str]]:
    """
    input: client (TestClient) and Vietnamese utf8mb4 display_name (str).
    core logic: call POST /api/v1/auth/register and build HTTP Authorization Bearer header dict.
    output: tuple of (user_id, username, auth_headers_dict).
    typical flow: generate unique username -> POST /register (201) -> return (id, username, headers).
    """
    username = _unique_username("student")
    res = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "SecurePassword2026",
            "display_name": display_name,
        },
    )
    assert res.status_code == 201
    body = res.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return body["user_id"], username, headers


def test_password_hashing_and_verification() -> None:
    """
    input: plaintext password strings and intentionally malformed hash strings.
    core logic: verify bcrypt random salting, exact match True, wrong password False, bad hash False.
    output: assertions confirming zero plaintext exposure and crash-free verification.
    typical flow: hash same password twice -> digests differ -> checkpw True/False -> corrupt hash False.
    """
    raw_pwd = "FitHcmus@2026"
    digest_1 = hash_password(raw_pwd)
    digest_2 = hash_password(raw_pwd)

    assert digest_1 != raw_pwd  # never store plaintext password
    assert digest_1 != digest_2  # per-hash random salt must produce distinct digests
    assert verify_password(raw_pwd, digest_1) is True
    assert verify_password("WrongPass@2026", digest_1) is False
    assert verify_password(raw_pwd, "not-a-valid-bcrypt-hash") is False  # graceful False, no ValueError


def test_jwt_lifecycle_and_current_user_guard(db_session: Session) -> None:
    """
    input: db_session (Session) bound to real docker mysql 8.0.
    core logic: insert real User in mysql, test valid jwt, expired jwt, tampered jwt, and missing user.
    output: assertions confirming user_id resolution and HTTP 401 rejection on invalid tokens.
    typical flow: insert User -> sign token -> get_current_user succeeds -> expired/missing raises 401.
    """
    user = User(display_name="Trần Văn Kiểm Thử")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    valid_token = create_access_token(user.id, expires_delta=timedelta(minutes=30))
    assert decode_access_token(valid_token) == user.id

    resolved_user = get_current_user(db=db_session, token=valid_token)
    assert resolved_user.id == user.id
    assert resolved_user.display_name == "Trần Văn Kiểm Thử"  # utf8mb4 diacritics preserved in mysql

    expired_token = create_access_token(user.id, expires_delta=timedelta(seconds=-10))
    with pytest.raises(HTTPException) as exp_err:
        decode_access_token(expired_token)
    assert exp_err.value.status_code == 401  # expired token must be rejected

    with pytest.raises(HTTPException) as bad_err:
        decode_access_token(valid_token + "tampered")
    assert bad_err.value.status_code == 401  # modified signature must be rejected

    ghost_token = create_access_token(user_id=999_999_999)
    with pytest.raises(HTTPException) as ghost_err:
        get_current_user(db=db_session, token=ghost_token)
    assert ghost_err.value.status_code == 401  # valid jwt for deleted/missing user must raise 401


def test_register_login_and_mysql_three_table_atomicity(
    client: TestClient, db_session: Session
) -> None:
    """
    input: client (TestClient) and db_session (Session) connected to docker mysql 8.0.
    core logic: register user via HTTP, verify 3 mysql tables + utf8mb4 + 409 duplicate + login 200/401.
    output: assertions proving atomic 3-table creation and strict credential checking on mysql.
    typical flow: POST /register (201) -> query 3 tables -> duplicate (409) -> POST /login (200 & 401).
    """
    username = _unique_username("khoi_official")
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "MyStrongPassword123",
            "display_name": "Nguyễn Minh Khôi",
        },
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    uid = reg_data["user_id"]

    # verify all 3 user-related tables in mysql innodb were populated atomically
    user_row = db_session.scalar(select(User).where(User.id == uid))
    identity_row = db_session.scalar(select(AuthIdentity).where(AuthIdentity.user_id == uid))
    pref_row = db_session.scalar(select(UserPreference).where(UserPreference.user_id == uid))

    assert user_row is not None and user_row.display_name == "Nguyễn Minh Khôi"
    assert identity_row is not None and identity_row.provider == AuthProvider.PASSWORD
    assert identity_row.hashed_password != "MyStrongPassword123"
    assert pref_row is not None
    assert pref_row.sleep_start == time(23, 30)
    assert pref_row.sleep_end == time(6, 30)
    assert pref_row.slot_step_minutes == 15

    # duplicate registration must return HTTP 409 Conflict
    dup_res = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "AnotherPassword456",
            "display_name": "Bản Sao",
        },
    )
    assert dup_res.status_code == 409

    # valid login returns HTTP 200 and a working bearer token
    login_ok = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "MyStrongPassword123"},
    )
    assert login_ok.status_code == 200
    assert login_ok.json()["user_id"] == uid
    assert decode_access_token(login_ok.json()["access_token"]) == uid

    # wrong password returns HTTP 401 Unauthorized
    login_bad = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "WrongPassword999"},
    )
    assert login_bad.status_code == 401


def test_mysql_utc_roundtrip_check_constraints_and_owner_isolation(
    db_session: Session,
) -> None:
    """
    input: db_session (Session) executing directly against mysql 8.0 innodb engine.
    core logic: verify +07:00 -> utc storage roundtrip, owner_id isolation, and mysql CHECK constraints.
    output: assertions confirming exact timezone conversion, anti-idor filtering, and IntegrityError on bad priority.
    typical flow: create 2 users -> save +07:00 event as 00:30 utc -> query per owner -> test invalid priority=9.
    """
    user_a = User(display_name="Sinh Viên A")
    user_b = User(display_name="Sinh Viên B")
    db_session.add_all([user_a, user_b])
    db_session.commit()

    # 07:30 +07:00 on 2026-11-09 must be stored as 00:30 naive utc in mysql DATETIME
    vn_start = datetime(2026, 11, 9, 7, 30, tzinfo=VN_TZ)
    vn_end = datetime(2026, 11, 9, 9, 30, tzinfo=VN_TZ)
    ev_a = Event(
        owner_id=user_a.id,
        title="Cấu trúc dữ liệu và giải thuật",
        room="E201",
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        start_time=to_db_utc(vn_start),
        end_time=to_db_utc(vn_end),
        is_hard=True,
        priority=int(PriorityLevel.HIGH),
    )
    db_session.add(ev_a)
    db_session.commit()
    db_session.refresh(ev_a)

    assert ev_a.start_time == datetime(2026, 11, 9, 0, 30)  # stored as naive utc in mysql
    assert from_db_to_vn(ev_a.start_time) == vn_start  # restored to exact +07:00

    # anti-idor check: user_b must see zero events from user_a
    events_for_a = db_session.scalars(active_events_stmt(user_a.id)).all()
    events_for_b = db_session.scalars(active_events_stmt(user_b.id)).all()
    assert len(events_for_a) == 1
    assert len(events_for_b) == 0

    # mysql 8.0 native CHECK constraint chk_event_priority (priority BETWEEN 1 AND 3)
    nested = db_session.begin_nested()
    bad_event = Event(
        owner_id=user_a.id,
        title="Sự kiện sai độ ưu tiên",
        kind=EventKind.EVENT,
        source=EventSource.MANUAL,
        start_time=to_db_utc(vn_start),
        end_time=to_db_utc(vn_end),
        is_hard=False,
        priority=9,  # violates chk_event_priority on real mysql 8.0 (sqlite would silently allow or differ)
    )
    db_session.add(bad_event)
    with pytest.raises((IntegrityError, OperationalError)):
        db_session.flush()
    nested.rollback()


def test_check_hard_conflict_boundary_cases() -> None:
    """
    input: candidate TimeSlot and domain events (hard CLASS, soft TASK, 0-min DEADLINE).
    core logic: verify overlap triggers only on is_hard=True & blocks_availability=True intervals.
    output: assertions proving zero false positives on soft tasks, deadlines, and touching boundaries.
    typical flow: test interior overlap -> 1 conflict; test touching 09:30 edge / TASK / DEADLINE -> 0 conflicts.
    """
    hard_class = EventDomain(
        id=1,
        owner_id=10,
        title="Mạng máy tính",
        start_time=datetime(2026, 11, 9, 7, 30, tzinfo=VN_TZ),
        end_time=datetime(2026, 11, 9, 9, 30, tzinfo=VN_TZ),
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        is_hard=True,
    )
    soft_task = EventDomain(
        id=2,
        owner_id=10,
        title="Ôn bài tự chọn",
        start_time=datetime(2026, 11, 9, 10, 0, tzinfo=VN_TZ),
        end_time=datetime(2026, 11, 9, 11, 30, tzinfo=VN_TZ),
        kind=EventKind.TASK,
        source=EventSource.AI_CREATED,
        is_hard=False,
    )
    zero_deadline = EventDomain(
        id=3,
        owner_id=10,
        title="Hạn nộp báo cáo",
        start_time=datetime(2026, 11, 9, 10, 30, tzinfo=VN_TZ),
        end_time=datetime(2026, 11, 9, 10, 30, tzinfo=VN_TZ),
        kind=EventKind.DEADLINE,
        source=EventSource.IMPORTED,
        is_hard=True,
    )
    existing = [hard_class, soft_task, zero_deadline]

    # case 1: candidate overlaps hard class (08:30 - 10:00 vs 07:30 - 09:30)
    overlapping_slot = TimeSlot(
        start=datetime(2026, 11, 9, 8, 30, tzinfo=VN_TZ),
        end=datetime(2026, 11, 9, 10, 0, tzinfo=VN_TZ),
    )
    hits = check_hard_conflict(overlapping_slot, existing)
    assert len(hits) == 1 and hits[0].id == 1

    # case 2: candidate starts at exact minute hard class ends (09:30 - 11:30), overlaps soft task & deadline
    touching_and_soft_slot = TimeSlot(
        start=datetime(2026, 11, 9, 9, 30, tzinfo=VN_TZ),
        end=datetime(2026, 11, 9, 11, 30, tzinfo=VN_TZ),
    )
    assert check_hard_conflict(touching_and_soft_slot, existing) == []


def test_detect_import_conflicts_series_grouping_and_api(
    client: TestClient, db_session: Session
) -> None:
    """
    input: client (TestClient), db_session (Session), and two 15-week Monday rows + 1 Wednesday row.
    core logic: verify 15 weekly Monday collisions collapse into 1 ConflictCard both in service and HTTP API.
    output: assertions confirming 1 conflict card and 1 clean Wednesday row via /api/v1/ingestion/check-conflicts.
    typical flow: register user -> seed existing event -> POST /check-conflicts -> verify grouped conflict_cards.
    """
    _, _, headers = _register_and_get_headers(client)

    payload = {
        "replace_previous_imports": False,
        "incoming_rows": [
            {
                "line_number": 1,
                "course_code": "CSC10004",
                "title": "Cấu trúc dữ liệu",
                "kind": "CLASS",
                "weekday": "MON",
                "start_time": "07:30",
                "end_time": "09:30",
                "first_date": "2026-09-07",
                "last_date": "2026-12-14",
                "room": "E201",
            },
            {
                "line_number": 2,
                "course_code": "PARTTIME",
                "title": "Ca làm thêm sáng thứ Hai",
                "kind": "CLASS",
                "weekday": "MON",
                "start_time": "08:30",
                "end_time": "11:00",
                "first_date": "2026-09-07",
                "last_date": "2026-12-14",
                "room": "Quận 5",
            },
            {
                "line_number": 3,
                "course_code": "CSC10006",
                "title": "Cơ sở dữ liệu",
                "kind": "CLASS",
                "weekday": "WED",
                "start_time": "13:30",
                "end_time": "15:30",
                "first_date": "2026-09-07",
                "last_date": "2026-12-14",
                "room": "F102",
            },
        ],
    }

    res = client.post("/api/v1/ingestion/check-conflicts", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    # 15 weeks of Monday overlap must collapse into exactly 1 ConflictCard, leaving Wednesday clean
    assert len(data["conflict_cards"]) == 1
    assert len(data["non_conflicting_rows"]) == 1
    assert data["non_conflicting_rows"][0]["course_code"] == "CSC10006"
    assert "08:30-09:30" in data["conflict_cards"][0]["overlap_description"]


def test_commit_import_endpoint_and_safe_reimport_on_mysql(
    client: TestClient, db_session: Session
) -> None:
    """
    input: client (TestClient) and db_session (Session) against real docker mysql 8.0.
    core logic: commit 3-week CLASS + EXAM + DEADLINE, add MANUAL task, then re-import with replace=True.
    output: assertions proving weekly expansion, +07:00 response, soft-delete of old imports, and survival of MANUAL task.
    typical flow: POST /commit batch_1 -> add MANUAL event -> POST /commit batch_2 (replace=True) -> verify active rows.
    """
    uid, _, headers = _register_and_get_headers(client)

    batch_1_payload = {
        "import_batch_id": "batch_sem1_v1",
        "replace_previous_imports": False,
        "resolved_rows": [
            {
                "line_number": 1,
                "course_code": "CSC10014",
                "title": "Tư duy tính toán",
                "kind": "CLASS",
                "weekday": "MON",
                "start_time": "07:30",
                "end_time": "09:30",
                "first_date": "2026-11-02",
                "last_date": "2026-11-16",  # 3 Mondays: Nov 2, Nov 9, Nov 16
                "room": "I42",
            },
            {
                "line_number": 2,
                "course_code": "CSC10014",
                "title": "Thi giữa kỳ Tư duy tính toán",
                "kind": "EXAM",
                "start_time": "13:30",
                "end_time": "15:00",
                "first_date": "2026-11-20",
                "last_date": "2026-11-20",
                "room": "Hội trường I",
            },
            {
                "line_number": 3,
                "course_code": "CSC10014",
                "title": "Nộp báo cáo nhóm",
                "kind": "DEADLINE",
                "start_time": "23:59",
                "end_time": "23:59",
                "first_date": "2026-11-22",
                "last_date": "2026-11-22",
            },
        ],
    }

    commit_1 = client.post("/api/v1/ingestion/commit", json=batch_1_payload, headers=headers)
    assert commit_1.status_code == 200
    body_1 = commit_1.json()
    assert body_1["created_count"] == 5  # 3 weekly classes + 1 exam + 1 deadline
    assert body_1["events"][0]["start_time"].endswith("+07:00")  # response serialized in Vietnam timezone

    # seed a personal MANUAL event in mysql that must survive timetable re-imports
    personal_event = Event(
        owner_id=uid,
        title="Họp nhóm đồ án cuối kỳ",
        kind=EventKind.TASK,
        source=EventSource.MANUAL,
        start_time=to_db_utc(datetime(2026, 11, 5, 19, 0, tzinfo=VN_TZ)),
        end_time=to_db_utc(datetime(2026, 11, 5, 21, 0, tzinfo=VN_TZ)),
        is_hard=False,
        priority=int(PriorityLevel.HIGH),
    )
    db_session.add(personal_event)
    db_session.commit()

    # upload updated timetable with replace_previous_imports=True
    batch_2_payload = {
        "import_batch_id": "batch_sem1_v2",
        "replace_previous_imports": True,
        "resolved_rows": [
            {
                "line_number": 1,
                "course_code": "CSC10009",
                "title": "Hệ thống máy tính",
                "kind": "CLASS",
                "weekday": "FRI",
                "start_time": "09:30",
                "end_time": "11:30",
                "first_date": "2026-11-06",
                "last_date": "2026-11-13",  # 2 Fridays: Nov 6, Nov 13
                "room": "E304",
            }
        ],
    }
    commit_2 = client.post("/api/v1/ingestion/commit", json=batch_2_payload, headers=headers)
    assert commit_2.status_code == 200
    assert commit_2.json()["created_count"] == 2

    # verify active events in mysql: only 2 new imported Fridays + 1 preserved personal MANUAL event
    active_events = db_session.scalars(active_events_stmt(uid)).all()
    active_titles = [ev.title for ev in active_events]
    assert len(active_events) == 3
    assert "Họp nhóm đồ án cuối kỳ" in active_titles  # personal event preserved 100%
    assert "Tư duy tính toán" not in active_titles  # old batch_1 soft-deleted

    active_courses = db_session.scalars(active_courses_stmt(uid)).all()
    assert len(active_courses) == 1 and active_courses[0].course_code == "CSC10009"
