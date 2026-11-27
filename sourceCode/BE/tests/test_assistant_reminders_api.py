# owner: Database & AI (API tests for /assistant and /reminders; uses the shared mysql savepoint fixtures)
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from database import UTC_TZ, to_db_utc
from models import AiErrorLog, Event, EventKind, EventSource, Proposal, ProposalStatus, Reminder, Task
from routers import reminders as reminders_router
from services import ai_logging, nlu


@pytest.fixture(autouse=True)
def _no_llm_and_isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_logging, "LOG_PATH", tmp_path / "ai.jsonl")
    monkeypatch.setattr(reminders_router, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(nlu, "VLLM_ENDPOINT", "http://127.0.0.1:1/v1/chat/completions")  # refused instantly


def _register(client, name: str) -> dict:
    res = client.post("/api/v1/auth/register", json={"username": name, "password": "secret12", "display_name": name})
    assert res.status_code in (200, 201), res.text
    body = res.json()
    return {"id": body["user_id"], "h": {"Authorization": f"Bearer {body['access_token']}"}}


def _event(db: Session, owner_id: int, hours_ahead: int = 48) -> Event:
    start = datetime.now(UTC_TZ) + timedelta(hours=hours_ahead)
    ev = Event(owner_id=owner_id, title="Giải tích", kind=EventKind.CLASS, source=EventSource.MANUAL,
               start_time=to_db_utc(start), end_time=to_db_utc(start + timedelta(hours=2)), is_hard=True)
    db.add(ev)
    db.commit()
    return ev


def test_understand_requires_auth(client):
    assert client.post("/api/v1/assistant/understand", json={"prompt": "xếp 2 tiếng"}).status_code == 401


def test_understand_falls_back_logs_and_abandons(client, db_session):
    u = _register(client, "ai_user_1")
    task = Task(owner_id=u["id"], title="t", duration_minutes=60)
    db_session.add(task)
    db_session.flush()
    now = to_db_utc(datetime.now(UTC_TZ))
    p = Proposal(owner_id=u["id"], task_id=task.id, start_time=now, end_time=now, status=ProposalStatus.PROPOSED)
    db_session.add(p)
    db_session.commit()

    res = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "xep 3 tieng lam do an ngay mai"})
    assert res.status_code == 200
    body = res.json()
    assert body["nlu"]["fallback_mode"] is True and body["nlu"]["duration_minutes"] == 180
    assert body["abandoned_proposals"] == 1 and body["message"]
    db_session.refresh(p)
    assert p.status == ProposalStatus.ABANDONED
    assert db_session.query(AiErrorLog).filter_by(user_id=u["id"]).count() == 1


def test_reschedule_prompt_does_not_abandon(client, db_session):
    from datetime import datetime, timedelta

    from database import UTC_TZ, to_db_utc
    from models import Proposal, ProposalStatus, Task

    u = _register(client, "ai_user_2")
    task = Task(owner_id=u["id"], title="học bài", duration_minutes=60)
    db_session.add(task)
    db_session.flush()
    start = to_db_utc(datetime.now(UTC_TZ) + timedelta(days=1))
    waiting = Proposal(owner_id=u["id"], task_id=task.id, start_time=start, end_time=start + timedelta(hours=1),
                       status=ProposalStatus.PROPOSED)
    db_session.add(waiting)
    db_session.commit()
    res = client.post("/api/v1/assistant/understand", headers=u["h"],
                      json={"prompt": "dời sang tối", "reschedule_proposal_id": waiting.id})
    assert res.status_code == 200 and res.json()["abandoned_proposals"] == 0  # a reschedule is not a new topic


def test_reschedule_of_an_unknown_or_foreign_proposal_is_404(client):
    u = _register(client, "ai_user_3")
    res = client.post("/api/v1/assistant/understand", headers=u["h"],
                      json={"prompt": "dời sang tối", "reschedule_proposal_id": 999999})
    assert res.status_code == 404  # never leak or touch somebody else's proposal


def test_reminder_lifecycle_and_audit(client, db_session):
    u = _register(client, "rem_user_1")
    ev = _event(db_session, u["id"])
    put = client.put(f"/api/v1/reminders/{ev.id}", headers=u["h"], json={"offset_minutes": 45})
    assert put.status_code == 200 and put.json()["fire_at"].endswith("+07:00")
    assert client.put(f"/api/v1/reminders/{ev.id}", headers=u["h"], json={"offset_minutes": 15}).json()["offset_minutes"] == 15
    assert client.post(f"/api/v1/reminders/{ev.id}/scheduled", headers=u["h"], json={}).json()["scheduled_on_device_at"]
    assert client.post(f"/api/v1/reminders/{ev.id}/delivered", headers=u["h"], json={}).json()["delivered_at"]
    rows = client.get("/api/v1/reminders/audit", headers=u["h"]).json()
    assert len(rows) == 1 and rows[0]["delivered_at"] and rows[0]["scheduled_on_device_at"]
    lines = reminders_router.AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4  # created, updated, scheduled, delivered


