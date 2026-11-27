"""Coverage boost tests for routers/events.py and services/temporal.py (no server required)."""
from datetime import datetime, timedelta

import pytest

from database import VN_TZ, to_db_utc
from models import Event, EventKind, EventSource
from services.temporal import resolve_date_hint


# ===========================================================================
# 1. routers/events.py (create, patch, delete, reminder-audit, preferences)
# ===========================================================================
def test_events_create_deadline_and_validation(client, alice):
    start = datetime(2026, 12, 1, 9, 0, tzinfo=VN_TZ)
    end = datetime(2026, 12, 1, 11, 0, tzinfo=VN_TZ)

    # Regular important EVENT creates event + reminder
    res = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={
            "title": "  Team sync  ",
            "kind": "EVENT",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "room": "  B1.02 ",
            "is_important": True,
        },
    )
    assert res.status_code == 201, res.text
    ev = res.json()
    assert ev["title"] == "Team sync" and ev["room"] == "B1.02" and ev["is_important"] is True

    # DEADLINE forces end_time == start_time
    dl = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={
            "title": "Submit report",
            "kind": "DEADLINE",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
        },
    )
    assert dl.status_code == 201, dl.text
    assert dl.json()["start_time"] == dl.json()["end_time"]

    # Blank title -> 422
    bad_title = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "   ", "kind": "EVENT", "start_time": start.isoformat(), "end_time": end.isoformat()},
    )
    assert bad_title.status_code == 422

    # end_time <= start_time -> 422
    bad_range = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "Bad", "kind": "EVENT", "start_time": end.isoformat(), "end_time": start.isoformat()},
    )
    assert bad_range.status_code == 422

    # Naive datetime is coerced to VN_TZ -> 201
    naive = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "Naive", "kind": "EVENT", "start_time": "2026-12-01T09:00:00", "end_time": "2026-12-01T10:00:00"},
    )
    assert naive.status_code == 201


def test_events_patch_delete_idor_and_hard_guard(client, alice, bob, db):
    start = datetime(2026, 12, 2, 14, 0, tzinfo=VN_TZ)
    end = datetime(2026, 12, 2, 16, 0, tzinfo=VN_TZ)

    ev_id = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "Study", "kind": "EVENT", "start_time": start.isoformat(), "end_time": end.isoformat()},
    ).json()["id"]

    # Patch title, room, time, toggle important True -> False -> True
    p1 = client.patch(
        f"/api/v1/events/{ev_id}",
        headers=alice.h,
        json={
            "title": "Deep Study",
            "room": "Library",
            "start_time": (start + timedelta(hours=1)).isoformat(),
            "end_time": (end + timedelta(hours=1)).isoformat(),
            "is_important": True,
        },
    )
    assert p1.status_code == 200 and p1.json()["title"] == "Deep Study" and p1.json()["is_important"] is True

    # Start changed while already important resets reminder timestamps
    p2 = client.patch(
        f"/api/v1/events/{ev_id}",
        headers=alice.h,
        json={"start_time": (start + timedelta(minutes=30)).isoformat()},
    )
    assert p2.status_code == 200

    # Toggle important False -> deletes reminder
    p3 = client.patch(f"/api/v1/events/{ev_id}", headers=alice.h, json={"is_important": False})
    assert p3.status_code == 200 and p3.json()["is_important"] is False

    # Invalid end <= start on patch -> 400
    bad_patch = client.patch(
        f"/api/v1/events/{ev_id}",
        headers=alice.h,
        json={"start_time": end.isoformat(), "end_time": start.isoformat()},
    )
    assert bad_patch.status_code == 400

    # Anti-IDOR: bob cannot patch or delete alice's event
    assert client.patch(f"/api/v1/events/{ev_id}", headers=bob.h, json={"title": "Hack"}).status_code == 404
    assert client.delete(f"/api/v1/events/{ev_id}", headers=bob.h).status_code == 404

    # DEADLINE patch keeps zero duration
    dl_id = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "HW", "kind": "DEADLINE", "start_time": start.isoformat(), "end_time": start.isoformat()},
    ).json()["id"]
    dl_p = client.patch(
        f"/api/v1/events/{dl_id}",
        headers=alice.h,
        json={"end_time": (start + timedelta(hours=2)).isoformat()},
    )
    assert dl_p.status_code == 200 and dl_p.json()["start_time"] == dl_p.json()["end_time"]

    # Hard CLASS event cannot have time edited
    hard_ev = Event(
        owner_id=alice.id,
        title="Math",
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        start_time=to_db_utc(start),
        end_time=to_db_utc(end),
        is_hard=True,
    )
    db.add(hard_ev)
    db.commit()
    assert client.patch(
        f"/api/v1/events/{hard_ev.id}",
        headers=alice.h,
        json={"start_time": (start + timedelta(hours=1)).isoformat()},
    ).status_code == 400

    # Soft delete and second delete -> 404
    assert client.delete(f"/api/v1/events/{ev_id}", headers=alice.h).status_code == 204
    assert client.delete(f"/api/v1/events/{ev_id}", headers=alice.h).status_code == 404


