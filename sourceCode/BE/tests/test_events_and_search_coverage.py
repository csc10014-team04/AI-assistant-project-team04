import json
import time as py_time
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from database import VN_TZ
from models import CsvRowKind, EventDomain, EventKind, EventSource, ParsedCsvRow, Proposal, ProposalStatus, Weekday
from routers import assistant as assistant_router
from services import nlu, parser, privacy, rag, search_engine, security, validator


REAL_HTTPX_CLIENT = httpx.Client


def _register(client, prefix: str = "cov") -> dict:
    """register a fresh test user and return id and auth headers."""
    uname = f"{prefix}_{uuid.uuid4().hex[:8]}"
    res = client.post(
        "/api/v1/auth/register",
        json={"username": uname, "password": "Password123", "display_name": "Coverage User"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    return {"id": body["user_id"], "h": {"Authorization": f"Bearer {body['access_token']}"}}


def _mock_llm(monkeypatch, answer_text: str) -> None:
    """route outbound httpx calls in search_engine to an in-memory mock response."""
    def _factory(*args, **kwargs):
        return REAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"choices": [{"message": {"content": answer_text}}]})
            )
        )

    monkeypatch.setattr(search_engine.httpx, "Client", _factory)


# ---------------------------------------------------------------------------
# events router lifecycle & preferences edge cases
# ---------------------------------------------------------------------------


def test_events_edge_cases_and_preferences_bounds(client):
    u = _register(client, "evt_cov")

    # whitespace-only title -> 422
    bad_title = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "   ",
            "kind": "TASK",
            "start_time": "2026-10-20T08:00:00+07:00",
            "end_time": "2026-10-20T09:00:00+07:00",
        },
    )
    assert bad_title.status_code == 422

    # naive timestamps default to +07:00; exam sets is_hard=True
    res_exam = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Thi giua ky",
            "kind": "EXAM",
            "start_time": "2026-10-25T07:30:00",
            "end_time": "2026-10-25T09:30:00",
        },
    )
    assert res_exam.status_code == 201, res_exam.text
    exam = res_exam.json()
    assert exam["is_hard"] is True
    assert exam["start_time"].endswith("+07:00")

    # soft event patch: title, room, invalid date -> 422, end <= start -> 400
    res_task = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Doc sach",
            "kind": "EVENT",
            "start_time": "2026-10-26T14:00:00+07:00",
            "end_time": "2026-10-26T15:00:00+07:00",
        },
    )
    assert res_task.status_code == 201
    ev_id = res_task.json()["id"]

    assert client.patch(
        f"/api/v1/events/{ev_id}",
        headers=u["h"],
        json={"title": "Doc sach chieu", "room": "Thu vien"},
    ).json()["room"] == "Thu vien"

    assert client.patch(
        f"/api/v1/events/{ev_id}",
        headers=u["h"],
        json={"start_time": "invalid-dt"},
    ).status_code == 422

    # deadline patch preserves zero duration whether only start or only end is supplied
    dl = client.post(
        "/api/v1/events",
        headers=u["h"],
        json={
            "title": "Nop bao cao",
            "kind": "DEADLINE",
            "start_time": "2026-10-28T23:00:00+07:00",
            "end_time": "2026-10-28T23:00:00+07:00",
        },
    ).json()
    p1 = client.patch(
        f"/api/v1/events/{dl['id']}",
        headers=u["h"],
        json={"start_time": "2026-10-29T20:00:00+07:00"},
    ).json()
    assert p1["start_time"] == p1["end_time"]

    p2 = client.patch(
        f"/api/v1/events/{dl['id']}",
        headers=u["h"],
        json={"end_time": "2026-10-29T22:00:00+07:00"},
    ).json()
    assert p2["start_time"] == p2["end_time"] == "2026-10-29T22:00:00+07:00"

    # reminder-audit creates then updates existing reminder record
    r1 = client.post(f"/api/v1/events/{ev_id}/reminder-audit", headers=u["h"], json={"offset_minutes": 15})
    r2 = client.post(f"/api/v1/events/{ev_id}/reminder-audit", headers=u["h"], json={"offset_minutes": 45})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["offset_minutes"] == 45

    # preferences clamping & explicit sleep_start/sleep_end fields
    pref_res = client.post(
        "/api/v1/user/preferences",
        headers=u["h"],
        json={
            "sleep_start": "23:45",
            "sleep_end": "07:15",
            "min_break_minutes": -10,
            "max_block_minutes": 999,
        },
    )
    assert pref_res.status_code == 200
    pref_body = pref_res.json()
    assert pref_body["sleep_start"] == "23:45"
    assert pref_body["sleep_end"] == "07:15"
    assert pref_body["min_break_minutes"] == 0
    assert pref_body["max_block_minutes"] == 720

    # run end<=start rejection last so dirty orm time mutation in shared test session stays isolated
    assert client.patch(
        f"/api/v1/events/{ev_id}",
        headers=u["h"],
        json={"start_time": "2026-10-26T16:00:00+07:00"},
    ).status_code == 400


