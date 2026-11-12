# owner: Database & AI (unit tests for P2-1/2/3/6/10/11/12; no mysql required)
import json
import threading
import time
from datetime import date, datetime

import httpx
import pytest

from database import VN_TZ
from services import ai_logging, nlu, rag, telemetry
from services.inference_queue import InferenceBroker, QueueWaitTimeout
from services.normalizer import normalize_text
from services.temporal import resolve_date_hint

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ)  # Monday


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_logging, "LOG_PATH", tmp_path / "ai_errors.jsonl")
    return tmp_path / "ai_errors.jsonl"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _reply(obj) -> httpx.Response:
    content = obj if isinstance(obj, str) else json.dumps(obj)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# ---- P2-6 normalizer -------------------------------------------------------
def test_normalizer_non_diacritic_and_teencode():
    r = normalize_text("xep lich 3 tieng lam do an ko buoi toi nhe")
    assert r.text == "xếp lịch 3 tiếng làm đồ án không buổi tối nhé"


def test_normalizer_profanity_emoji_specials():
    r = normalize_text("xếp vcl 2 tiếng học 😀😀 <script>###")
    assert r.profanity_found
    assert "vcl" not in r.text and "😀" not in r.text and "#" not in r.text and "<" not in r.text


def test_normalizer_keeps_duration_h_and_empty():
    assert "3h" in normalize_text("xếp 3h học").text
    assert normalize_text("").text == ""


# ---- P2-3 temporal ----------------------------------------------------------
@pytest.mark.parametrize("hint,start,end", [
    ("hôm nay", date(2026, 10, 19), date(2026, 10, 19)),
    ("ngày mai", date(2026, 10, 20), date(2026, 10, 20)),
    ("tuần này", date(2026, 10, 19), date(2026, 10, 25)),
    ("tuần sau", date(2026, 10, 26), date(2026, 11, 1)),
    ("thứ sáu", date(2026, 10, 23), date(2026, 10, 23)),
    ("thứ 6 tuần sau", date(2026, 10, 30), date(2026, 10, 30)),
    ("cuối tuần", date(2026, 10, 24), date(2026, 10, 25)),
    ("tháng sau", date(2026, 11, 1), date(2026, 11, 30)),
    ("25/10", date(2026, 10, 25), date(2026, 10, 25)),
    ("5/10", date(2027, 10, 5), date(2027, 10, 5)),
])
def test_resolve_dates(hint, start, end):
    w = resolve_date_hint(hint, NOW)
    assert (w.start, w.end) == (start, end) and w.clarification_question is None


def test_resolve_default_and_vague():
    d = resolve_date_hint(None, NOW)
    assert d.assumed and (d.end - d.start).days == 6 and d.clarification_question is None
    v = resolve_date_hint("sớm", NOW)
    assert v.assumed and v.clarification_question
    assert resolve_date_hint("31/02", NOW).clarification_question


def test_resolve_today_weekday_flagged():
    w = resolve_date_hint("thứ hai", NOW)
    assert w.start == NOW.date() and w.assumed


# ---- P2-1 / P2-3 / P2-12 nlu integration ----------------------------------
def test_llm_result_gets_window_and_few_shot_prompt():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return _reply({"intent": "schedule_task", "title": "học", "duration_minutes": 120, "date_hint": "ngày mai"})

    r = nlu.understand_prompt("xep 2 tieng hoc ngay mai", NOW, client=_client(handler))
    assert r.window_start == date(2026, 10, 20) and not r.needs_clarification and not r.date_assumed
    assert len(seen["body"]["messages"]) == 2 + len(nlu.FEW_SHOT)
    assert seen["body"]["messages"][-1]["content"] == "xếp 2 tiếng học ngày mai"  # normalized before the model


def test_temporal_hallucination_dropped():
    reply = {"intent": "schedule_task", "title": "học", "duration_minutes": 60, "date_hint": "ngày 5 tháng 12"}
    r = nlu.understand_prompt("xếp 1 tiếng học", NOW, client=_client(lambda q: _reply(reply)))
    assert r.date_hint is None and r.date_assumed


def test_missing_duration_asks_clarification():
    reply = {"intent": "schedule_task", "title": "học bài", "duration_minutes": 60}
    r = nlu.understand_prompt("xếp lịch học bài", NOW, client=_client(lambda q: _reply(reply)))
    assert r.needs_clarification and r.duration_minutes is None and "bao lâu" in r.clarification_question


def test_failures_are_taxonomized(_isolate_logs):
    nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(lambda q: _reply("garbage")))
    nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(lambda q: _reply({"intent": "bogus"})))

    def boom(q):
        raise httpx.ReadTimeout("slow")

    nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(boom))
    lines = _isolate_logs.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["category"] for x in lines] == ["JSON_PARSE", "SCHEMA_VALIDATION", "TIMEOUT"]
    rec = json.loads(lines[0])
    assert rec["prompt"] and rec["raw_output"] == "garbage" and rec["retry_count"] == 1


