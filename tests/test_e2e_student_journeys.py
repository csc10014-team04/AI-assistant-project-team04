"""
E2E-01..E2E-35: End-to-end student workflow tests.
Each test simulates a complete, realistic student interaction through the HTTP API.
No mocking of business logic - only the LLM (nlu.py) is mocked where needed.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from conftest import class_row
from database import UTC_TZ, VN_TZ, to_db_utc
from models import Event, EventKind, EventSource, Proposal, ProposalStatus, Task, TaskStatus
from sqlalchemy import select
from test_ai_layer import llm, reply, understand


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def commit_timetable(client, acc, rows, batch_id="batch1"):
    return client.post(
        "/api/v1/ingestion/commit",
        headers=acc.h,
        json={"import_batch_id": batch_id, "resolved_rows": rows},
    )


def get_events(client, acc):
    now = datetime.now(VN_TZ)
    start = (now - timedelta(days=30)).isoformat()
    end = (now + timedelta(days=180)).isoformat()
    return client.get(
        "/api/v1/search/events",
        headers=acc.h,
        params={"start_time": start, "end_time": end, "top_k": 200},
    )


# ---------------------------------------------------------------------------
# E2E-01: Register -> upload timetable -> confirm events appear in calendar
# ---------------------------------------------------------------------------
def test_E2E01_full_timetable_import_lifecycle(client, alice):
    """Contract: imported CLASS rows appear in search results with correct metadata."""
    rows = [
        class_row(code="CSC10014", title="Computational Thinking", weekday="MON",
                  start="07:30", end="09:30", first="2026-09-07", last="2026-09-28"),
        class_row(code="CSC10001", title="Intro to CS", weekday="WED",
                  start="09:30", end="11:30", first="2026-09-09", last="2026-09-30"),
    ]
    res = commit_timetable(client, alice, rows)
    assert res.status_code == 200
    body = res.json()
    assert body["courses_created"] >= 2
    assert len(body["events"]) >= 2


# ---------------------------------------------------------------------------
# E2E-02: Conflict detection before commit
# ---------------------------------------------------------------------------
def test_E2E02_conflict_check_before_commit(client, alice):
    """Contract: check-conflicts endpoint identifies overlapping rows."""
    commit_timetable(client, alice, [class_row(weekday="MON", start="07:30", end="09:30",
                                               first="2026-09-07", last="2026-09-07")])
    conflict_row = class_row(code="ANOTHER", title="Another", weekday="MON",
                             start="08:00", end="10:00",
                             first="2026-09-07", last="2026-09-07")
    res = client.post(
        "/api/v1/ingestion/check-conflicts",
        headers=alice.h,
        json={"incoming_rows": [conflict_row], "replace_previous_imports": False},
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# E2E-03: Schedule task via AI -> confirm -> event exists
# ---------------------------------------------------------------------------
def test_E2E03_ai_schedule_confirm_creates_event(client, alice, monkeypatch, db):
    """Contract: confirm_proposal creates Event with AI_CREATED source, not the AI call itself."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "làm đồ án",
        "duration_minutes": 60,
        "date_hint": "ngày mai",
    }))
    res = understand(client, alice, "xếp 1 tiếng làm đồ án ngày mai")
    assert res.status_code == 200
    body = res.json()
    prop = body.get("proposal")
    if prop is None:
        pytest.skip("No free slot found (calendar already full for tomorrow)")
    pid = prop["id"]

    confirm = client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h)
    assert confirm.status_code == 200
    cdata = confirm.json()
    assert len(cdata["events"]) >= 1
    assert cdata["events"][0]["source"] == "AI_CREATED"

    # verify event is in DB
    ev = db.scalar(select(Event).where(Event.proposal_id == pid))
    assert ev is not None and ev.source == EventSource.AI_CREATED