def test_reminder_idor_blocked(client, db_session):
    a, b = _register(client, "rem_a"), _register(client, "rem_b")
    ev = _event(db_session, a["id"])
    assert client.put(f"/api/v1/reminders/{ev.id}", headers=b["h"], json={"offset_minutes": 5}).status_code == 404
    assert client.post(f"/api/v1/reminders/{ev.id}/delivered", headers=b["h"], json={}).status_code == 404
    assert client.get("/api/v1/reminders/audit", headers=b["h"]).json() == []


def test_events_create_patch_delete_and_audit(client, db_session):
    u = _register(client, "evt_user_1")
    other = _register(client, "evt_user_2")

    # unauthorized create is rejected
    unauth = client.post(
        "/api/v1/events",
        json={
            "title": "No Auth",
            "kind": "TASK",
            "start_time": "2026-10-20T08:00:00+07:00",
            "end_time": "2026-10-20T09:30:00+07:00",
        },
    )
    assert unauth.status_code == 401

    # create TASK with room and is_important=True -> auto creates Reminder
    res_task = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "  Ôn tập CTDL  ",
            "kind": "TASK",
            "start_time": "2026-10-20T08:00:00+07:00",
            "end_time": "2026-10-20T09:30:00+07:00",
            "room": "  B03  ",
            "is_important": True,
        },
    )
    assert res_task.status_code == 201, res_task.text
    task_body = res_task.json()
    assert task_body["title"] == "Ôn tập CTDL"
    assert task_body["room"] == "B03"
    assert task_body["kind"] == "TASK"
    assert task_body["is_hard"] is False
    assert task_body["is_important"] is True
    assert db_session.query(Reminder).filter_by(event_id=task_body["id"], owner_id=u["id"]).count() == 1

    # create CLASS -> is_hard=True even without weekday
    res_cls = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Toán rời rạc",
            "kind": "CLASS",
            "start_time": "2026-10-21T07:30:00+07:00",
            "end_time": "2026-10-21T09:30:00+07:00",
            "is_important": False,
        },
    )
    assert res_cls.status_code == 201, res_cls.text
    cls_body = res_cls.json()
    assert cls_body["is_hard"] is True

    # create DEADLINE with non-equal end_time -> normalized to zero duration
    res_dl = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Nộp đồ án",
            "kind": "DEADLINE",
            "start_time": "2026-10-22T23:30:00+07:00",
            "end_time": "2026-10-22T23:59:00+07:00",
            "is_important": True,
        },
    )
    assert res_dl.status_code == 201, res_dl.text
    dl_body = res_dl.json()
    assert dl_body["start_time"] == dl_body["end_time"]

    # non-deadline with end_time <= start_time is rejected
    bad_time = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Bad",
            "kind": "EVENT",
            "start_time": "2026-10-20T10:00:00+07:00",
            "end_time": "2026-10-20T10:00:00+07:00",
        },
    )
    assert bad_time.status_code == 422

    # patch soft event time & toggle is_important
    patch_ok = client.patch(
        f"/api/v1/events/{task_body['id']}",
        headers=u["h"],
        json={
            "start_time": "2026-10-20T14:00:00+07:00",
            "end_time": "2026-10-20T16:00:00+07:00",
            "is_important": False,
        },
    )
    assert patch_ok.status_code == 200, patch_ok.text
    assert patch_ok.json()["is_important"] is False
    assert db_session.query(Reminder).filter_by(event_id=task_body["id"]).count() == 0

    # toggle is_important back to True creates Reminder
    patch_imp = client.patch(
        f"/api/v1/events/{task_body['id']}",
        headers=u["h"],
        json={"is_important": True},
    )
    assert patch_imp.status_code == 200
    assert db_session.query(Reminder).filter_by(event_id=task_body["id"]).count() == 1

    # hard event blocks time edit
    patch_hard = client.patch(
        f"/api/v1/events/{cls_body['id']}",
        headers=u["h"],
        json={"start_time": "2026-10-21T08:00:00+07:00"},
    )
    assert patch_hard.status_code == 400

    # reminder-audit writes jsonl log and returns fire_at
    audit_res = client.post(
        f"/api/v1/events/{cls_body['id']}/reminder-audit",
        headers=u["h"],
        json={"offset_minutes": 30},
    )
    assert audit_res.status_code == 200, audit_res.text
    audit_body = audit_res.json()
    assert audit_body["fire_at"] == "2026-10-21T07:00:00+07:00"
    assert reminders_router.AUDIT_LOG_PATH.exists()
    assert any(json_line for json_line in reminders_router.AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines())

    # idor check and soft-delete
    assert client.patch(f"/api/v1/events/{task_body['id']}", headers=other["h"], json={"title": "Hacked"}).status_code == 404
    assert client.delete(f"/api/v1/events/{task_body['id']}", headers=other["h"]).status_code == 404

    del_res = client.delete(f"/api/v1/events/{task_body['id']}", headers=u["h"])
    assert del_res.status_code == 204
    assert client.patch(f"/api/v1/events/{task_body['id']}", headers=u["h"], json={"title": "Gone"}).status_code == 404


