"""PR-01..PR-12: proposal lifecycle API (AGENTS.md section 4): create -> confirm / reject / reschedule, manual picker."""
from datetime import datetime, timedelta

from sqlalchemy import select

from database import UTC_TZ, VN_TZ, to_db_utc
from models import Event, EventKind, EventSource, Proposal, ProposalStatus, Reminder, Task, TaskStatus
from test_ai_layer import llm, reply, understand

SCHEDULE = {"intent": "schedule_task", "title": "làm đồ án", "duration_minutes": 120, "date_hint": "ngày mai"}


def make_proposal(client, acc, monkeypatch, **extra):
    llm(monkeypatch, lambda r: reply(SCHEDULE))
    res = understand(client, acc, "xếp 2 tiếng làm đồ án ngày mai", **extra)
    assert res.status_code == 200, res.text
    return res.json()


def test_PR01_understand_returns_a_proposal_and_writes_no_event(client, alice, db, monkeypatch):
    body = make_proposal(client, alice, monkeypatch)
    p = body["proposal"]
    assert p["status"] == "PROPOSED" and p["task_title"] == "làm đồ án" and p["duration_minutes"] == 120
    start, end = datetime.fromisoformat(p["start_time"]), datetime.fromisoformat(p["end_time"])
    assert end - start == timedelta(minutes=120) and start.minute % 15 == 0 and start.utcoffset() == timedelta(hours=7)
    assert db.scalars(select(Event)).all() == []  # the AI never writes to events directly


def test_PR02_confirm_creates_task_event_reminder_and_updates_task(client, alice, db, monkeypatch):
    pid = make_proposal(client, alice, monkeypatch)["proposal"]["id"]
    res = client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h)
    assert res.status_code == 200, res.text
    out = res.json()
    ev = db.scalars(select(Event)).one()
    assert ev.kind == EventKind.TASK and ev.source == EventSource.AI_CREATED and ev.proposal_id == pid
    assert db.scalars(select(Reminder)).one().event_id == ev.id
    assert out["reminders"][0]["event_id"] == ev.id and out["reminders"][0]["fire_at"]  # phone schedules its alarm here
    assert db.get(Proposal, pid).status == ProposalStatus.CONFIRMED
    assert db.scalars(select(Task)).one().status == TaskStatus.SCHEDULED


def test_PR03_confirm_twice_is_rejected_with_409(client, alice, monkeypatch):
    pid = make_proposal(client, alice, monkeypatch)["proposal"]["id"]
    assert client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h).status_code == 200
    assert client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h).status_code == 409


def test_PR04_confirm_revalidates_conflicts_if_calendar_changed(client, alice, db, monkeypatch):
    p = make_proposal(client, alice, monkeypatch)["proposal"]
    start = datetime.fromisoformat(p["start_time"])
    db.add(Event(owner_id=alice.id, title="Thi giữa kỳ", kind=EventKind.EXAM, source=EventSource.IMPORTED, is_hard=True,
                 start_time=to_db_utc(start - timedelta(minutes=30)), end_time=to_db_utc(start + timedelta(minutes=30))))
    db.commit()
    res = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    assert res.status_code == 409 and "Thi giữa kỳ" in res.json()["detail"]
    assert db.scalars(select(Event).where(Event.kind == EventKind.TASK)).all() == []  # nothing half-written
    assert db.get(Proposal, p["id"]).status == ProposalStatus.PROPOSED


def test_PR05_reject_marks_rejected_and_leaves_calendar_empty(client, alice, db, monkeypatch):
    pid = make_proposal(client, alice, monkeypatch)["proposal"]["id"]
    res = client.post(f"/api/v1/proposals/{pid}/reject", headers=alice.h)
    assert res.status_code == 200 and res.json()["status"] == "REJECTED"
    assert db.scalars(select(Event)).all() == []
    assert client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h).status_code == 409


def test_PR06_other_users_cannot_see_or_change_a_proposal(client, alice, bob, monkeypatch):
    pid = make_proposal(client, alice, monkeypatch)["proposal"]["id"]
    for path, method in ((f"/api/v1/proposals/{pid}", "get"), (f"/api/v1/proposals/{pid}/confirm", "post"),
                         (f"/api/v1/proposals/{pid}/reject", "post")):
        assert getattr(client, method)(path, headers=bob.h).status_code == 404  # anti-IDOR


