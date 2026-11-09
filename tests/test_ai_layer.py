"""AI-01..AI-16: NLU pipeline through the HTTP API (P1-7, P2-1/2/3/6), fallback (P1-9 server side), privacy (P1-2), reminders (P2-13)."""
import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from conftest import class_row
from database import UTC_TZ, to_db_utc
from models import AiErrorLog, Event, EventKind, EventSource, Proposal, ProposalStatus, Task
from services import nlu, privacy

REAL_CLIENT = httpx.Client


def llm(monkeypatch, handler):
    """route nlu's outbound call to a fake vLLM; returns the list of captured request bodies."""
    seen = []

    def wrapped(request):
        seen.append(json.loads(request.content))
        return handler(request)

    monkeypatch.setattr(nlu.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(wrapped)))
    return seen


def reply(obj):
    return httpx.Response(200, json={"choices": [{"message": {"content": obj if isinstance(obj, str) else json.dumps(obj)}}]})


def understand(client, acc, prompt, **extra):
    return client.post("/api/v1/assistant/understand", headers=acc.h, json={"prompt": prompt, **extra})


# ---------------- P1-7 / P2-1: extraction through the API -------------------------------------
def test_AI01_happy_path_extracts_intent_duration_and_window(client, alice, monkeypatch):
    llm(monkeypatch, lambda r: reply({"intent": "schedule_task", "title": "làm đồ án CTDL", "duration_minutes": 180,
                                      "avoid_time_of_day": "evening", "date_hint": "tuần này"}))
    body = understand(client, alice, "Xếp cho mình 3 tiếng làm đồ án CTDL tuần này, không làm buổi tối nhé").json()
    n = body["nlu"]
    assert n["intent"] == "schedule_task" and n["duration_minutes"] == 180 and n["source"] == "llm"
    assert n["avoid_time_of_day"] == "evening" and n["window_start"] and n["fallback_mode"] is False
    assert "đang bận" not in (body["message"] or "")  # no AI-busy notice; a proposal message depends on free slots today


def test_AI02_model_hallucinated_duration_is_overridden_by_the_users_words(client, alice, monkeypatch):
    llm(monkeypatch, lambda r: reply({"intent": "schedule_task", "title": "học", "duration_minutes": 30}))
    assert understand(client, alice, "xếp 2 tiếng học bài").json()["nlu"]["duration_minutes"] == 120


def test_AI03_invented_date_not_in_prompt_is_discarded(client, alice, monkeypatch):
    llm(monkeypatch, lambda r: reply({"intent": "schedule_task", "title": "học", "duration_minutes": 60, "date_hint": "ngày 5 tháng 12"}))
    n = understand(client, alice, "xếp 1 tiếng học").json()["nlu"]
    assert n["date_hint"] is None and n["date_assumed"] is True  # default 7-day window, flagged as an assumption


def test_AI04_malformed_json_is_retried_once_then_falls_back(client, alice, monkeypatch, db):
    seen = llm(monkeypatch, lambda r: reply("Sure! here you go: not json"))
    body = understand(client, alice, "xep 2 tieng hoc bai").json()
    assert len(seen) == 2  # one retry
    assert body["nlu"]["fallback_mode"] is True and body["nlu"]["duration_minutes"] == 120 and body["message"]
    assert db.scalar(select(AiErrorLog).where(AiErrorLog.user_id == alice.id)).retry_count == 1


def test_AI05_llm_down_returns_200_fallback_never_500(client, alice):
    res = understand(client, alice, "xếp 3 tiếng làm đồ án ngày mai")  # conftest points the LLM at a closed port
    assert res.status_code == 200
    n = res.json()["nlu"]
    assert n["fallback_mode"] is True and n["duration_minutes"] == 180 and n["window_start"]
    assert n["fallback_reason"].startswith("INFRA_CRASH")  # cause is returned so the host can diagnose it