def test_events_reminder_audit_and_user_preferences(client, alice):
    start = datetime(2026, 12, 3, 10, 0, tzinfo=VN_TZ)
    end = datetime(2026, 12, 3, 11, 0, tzinfo=VN_TZ)
    ev_id = client.post(
        "/api/v1/events",
        headers=alice.h,
        json={"title": "Quiz", "kind": "EVENT", "start_time": start.isoformat(), "end_time": end.isoformat()},
    ).json()["id"]

    # First call creates reminder; second call updates existing reminder
    r1 = client.post(f"/api/v1/events/{ev_id}/reminder-audit", headers=alice.h, json={"offset_minutes": 15})
    assert r1.status_code == 200 and r1.json()["offset_minutes"] == 15
    r2 = client.post(f"/api/v1/events/{ev_id}/reminder-audit", headers=alice.h, json={"offset_minutes": 45})
    assert r2.status_code == 200 and r2.json()["offset_minutes"] == 45

    # Preferences GET and POST (both sleep_schedule and individual fields + invalid numeric fallback)
    g1 = client.get("/api/v1/user/preferences", headers=alice.h)
    assert g1.status_code == 200 and "sleep_start" in g1.json()

    s1 = client.post(
        "/api/v1/user/preferences",
        headers=alice.h,
        json={
            "sleep_schedule": "Ngủ: 23:00 - Dậy: 06:00",
            "min_break_minutes": 10,
            "max_block_minutes": 120,
        },
    )
    assert s1.status_code == 200 and s1.json()["sleep_start"] == "23:00" and s1.json()["sleep_end"] == "06:00"

    s2 = client.post(
        "/api/v1/user/preferences",
        headers=alice.h,
        json={
            "sleep_start": "22:30",
            "sleep_end": "05:30",
            "min_break_minutes": "bad",
            "max_block_minutes": "bad",
        },
    )
    assert s2.status_code == 200 and s2.json()["sleep_start"] == "22:30" and s2.json()["sleep_end"] == "05:30"


# ===========================================================================
# 2. services/temporal.py (resolve_date_hint branches)
# ===========================================================================
NOW_REF = datetime(2026, 5, 15, 9, 0, tzinfo=VN_TZ)  # Friday 2026-05-15


@pytest.mark.parametrize(
    "hint,expect_clarify",
    [
        ("December 20", False),
        ("20th December 2026", False),
        ("January 10", False),          # past in current year -> wraps to next year
        ("February 30", True),          # invalid day in month
        ("2026-12-25", False),
        ("2026-02-30", True),           # invalid ISO date
        ("20/12", False),
        ("20/12/26", False),
        ("10/01", False),               # past in current year -> wraps to next year
        ("31/02", True),                # invalid dd/mm
        ("28th", False),
        ("5th", False),                 # past day in month -> wraps to next month
        ("35th", True),                 # invalid day of month
        ("hôm nay", False),
        ("ngày mai", False),
        ("ngày kia", False),
        ("tuần này", False),
        ("tuần sau", False),
        ("cuối tuần", False),
        ("next weekend", False),
        ("tháng sau", False),
        ("cuối tháng", False),
        ("next monday", False),
        ("friday", False),              # same weekday as NOW_REF -> assumed=True
        ("this friday", False),
        ("thứ 4", False),
        ("thứ 2 tuần sau", False),
        ("chủ nhật", False),
        ("thứ 6", False),               # same weekday as NOW_REF -> assumed=True
        ("completely unknown xyz", True),
    ],
)
def test_temporal_resolve_date_hint_branches(hint, expect_clarify):
    res = resolve_date_hint(hint, NOW_REF)
    if expect_clarify:
        assert res.clarification_question is not None
    else:
        assert res.clarification_question is None
        assert res.start <= res.end