# ---------------------------------------------------------------------------
# search endpoints & search_engine coverage + b-16 & b-17 regressions
# ---------------------------------------------------------------------------


def test_search_events_filters_semantic_and_b16_redirect(client):
    u = _register(client, "search_cov")

    # check query parser features
    now_ref = datetime(2026, 10, 19, 8, 0, tzinfo=VN_TZ)
    q_meta = search_engine.optimize_search_query("lịch thi xstk chiều mai phòng B1.02", now_ref)
    assert q_meta["kind"] == EventKind.EXAM
    assert q_meta["time_of_day"] == "afternoon"
    assert q_meta["room_hint"] == "B1.02"
    assert "xác suất thống kê" in q_meta["normalized_query"]

    # seed sample events across categories
    for payload in [
        {
            "title": "Xác suất thống kê",
            "kind": "CLASS",
            "start_time": "2026-10-20T07:30:00+07:00",
            "end_time": "2026-10-20T09:30:00+07:00",
            "room": "B1.02",
        },
        {
            "title": "Thi cuối kỳ CTDL",
            "kind": "EXAM",
            "start_time": "2026-10-21T13:30:00+07:00",
            "end_time": "2026-10-21T15:30:00+07:00",
            "room": "E202",
        },
        {
            "title": "Sinh hoạt câu lạc bộ",
            "kind": "EVENT",
            "start_time": "2026-10-22T18:00:00+07:00",
            "end_time": "2026-10-22T20:00:00+07:00",
            "room": "Hoi truong",
        },
    ]:
        assert client.post("/api/v1/events", headers=u["h"], json=payload).status_code == 201

    # empty query returns seeded events via sql path
    all_res = client.get("/api/v1/search/events", headers=u["h"], params={"q": ""})
    assert all_res.status_code == 200 and all_res.json()["total"] == 3

    # invalid time range rejected
    bad_range = client.get(
        "/api/v1/search/events",
        headers=u["h"],
        params={"q": "xstk", "start_from": "2026-10-22T10:00:00+07:00", "end_until": "2026-10-20T10:00:00+07:00"},
    )
    assert bad_range.status_code == 422

    # abbreviation & semantic concept matching + room/kind filter
    math_res = client.get("/api/v1/search/events", headers=u["h"], params={"q": "toan", "room": "B1"})
    assert math_res.status_code == 200
    assert any("Xác suất thống kê" in ev["title"] for ev in math_res.json()["events"])

    exam_res = client.get("/api/v1/search/events", headers=u["h"], params={"q": "ctdl", "kind": "EXAM"})
    assert exam_res.status_code == 200 and exam_res.json()["total"] == 1

    # b-16: scheduling commands in search tab must redirect to chat_home
    for cmd in ("xếp 2 tiếng học bài", "lên lịch học bài ngày mai", "schedule 2 hours study"):
        redir = client.get("/api/v1/search/events", headers=u["h"], params={"q": cmd})
        assert redir.status_code == 200
        body = redir.json()
        assert body["redirect_target"] == "chat_home"
        assert body["redirect_button_label"] == "AI Assistant"

    # genuine schedule queries must not redirect
    for qry in ("what is my schedule today", "lịch thi xstk"):
        normal = client.get("/api/v1/search/events", headers=u["h"], params={"q": qry})
        assert normal.status_code == 200 and normal.json()["redirect_target"] is None

    # /search/free-slots valid and invalid window
    ok_free = client.post(
        "/api/v1/search/free-slots",
        headers=u["h"],
        json={
            "window_start": "2026-10-23T06:30:00+07:00",
            "window_end": "2026-10-23T12:00:00+07:00",
            "duration_minutes": 60,
        },
    )
    assert ok_free.status_code == 200 and ok_free.json()["total"] >= 1

    bad_free = client.post(
        "/api/v1/search/free-slots",
        headers=u["h"],
        json={
            "window_start": "2026-10-23T12:00:00+07:00",
            "window_end": "2026-10-23T10:00:00+07:00",
            "duration_minutes": 60,
        },
    )
    assert bad_free.status_code == 422