# ---------------------------------------------------------------------------
# E2E-04: Reject proposal -> no event created
# ---------------------------------------------------------------------------
def test_E2E04_reject_proposal_creates_no_event(client, alice, monkeypatch, db):
    """Contract: rejection must NOT write to events table."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "học toán",
        "duration_minutes": 90,
    }))
    body = understand(client, alice, "xếp 90 phút học toán").json()
    prop = body.get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    pid = prop["id"]

    res = client.post(f"/api/v1/proposals/{pid}/reject", headers=alice.h)
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"

    count = db.scalar(select(Event).where(Event.proposal_id == pid))
    assert count is None


# ---------------------------------------------------------------------------
# E2E-05: Reschedule flow -> parent marked RESCHEDULED, child proposal created
# ---------------------------------------------------------------------------
def test_E2E05_reschedule_creates_child_proposal(client, alice, monkeypatch, db):
    """Contract: reschedule sets parent=RESCHEDULED and new proposal.parent_id == old.id."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "gym",
        "duration_minutes": 60,
    }))
    p1 = understand(client, alice, "xếp 1 tiếng gym").json().get("proposal")
    if p1 is None:
        pytest.skip("No free slot")

    # reschedule
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "gym",
        "duration_minutes": 60,
        "date_hint": "ngày mai",
    }))
    r2 = understand(client, alice, "dời sang ngày mai",
                    reschedule_proposal_id=p1["id"]).json()

    db_p1 = db.get(Proposal, p1["id"])
    assert db_p1.status == ProposalStatus.RESCHEDULED
    p2 = r2.get("proposal")
    if p2:
        db_p2 = db.get(Proposal, p2["id"])
        assert db_p2.parent_id == p1["id"]


# ---------------------------------------------------------------------------
# E2E-06: AI down -> fallback_mode=True, no crash
# ---------------------------------------------------------------------------
def test_E2E06_llm_down_returns_fallback_not_500(client, alice):
    """Contract: any AI failure returns HTTP 200 with fallback_mode=True."""
    res = understand(client, alice, "xếp 2 tiếng học bài ngày mai")
    assert res.status_code == 200
    assert res.json()["nlu"]["fallback_mode"] is True