def test_PR07_reschedule_creates_child_proposal_for_same_task_at_new_slot(client, alice, db, monkeypatch):
    first = make_proposal(client, alice, monkeypatch)["proposal"]
    llm(monkeypatch, lambda r: reply({"intent": "reschedule", "preferred_time_of_day": "evening", "date_hint": "ngày mai"}))
    res = understand(client, alice, "dời sang buổi tối", reschedule_proposal_id=first["id"])
    assert res.status_code == 200, res.text
    new = res.json()["proposal"]
    assert new["parent_id"] == first["id"] and new["task_id"] == first["task_id"] and new["task_title"] == "làm đồ án"
    assert new["start_time"] != first["start_time"]  # the rejected slot is excluded
    assert datetime.fromisoformat(new["start_time"]).hour >= 18  # honours "evening"
    assert db.get(Proposal, first["id"]).status == ProposalStatus.RESCHEDULED
    assert res.json()["abandoned_proposals"] == 0  # a reschedule is not a new topic


def test_PR08_new_root_prompt_abandons_the_pending_proposal(client, alice, db, monkeypatch):
    first = make_proposal(client, alice, monkeypatch)["proposal"]
    second = make_proposal(client, alice, monkeypatch)
    assert second["abandoned_proposals"] == 1
    assert db.get(Proposal, first["id"]).status == ProposalStatus.ABANDONED


def test_PR09_ai_down_gives_fallback_and_no_proposal(client, alice):
    body = understand(client, alice, "xếp 2 tiếng làm đồ án ngày mai").json()  # conftest: AI is down
    assert body["nlu"]["fallback_mode"] is True and body["proposal"] is None and body["message"]


def test_PR10_manual_pick_places_task_at_gap_start_with_source_manual(client, alice, db):
    gap_start = (datetime.now(VN_TZ) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    res = client.post("/api/v1/proposals/manual", headers=alice.h, json={
        "title": "đi livestream", "duration_minutes": 180,
        "slot_start": gap_start.isoformat(), "slot_end": (gap_start + timedelta(hours=14)).isoformat()})
    assert res.status_code == 201, res.text
    ev = db.scalars(select(Event)).one()
    assert ev.source == EventSource.MANUAL and ev.kind == EventKind.TASK
    assert ev.end_time - ev.start_time == timedelta(hours=3)  # 3 h, not the whole 14 h gap
    assert db.scalars(select(Reminder)).one().event_id == ev.id


def test_PR11_manual_pick_validates_slot_length_and_grid(client, alice):
    start = (datetime.now(VN_TZ) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    short = {"title": "x", "duration_minutes": 120, "slot_start": start.isoformat(), "slot_end": (start + timedelta(hours=1)).isoformat()}
    assert client.post("/api/v1/proposals/manual", headers=alice.h, json=short).status_code == 422
    off_grid = {**short, "slot_start": (start + timedelta(minutes=7)).isoformat(), "slot_end": (start + timedelta(hours=5)).isoformat()}
    assert client.post("/api/v1/proposals/manual", headers=alice.h, json=off_grid).status_code == 422


def test_PR12_manual_pick_cannot_overlap_an_existing_class(client, alice, db):
    start = (datetime.now(VN_TZ) + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    db.add(Event(owner_id=alice.id, title="Toán", kind=EventKind.CLASS, source=EventSource.IMPORTED, is_hard=True,
                 start_time=to_db_utc(start), end_time=to_db_utc(start + timedelta(hours=2))))
    db.commit()
    res = client.post("/api/v1/proposals/manual", headers=alice.h, json={
        "title": "x", "duration_minutes": 60, "slot_start": start.isoformat(), "slot_end": (start + timedelta(hours=3)).isoformat()})
    assert res.status_code == 409 and "Toán" in res.json()["detail"]
    assert db.scalars(select(Task)).all() == []  # rolled back, no orphan task
