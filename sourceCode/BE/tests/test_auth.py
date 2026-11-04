# owner: Khoi (mysql-backed module & api tests for security, jwt, registration, and login)
import uuid
from datetime import datetime, time, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, active_events_stmt, from_db_to_vn, to_db_utc
from models import (
    AuthIdentity,
    AuthProvider,
    Event,
    EventKind,
    EventSource,
    PriorityLevel,
    User,
    UserPreference,
)
from services.security import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)


def _unique_username(prefix: str = "khoi_auth") -> str:
    """
    input: prefix (str) identifying the test scenario.
    core logic: append an 8-char uuid suffix so usernames never collide.
    output: str unique username safe for repeated test executions.
    typical flow: prefix='khoi_auth' -> 'khoi_auth_a1b2c3d4'.
    """
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


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
    assert ghost_err.value.status_code == 401  # valid jwt for missing user must raise 401


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
    output: assertions confirming exact timezone conversion, anti-idor filtering, and error on bad priority.
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
        priority=9,  # violates chk_event_priority on real mysql 8.0
    )
    db_session.add(bad_event)
    with pytest.raises((IntegrityError, OperationalError)):
        db_session.flush()
    nested.rollback()