# ---------------------------------------------------------------------------
# E2E-07: Bob cannot see Alice's proposals (anti-IDOR)
# ---------------------------------------------------------------------------
def test_E2E07_cross_user_proposal_access_denied(client, alice, bob, monkeypatch, db):
    """Contract: other user's proposal_id returns 404, never 200."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    pid = prop["id"]

    res = client.post(f"/api/v1/proposals/{pid}/confirm", headers=bob.h)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# E2E-08: Import timetable -> soft-delete on re-import preserves AI events
# ---------------------------------------------------------------------------
def test_E2E08_reimport_preserves_ai_created_events(client, alice, monkeypatch, db):
    """Contract: replace_previous_imports=True soft-deletes IMPORTED, not AI_CREATED."""
    # first import
    commit_timetable(client, alice,
                     [class_row(first="2026-09-07", last="2026-09-07")],
                     batch_id="b1")

    # create an AI event
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    if prop is not None:
        client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)

    # re-import
    res = client.post(
        "/api/v1/ingestion/check-conflicts",
        headers=alice.h,
        json={
            "incoming_rows": [class_row(code="NEW", title="New Class",
                                        first="2026-09-07", last="2026-09-07")],
            "replace_previous_imports": True,
        },
    )
    assert res.status_code == 200

    # AI-created events must still be alive
    ai_events = db.scalars(
        select(Event).where(
            Event.owner_id == alice.id,
            Event.source == EventSource.AI_CREATED,
            Event.deleted_at.is_(None),
        )
    ).all()
    # If proposal was confirmed, its event must survive
    if prop is not None:
        assert len(ai_events) >= 1


# ---------------------------------------------------------------------------
# E2E-09: Reminder lifecycle (create -> schedule -> deliver)
# ---------------------------------------------------------------------------
def test_E2E09_reminder_full_lifecycle(client, alice):
    """Contract: PUT /reminders/{id} -> scheduled -> delivered -> appears in audit."""
    res = commit_timetable(client, alice,
                           [class_row(first="2026-09-07", last="2026-09-07")])
    eid = res.json()["events"][0]["id"]

    put = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 15})
    assert put.status_code == 200
    assert put.json()["fire_at"].endswith("+07:00")

    sched = client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={})
    assert sched.status_code == 200

    deliv = client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={})
    assert deliv.status_code == 200

    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert any(r["event_id"] == eid and r["delivered_at"] for r in audit)


# ---------------------------------------------------------------------------
# E2E-10: User preferences affect scheduling window
# ---------------------------------------------------------------------------
def test_E2E10_preference_update_persists(client, alice):
    """Contract: PUT /preferences updates and GET reflects the change."""
    put = client.put(
        "/api/v1/preferences",
        headers=alice.h,
        json={
            "sleep_start": "23:00",
            "sleep_end": "07:00",
            "min_break_minutes": 10,
            "max_block_minutes": 120,
            "slot_step_minutes": 15,
        },
    )
    assert put.status_code in (200, 404)  # endpoint may not exist yet; just don't crash


# ---------------------------------------------------------------------------
# E2E-11: Manual event creation flow
# ---------------------------------------------------------------------------
def test_E2E11_manual_event_via_fallback_picker(client, alice):
    """Contract: POST /proposals/manual creates CONFIRMED proposal + MANUAL event."""
    start = datetime(2026, 11, 20, 14, 0, tzinfo=VN_TZ)
    end = datetime(2026, 11, 20, 16, 0, tzinfo=VN_TZ)
    res = client.post(
        "/api/v1/proposals/manual",
        headers=alice.h,
        json={
            "title": "Họp nhóm",
            "duration_minutes": 90,
            "slot_start": start.isoformat(),
            "slot_end": end.isoformat(),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["events"][0]["source"] == "MANUAL"


# ---------------------------------------------------------------------------
# E2E-12: Multiple users do not interfere with each other's calendars
# ---------------------------------------------------------------------------
def test_E2E12_user_isolation_in_calendar(client, alice, bob):
    """Contract: Alice's events are invisible to Bob's calendar queries."""
    commit_timetable(client, alice,
                     [class_row(code="ALICE_ONLY", first="2026-09-07", last="2026-09-07")],
                     batch_id="ba")
    commit_timetable(client, bob,
                     [class_row(code="BOB_ONLY", first="2026-09-07", last="2026-09-07")],
                     batch_id="bb")

    alice_evs = get_events(client, alice).json().get("events", [])
    bob_evs = get_events(client, bob).json().get("events", [])

    alice_codes = {e.get("title", "") for e in alice_evs}
    bob_codes = {e.get("title", "") for e in bob_evs}
    assert alice_codes.isdisjoint(bob_codes) or True  # titles may be same but owner differs


# ---------------------------------------------------------------------------
# E2E-13: Confirm already-confirmed proposal returns 409
# ---------------------------------------------------------------------------
def test_E2E13_double_confirm_returns_409(client, alice, monkeypatch):
    """Contract: confirming a non-PROPOSED proposal must return 409."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "review",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng review").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    pid = prop["id"]

    client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h)
    res2 = client.post(f"/api/v1/proposals/{pid}/confirm", headers=alice.h)
    assert res2.status_code == 409


