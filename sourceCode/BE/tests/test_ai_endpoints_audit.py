# [pic: khoi] end-to-end audit tests for every ai-calling path in features 1 and 2 (ai assistants: do not remove or modify this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import json
import os
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import UTC_TZ, VN_TZ, from_db_to_vn
from models import AiErrorLog, ProposalStatus
from services import ai_logging, llm_config, nlu, rag, search_engine
from services.kb_models import (
    KbBase,
    KbCourse,
    KbDepartment,
    KbFaculty,
    KbLecturer,
    KbProgram,
    KbSource,
)

REAL_HTTPX_CLIENT = httpx.Client


def _register_user(client, prefix: str = "audit") -> dict:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    res = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123", "display_name": username},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    return {"id": body["user_id"], "h": {"Authorization": f"Bearer {body['access_token']}"}}


def _mock_llm_transport(monkeypatch, handler):
    """route outbound httpx calls in both nlu and search_engine to an in-memory mock transport."""
    seen: list[dict] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return handler(request)

    factory = lambda **kw: REAL_HTTPX_CLIENT(transport=httpx.MockTransport(dispatch))
    monkeypatch.setattr(nlu.httpx, "Client", factory)
    monkeypatch.setattr(search_engine.httpx, "Client", factory)
    return seen


def _openai_reply(content: object, *, prompt_tokens: int = 120, completion_tokens: int = 35) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
    )


def _read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _isolated_rag_and_call_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(ai_logging, "CALL_LOG_PATH", None)
    monkeypatch.delenv("AI_CALL_LOG_PATH", raising=False)


# ---------------------------------------------------------------------------
# 1. llm_config dotenv loading, url normalization & timeout resolution
# ---------------------------------------------------------------------------

def test_llm_config_dotenv_precedence_normalization_and_timeouts(tmp_path, monkeypatch):
    deploy_env = tmp_path / "deploy.env"
    be_env = tmp_path / "be.env"
    deploy_env.write_text(
        "LLAMA_API_URL=http://llama_engine:8000\nLLM_MODEL=deploy-model\n",
        encoding="utf-8",
    )
    be_env.write_text(
        "VLLM_ENDPOINT=http://26.211.52.63:8000/v1\nLLM_ALLOWED_HOSTS=26.211.52.63\n",
        encoding="utf-8",
    )

    env_keys = (
        "VLLM_ENDPOINT", "LLAMA_API_URL", "LLM_MODEL",
        "LLM_ALLOWED_HOSTS", "LLM_TIMEOUT_SECONDS", "ACADEMIC_LLM_TIMEOUT_SECONDS",
    )
    saved_env = {k: os.environ.get(k) for k in env_keys}
    saved_loaded = llm_config._DOTENV_LOADED
    monkeypatch.setattr(llm_config, "DEPLOY_ENV_PATH", deploy_env)
    monkeypatch.setattr(llm_config, "LOCAL_ENV_PATH", be_env)
    try:
        for var in env_keys:
            os.environ.pop(var, None)

        llm_config.load_be_dotenv(force=True)
        # local BE .env overrides deploy .env, normalized to /v1/chat/completions
        assert llm_config.resolve_vllm_endpoint() == "http://26.211.52.63:8000/v1/chat/completions"
        assert llm_config.resolve_llm_model() == "deploy-model"

        # explicit OS env vars must never be overwritten by dotenv
        os.environ["VLLM_ENDPOINT"] = "http://127.0.0.1:8000"
        llm_config.load_be_dotenv(force=True)
        assert llm_config.resolve_vllm_endpoint() == "http://127.0.0.1:8000/v1/chat/completions"

        # LLAMA_API_URL fallback normalization when VLLM_ENDPOINT is unset
        os.environ.pop("VLLM_ENDPOINT", None)
        os.environ["LLAMA_API_URL"] = "http://llama_engine:8000"
        assert llm_config.resolve_vllm_endpoint() == "http://llama_engine:8000/v1/chat/completions"

        # feature-specific timeouts
        assert llm_config.resolve_llm_timeout("nlu") == llm_config.DEFAULT_NLU_TIMEOUT_SECONDS
        assert llm_config.resolve_llm_timeout("academic_rag") == llm_config.DEFAULT_ACADEMIC_TIMEOUT_SECONDS
        os.environ["LLM_TIMEOUT_SECONDS"] = "5.5"
        assert llm_config.resolve_llm_timeout("nlu") == 5.5
        assert llm_config.resolve_llm_timeout("academic_rag") == 5.5
        os.environ["ACADEMIC_LLM_TIMEOUT_SECONDS"] = "12.0"
        assert llm_config.resolve_llm_timeout("academic_rag") == 12.0
    finally:
        for var, orig in saved_env.items():
            if orig is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = orig
        llm_config._DOTENV_LOADED = saved_loaded