def test_academic_rag_b17_refusal_clears_citations_and_upload_validation(client, monkeypatch, tmp_path):
    u = _register(client, "rag_cov")
    monkeypatch.setattr(rag, "RAG_DIR", tmp_path)

    # unsupported upload extension -> 422
    bad_ext = client.post(
        "/api/v1/search/academic/documents",
        headers=u["h"],
        files={"file": ("sheet.xlsx", b"dummy", "application/octet-stream")},
    )
    assert bad_ext.status_code == 422

    # seed academic doc so retrieval returns hits
    handbook = "Quy chế đào tạo đại học KHTN: sinh viên cần tích lũy đủ 138 tín chỉ để tốt nghiệp.\n".encode("utf-8")
    up_ok = client.post(
        "/api/v1/search/academic/documents",
        headers=u["h"],
        files={"file": ("quy_che.txt", handbook, "text/plain")},
    )
    assert up_ok.status_code == 200

    # empty whitespace query -> english validation prompt
    empty_q = search_engine.ask_academic_knowledge_base("   ", directory=tmp_path)
    assert empty_q["answer"] == "Please enter an academic question."

    # b-17: when llm states the context does not mention the topic, drop unrelated citations
    _mock_llm(monkeypatch, "Tài liệu không đề cập đến mức lương lập trình viên tại Mỹ.")
    refusal = client.post(
        "/api/v1/search/academic/ask",
        headers=u["h"],
        json={"query": "Quy định đào tạo về lương lập trình viên tại Mỹ là bao nhiêu?"},
    )
    assert refusal.status_code == 200
    body = refusal.json()
    assert body["fallback_mode"] is False
    assert body["citations"] == []


# ---------------------------------------------------------------------------
# regression tests for fixed qa bugs (b-02..b-15)
# ---------------------------------------------------------------------------


def test_b02_b03_b04_parser_timezone_and_bom_regressions():
    header = "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
    # b-02 + b-04: timezone suffixes on start/end must be isolated without crashing
    for s_t, e_t in (("08:00Z", "10:00"), ("08:00", "10:00Z"), ("08:00+07:00", "10:00"), ("08:00Z", "10:00Z")):
        content = f"{header}CSC101,Intro,MON,{s_t},{e_t},A1,2026-09-07,2026-12-14,CLASS\n"
        res = parser.parse_timetable_content(content, "tz.csv")
        assert len(res.valid_rows) == 0
        assert len(res.invalid_rows) == 1
        assert res.invalid_rows[0].error_code in {"INVALID_START_TIME", "INVALID_END_TIME"}

    # b-03: utf-8 bom header parses cleanly
    bom_bytes = ("\ufeff" + header + "CSC101,Intro,MON,08:00,10:00,A1,2026-09-07,2026-12-14,CLASS\n").encode("utf-8")
    res_bom = parser.parse_timetable_file(bom_bytes, "excel_bom.csv")
    assert len(res_bom.valid_rows) == 1
    assert res_bom.invalid_rows == []


def test_b05_b06_nlu_delete_variants_and_english_queries():
    assert nlu.rule_based_understand("xoá buổi gym hôm nay").intent == "delete_event"
    assert nlu.rule_based_understand("huỷ lịch học nhóm").intent == "delete_event"
    assert nlu.rule_based_understand("what is on my schedule today").intent == "query_schedule"
    assert nlu.rule_based_understand("show my schedule for tomorrow").intent == "query_schedule"
    assert nlu.rule_based_understand("schedule 2 hours study tomorrow").intent == "schedule_task"