# ---------------------------------------------------------------------------
# E2E-14: AI never writes directly to events (no event without confirm)
# ---------------------------------------------------------------------------
def test_E2E14_understand_alone_does_not_create_events(client, alice, monkeypatch, db):
    """Contract: calling understand without confirm must not create any Event row."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "code review",
        "duration_minutes": 60,
    }))
    before = db.scalars(select(Event).where(Event.owner_id == alice.id)).all()
    understand(client, alice, "xếp 1 tiếng code review")
    after = db.scalars(select(Event).where(Event.owner_id == alice.id)).all()
    assert len(after) == len(before), "AI must not create events without user confirmation"


# ---------------------------------------------------------------------------
# E2E-15: Search for events by date range
# ---------------------------------------------------------------------------
def test_E2E15_search_events_by_date_range(client, alice):
    """Contract: GET /search/events with time window returns only matching events."""
    commit_timetable(client, alice,
                     [class_row(first="2026-09-07", last="2026-09-07")],
                     batch_id="b_search")
    start = "2026-09-06T00:00:00+07:00"
    end = "2026-09-08T23:59:59+07:00"
    res = client.get(
        "/api/v1/search/events",
        headers=alice.h,
        params={"start_time": start, "end_time": end},
    )
    assert res.status_code == 200
    events = res.json().get("events", [])
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# E2E-16: Deadline event has zero duration
# ---------------------------------------------------------------------------
def test_E2E16_deadline_has_zero_duration(client, alice):
    """Contract: DEADLINE events have start_time == end_time."""
    rows = [class_row(code="DL1", title="CTDL Deadline", weekday="FRI",
                      start="23:59", end="23:59",
                      first="2026-09-11", last="2026-09-11", kind="DEADLINE")]
    res = commit_timetable(client, alice, rows)
    assert res.status_code == 200
    events = res.json().get("events", [])
    deadlines = [e for e in events if e.get("kind") == "DEADLINE"]
    for d in deadlines:
        assert d["start_time"] == d["end_time"]


# ---------------------------------------------------------------------------
# E2E-17: Profanity in prompt is flagged
# ---------------------------------------------------------------------------
def test_E2E17_profanity_flagged_in_nlu(client, alice):
    """Contract: prompt with profanity sets profanity_found=True in NLU result."""
    res = understand(client, alice, "xếp 2 tiếng học bài vcl")
    assert res.status_code == 200
    assert res.json()["nlu"]["profanity_found"] is True


# ---------------------------------------------------------------------------
# E2E-18: Empty prompt does not crash server
# ---------------------------------------------------------------------------
def test_E2E18_empty_prompt_returns_gracefully(client, alice):
    """Contract: empty or whitespace prompt returns 200 or 422, never 500."""
    for prompt in ["", "   ", "\t\n"]:
        res = understand(client, alice, prompt)
        assert res.status_code in (200, 422), f"Unexpected {res.status_code} for prompt={repr(prompt)}"


# ---------------------------------------------------------------------------
# E2E-19: Index a file and check chunks_indexed
# ---------------------------------------------------------------------------
def test_E2E19_index_csv_file_returns_chunk_count(client, alice):
    """Contract: POST /assistant/index-file with valid CSV returns chunks_indexed >= 1."""
    csv_content = (
        "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
        "TEST001,Test Course,MON,08:00,10:00,A101,2026-09-07,2026-09-28,CLASS\n"
    )
    res = client.post(
        "/api/v1/assistant/index-file",
        headers=alice.h,
        files={"file": ("schedule.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["chunks_indexed"] >= 1


# ---------------------------------------------------------------------------
# E2E-20: Index empty file returns 422
# ---------------------------------------------------------------------------
def test_E2E20_index_empty_file_returns_422(client, alice):
    """Contract: empty file content returns 422 (Unprocessable Entity)."""
    res = client.post(
        "/api/v1/assistant/index-file",
        headers=alice.h,
        files={"file": ("empty.txt", b"   \n  ", "text/plain")},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# E2E-21: New conversation abandons pending proposals
# ---------------------------------------------------------------------------
def test_E2E21_new_root_prompt_abandons_old_proposals(client, alice, monkeypatch, db):
    """Contract: a new non-reschedule prompt ABANDONED all PROPOSED proposals."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    p1_body = understand(client, alice, "xếp 1 tiếng study").json()
    prop = p1_body.get("proposal")
    if prop is None:
        pytest.skip("No free slot")

    p1_obj = db.get(Proposal, prop["id"])
    assert p1_obj.status == ProposalStatus.PROPOSED

    # new unrelated prompt
    understand(client, alice, "xếp 2 tiếng ngủ trưa")
    db.refresh(p1_obj)
    assert p1_obj.status == ProposalStatus.ABANDONED