def test_user_preferences_get_and_post(client):
    u = _register(client, "pref_user_1")
    res_get = client.get("/api/v1/user/preferences", headers=u["h"])
    assert res_get.status_code == 200, res_get.text
    defaults = res_get.json()
    assert defaults["sleep_start"] == "23:30" and defaults["sleep_end"] == "06:30"

    res_post = client.post(
        "/api/v1/user/preferences",
        headers=u["h"],
        json={
            "sleep_schedule": "Ngủ: 22:30 - Dậy: 06:00",
            "min_break_minutes": "45",
            "max_continuous_minutes": "150",
        },
    )
    assert res_post.status_code == 200, res_post.text
    updated = res_post.json()
    assert updated["sleep_start"] == "22:30"
    assert updated["sleep_end"] == "06:00"
    assert updated["min_break_minutes"] == 45
    assert updated["max_block_minutes"] == 150

    res_get_2 = client.get("/api/v1/user/preferences", headers=u["h"])
    assert res_get_2.status_code == 200
    assert res_get_2.json()["sleep_start"] == "22:30"
    assert res_get_2.json()["sleep_end"] == "06:00"


def test_x_process_time_ms_header(client):
    ok_res = client.get("/health")
    assert ok_res.status_code == 200
    assert float(ok_res.headers["X-Process-Time-Ms"]) >= 0.0

    not_found = client.get("/api/v1/nonexistent-endpoint")
    assert not_found.status_code == 404
    assert float(not_found.headers["X-Process-Time-Ms"]) >= 0.0

    invalid = client.post("/api/v1/auth/register", json={"username": "ab"})
    assert invalid.status_code == 422
    assert float(invalid.headers["X-Process-Time-Ms"]) >= 0.0


def test_reschedule_inherits_parent_duration_without_clarification(client, db_session, monkeypatch):
    import json

    class _FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps(self._payload)}}]}

    monkeypatch.setattr(
        nlu.httpx.Client,
        "post",
        lambda self, *args, **kwargs: _FakeResp(
            {"intent": "schedule_task", "title": "run", "duration_minutes": 60, "date_hint": "ngày mai"}
        ),
    )

    u = _register(client, "ai_user_resched")
    task = Task(owner_id=u["id"], title="run", duration_minutes=60)
    db_session.add(task)
    db_session.flush()
    start = to_db_utc(datetime.now(UTC_TZ) + timedelta(days=1))
    parent = Proposal(
        owner_id=u["id"],
        task_id=task.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=ProposalStatus.PROPOSED,
    )
    db_session.add(parent)
    db_session.commit()

    res = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "dời sang ngày mai", "reschedule_proposal_id": parent.id},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["nlu"]["needs_clarification"] is False
    assert body["nlu"]["duration_minutes"] == 60
    assert body["proposal"] is not None
    assert body["proposal"]["parent_id"] == parent.id
    db_session.refresh(parent)
    assert parent.status == ProposalStatus.RESCHEDULED


def test_clarification_duration_reply_keeps_task_and_no_busy_fallback(client, monkeypatch):
    import json

    class _FakeResp:
        status_code = 200
        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": json.dumps(self._payload)}}]}

    def fake_post(self, *args, **kwargs):
        msgs = (kwargs.get("json") or {}).get("messages") or []
        sent = msgs[-1]["content"] if msgs else ""
        if "2 tiếng" in sent or "5 tiếng" in sent:
            return _FakeResp({"intent": "schedule_task", "title": "học bài", "duration_minutes": 120})
        return _FakeResp({"intent": "schedule_task", "title": "học bài", "duration_minutes": None})

    monkeypatch.setattr(nlu.httpx.Client, "post", fake_post)
    u = _register(client, "ai_user_clarif_dur")

    turn1 = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "xếp lịch học bài"},
    )
    assert turn1.status_code == 200, turn1.text
    b1 = turn1.json()
    assert b1["nlu"]["needs_clarification"] is True and b1["nlu"]["fallback_mode"] is False

    turn2 = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "khoảng 2 tiếng"},
    )
    assert turn2.status_code == 200, turn2.text
    b2 = turn2.json()
    assert b2["nlu"]["fallback_mode"] is False
    assert b2["nlu"]["needs_clarification"] is False
    assert b2["nlu"]["duration_minutes"] == 120
    assert b2["proposal"] is not None
    assert "học bài" in b2["proposal"]["task_title"]


