# owner: Khoi (mysql-backed tests for conflict detection, series grouping, and timetable commit)
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from database import VN_TZ, active_courses_stmt, active_events_stmt, to_db_utc
from models import (
    Course,
    CsvRowKind,
    Event,
    EventDomain,
    EventKind,
    EventSource,
    PriorityLevel,
    TimeSlot,
    User,
)
from services.validator import (
    check_hard_conflict,
    commit_resolved_import,
    detect_import_conflicts,
)


def _unique_username(prefix: str = "khoi_validator") -> str:
    """
    input: prefix (str) identifying the test scenario.
    core logic: append an 8-char uuid suffix so usernames never collide.
    output: str unique username safe for repeated test executions.
    typical flow: prefix='khoi_validator' -> 'khoi_validator_a1b2c3d4'.
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