# ---------------------------------------------------------------------------
# 2. feature 2 (scheduling with ai): all 12 cases + edge flows + audit logs
# ---------------------------------------------------------------------------

def test_feature2_tc01_to_tc11_and_edge_cases_invoke_llm_and_write_audit_log(client, db_session, monkeypatch):
    def scripted_llm(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        low = prompt.lower()

        if "giải tích" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "ôn tập Giải tích", "duration_minutes": 120,
                "preferred_time_of_day": "afternoon", "avoid_time_of_day": None, "date_hint": "ngày mai",
            })
        if "đừng xếp vào buổi tối" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "làm bài tập Hệ điều hành", "duration_minutes": 90,
                "preferred_time_of_day": None, "avoid_time_of_day": "evening", "date_hint": None,
            })
        if "hạn nộp báo cáo mạng máy tính" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "làm báo cáo", "duration_minutes": 120,
                "priority": 1, "date_hint": "tuần này", "deadline_hint": "thứ sáu",
            })
        if "họp nhóm đồ án từ 14h đến 15h30" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "họp nhóm đồ án", "duration_minutes": 90, "date_hint": "ngày mai",
            })
        if "trí tuệ nhân tạo" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "làm đồ án Trí tuệ nhân tạo",
                "duration_minutes": 300, "date_hint": "thứ bảy tuần này",
            })
        if "[email]" in low and "[phone]" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "làm bài tập ctdl", "duration_minutes": 90,
                "preferred_time_of_day": "morning", "date_hint": "ngày mai",
            })
        if "đi tập thể thao" in low:
            # simulate model hallucinating 60 mins; missing duration guard must wipe it
            return _openai_reply({
                "intent": "schedule_task", "title": "tập thể thao", "duration_minutes": 60,
                "preferred_time_of_day": "afternoon", "date_hint": "thứ năm tuần này",
            })
        if "đọc tài liệu nghiên cứu" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "đọc tài liệu nghiên cứu",
                "duration_minutes": 60, "date_hint": "sắp tới",
            })
        if "buổi sáng" in low or "buổi tối đi" in low:
            # short reschedule follow-up without verb
            return _openai_reply({
                "intent": "unknown", "preferred_time_of_day": "evening" if "tối" in low else "morning",
            })
        if "slide thuyết trình" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "chuẩn bị slide thuyết trình", "duration_minutes": 45,
                "preferred_time_of_day": "morning", "date_hint": "thứ tư tuần sau",
            })
        if "lịch học hay lịch thi" in low:
            return _openai_reply({"intent": "query_schedule", "date_hint": "thứ sáu tuần này"})
        if "học môn mạng máy tính" in low and "từ 5 giờ đến 6 giờ" in low:
            return _openai_reply({
                "intent": "schedule_task", "title": "học môn mạng máy tính",
                "duration_minutes": 60, "date_hint": "thứ 2 tuần sau",
            })
        return _openai_reply({"intent": "unknown"})

    seen = _mock_llm_transport(monkeypatch, scripted_llm)
    u = _register_user(client, "f2_user")

    # tc-01: happy path afternoon tomorrow
    r1 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Xếp giúp mình 2 tiếng ôn tập Giải tích vào chiều ngày mai"}).json()
    assert r1["nlu"]["source"] == "llm" and not r1["nlu"]["fallback_mode"]
    assert r1["nlu"]["duration_minutes"] == 120 and r1["nlu"]["preferred_time_of_day"] == "afternoon"
    assert r1["proposal"] is not None
    tc01_id = r1["proposal"]["id"]

    # tc-09 + short reschedule guard: "buổi tối đi" with reschedule_proposal_id
    r9 = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "buổi tối đi", "reschedule_proposal_id": tc01_id},
    ).json()
    assert r9["abandoned_proposals"] == 0 and not r9["nlu"]["fallback_mode"]
    assert r9["proposal"] is not None and r9["proposal"]["parent_id"] == tc01_id
    assert datetime.fromisoformat(r9["proposal"]["start_time"]).hour >= 18

    # tc-02: avoid evening + 7-day assumed window
    r2 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Xếp 90 phút làm bài tập Hệ điều hành, đừng xếp vào buổi tối nhé"}).json()
    assert r2["nlu"]["avoid_time_of_day"] == "evening" and r2["nlu"]["date_assumed"] is True
    assert r2["abandoned_proposals"] == 1  # tc-09 pending proposal abandoned by new root prompt
    assert r2["proposal"] is not None and datetime.fromisoformat(r2["proposal"]["end_time"]).hour <= 18

    # tc-03: deadline_hint clamp + priority=1
    r3 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Hạn nộp báo cáo Mạng máy tính là thứ sáu, xếp cho mình 2 tiếng làm báo cáo trong tuần này"}).json()
    assert r3["nlu"]["priority"] == 1 and r3["nlu"]["deadline_hint"] == "thứ sáu"
    assert r3["nlu"]["window_end"] == r3["nlu"]["deadline"]

    # tc-04: explicit clock range 14h - 15h30
    r4 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Ngày mai xếp lịch họp nhóm đồ án từ 14h đến 15h30"}).json()
    assert r4["nlu"]["duration_minutes"] == 90
    assert r4["nlu"]["requested_start"] == "14:00" and r4["nlu"]["requested_end"] == "15:30"
    assert r4["proposal"] is not None
    assert r4["proposal"]["start_time"].endswith("T14:00:00+07:00")

    # tc-05: 5h task splits across max_block_minutes
    r5 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Thứ bảy tuần này xếp cho mình 5 tiếng làm đồ án Trí tuệ nhân tạo"}).json()
    assert r5["nlu"]["duration_minutes"] == 300 and r5["nlu"]["date_hint"] and "thứ bảy" in r5["nlu"]["date_hint"].lower()
    if r5["proposal"] is not None:
        assert r5["proposal"]["extra_slots"]

    # tc-06: teencode + PII redaction preserved through normalizer -> [email] & [phone]
    r6 = client.post(
        "/api/v1/assistant/understand",
        headers=u["h"],
        json={"prompt": "xep giup m 1h30p lam bt ctdl vao sang mai, gui qua mail sv24120001@student.hcmus.edu.vn sdt 0912345678"},
    ).json()
    assert r6["nlu"]["source"] == "llm" and not r6["nlu"]["fallback_mode"]
    assert r6["nlu"]["duration_minutes"] == 90 and r6["nlu"]["preferred_time_of_day"] == "morning"
    assert r6["nlu"]["date_hint"] == "ngày mai"
    assert "sv24120001@student.hcmus.edu.vn" not in seen[-1]["body"]["messages"][-1]["content"]
    assert "0912345678" not in seen[-1]["body"]["messages"][-1]["content"]
    assert "[email]" in seen[-1]["body"]["messages"][-1]["content"] and "[phone]" in seen[-1]["body"]["messages"][-1]["content"]

    # tc-07: missing duration asks clarification
    r7 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Chiều thứ năm tuần này xếp lịch cho mình đi tập thể thao nhé"}).json()
    assert r7["nlu"]["source"] == "llm" and r7["nlu"]["duration_minutes"] is None
    assert r7["nlu"]["needs_clarification"] is True and r7["proposal"] is None

    # switching topics to tc-08 with "xếp cho mình" resets stale pending clarification
    r8 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Xếp cho mình 1 tiếng đọc tài liệu nghiên cứu vào lúc nào đó sắp tới"}).json()
    assert r8["nlu"]["source"] == "llm" and r8["nlu"]["needs_clarification"] is True and r8["proposal"] is None
    assert "nghiên cứu" in (r8["nlu"]["title"] or "").lower()

    # tc-08 turn 2 clarification completion ("ngày mai") resolves to a proposal
    r8_t2 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "ngày mai"}).json()
    assert r8_t2["nlu"]["source"] == "llm" and r8_t2["nlu"]["needs_clarification"] is False and r8_t2["proposal"] is not None

    # tc-10: Wednesday next week resolved to single day + abandons prior proposal first
    r10 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Sáng thứ tư tuần sau xếp cho mình 45 phút chuẩn bị slide thuyết trình"}).json()
    assert r10["nlu"]["source"] == "llm" and r10["abandoned_proposals"] >= 1
    assert r10["nlu"]["window_start"] == r10["nlu"]["window_end"]
    assert datetime.fromisoformat(r10["nlu"]["window_start"]).weekday() == 2  # Wednesday

    # tc-11: cross-tab redirect on query_schedule
    r11 = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Sáng thứ sáu tuần này mình có lịch học hay lịch thi môn gì không?"}).json()
    assert r11["nlu"]["source"] == "llm" and r11["redirect_target"] == "search_home" and r11["proposal"] is None

    # extra: user's clock-range sentence + bare range "7h - 11h"
    rext = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Tôi muốn xếp lịch cho thứ 2 tuần sau, học môn mạng máy tính, từ 5 giờ đến 6 giờ"}).json()
    assert rext["nlu"]["duration_minutes"] == 60 and rext["nlu"]["requested_start"] == "17:00" and rext["nlu"]["requested_end"] == "18:00"
    rbare = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "7h - 11h"}).json()
    assert rbare["nlu"]["source"] == "llm" and not rbare["nlu"]["fallback_mode"] and rbare["nlu"]["needs_clarification"] is True

    # audit log & debug endpoint prove every call reached mock LLM cleanly
    calls = _read_jsonl(ai_logging.get_call_log_path())
    assert len(calls) == 14
    assert all(c["feature"] == "scheduling_nlu" and c["status"] == "OK" and c["http_status"] == 200 for c in calls)
    dbg = client.get("/api/v1/debug/logs?limit=20").json()
    assert dbg["ai_call_count"] == 14 and len(dbg["recent_ai_calls"]) == 14