def test_split_task_and_batch_respect_min_break_between_max_blocks(client, db_session):
    from sqlalchemy import select
    from database import VN_TZ, from_db_to_vn
    from models import TimeSlot, UserPreference
    from services.nlu import NluResult
    from services.proposals import create_proposal, schedule_pending_tasks, split_task

    base = datetime(2026, 11, 20, 8, 0, tzinfo=VN_TZ)
    exact_6h = [TimeSlot(base, base + timedelta(minutes=360))]
    # 360 min task with cap=180 and min_break=30 cannot fit inside an exact 360 min gap
    assert split_task(exact_6h, 360, 180, min_break=30) is None

    gap_6h30 = [TimeSlot(base, base + timedelta(minutes=390))]
    pieces = split_task(gap_6h30, 360, 180, min_break=30)
    assert pieces is not None and len(pieces) == 2
    assert pieces[0].duration_minutes() == 180 and pieces[1].duration_minutes() == 180
    assert pieces[1].start - pieces[0].end == timedelta(minutes=30)

    # create_proposal splits 6h task with 30m break between 3h max blocks
    u = _register(client, "break_batch_u")
    pref = db_session.scalar(select(UserPreference).where(UserPreference.user_id == u["id"]))
    pref.min_break_minutes = 30
    pref.max_block_minutes = 180
    db_session.flush()

    nlu_6h = NluResult(
        intent="schedule_task", title="deep work", duration_minutes=360,
        window_start=base.date(), window_end=base.date(),
    )
    prop = create_proposal(db_session, u["id"], nlu_6h, "6h deep work", base - timedelta(hours=1))
    assert prop is not None and prop.extra_slots_json and len(prop.extra_slots_json) == 1
    first_end = from_db_to_vn(prop.end_time)
    second_start = datetime.fromisoformat(prop.extra_slots_json[0]["start_time"])
    assert second_start - first_end >= timedelta(minutes=30)

    # Batch queue also inserts min_break between consecutive scheduled tasks
    db_session.add(Task(owner_id=u["id"], title="t1", duration_minutes=60, priority=1))
    db_session.add(Task(owner_id=u["id"], title="t2", duration_minutes=60, priority=2))
    db_session.commit()

    batch = schedule_pending_tasks(db_session, u["id"], base - timedelta(hours=1), base.date(), base.date())
    assert len(batch.proposals) == 2
    s1_end = from_db_to_vn(batch.proposals[0].end_time)
    s2_start = from_db_to_vn(batch.proposals[1].start_time)
    assert s2_start - s1_end >= timedelta(minutes=30)


def test_fallback_available_slots_match_requested_duration(client):
    u = _register(client, "fallback_dur_u")
    res = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "xếp 3 tiếng làm đồ án ngày mai"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["nlu"]["fallback_mode"] is True
    assert body["nlu"]["duration_minutes"] == 180
    slots = body["available_slots"]
    assert len(slots) >= 1
    for slot in slots:
        assert slot["duration_minutes"] == 180
        delta = datetime.fromisoformat(slot["end_time"]) - datetime.fromisoformat(slot["start_time"])
        assert delta == timedelta(minutes=180)


def test_fe_fallback_slot_slicing_and_clip_duration():
    import sys
    from pathlib import Path

    fe_dir = Path(__file__).resolve().parents[2] / "FE"
    if str(fe_dir) not in sys.path:
        sys.path.insert(0, str(fe_dir))
    import fallback  # noqa: E402

    raw_gaps = [{"start_time": "2026-11-20T06:30:00+07:00", "end_time": "2026-11-20T14:30:00+07:00", "duration_minutes": 480}]
    sliced = fallback.slice_slots_to_duration(raw_gaps, 180)
    assert len(sliced) == 2
    assert sliced[0]["start_time"].endswith("06:30:00+07:00") and sliced[0]["end_time"].endswith("09:30:00+07:00")
    assert sliced[1]["start_time"].endswith("09:30:00+07:00") and sliced[1]["end_time"].endswith("12:30:00+07:00")

    cs, ce = fallback.clip_slot_to_window(
        "2026-11-20T11:45:00+07:00", "2026-11-20T23:30:00+07:00", None, duration_minutes=180
    )
    assert cs.endswith("11:45:00+07:00") and ce.endswith("14:45:00+07:00")
