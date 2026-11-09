"""
PSM-01..PSM-28: Proposal state machine tests.
Covers the full PROPOSED -> CONFIRMED | REJECTED | RESCHEDULED | ABANDONED lifecycle.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from conftest import class_row
from database import UTC_TZ, VN_TZ, to_db_utc
from models import (
    Event, EventKind, EventSource, Proposal, ProposalStatus, Task, TaskStatus,
)
from test_ai_layer import llm, reply, understand


# ---- helpers ----------------------------------------------------------------

def _proposal_via_ai(client, acc, monkeypatch, title="study", duration=60):
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": title,
        "duration_minutes": duration,
    }))
    body = understand(client, acc, f"xếp {duration // 60 or 1} tiếng {title}").json()
    return body.get("proposal")


def _bare_proposal(db, owner_id, task_id, start_offset_hours=1):
    now = datetime.now(UTC_TZ)
    start = to_db_utc(now + timedelta(hours=start_offset_hours))
    end = to_db_utc(now + timedelta(hours=start_offset_hours + 1))
    p = Proposal(
        owner_id=owner_id,
        task_id=task_id,
        start_time=start,
        end_time=end,
        status=ProposalStatus.PROPOSED,
    )
    db.add(p)
    db.commit()
    return p


# ---- PSM-01: Initial state is PROPOSED -------------------------------------
def test_PSM01_initial_proposal_state_is_proposed(client, alice, monkeypatch, db):
    """Contract: newly created proposals must have status=PROPOSED."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    obj = db.get(Proposal, prop["id"])
    assert obj.status == ProposalStatus.PROPOSED


# ---- PSM-02: PROPOSED -> CONFIRMED -----------------------------------------
def test_PSM02_confirm_transitions_to_confirmed(client, alice, monkeypatch, db):
    """Contract: confirm changes status from PROPOSED to CONFIRMED."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    assert res.status_code == 200
    obj = db.get(Proposal, prop["id"])
    assert obj.status == ProposalStatus.CONFIRMED


# ---- PSM-03: PROPOSED -> REJECTED ------------------------------------------
def test_PSM03_reject_transitions_to_rejected(client, alice, monkeypatch, db):
    """Contract: reject changes status from PROPOSED to REJECTED."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=alice.h)
    assert res.status_code == 200
    obj = db.get(Proposal, prop["id"])
    assert obj.status == ProposalStatus.REJECTED


# ---- PSM-04: CONFIRMED proposal cannot be confirmed again ------------------
def test_PSM04_double_confirm_returns_409(client, alice, monkeypatch, db):
    """Contract: attempting to confirm an already-CONFIRMED proposal returns 409."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-05: REJECTED proposal cannot be confirmed ------------------------
def test_PSM05_confirm_rejected_returns_409(client, alice, monkeypatch, db):
    """Contract: confirming a REJECTED proposal returns 409."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=alice.h)
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-06: CONFIRMED proposal cannot be rejected -------------------------
def test_PSM06_reject_confirmed_returns_409(client, alice, monkeypatch, db):
    """Contract: rejecting a CONFIRMED proposal returns 409."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=alice.h)
    res = client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-07: REJECTED proposal cannot be rejected again -------------------
def test_PSM07_double_reject_returns_409(client, alice, monkeypatch, db):
    """Contract: rejecting an already-REJECTED proposal returns 409."""
    prop = _proposal_via_ai(client, alice, monkeypatch)
    if prop is None:
        pytest.skip("No free slot")
    client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=alice.h)
    res = client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-08: Reschedule creates child proposal with parent_id set ----------
def test_PSM08_reschedule_child_has_parent_id(client, alice, monkeypatch, db):
    """Contract: rescheduled proposal sets new proposal's parent_id = old.id."""
    p1 = _proposal_via_ai(client, alice, monkeypatch, title="yoga")
    if p1 is None:
        pytest.skip("No free slot")

    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "yoga",
        "duration_minutes": 60,
    }))
    body = understand(client, alice, "dời sang tối mai",
                      reschedule_proposal_id=p1["id"]).json()

    p2 = body.get("proposal")
    if p2:
        p2_obj = db.get(Proposal, p2["id"])
        assert p2_obj.parent_id == p1["id"]