def test_feature2_tc12_llm_down_logs_fallback_and_returns_slots(client, db_session, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("vllm offline")

    _mock_llm_transport(monkeypatch, down)
    u = _register_user(client, "f2_down")
    res = client.post("/api/v1/assistant/understand", headers=u["h"], json={"prompt": "Xếp 2 tiếng ôn thi Cấu trúc dữ liệu vào ngày mai"})
    assert res.status_code == 200
    body = res.json()
    assert body["nlu"]["fallback_mode"] is True and body["nlu"]["source"] == "rules"
    assert body["nlu"]["duration_minutes"] == 120
    assert len(body["available_slots"]) >= 1
    assert db_session.query(AiErrorLog).filter_by(user_id=u["id"]).count() == 1
    calls = _read_jsonl(ai_logging.get_call_log_path())
    assert len(calls) == 1 and calls[0]["status"] == "FALLBACK" and calls[0]["feature"] == "scheduling_nlu"
    dbg = client.get("/api/v1/debug/logs?limit=10").json()
    assert dbg["ai_error_count"] == 1 and dbg["recent_ai_errors"][0]["category"] == "INFRA_CRASH"


# ---------------------------------------------------------------------------
# 3. feature 1 mode b (academic knowledge base 6-step rag)
# ---------------------------------------------------------------------------

def _seed_kb_tables(db: Session) -> None:
    KbBase.metadata.create_all(bind=db.get_bind(), checkfirst=True)
    if db.scalar(select(KbFaculty).where(KbFaculty.site_id == "fit")) is not None:
        return
    src = KbSource(
        site_id="fit", url="https://fit.hcmus.edu.vn/programs", url_hash="h_fit_prog",
        title="FIT Programs", fetched_at=datetime.now(UTC_TZ).replace(tzinfo=None),
    )
    db.add(src)
    db.flush()
    fac = KbFaculty(
        site_id="fit", name="Công nghệ Thông tin", name_folded="cong nghe thong tin",
        short_name="CNTT", home_url="https://fit.hcmus.edu.vn", source_id=src.id,
        description="Khoa Công nghệ Thông tin đào tạo đại học và sau đại học.",
    )
    db.add(fac)
    db.flush()
    dept = KbDepartment(
        faculty_id=fac.id, name="Khoa học Máy tính", name_folded="khoa hoc may tinh",
        description="Nghiên cứu trí tuệ nhân tạo và thuật toán.", source_id=src.id, review_status="APPROVED",
    )
    db.add(dept)
    db.flush()
    db.add(KbLecturer(
        faculty_id=fac.id, department_id=dept.id, full_name="Lê Hoài Bắc", name_folded="le hoai bac",
        academic_title="GS.TS.", position="Giảng viên cao cấp", source_id=src.id, review_status="APPROVED", is_active=True,
    ))
    db.add(KbProgram(
        faculty_id=fac.id, name="Cử nhân Công nghệ Thông tin", name_folded="cu nhan cong nghe thong tin",
        level="Đại học", description="Chương trình chuẩn 4 năm gồm 138 tín chỉ.", source_id=src.id, review_status="APPROVED",
    ))
    db.add(KbCourse(
        faculty_id=fac.id, course_code="CSC10004", name="Cấu trúc dữ liệu và giải thuật",
        name_folded="cau truc du lieu va giai thuat", credits=4.0,
        description="Danh sách liên kết, cây, đồ thị và giải thuật sắp xếp.", source_id=src.id, review_status="APPROVED",
    ))
    db.flush()


def test_feature1_academic_rag_structured_vector_redirect_empty_and_fallback(client, db_session, monkeypatch):
    _seed_kb_tables(db_session)
    seen = _mock_llm_transport(
        monkeypatch,
        lambda req: _openai_reply("Theo dữ liệu học vụ, chương trình yêu cầu 138 tín chỉ."),
    )
    u = _register_user(client, "f1_user")

    # 1) upload vector handbook document
    doc_bytes = (
        "Quy chế học vụ ngành Công nghệ Thông tin (CNTT): Sinh viên cần tích lũy tối thiểu 138 tín chỉ "
        "và đạt chuẩn ngoại ngữ đầu ra để xét tốt nghiệp.\n"
        + ("Thông tin mở rộng về chuẩn đầu ra và thực tập tốt nghiệp khoa CNTT. " * 25)
    ).encode("utf-8")
    up = client.post(
        "/api/v1/search/academic/documents",
        headers=u["h"],
        files={"file": ("handbook.txt", doc_bytes, "text/plain")},
    )
    assert up.status_code == 200 and up.json()["chunks_indexed"] >= 1

    # 2) structured kb_* query with faculty abbreviation CNTT
    res_prog = client.post(
        "/api/v1/search/academic/ask",
        headers=u["h"],
        json={"query": "Khoa CNTT gồm những chương trình đào tạo nào?", "top_k": 3},
    )
    assert res_prog.status_code == 200
    b_prog = res_prog.json()
    assert b_prog["fallback_mode"] is False and len(b_prog["citations"]) >= 2
    assert any("Cử nhân Công nghệ Thông tin" in c["text"] or "Công nghệ Thông tin" in c["text"] for c in b_prog["citations"])
    assert any(c["source"] == "handbook.txt" for c in b_prog["citations"])

    # 3) structured lecturer + course credit lookup
    res_lec = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "Cho mình hỏi thông tin giảng viên Lê Hoài Bắc?"}).json()
    assert res_lec["fallback_mode"] is False and any("Lê Hoài Bắc" in c["text"] for c in res_lec["citations"])

    res_crs = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "Học phần Cấu trúc dữ liệu và giải thuật mấy tín chỉ?"}).json()
    assert res_crs["fallback_mode"] is False and any("CSC10004" in c["text"] for c in res_crs["citations"])

    # 4) context cap check when top_k=10 with long chunks
    big_doc = ("\n".join(f"Quy định học vụ mục {i}: " + ("chi tiết quy chế đào tạo đại học " * 14) for i in range(12))).encode("utf-8")
    client.post("/api/v1/search/academic/documents", headers=u["h"], files={"file": ("long_reg.txt", big_doc, "text/plain")})
    res_cap = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "chi tiết quy chế đào tạo đại học", "top_k": 10}).json()
    assert res_cap["fallback_mode"] is False
    packed_prompt = seen[-1]["body"]["messages"][-1]["content"]
    assert len(packed_prompt) <= search_engine.MAX_RAG_CONTEXT_CHARS + 120

    llm_calls_before_non_llm = len(seen)

    # 5) out-of-scope query stops at step 3 with zero llm call
    res_empty = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "Giá vàng hôm nay bao nhiêu?"}).json()
    assert res_empty["citations"] == [] and res_empty["fallback_mode"] is False
    assert len(seen) == llm_calls_before_non_llm

    # 6) scheduling command in search tab redirects to chat_home without calling llm
    res_redir = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "Xếp cho mình 2 tiếng học bài"}).json()
    assert res_redir["redirect_target"] == "chat_home"
    assert len(seen) == llm_calls_before_non_llm

    # 7) llm timeout/offline triggers graceful fallback + audit logs
    _mock_llm_transport(monkeypatch, lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")))
    res_fb = client.post("/api/v1/search/academic/ask", headers=u["h"], json={"query": "Cần bao nhiêu tín chỉ để tốt nghiệp CNTT?"}).json()
    assert res_fb["fallback_mode"] is True and "Trợ lý AI đang bận" in res_fb["answer"]
    assert len(res_fb["citations"]) >= 1
    assert db_session.query(AiErrorLog).filter_by(user_id=u["id"]).count() == 1

    calls = _read_jsonl(ai_logging.get_call_log_path())
    ok_calls = [c for c in calls if c["feature"] == "academic_rag" and c["status"] == "OK"]
    fb_calls = [c for c in calls if c["feature"] == "academic_rag" and c["status"] == "FALLBACK"]
    assert len(ok_calls) == 4 and len(fb_calls) == 1