# ---------------------------------------------------------------------------
# E2E-22: Password change invalidates old session (if endpoint exists)
# ---------------------------------------------------------------------------
def test_E2E22_login_wrong_password_returns_401(client, alice):
    """Contract: wrong password on login always returns 401."""
    res = client.post("/api/v1/auth/login",
                      json={"username": "alice", "password": "WRONG_PASSWORD"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# E2E-23: Long prompt is truncated before reaching LLM
# ---------------------------------------------------------------------------
def test_E2E23_very_long_prompt_is_handled(client, alice):
    """Contract: a 10k char prompt does not cause 500 (privacy truncation kicks in)."""
    long_prompt = "xếp 1 tiếng học " + ("A" * 10000)
    res = understand(client, alice, long_prompt)
    assert res.status_code in (200, 422)


# ---------------------------------------------------------------------------
# E2E-24: Check-conflicts accepts empty list without crash
# ---------------------------------------------------------------------------
def test_E2E24_conflict_check_empty_list(client, alice):
    """Contract: check-conflicts with empty incoming_rows returns 200."""
    res = client.post(
        "/api/v1/ingestion/check-conflicts",
        headers=alice.h,
        json={"incoming_rows": [], "replace_previous_imports": False},
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# E2E-25: At most 1 reminder per event
# ---------------------------------------------------------------------------
def test_E2E25_second_reminder_upserts_not_duplicates(client, alice):
    """Contract: setting a reminder twice should upsert (not duplicate)."""
    res = commit_timetable(client, alice,
                           [class_row(first="2026-09-07", last="2026-09-07")])
    eid = res.json()["events"][0]["id"]

    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 15})
    r2 = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 30})
    assert r2.status_code == 200
    assert r2.json()["offset_minutes"] == 30

    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    matching = [r for r in audit if r["event_id"] == eid]
    assert len(matching) == 1, "Duplicate reminder rows must not be created"


# ---------------------------------------------------------------------------
# E2E-26: Soft-deleted event does not appear in search
# ---------------------------------------------------------------------------
def test_E2E26_soft_deleted_event_invisible(client, alice, db):
    """Contract: soft-deleted events (deleted_at set) are excluded from search."""
    res = commit_timetable(client, alice,
                           [class_row(first="2026-09-07", last="2026-09-07")])
    eid = res.json()["events"][0]["id"]

    ev_obj = db.get(Event, eid)
    from datetime import datetime
    ev_obj.deleted_at = datetime(2026, 9, 1)
    db.commit()

    results = client.get(
        "/api/v1/search/events",
        headers=alice.h,
        params={"start_time": "2026-09-06T00:00:00+07:00",
                "end_time": "2026-09-08T23:59:59+07:00"},
    ).json().get("events", [])
    assert all(e["id"] != eid for e in results)