def test_AI06_every_failure_is_logged_in_db_and_in_taxonomy_file(client, alice, db, tmp_path):
    understand(client, alice, "xếp 3 tiếng làm đồ án")
    row = db.scalar(select(AiErrorLog).where(AiErrorLog.user_id == alice.id))
    assert row.error_type.value == "INFRA_CRASH" and row.triggered_fallback is True and "xếp" in row.prompt_text
    line = json.loads((tmp_path / "ai_errors.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["category"] == "INFRA_CRASH" and line["prompt"] and line["reason"]


# ---------------- P2-3 / P2-6: ambiguity and dirty input -----------------------------------------
@pytest.mark.parametrize("prompt", [
    "xep 2 tieng hoc bai ngay mai ko buoi toi",         # no diacritics + teencode
    "xếp 2 tiếng học bài 😀😀 ngày mai",                  # emoji
    "xếp 2 tiếng học bài vcl ngày mai",                  # profanity
    "xếp   2   tiếng\t học bài\x00 ngày mai <script>",  # control chars / markup
])
def test_AI07_dirty_input_still_yields_clean_extraction(client, alice, prompt):
    n = understand(client, alice, prompt).json()["nlu"]
    assert n["duration_minutes"] == 120 and n["intent"] == "schedule_task" and n["date_hint"] == "ngày mai"


def test_AI08_profanity_is_flagged_for_the_ui(client, alice):
    assert understand(client, alice, "xếp 2 tiếng học bài vcl").json()["nlu"]["profanity_found"] is True


def test_AI09_missing_duration_triggers_clarifying_question(client, alice):
    n = understand(client, alice, "xếp lịch học bài ngày mai").json()["nlu"]
    assert n["needs_clarification"] is True and "bao lâu" in n["clarification_question"]


def test_AI10_vague_date_asks_instead_of_guessing(client, alice):
    n = understand(client, alice, "xếp 2 tiếng học bài sớm").json()["nlu"]
    assert n["needs_clarification"] is True and n["date_assumed"] is True


def test_AI11_prompt_is_sanitized_before_leaving_the_server(client, alice, monkeypatch):
    seen = llm(monkeypatch, lambda r: reply({"intent": "schedule_task", "title": "x", "duration_minutes": 60}))
    understand(client, alice, "xếp 1 tiếng họp, gọi 0901234567 hoặc mail me@school.edu hay http://evil.io/x")
    sent = seen[0]["messages"][-1]["content"]
    assert "0901234567" not in sent and "me@school.edu" not in sent and "evil.io" not in sent  # P1-2 PII redaction


# ---------------- P2-7: abandonment ---------------------------------------------------------------
def test_AI12_new_root_prompt_abandons_pending_proposals_but_reschedule_does_not(client, alice, db):
    task = Task(owner_id=alice.id, title="t", duration_minutes=60)
    db.add(task)
    db.flush()
    now = to_db_utc(datetime.now(UTC_TZ))
    p = Proposal(owner_id=alice.id, task_id=task.id, start_time=now, end_time=now, status=ProposalStatus.PROPOSED)
    db.add(p)
    db.commit()
    assert understand(client, alice, "dời sang tối", reschedule_proposal_id=p.id).json()["abandoned_proposals"] == 0
    db.refresh(p)
    assert p.status == ProposalStatus.PROPOSED
    assert understand(client, alice, "xếp 1 tiếng đọc sách").json()["abandoned_proposals"] == 1
    db.refresh(p)
    assert p.status == ProposalStatus.ABANDONED


def test_AI13_abandonment_never_touches_another_users_proposals(client, alice, bob, db):
    task = Task(owner_id=bob.id, title="t", duration_minutes=60)
    db.add(task)
    db.flush()
    now = to_db_utc(datetime.now(UTC_TZ))
    p = Proposal(owner_id=bob.id, task_id=task.id, start_time=now, end_time=now, status=ProposalStatus.PROPOSED)
    db.add(p)
    db.commit()
    understand(client, alice, "xếp 1 tiếng đọc sách")
    db.refresh(p)
    assert p.status == ProposalStatus.PROPOSED


# ---------------- P1-2 privacy helpers ----------------------------------------------------------
@pytest.mark.parametrize("url,private", [
    ("http://127.0.0.1:8000/v1", True), ("http://llama_engine:8000/v1", True), ("http://192.168.100.112:8000", True),
    ("https://api.openai.com/v1", False), ("http://8.8.8.8:8000", False), ("http://evil.example.com", False),
])
def test_AI14_llm_calls_are_only_allowed_to_private_hosts(url, private):
    assert privacy.is_private_endpoint(url) is private


def test_AI15_public_llm_endpoint_is_refused_and_falls_back(client, alice, monkeypatch):
    monkeypatch.setattr(nlu, "VLLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    seen = llm(monkeypatch, lambda r: reply({"intent": "schedule_task"}))
    n = understand(client, alice, "xếp 2 tiếng học").json()["nlu"]
    assert seen == [] and n["fallback_mode"] is True  # schedule data never left the machine


def test_AI16_rag_index_is_per_user_and_encrypted_on_disk(client, alice, bob, tmp_path):
    csv = ("course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
           "SECRET1,Môn bí mật,MON,07:30,09:30,B1,2026-09-07,2026-12-14,CLASS\n")
    res = client.post("/api/v1/assistant/index-file", headers=alice.h, files={"file": ("tt.csv", csv.encode("utf-8"), "text/csv")})
    assert res.status_code == 200 and res.json()["chunks_indexed"] >= 1
    files = list((tmp_path / "rag").glob("*.idx"))
    assert len(files) == 1 and b"SECRET1" not in files[0].read_bytes()
    empty = client.post("/api/v1/assistant/index-file", headers=bob.h, files={"file": ("e.txt", b"  \n ", "text/plain")})
    assert empty.status_code == 422


# ---------------- P2-13 reminders ----------------------------------------------------------------
def _event_id(client, acc):
    res = client.post("/api/v1/ingestion/commit", headers=acc.h,
                      json={"import_batch_id": "r", "resolved_rows": [class_row(last="2026-09-07")]})
    return res.json()["events"][0]["id"]


def test_AI17_reminder_lifecycle_is_audited(client, alice, tmp_path):
    eid = _event_id(client, alice)
    put = client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 30}).json()
    assert put["fire_at"].startswith("2026-09-07T07:00:00") and put["fire_at"].endswith("+07:00")  # 07:30 - 30 min
    assert client.post(f"/api/v1/reminders/{eid}/scheduled", headers=alice.h, json={}).json()["scheduled_on_device_at"]
    assert client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={}).json()["delivered_at"]
    trail = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    assert len(trail) == 1 and trail[0]["delivered_at"]
    actions = [json.loads(x)["action"] for x in (tmp_path / "reminder_audit.jsonl").read_text().splitlines()]
    assert actions == ["created", "scheduled", "delivered"]