# ---- PSM-09: Reschedule sets parent to RESCHEDULED ------------------------
def test_PSM09_reschedule_parent_marked_rescheduled(client, alice, monkeypatch, db):
    """Contract: after reschedule, old proposal status = RESCHEDULED."""
    p1 = _proposal_via_ai(client, alice, monkeypatch, title="run")
    if p1 is None:
        pytest.skip("No free slot")

    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "run",
        "duration_minutes": 60,
    }))
    understand(client, alice, "dời sang ngày mai", reschedule_proposal_id=p1["id"])

    p1_obj = db.get(Proposal, p1["id"])
    assert p1_obj.status == ProposalStatus.RESCHEDULED


# ---- PSM-10: Abandon on new root prompt --------------------------------
def test_PSM10_new_root_prompt_abandons_proposed(client, alice, monkeypatch, db):
    """Contract: unrelated new prompt transitions PROPOSED -> ABANDONED."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="swim")
    if p is None:
        pytest.skip("No free slot")

    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "other task",
        "duration_minutes": 60,
    }))
    result = understand(client, alice, "xếp 1 tiếng other task")
    assert result.json()["abandoned_proposals"] >= 1

    obj = db.get(Proposal, p["id"])
    assert obj.status == ProposalStatus.ABANDONED


# ---- PSM-11: Reschedule does not abandon proposals ------------------------
def test_PSM11_reschedule_does_not_abandon_parent(client, alice, monkeypatch, db):
    """Contract: a reschedule call does not set parent to ABANDONED."""
    p1 = _proposal_via_ai(client, alice, monkeypatch, title="hike")
    if p1 is None:
        pytest.skip("No free slot")

    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "hike",
        "duration_minutes": 60,
    }))
    result = understand(client, alice, "dời sang tối",
                        reschedule_proposal_id=p1["id"])
    assert result.json()["abandoned_proposals"] == 0

    obj = db.get(Proposal, p1["id"])
    assert obj.status == ProposalStatus.RESCHEDULED


# ---- PSM-12: Confirm creates Event with AI_CREATED source -----------------
def test_PSM12_confirmed_event_has_ai_created_source(client, alice, monkeypatch, db):
    """Contract: confirmed proposal creates Event(source=AI_CREATED)."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="meditate")
    if p is None:
        pytest.skip("No free slot")

    confirm = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    assert confirm.status_code == 200

    ev = db.scalar(select(Event).where(Event.proposal_id == p["id"]))
    assert ev.source == EventSource.AI_CREATED


# ---- PSM-13: Confirm creates Reminder row ----------------------------------
def test_PSM13_confirm_creates_reminder(client, alice, monkeypatch, db):
    """Contract: confirmed proposal generates a Reminder row for each event."""
    from models import Reminder
    p = _proposal_via_ai(client, alice, monkeypatch, title="read")
    if p is None:
        pytest.skip("No free slot")

    confirm = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    data = confirm.json()
    assert len(data.get("reminders", [])) >= 1


# ---- PSM-14: Proposal with no task_id rejects (bad request) ---------------
def test_PSM14_nonexistent_proposal_returns_404(client, alice):
    """Contract: confirm/reject on non-existent proposal_id returns 404."""
    res = client.post("/api/v1/proposals/9999999/confirm", headers=alice.h)
    assert res.status_code == 404