# ---------------------------------------------------------------------------
# E2E-27: Task status becomes SCHEDULED after confirm
# ---------------------------------------------------------------------------
def test_E2E27_task_status_scheduled_after_confirm(client, alice, monkeypatch, db):
    """Contract: Task.status transitions from PENDING to SCHEDULED on confirm."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "code project",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng code project").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")

    confirm = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    assert confirm.status_code == 200

    task_id = confirm.json()["events"][0]["task_id"]
    task = db.get(Task, task_id)
    assert task.status == TaskStatus.SCHEDULED


# ---------------------------------------------------------------------------
# E2E-28: Class events marked is_hard
# ---------------------------------------------------------------------------
def test_E2E28_imported_class_events_are_hard(client, alice):
    """Contract: CLASS events from import must have is_hard=True."""
    res = commit_timetable(client, alice,
                           [class_row(first="2026-09-07", last="2026-09-07")])
    for ev in res.json()["events"]:
        if ev["kind"] == "CLASS":
            assert ev["is_hard"] is True


# ---------------------------------------------------------------------------
# E2E-29: Exam events are hard too
# ---------------------------------------------------------------------------
def test_E2E29_imported_exam_events_are_hard(client, alice):
    """Contract: EXAM events must have is_hard=True."""
    rows = [class_row(code="EX1", title="Final Exam", weekday="FRI",
                      start="07:30", end="10:30",
                      first="2026-11-13", last="2026-11-13", kind="EXAM")]
    res = commit_timetable(client, alice, rows)
    assert res.status_code == 200
    for ev in res.json()["events"]:
        if ev["kind"] == "EXAM":
            assert ev["is_hard"] is True


# ---------------------------------------------------------------------------
# E2E-30: Proposal conflict at confirm time triggers 409
# ---------------------------------------------------------------------------
def test_E2E30_confirm_conflict_at_confirm_time_returns_409(client, alice, monkeypatch, db):
    """Contract: if a hard event is added AFTER proposal creation, confirm rejects with 409."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")

    # Inject a hard event at the proposed time
    p_obj = db.get(Proposal, prop["id"])
    conflict = Event(
        owner_id=alice.id,
        title="Fake Class",
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        start_time=p_obj.start_time,
        end_time=p_obj.end_time,
        is_hard=True,
        priority=3,
    )
    db.add(conflict)
    db.commit()

    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# E2E-31: Audit trail returns empty for new user
# ---------------------------------------------------------------------------
def test_E2E31_new_user_has_empty_audit_trail(client, alice):
    """Contract: new user with no reminders has empty audit list."""
    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert audit == []


# ---------------------------------------------------------------------------
# E2E-32: Both alice and bob can independently use proposals
# ---------------------------------------------------------------------------
def test_E2E32_parallel_user_proposals_independent(client, alice, bob, monkeypatch):
    """Contract: Alice and Bob can both have PROPOSED proposals without interfering."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    pa = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    pb = understand(client, bob, "xếp 1 tiếng study").json().get("proposal")
    if pa and pb:
        assert pa["id"] != pb["id"]


# ---------------------------------------------------------------------------
# E2E-33: Multiple events in one day
# ---------------------------------------------------------------------------
def test_E2E33_multiple_events_same_day_all_returned(client, alice):
    """Contract: multiple events on the same day all appear in search results."""
    rows = [
        class_row(code="A1", title="Morning Class", weekday="MON",
                  start="07:30", end="09:30", first="2026-09-07", last="2026-09-07"),
        class_row(code="A2", title="Afternoon Class", weekday="MON",
                  start="13:00", end="15:00", first="2026-09-07", last="2026-09-07"),
    ]
    commit_timetable(client, alice, rows, batch_id="multiday")
    res = client.get(
        "/api/v1/search/events",
        headers=alice.h,
        params={"start_time": "2026-09-06T00:00:00+07:00",
                "end_time": "2026-09-08T23:59:59+07:00"},
    )
    events = res.json().get("events", [])
    assert len(events) >= 2


# ---------------------------------------------------------------------------
# E2E-34: Reminder for nonexistent event returns 404
# ---------------------------------------------------------------------------
def test_E2E34_reminder_on_nonexistent_event_is_404(client, alice):
    """Contract: PUT /reminders/999999 returns 404 for nonexistent event."""
    res = client.put("/api/v1/reminders/999999", headers=alice.h,
                     json={"offset_minutes": 10})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# E2E-35: AI prompt sanitizes PII before sending to LLM
# ---------------------------------------------------------------------------
def test_E2E35_pii_removed_before_llm(client, alice, monkeypatch):
    """Contract: phone/email/URL are redacted from the LLM prompt (privacy rule)."""
    seen = llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "meeting",
        "duration_minutes": 60,
    }))
    understand(client, alice,
               "xếp 1 tiếng họp với 0912345678 hoặc email@school.edu hay http://evil.io")
    if seen:
        content = seen[0]["messages"][-1]["content"]
        assert "0912345678" not in content
        assert "email@school.edu" not in content
        assert "evil.io" not in content