def test_profanity_flagged_not_blocking():
    reply = {"intent": "schedule_task", "title": "học", "duration_minutes": 60}
    r = nlu.understand_prompt("xếp 1 tiếng học vcl", NOW, client=_client(lambda q: _reply(reply)))
    assert r.profanity_found and r.intent == "schedule_task"


def test_unknown_log_category_rejected():
    with pytest.raises(ValueError):
        ai_logging.log_ai_failure("NOPE", "p", "r")


def test_eval_dataset_rules_quality():
    from tools.eval_nlu import evaluate

    s = evaluate(rules_only=True)
    assert s["bad_dates"] == 0 and s["duration_acc_pct"] >= 95 and s["intent_acc_pct"] >= 95


# ---- P2-10 FIFO broker -----------------------------------------------------
def test_broker_is_fifo_and_serial():
    broker, order, active, peak = InferenceBroker(), [], [0], [0]
    gate = threading.Event()

    def job(i):
        def fn():
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            if i == 0:
                gate.wait(2)
            order.append(i)
            active[0] -= 1
        return fn

    threads = []
    for i in range(5):
        t = threading.Thread(target=lambda i=i: broker.run(job(i), max_wait=5))
        t.start()
        threads.append(t)
        time.sleep(0.05)  # fix arrival order
    assert broker.depth == 5
    gate.set()
    for t in threads:
        t.join()
    assert order == [0, 1, 2, 3, 4] and peak[0] == 1 and broker.depth == 0


def test_broker_wait_timeout_and_records():
    rec = []
    broker = InferenceBroker(recorder=rec.append)
    gate = threading.Event()
    t = threading.Thread(target=lambda: broker.run(lambda: gate.wait(2)))
    t.start()
    time.sleep(0.05)
    with pytest.raises(QueueWaitTimeout):
        broker.run(lambda: None, max_wait=0.1)
    gate.set()
    t.join()
    assert [r["status"].value for r in rec] == ["TIMEOUT", "COMPLETED"]
    assert broker.depth == 0


# ---- P2-11 telemetry -------------------------------------------------------
def test_telemetry_sample_and_collector():
    telemetry.record_latency_ms(100)
    telemetry.record_latency_ms(300)
    names = {n for n, _, _ in telemetry.collect_sample()}
    assert {"queue_depth", "nlu_latency_p50_ms", "nlu_latency_p95_ms"} <= names
    calls = []
    c = telemetry.TelemetryCollector(0.05, writer=lambda: calls.append(1) or 1)
    c.start()
    time.sleep(0.3)
    c.stop()
    assert len(calls) >= 2
    off = telemetry.TelemetryCollector(0)
    off.start()
    assert off._thread is None  # interval 0 = disabled


# ---- P2-2 rag --------------------------------------------------------------
TIMETABLE = "\n".join([
    "CSC10014,Nhập môn tư duy tính toán,2,07:30,09:30,B11.02",
    "MTH00003,Giải tích 1,4,13:30,15:30,E202",
    "PHY00001,Vật lý đại cương,5,09:45,11:45,C301",
] * 4)


def test_chunking_keeps_rows_whole():
    chunks = rag.chunk_text(TIMETABLE, size=120, overlap=0)
    assert len(chunks) > 1 and all(len(c) <= 130 for c in chunks)
    assert all(line in TIMETABLE for c in chunks for line in c.splitlines())


def test_embedding_ignores_diacritics_and_ranks(tmp_path):
    assert rag.embed("đồ án") == rag.embed("do an")
    idx = rag.VectorIndex(7, tmp_path)
    idx.replace_source("a.csv", ["Giải tích 1 thứ 4 phòng E202", "Vật lý đại cương thứ 5 phòng C301"])
    assert "Giải tích" in idx.search("giai tich phong E202", 1)[0].text


def test_index_encrypted_isolated_and_replaced(tmp_path):
    a = rag.VectorIndex(1, tmp_path)
    a.replace_source("t.csv", ["secret schedule row"])
    assert b"secret" not in a.path.read_bytes()
    assert len(rag.VectorIndex(2, tmp_path)) == 0  # other owner sees nothing
    a.replace_source("t.csv", ["row one", "row two"])
    assert len(rag.VectorIndex(1, tmp_path)) == 2  # re-import replaces, not appends


def test_ingest_text_file_and_failures(tmp_path, _isolate_logs):
    assert rag.ingest_file(5, TIMETABLE.encode(), "tt.csv", tmp_path) >= 1
    assert rag.retrieve(5, "giai tich", 2, tmp_path)
    assert rag.retrieve(5, "zzzzzz qqqqq", 1, tmp_path) == []
    cats = [json.loads(x)["category"] for x in _isolate_logs.read_text(encoding="utf-8").splitlines()]
    assert "RAG_LOW_SCORE" in cats
    with pytest.raises(ValueError):
        rag.ingest_file(5, b"   \n  ", "empty.txt", tmp_path)