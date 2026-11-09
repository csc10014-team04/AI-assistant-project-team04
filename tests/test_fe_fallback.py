"""FB-01..FB-06: client-side AI timeout fallback helpers (P1-9). Pure Python, no Kivy needed."""
import socket
import sys

import pytest

from conftest import FE_DIR

sys.path.insert(0, str(FE_DIR))
import fallback  # noqa: E402


def test_FB01_timeouts_are_recognised_but_refused_connections_are_not():
    assert fallback.is_timeout(TimeoutError()) and fallback.is_timeout(socket.timeout("timed out"))
    assert fallback.is_timeout(Exception("The read operation timed out"))
    assert not fallback.is_timeout(ConnectionRefusedError("refused")) and not fallback.is_timeout(OSError("no route"))


def test_FB02_parse_request_reads_duration_and_activity():
    r = fallback.parse_request("xếp giúp mình 3 tiếng làm đồ án nhé")
    assert r == {"title": "làm đồ án", "duration_minutes": 180, "fallback_mode": True}


@pytest.mark.parametrize("text,minutes", [("học bài 45 phút", 45), ("đọc sách 1,5 giờ", 90), ("họp 2h", 120)])
def test_FB03_parse_request_units(text, minutes):
    assert fallback.parse_request(text)["duration_minutes"] == minutes


def test_FB04_missing_or_absurd_duration_falls_back_to_60():
    assert fallback.parse_request("xếp lịch học bài")["duration_minutes"] == 60
    assert fallback.parse_request("ngủ 100 giờ")["duration_minutes"] == 60  # outside 15..720


def test_FB05_empty_title_gets_a_default_name():
    assert fallback.parse_request("xếp 2 tiếng")["title"] == "Hoạt động"


def test_FB06_timeout_is_a_strict_positive_number_and_wired_into_the_chat_request():
    assert 0 < fallback.AI_TIMEOUT_SECONDS <= 10
    client_src = (FE_DIR / "api_client.py").read_text(encoding="utf-8")
    assert "timeout=AI_TIMEOUT_SECONDS" in client_src and "reschedule_proposal_id" in client_src



@pytest.mark.parametrize("text,title,minutes", [
    ("hãy xếp lịch học tư duy tính toán từ 7h đến 18h", "học tư duy tính toán", 660),
    ("xếp lịch học bài từ 8h đến 10h30", "học bài", 150),
    ("xếp 1h30 làm đồ án", "làm đồ án", 90),
    ("họp nhóm lúc 9h", "họp nhóm", 60),                      # a clock time is not a length: default 60
])
def test_FB07_offline_parser_handles_time_ranges_and_clock_times(text, title, minutes):
    r = fallback.parse_request(text)
    assert (r["title"], r["duration_minutes"]) == (title, minutes)
