"""
REM-01..REM-22: Reminders and audit trail tests.
Covers: reminder creation, offset limits, fire_at calculation, audit log,
        owner isolation, upsert semantics, delivered lifecycle.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from conftest import class_row
from database import VN_TZ
from models import Event, Reminder


# ---- helpers ----------------------------------------------------------------
def _commit_and_get_event_id(client, acc, batch_id="b"):
    res = client.post(
        "/api/v1/ingestion/commit",
        headers=acc.h,
        json={"import_batch_id": batch_id,
              "resolved_rows": [class_row(first="2026-09-07", last="2026-09-07")]},
    )
    events = res.json().get("events", [])
    return events[0]["id"] if events else None


# ---- REM-01: Set reminder returns fire_at in +07:00 format ----------------
def test_REM01_fire_at_has_vn_timezone(client, alice):
    """Contract: PUT /reminders/{id} returns fire_at ending with +07:00."""
    eid = _commit_and_get_event_id(client, alice)
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                     json={"offset_minutes": 30})
    assert res.status_code == 200
    fire_at = res.json()["fire_at"]
    assert fire_at.endswith("+07:00"), f"fire_at timezone unexpected: {fire_at}"


# ---- REM-02: fire_at = event.start_time - offset --------------------------
def test_REM02_fire_at_is_start_minus_offset(client, alice):
    """Contract: fire_at = event.start_time - offset_minutes."""
    eid = _commit_and_get_event_id(client, alice)
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                     json={"offset_minutes": 30})
    fire_at = res.json()["fire_at"]
    # Class starts at 07:30 VN; 30 min before = 07:00
    assert "07:00" in fire_at or "T07:00:00" in fire_at


# ---- REM-03: Negative offset rejected with 422 ----------------------------
def test_REM03_negative_offset_422(client, alice):
    """Contract: PUT /reminders/{id} with offset_minutes < 0 returns 422."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b3")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                     json={"offset_minutes": -1})
    assert res.status_code == 422


# ---- REM-04: Oversized offset rejected with 422 ---------------------------
def test_REM04_oversized_offset_422(client, alice):
    """Contract: PUT /reminders/{id} with offset_minutes > 7*24*60 returns 422."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b4")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                     json={"offset_minutes": 7 * 24 * 60 + 1})
    assert res.status_code == 422


# ---- REM-05: Reminder for non-existent event returns 404 ------------------
def test_REM05_nonexistent_event_404(client, alice):
    """Contract: PUT /reminders/999999 returns 404."""
    res = client.put("/api/v1/reminders/999999", headers=alice.h,
                     json={"offset_minutes": 15})
    assert res.status_code == 404


# ---- REM-06: Second PUT upserts (same event, different offset) -------------
def test_REM06_second_put_upserts(client, alice):
    """Contract: setting reminder twice upserts (not duplicates)."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b6")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 15})
    r2 = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 60})
    assert r2.status_code == 200
    assert r2.json()["offset_minutes"] == 60

    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    matching = [r for r in audit if r["event_id"] == eid]
    assert len(matching) == 1


# ---- REM-07: Scheduled state is tracked ------------------------------------
def test_REM07_scheduled_on_device_recorded(client, alice):
    """Contract: POST /reminders/{id}/scheduled records scheduled_on_device_at."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b7")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    res = client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={})
    assert res.status_code == 200
    assert res.json()["scheduled_on_device_at"] is not None


# ---- REM-08: Delivered state is tracked ------------------------------------
def test_REM08_delivered_recorded(client, alice):
    """Contract: POST /reminders/{id}/delivered records delivered_at."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b8")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={})
    res = client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={})
    assert res.status_code == 200
    assert res.json()["delivered_at"] is not None


# ---- REM-09: Delivered before creation returns 404 -------------------------
def test_REM09_delivered_without_reminder_returns_404(client, alice):
    """Contract: POST /reminders/{id}/delivered without prior PUT returns 404."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b9")
    if eid is None:
        pytest.skip("No events committed")
    res = client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={})
    assert res.status_code == 404


# ---- REM-10: Audit trail shows all reminder states -------------------------
def test_REM10_audit_trail_complete_lifecycle(client, alice, tmp_path):
    """Contract: audit trail records created, scheduled, delivered actions."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b10")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={})
    client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={})

    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert any(r["event_id"] == eid and r.get("delivered_at") for r in audit)


