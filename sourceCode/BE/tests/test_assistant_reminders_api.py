# owner: Database & AI (API tests for /assistant and /reminders; uses the shared mysql savepoint fixtures)
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from database import UTC_TZ, to_db_utc
from models import AiErrorLog, Event, EventKind, EventSource, Proposal, ProposalStatus, Task
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
