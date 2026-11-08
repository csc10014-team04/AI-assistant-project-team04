"""SC-01..: edge-case scheduling (P2-4 splitting, demotion), priority queue (P2-5). Builds on the proposal API."""
from datetime import datetime, timedelta

from sqlalchemy import select

from database import VN_TZ, to_db_utc
from models import Event, EventKind, EventSource, TimeSlot, UserPreference
from services.proposals import split_task
from test_ai_layer import llm, reply, understand

T0 = datetime(2026, 9, 7, 6, 30, tzinfo=VN_TZ)


def gap(start_min: int, length_min: int) -> TimeSlot:
    s = T0 + timedelta(minutes=start_min)
    return TimeSlot(s, s + timedelta(minutes=length_min))


def mins(slots):
    return [s.duration_minutes() for s in slots]


# ---------------- pure splitting algorithm ---------------------------------------------------
def test_SC01_split_uses_two_small_gaps_when_no_gap_is_long_enough():
    pieces = split_task([gap(0, 60), gap(120, 60)], 120, cap=180)
    assert mins(pieces) == [60, 60] and pieces[0].start < pieces[1].start


def test_SC02_split_respects_the_longest_block_cap():
    pieces = split_task([gap(0, 600)], 400, cap=180)
    assert sum(mins(pieces)) == 400 and max(mins(pieces)) <= 180


def test_SC03_split_avoids_a_tiny_last_piece():
    pieces = split_task([gap(0, 600)], 190, cap=180)
    assert sum(mins(pieces)) == 190 and min(mins(pieces)) >= 30  # 160 + 30, not 180 + 10


def test_SC04_split_fails_when_free_time_is_not_enough_and_never_overlaps():
    assert split_task([gap(0, 60), gap(120, 30)], 120, cap=180) is None
    pieces = split_task([gap(0, 90), gap(100, 90)], 150, cap=180)
    assert pieces and all(not a.overlaps(b) for i, a in enumerate(pieces) for b in pieces[i + 1:])


# ---------------- through the API --------------------------------------------------------------
def _fragment_tomorrow(db, user):
    """tomorrow is fully booked except two 60-minute gaps (06:30-07:30 and 09:00-10:00)."""
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
    pref.min_break_minutes = 0
    day = (datetime.now(VN_TZ) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    for start, end, title in ((7.5, 9, "Toán"), (10, 23.5, "Lý")):
        db.add(Event(owner_id=user.id, title=title, kind=EventKind.CLASS, source=EventSource.IMPORTED, is_hard=True,
                     start_time=to_db_utc(day + timedelta(hours=start)), end_time=to_db_utc(day + timedelta(hours=end))))
    db.commit()


def test_SC05_long_task_is_split_across_gaps_and_stored_in_extra_slots(client, alice, db, monkeypatch):
    _fragment_tomorrow(db, alice)
    llm(monkeypatch, lambda r: reply({"intent": "schedule_task", "title": "làm đồ án", "duration_minutes": 120, "date_hint": "ngày mai"}))
    body = understand(client, alice, "xếp 2 tiếng làm đồ án ngày mai").json()
    p = body["proposal"]
    assert p is not None, body
    first = datetime.fromisoformat(p["end_time"]) - datetime.fromisoformat(p["start_time"])
    assert first == timedelta(minutes=60) and len(p["extra_slots"]) == 1 and "chia thành 2 khối" in p["rationale"]

    res = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    assert res.status_code == 200, res.text
    events = db.scalars(select(Event).where(Event.kind == EventKind.TASK)).all()
    assert len(events) == 2 and sum((e.end_time - e.start_time).seconds // 60 for e in events) == 120
    assert len(res.json()["reminders"]) == 2  # one reminder per block


# ---------------- priority queue (P2-5) and dropping low-priority items (P2-4) -----------------
def _task(client, acc, title, minutes, **extra):
    res = client.post("/api/v1/tasks", headers=acc.h, json={"title": title, "duration_minutes": minutes, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def test_SC06_priority_is_user_given_inferred_or_default(client, alice):
    assert _task(client, alice, "đọc sách", 60, priority=2)["priority_source"] == "USER"
    urgent = _task(client, alice, "nộp bài gấp", 60)
    assert urgent["priority"] == 1 and urgent["priority_source"] == "AI"
    plain = _task(client, alice, "đọc sách", 60)
    assert plain["priority"] == 3 and plain["priority_source"] == "DEFAULT"


def test_SC07_task_list_is_in_queue_order(client, alice):
    _task(client, alice, "c-low", 60, priority=3)
    _task(client, alice, "a-high", 60, priority=1)
    _task(client, alice, "b-mid", 60, priority=2)
    assert [t["title"] for t in client.get("/api/v1/tasks", headers=alice.h).json()] == ["a-high", "b-mid", "c-low"]


def test_SC08_schedule_serves_high_priority_first_and_drops_the_lowest(client, alice, db):
    _fragment_tomorrow(db, alice)  # tomorrow has only 2 x 60 minutes free
    tomorrow = (datetime.now(VN_TZ) + timedelta(days=1)).date().isoformat()
    _task(client, alice, "thấp", 60, priority=3)
    _task(client, alice, "cao", 60, priority=1)
    _task(client, alice, "vừa", 60, priority=2)
    res = client.post("/api/v1/tasks/schedule", headers=alice.h, json={"window_start": tomorrow, "window_end": tomorrow})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [p["task_title"] for p in body["proposals"]] == ["cao", "vừa"]  # priority order
    assert [u["task"]["title"] for u in body["unscheduled"]] == ["thấp"] and "ưu tiên thấp" in body["unscheduled"][0]["reason"]
    slots = sorted((p["start_time"], p["end_time"]) for p in body["proposals"])
    assert slots[0][1] <= slots[1][0]  # promised blocks never overlap each other


def test_SC09_scheduled_tasks_are_not_scheduled_twice(client, alice, db):
    _fragment_tomorrow(db, alice)
    tomorrow = (datetime.now(VN_TZ) + timedelta(days=1)).date().isoformat()
    _task(client, alice, "một", 60, priority=1)
    first = client.post("/api/v1/tasks/schedule", headers=alice.h, json={"window_start": tomorrow, "window_end": tomorrow}).json()
    assert len(first["proposals"]) == 1
    client.post(f"/api/v1/proposals/{first['proposals'][0]['id']}/confirm", headers=alice.h)
    again = client.post("/api/v1/tasks/schedule", headers=alice.h, json={}).json()
    assert again["proposals"] == [] and again["unscheduled"] == []  # nothing pending any more


def test_SC10_tasks_are_private_and_soft_deleted(client, alice, bob):
    t = _task(client, alice, "bí mật", 60)
    assert client.patch(f"/api/v1/tasks/{t['id']}", headers=bob.h, json={"priority": 1}).status_code == 404
    assert client.delete(f"/api/v1/tasks/{t['id']}", headers=bob.h).status_code == 404
    assert client.patch(f"/api/v1/tasks/{t['id']}", headers=alice.h, json={"priority": 1}).json()["priority_source"] == "USER"
    assert client.delete(f"/api/v1/tasks/{t['id']}", headers=alice.h).status_code == 204
    assert client.get("/api/v1/tasks", headers=alice.h).json() == []