def test_b07_validator_sweep_line_equivalence_and_speed():
    # build 120 rows across monday/tuesday to exercise sweep-line speed and overnight existing check
    incoming = [
        ParsedCsvRow(
            line_number=i + 2,
            title=f"Course {i}",
            kind=CsvRowKind.CLASS,
            start_time=time(7 + (i % 10), 0),
            end_time=time(8 + (i % 10), 0),
            first_date=date(2026, 9, 7),
            last_date=date(2026, 12, 14),
            course_code=f"CS{i:03d}",
            weekday=Weekday.MON if i % 2 == 0 else Weekday.TUE,
            room=f"B{i}",
        )
        for i in range(120)
    ]
    # include an overnight existing event touching monday morning
    existing = [
        EventDomain(
            id=1,
            owner_id=1,
            title="Overnight Maintenance",
            start_time=datetime(2026, 9, 6, 22, 0, tzinfo=VN_TZ),
            end_time=datetime(2026, 9, 7, 7, 30, tzinfo=VN_TZ),
            kind=EventKind.EVENT,
            source=EventSource.MANUAL,
            is_hard=False,
        )
    ]
    t0 = py_time.perf_counter()
    res = validator.detect_import_conflicts(incoming, existing)
    elapsed = py_time.perf_counter() - t0
    assert elapsed < 0.5
    assert len(res["conflict_cards"]) > 0
    assert any(c["option_b"] == existing[0] for c in res["conflict_cards"])


def test_b08_b09_b12_b15_security_rag_and_deadlock_fixes(monkeypatch, tmp_path):
    # b-08: production mode refuses default secrets
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        security.validate_security_config()
    with pytest.raises(RuntimeError):
        privacy.encrypt_text("secret")

    # pbkdf2 encryption rejects sha256 legacy tokens unless migration flag is enabled
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "unit-test-strong-encryption-secret-32")
    tok = privacy.encrypt_text("sensitive data")
    assert privacy.decrypt_text(tok) == "sensitive data"
    legacy_fernet = Fernet(
        privacy.base64.urlsafe_b64encode(
            privacy.hashlib.sha256(b"unit-test-strong-encryption-secret-32").digest()
        )
    )
    legacy_tok = legacy_fernet.encrypt(b"old data").decode("ascii")
    assert privacy.decrypt_text(legacy_tok) is None
    monkeypatch.setenv("ALLOW_LEGACY_SHA256_DECRYPT", "1")
    assert privacy.decrypt_text(legacy_tok) == "old data"
    monkeypatch.delenv("ALLOW_LEGACY_SHA256_DECRYPT", raising=False)

    # b-09: wrong key refuses silent overwrite in VectorIndex
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "owner-key-original-32-chars-minimum")
    idx = rag.VectorIndex(11, tmp_path)
    idx.replace_source("doc1", ["Cau truc du lieu va giai thuat thu 2"])
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "wrong-key-other-32-chars-minimum!!")
    bad_idx = rag.VectorIndex(11, tmp_path)
    assert len(bad_idx) == 0
    with pytest.raises(rag.IndexDecryptionError):
        bad_idx.replace_source("doc2", ["new payload"])
    # original data stays intact when key is restored
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "owner-key-original-32-chars-minimum")
    restored = rag.VectorIndex(11, tmp_path)
    assert len(restored) == 1
    bad_again = rag.VectorIndex(11, tmp_path)
    bad_again.clear()
    assert not bad_again.path.exists()

    # b-12: weekday separation & abbreviation matching while keeping accent invariance
    assert rag.embed("đồ án") == rag.embed("do an")
    v_ctdl = rag.embed("ctdl")
    v_full = rag.embed("Cấu trúc dữ liệu và giải thuật")
    assert sum(a * b for a, b in zip(v_ctdl, v_full)) >= 0.45
    v_t7 = rag.embed("thứ 7")
    v_t2 = rag.embed("thứ 2")
    v_sat = rag.embed("saturday")
    assert sum(a * b for a, b in zip(v_t7, v_sat)) > 0.99
    assert sum(a * b for a, b in zip(v_t7, v_t2)) < 0.30

    # b-15: runtime ddl helper removed from assistant router
    assert not hasattr(assistant_router, "_ensure_clarification_table")