def test_AI18_reminders_are_owner_isolated(client, alice, bob):
    eid = _event_id(client, alice)
    assert client.put(f"/api/v1/reminders/{eid}", headers=bob.h, json={"offset_minutes": 5}).status_code == 404
    assert client.post(f"/api/v1/reminders/{eid}/delivered", headers=bob.h, json={}).status_code == 404
    assert client.get("/api/v1/reminders/audit", headers=bob.h).json() == []


def test_AI19_reminder_offset_limits_and_missing_event(client, alice):
    eid = _event_id(client, alice)
    assert client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": -1}).status_code == 422
    assert client.put("/api/v1/reminders/999999", headers=alice.h, json={"offset_minutes": 5}).status_code == 404
    assert client.post(f"/api/v1/reminders/{eid}/delivered", headers=alice.h, json={}).status_code == 404  # no reminder yet


def test_AI20_deleted_event_disappears_from_reminder_audit(client, alice, db):
    eid = _event_id(client, alice)
    client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    db.get(Event, eid).deleted_at = datetime(2026, 9, 1)
    db.commit()
    assert client.get("/api/v1/reminders/audit", headers=alice.h).json() == []


def test_AI21_other_vague_phrases_also_trigger_a_question(client, alice):
    for sentence in ("xếp 2 tiếng học bài dạo này", "xếp 90 phút đọc sách sắp tới"):
        n = understand(client, alice, sentence).json()["nlu"]
        assert n["needs_clarification"] is True and "ngày nào" in n["clarification_question"], sentence
