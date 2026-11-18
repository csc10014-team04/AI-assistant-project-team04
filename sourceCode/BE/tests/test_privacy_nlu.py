# owner: Database & AI (unit tests for P1-2 privacy helpers and P1-7 NLU; no mysql required)
import json
from datetime import datetime

import httpx
import pytest

from database import VN_TZ
from services import nlu
from services.privacy import (
    decrypt_text, encrypt_text, is_private_endpoint, sanitize_prompt,
)

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _llm_reply(obj_or_text) -> httpx.Response:
    content = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_sanitize_redacts_pii_and_control_chars():
    out = sanitize_prompt("gọi 0901234567 hoặc a.b@x.com\x00 http://evil.io/x   ok")
    assert "[phone]" in out and "[email]" in out and "[url]" in out
    assert "\x00" not in out and "  " not in out


def test_sanitize_truncates():
    assert len(sanitize_prompt("a" * 5000)) == 500


@pytest.mark.parametrize("url,ok", [
    ("http://127.0.0.1:8000/v1", True), ("http://llama_engine:8000/v1", True),
    ("http://192.168.100.112:8000", True), ("https://api.openai.com/v1", False),
    ("http://8.8.8.8/x", False),
])
def test_private_endpoint(url, ok):
    assert is_private_endpoint(url) is ok


def test_encrypt_roundtrip_and_tamper():
    token = encrypt_text("xếp lịch học")
    assert token != "xếp lịch học" and decrypt_text(token) == "xếp lịch học"
    assert decrypt_text(token[:-4] + "AAAA") is None


def test_rules_extract_duration_and_avoid_evening():
    r = nlu.rule_based_understand("Xếp cho mình 3 tiếng làm đồ án CTDL tuần này, không làm buổi tối nhé")
    assert r.intent == "schedule_task" and r.duration_minutes == 180
    assert r.avoid_time_of_day == "evening" and r.preferred_time_of_day is None
    assert r.date_hint == "tuần này" and "đồ án" in r.title


def test_rules_decimal_and_minutes():
    assert nlu.extract_duration_minutes("1,5 tiếng") == 90
    assert nlu.extract_duration_minutes("45 phút") == 45
    assert nlu.extract_duration_minutes("100 giờ") is None


def test_llm_happy_path_and_duration_guard():
    # model hallucinates 60 min; literal text says 2 hours -> text wins
    reply = {"intent": "schedule_task", "title": "học bài", "duration_minutes": 60}
    r = nlu.understand_prompt("xếp 2 tiếng học bài", NOW, client=_client(lambda req: _llm_reply(reply)))
    assert r.source == "llm" and not r.fallback_mode and r.duration_minutes == 120


def test_llm_invented_duration_dropped():
    reply = {"intent": "schedule_task", "title": "gym", "duration_minutes": 90}
    r = nlu.understand_prompt("xếp lịch đi gym", NOW, client=_client(lambda req: _llm_reply(reply)))
    assert r.duration_minutes is None


def test_malformed_json_retries_then_falls_back():
    calls = []
    def handler(req):
        calls.append(1)
        return _llm_reply("not json at all")
    r = nlu.understand_prompt("xếp 2 tiếng học bài", NOW, client=_client(handler))
    assert len(calls) == 2 and r.fallback_mode and r.source == "rules" and r.duration_minutes == 120


def test_retry_recovers_on_second_attempt():
    replies = iter(["oops", json.dumps({"intent": "schedule_task", "title": "x", "duration_minutes": 30})])
    r = nlu.understand_prompt("30 phút đọc sách", NOW, client=_client(lambda req: _llm_reply(next(replies))))
    assert r.source == "llm" and r.duration_minutes == 30


def test_timeout_and_crash_fall_back():
    def timeout(req): raise httpx.ReadTimeout("slow")
    def refused(req): raise httpx.ConnectError("down")
    assert nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(timeout)).fallback_mode
    assert nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(refused)).fallback_mode


def test_5xx_falls_back():
    r = nlu.understand_prompt("xếp 2 tiếng học", NOW, client=_client(lambda req: httpx.Response(503)))
    assert r.fallback_mode and r.duration_minutes == 120


def test_naive_now_rejected():
    with pytest.raises(ValueError):
        nlu.understand_prompt("x", datetime(2026, 1, 1))


def test_private_endpoint_allowlist_and_tailscale(monkeypatch):
    assert is_private_endpoint("http://100.101.2.3:8000/v1")  # tailscale
    assert not is_private_endpoint("http://26.211.52.63:8000/v1")
    monkeypatch.setenv("LLM_ALLOWED_HOSTS", "26.211.52.63")
    assert is_private_endpoint("http://26.211.52.63:8000/v1")
    monkeypatch.setenv("LLM_ALLOWED_HOSTS", "26.0.0.0/8")
    assert is_private_endpoint("http://26.9.9.9:8000/v1")
    assert not is_private_endpoint("http://8.8.8.8:8000/v1")


def test_rules_explicit_duration_without_xep():
    r = nlu.rule_based_understand("học bài 2h từ 7h đến 11h")
    assert r.intent == "schedule_task" and r.duration_minutes == 120

    bare = nlu.rule_based_understand("7h - 11h")
    assert bare.intent == "unknown"


def test_healthy_llm_unknown_never_triggers_busy_fallback():
    unknown_client = _client(lambda req: _llm_reply({"intent": "unknown"}))

    for bare in ("2 tiếng", "5 tiếng", "khoảng 2 tiếng", "2 tiếng rưỡi"):
        r = nlu.understand_prompt(bare, NOW, client=unknown_client)
        assert not r.fallback_mode and r.source == "llm"
        assert r.needs_clarification and r.duration_minutes is not None and r.title is None

    for chitchat in ("đợi 2 tiếng rồi", "đổi ý rồi", "hủy kèo đi chơi", "có gì đâu", "lịch sự quá"):
        r = nlu.understand_prompt(chitchat, NOW, client=unknown_client)
        assert not r.fallback_mode and r.source == "llm" and r.intent == "unknown"


def test_half_hour_ruoi_duration_and_title():
    r = nlu.rule_based_understand("2 tiếng rưỡi")
    assert r.duration_minutes == 150 and r.title is None


def test_clock_range_vs_duration_range_disambiguation():
    clock_prompt = "Tôi muốn xếp lịch cho thứ 2 tuần sau, học môn mạng máy tính, từ 5 giờ đến 6 giờ"
    r_clock = nlu.rule_based_understand(clock_prompt)
    assert r_clock.intent == "schedule_task"
    assert r_clock.duration_minutes == 60
    assert nlu.parse_clock_window(clock_prompt) == (17 * 60, 18 * 60)

    r_morning = nlu.rule_based_understand("xếp lịch buổi sáng từ 5 giờ đến 6 giờ")
    assert r_morning.duration_minutes == 60
    assert nlu.parse_clock_window("xếp lịch buổi sáng từ 5 giờ đến 6 giờ") == (5 * 60, 6 * 60)

    for dur_prompt in (
        "Tôi muốn xếp lịch học mạng máy tính khoảng 5 đến 6 giờ",
        "xếp lịch học 5 đến 6 tiếng",
    ):
        r_dur = nlu.rule_based_understand(dur_prompt)
        assert r_dur.intent == "schedule_task"
        assert r_dur.duration_minutes == 360
        assert nlu.parse_clock_window(dur_prompt) is None