def test_reschedule_afternoon_not_redirected_and_query_does_not_mutate_parent(client, db_session, monkeypatch):
    u = _register(client, "resched_guard")
    replies = iter([
        {"intent": "schedule_task", "title": "play basketball", "duration_minutes": 60, "date_hint": "tomorrow"},
        {"intent": "query_schedule", "preferred_time_of_day": "afternoon"},
        {"intent": "schedule_task", "title": "play basketball", "duration_minutes": 60, "date_hint": "tomorrow"},
        {"intent": "query_schedule"},
    ])
    monkeypatch.setattr(
        nlu.httpx,
        "Client",
        lambda *a, **kw: REAL_HTTPX_CLIENT(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(replies))}}]})
            )
        ),
    )

    # 1. initial proposal at 8am tomorrow -> rescheduled cleanly by "in the afternoon please" even if llm returned query_schedule
    p1_res = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "play basketball 1 hour tomorrow at 8am"},
    )
    assert p1_res.status_code == 200
    p1_id = p1_res.json()["proposal"]["id"]

    resched = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "in the afternoon please", "reschedule_proposal_id": p1_id},
    )
    assert resched.status_code == 200
    r_body = resched.json()
    assert r_body["redirect_target"] is None
    assert r_body["nlu"]["intent"] == "reschedule"
    assert r_body["proposal"] is not None
    p1_row = db_session.get(Proposal, p1_id)
    assert p1_row is not None and p1_row.status == ProposalStatus.RESCHEDULED

    # 2. explicit schedule query during reschedule redirects without mutating parent status to RESCHEDULED
    p2_res = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "play basketball 1 hour tomorrow at 8am"},
    )
    assert p2_res.status_code == 200
    p2_id = p2_res.json()["proposal"]["id"]

    q_res = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "tuần này mình có lịch gì?", "reschedule_proposal_id": p2_id},
    )
    assert q_res.status_code == 200
    q_body = q_res.json()
    assert q_body["redirect_target"] == "search_home"
    assert q_body["proposal"] is None
    p2_row = db_session.get(Proposal, p2_id)
    assert p2_row is not None and p2_row.status == ProposalStatus.PROPOSED


def test_parse_preview_prefill_and_resolve_preview_batch_dates(client):
    hcmus_csv = (
        "Mã MH,Tên MH,Học Kỳ,Lịch LT,Lịch TH\n"
        'CSC10008,Mạng máy tính,1/26-27,"T4 07:30-09:10 (C.45)\nT6 07:30-09:10 (I.44)",\n'
        "BAA00030,Giáo dục quốc phòng - An ninh,1/26-27,,\n"
    ).encode("utf-8")

    prev = client.post(
        "/api/v1/ingestion/parse-preview",
        files={"file": ("tkb_hcmus.csv", hcmus_csv, "text/csv")},
    )
    assert prev.status_code == 200, prev.text
    p_body = prev.json()
    assert p_body["valid_count"] == 0
    assert p_body["invalid_count"] == 3

    inv = p_body["invalid_rows"]
    missing_date_rows = [r for r in inv if r["error_code"] == "EMPTY_FIRST_DATE"]
    no_sched_rows = [r for r in inv if r["error_code"] == "NO_SCHEDULE_DETECTED"]
    assert len(missing_date_rows) == 2
    assert len(no_sched_rows) == 1
    assert {r["prefill"]["weekday"] for r in missing_date_rows} == {"WED", "FRI"}
    assert {r["prefill"]["room"] for r in missing_date_rows} == {"C.45", "I.44"}

    corrected = []
    for r in missing_date_rows:
        item = dict(r["prefill"])
        item["line_number"] = r["line_number"]
        item["first_date"] = "2026-09-28"
        item["last_date"] = "2026-12-12"
        corrected.append(item)

    res = client.post(
        "/api/v1/ingestion/resolve-preview",
        json={
            "import_batch_id": p_body["import_batch_id"],
            "valid_rows": [],
            "corrected_rows": corrected,
            "skipped_line_numbers": [r["line_number"] for r in no_sched_rows],
        },
    )
    assert res.status_code == 200, res.text
    r_body = res.json()
    assert r_body["total_accepted"] == 2
    assert {row["weekday"] for row in r_body["all_valid_rows"]} == {"WED", "FRI"}
    assert {row["room"] for row in r_body["all_valid_rows"]} == {"C.45", "I.44"}