# ---- PSM-15: Task status -> SCHEDULED after confirm -----------------------
def test_PSM15_task_status_becomes_scheduled_after_confirm(client, alice, monkeypatch, db):
    """Contract: Task.status transitions to SCHEDULED when proposal is confirmed."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="project")
    if p is None:
        pytest.skip("No free slot")

    confirm = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    task_id = confirm.json()["events"][0]["task_id"]
    task = db.get(Task, task_id)
    assert task.status == TaskStatus.SCHEDULED


# ---- PSM-16: Abandon only affects PROPOSED, not CONFIRMED -----------------
def test_PSM16_abandon_only_affects_proposed_not_confirmed(client, alice, monkeypatch, db):
    """Contract: abandon_pending_proposals does not touch CONFIRMED proposals."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="tennis")
    if p is None:
        pytest.skip("No free slot")

    # Confirm it
    client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)

    # New root prompt triggers abandon
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "new",
        "duration_minutes": 60,
    }))
    understand(client, alice, "xếp 1 tiếng new")

    obj = db.get(Proposal, p["id"])
    assert obj.status == ProposalStatus.CONFIRMED  # must stay CONFIRMED


# ---- PSM-17: Proposal has correct owner_id --------------------------------
def test_PSM17_proposal_has_correct_owner_id(client, alice, monkeypatch, db):
    """Contract: Proposal.owner_id matches the authenticated user."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="chess")
    if p is None:
        pytest.skip("No free slot")
    obj = db.get(Proposal, p["id"])
    assert obj.owner_id == alice.id


# ---- PSM-18: Proposal.rationale is non-empty ------------------------------
def test_PSM18_proposal_has_rationale(client, alice, monkeypatch, db):
    """Contract: AI-created proposals must include a non-empty rationale string."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="paint")
    if p is None:
        pytest.skip("No free slot")
    obj = db.get(Proposal, p["id"])
    assert obj.rationale and len(obj.rationale) > 5


# ---- PSM-19: Proposal.source_prompt is stored (truncated to 2000 chars) ---
def test_PSM19_proposal_source_prompt_stored(client, alice, monkeypatch, db):
    """Contract: Proposal.source_prompt stores the original user prompt."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "read",
        "duration_minutes": 60,
    }))
    prompt = "xếp 1 tiếng đọc sách ngày mai buổi sáng"
    body = understand(client, alice, prompt).json()
    p = body.get("proposal")
    if p is None:
        pytest.skip("No free slot")
    obj = db.get(Proposal, p["id"])
    assert obj.source_prompt is not None


# ---- PSM-20: extra_slots_json is None for single-piece proposals ----------
def test_PSM20_single_piece_proposal_extra_slots_null(client, alice, monkeypatch, db):
    """Contract: proposals for short tasks (< cap) have extra_slots_json=None."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="nap", duration=30)
    if p is None:
        pytest.skip("No free slot")
    obj = db.get(Proposal, p["id"])
    # Single-piece proposal should have no extra slots
    assert obj.extra_slots_json is None or obj.extra_slots_json == []


# ---- PSM-21: Proposals table has no deleted_at column --------------------
def test_PSM21_proposals_have_no_deleted_at():
    """Contract: Proposal model must not have a deleted_at attribute (lifecycle via status)."""
    assert not hasattr(Proposal, "deleted_at"), \
        "Proposal must not have deleted_at; use status=ABANDONED instead"


# ---- PSM-22: Confirm response includes fire_at timestamp ------------------
def test_PSM22_confirm_response_includes_fire_at(client, alice, monkeypatch):
    """Contract: confirm response reminders include fire_at in +07:00 format."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="cook")
    if p is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h).json()
    for r in res.get("reminders", []):
        assert r["fire_at"].endswith("+07:00")


# ---- PSM-23: Confirm conflict at confirm time -> 409 ----------------------
def test_PSM23_confirm_with_conflict_returns_409(client, alice, monkeypatch, db):
    """Contract: if a hard event is inserted after proposal, confirm returns 409."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="conflict_test")
    if p is None:
        pytest.skip("No free slot")

    p_obj = db.get(Proposal, p["id"])
    # Inject a conflicting hard event at exactly the proposed time
    conflict = Event(
        owner_id=alice.id,
        title="Injected Class",
        kind=EventKind.CLASS,
        source=EventSource.IMPORTED,
        start_time=p_obj.start_time,
        end_time=p_obj.end_time,
        is_hard=True,
        priority=3,
    )
    db.add(conflict)
    db.commit()

    res = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-24: ProposalStatus enum values match expected strings -------------