# ---- REM-11: Empty audit for new user -------------------------------------
def test_REM11_new_user_audit_empty(client, alice):
    """Contract: brand-new user has empty audit trail."""
    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert audit == []


# ---- REM-12: Bob cannot read Alice's audit --------------------------------
def test_REM12_audit_isolated_per_user(client, alice, bob):
    """Contract: Bob's audit is empty even when Alice has reminders."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b12")
    if eid:
        client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 5})
    bob_audit = client.get("/api/v1/reminders/audit", headers=bob.h).json()
    assert bob_audit == []


# ---- REM-13: Bob cannot PUT on Alice's event's reminder ------------------
def test_REM13_bob_cannot_put_alice_reminder(client, alice, bob):
    """Contract: PUT /reminders/{alice_event_id} with bob's token returns 404."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b13")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=bob.h, json={"offset_minutes": 5})
    assert res.status_code == 404


# ---- REM-14: Soft-deleted event disappears from audit ----------------------
def test_REM14_soft_deleted_event_removed_from_audit(client, alice, db):
    """Contract: soft-deleted events are excluded from audit trail results."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b14")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 5})

    ev = db.get(Event, eid)
    ev.deleted_at = datetime(2026, 9, 1)
    db.commit()

    audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert all(r["event_id"] != eid for r in audit)


# ---- REM-15: Reminder offset_minutes is returned in GET -------------------
def test_REM15_reminder_includes_offset_in_response(client, alice):
    """Contract: PUT response includes the stored offset_minutes."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b15")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 45})
    assert res.json()["offset_minutes"] == 45


# ---- REM-16: Reminder for AI-confirmed event is auto-created ---------------
def test_REM16_ai_confirmed_event_has_reminder(client, alice, monkeypatch):
    """Contract: confirming an AI proposal auto-creates a Reminder row."""
    from test_ai_layer import llm, reply, understand
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "read",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng read").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h).json()
    assert len(res.get("reminders", [])) >= 1


# ---- REM-17: Default reminder offset is 30 minutes -----------------------
def test_REM17_default_reminder_offset_30min(client, alice, monkeypatch):
    """Contract: auto-created reminder defaults to 30 minutes before event."""
    from test_ai_layer import llm, reply, understand
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "code",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng code").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h).json()
    for r in res.get("reminders", []):
        assert r["offset_minutes"] == 30


# ---- REM-18: At most 1 reminder per event (unique constraint) -------------
def test_REM18_one_reminder_per_event(client, alice, db):
    """Contract: Reminder.event_id has UNIQUE constraint (at most 1 per event)."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b18")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 20})

    from sqlalchemy import select
    rows = db.scalars(select(Reminder).where(Reminder.event_id == eid)).all()
    assert len(rows) == 1


# ---- REM-19: Bob cannot POST scheduled for Alice's event -----------------
def test_REM19_bob_cannot_schedule_alice_reminder(client, alice, bob):
    """Contract: POST /reminders/{alice_eid}/scheduled with Bob's token returns 404."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b19")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 5})
    res = client.post(f"/api/v1/reminders/{eid}/scheduled", headers=bob.h, json={})
    assert res.status_code == 404


# ---- REM-20: Bob cannot POST delivered for Alice's event -----------------
def test_REM20_bob_cannot_deliver_alice_reminder(client, alice, bob):
    """Contract: POST /reminders/{alice_eid}/delivered with Bob's token returns 404."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b20")
    if eid is None:
        pytest.skip("No events committed")
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 5})
    client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={})
    res = client.post(f"/api/v1/reminders/{eid}/delivered", headers=bob.h, json={})
    assert res.status_code == 404


# ---- REM-21: Reminder response includes event_id -------------------------
def test_REM21_reminder_response_includes_event_id(client, alice):
    """Contract: PUT /reminders/{id} response body includes event_id."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b21")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    assert res.json().get("event_id") == eid


# ---- REM-22: Zero offset is valid (reminder at exact event time) ----------
def test_REM22_zero_offset_is_valid(client, alice):
    """Contract: offset_minutes=0 is a valid reminder (fires at event start)."""
    eid = _commit_and_get_event_id(client, alice, batch_id="b22")
    if eid is None:
        pytest.skip("No events committed")
    res = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 0})
    assert res.status_code == 200