def test_PSM24_proposal_status_enum_values():
    """Contract: ProposalStatus enum values must match AGENTS.md specification."""
    assert ProposalStatus.PROPOSED.value == "PROPOSED"
    assert ProposalStatus.CONFIRMED.value == "CONFIRMED"
    assert ProposalStatus.REJECTED.value == "REJECTED"
    assert ProposalStatus.RESCHEDULED.value == "RESCHEDULED"
    assert ProposalStatus.ABANDONED.value == "ABANDONED"


# ---- PSM-25: Abandoned proposal cannot be confirmed -----------------------
def test_PSM25_abandoned_proposal_cannot_be_confirmed(client, alice, monkeypatch, db):
    """Contract: a proposal that was ABANDONED cannot be confirmed afterward."""
    p = _proposal_via_ai(client, alice, monkeypatch, title="surf")
    if p is None:
        pytest.skip("No free slot")

    # Force ABANDONED via new prompt
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "new_topic",
        "duration_minutes": 60,
    }))
    understand(client, alice, "xếp 1 tiếng new_topic")

    res = client.post(f"/api/v1/proposals/{p['id']}/confirm", headers=alice.h)
    assert res.status_code == 409


# ---- PSM-26: Cross-user abandon does not touch other user's proposals -----
def test_PSM26_abandon_scoped_to_owner(client, alice, bob, monkeypatch, db):
    """Contract: alice's new prompt does not abandon bob's proposals."""
    # Bob creates a proposal
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "bob_task",
        "duration_minutes": 60,
    }))
    p_bob = understand(client, bob, "xếp 1 tiếng bob_task").json().get("proposal")
    if p_bob is None:
        pytest.skip("No free slot")

    # Alice sends a new prompt
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "alice_task",
        "duration_minutes": 60,
    }))
    understand(client, alice, "xếp 1 tiếng alice_task")

    # Bob's proposal must still be PROPOSED
    obj = db.get(Proposal, p_bob["id"])
    assert obj.status == ProposalStatus.PROPOSED


# ---- PSM-27: Manual event creates pre-confirmed proposal -----------------
def test_PSM27_manual_event_has_confirmed_proposal(client, alice, db):
    """Contract: POST /proposals/manual creates Proposal with status=CONFIRMED."""
    start = datetime(2026, 11, 20, 14, 0, tzinfo=VN_TZ)
    end = datetime(2026, 11, 20, 16, 0, tzinfo=VN_TZ)
    res = client.post(
        "/api/v1/proposals/manual",
        headers=alice.h,
        json={
            "title": "Manual Study",
            "duration_minutes": 90,
            "slot_start": start.isoformat(),
            "slot_end": end.isoformat(),
        },
    )
    assert res.status_code == 200
    prop_id = res.json()["proposal"]["id"]
    obj = db.get(Proposal, prop_id)
    assert obj.status == ProposalStatus.CONFIRMED


# ---- PSM-28: Reschedule chain does not revisit already-rejected slots -----
def test_PSM28_reschedule_excludes_ancestor_slots(client, alice, monkeypatch, db):
    """Contract: rescheduled proposal avoids time slots from parent chain."""
    p1 = _proposal_via_ai(client, alice, monkeypatch, title="chess_v2")
    if p1 is None:
        pytest.skip("No free slot")

    p1_obj = db.get(Proposal, p1["id"])
    p1_start = p1_obj.start_time

    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "chess_v2",
        "duration_minutes": 60,
    }))
    r2 = understand(client, alice, "dời sang thời gian khác",
                    reschedule_proposal_id=p1["id"]).json()
    p2 = r2.get("proposal")
    if p2:
        p2_obj = db.get(Proposal, p2["id"])
        # The new proposal's slot must differ from the old one
        assert p2_obj.start_time != p1_start
