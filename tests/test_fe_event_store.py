"""ES-01..ES-08 (event store: the calendar shows real events) and ST-01..ST-03 (Docker status page)."""
import importlib.util
import sys
from datetime import date, datetime, timedelta

import httpx
import pytest

from conftest import DEPLOY_DIR, FE_DIR, REPO_ROOT

sys.path.insert(0, str(FE_DIR))
import event_store as es  # noqa: E402


class FakeApi:
    def __init__(self, token="tok", reply=None, mode="ok"):
        self.access_token, self.reply, self.mode, self.calls = token, reply or {"events": []}, mode, []

    def list_events(self, start, end, ok, failed, error, top_k=200):
        self.calls.append((start, end, top_k))
        {"ok": lambda: ok(None, self.reply), "refused": lambda: failed(None, {"detail": "nope"}),
         "down": lambda: error(None, "timed out")}[self.mode]()


BACKEND_EVENT = {"id": 7, "owner_id": 1, "title": "Toán rời rạc", "room": None, "kind": "CLASS", "source": "IMPORTED",
                 "start_time": "2026-11-09T09:00:00+07:00", "end_time": "2026-11-09T11:00:00+07:00",
                 "is_hard": True, "priority": 3, "is_important": True, "similarity_score": 1.0}


def test_ES01_logged_in_user_gets_backend_events_not_mock_data():
    s, api = es.EventStore(), FakeApi(reply={"events": [BACKEND_EVENT]})
    s.refresh(api, today=date(2026, 11, 9))
    assert [e["title"] for e in s.events] == ["Toán rời rạc"] and s.is_demo is False and s.last_error is None
    assert s.events[0]["room"] == "" and s.events[0]["is_important"] is True  # null room becomes "", flags kept


def test_ES02_request_covers_a_month_back_and_a_semester_ahead_and_asks_for_200():
    api = FakeApi()
    es.EventStore().refresh(api, today=date(2026, 11, 9))
    start, end, top_k = api.calls[0]
    assert datetime.fromisoformat(start).date() == date(2026, 11, 9) - timedelta(days=es.WINDOW_DAYS_BACK)
    assert datetime.fromisoformat(end).date() == date(2026, 11, 9) + timedelta(days=es.WINDOW_DAYS_AHEAD) and top_k == 200


def test_ES03_nobody_logged_in_means_demo_events_and_no_request():
    s, api = es.EventStore(), FakeApi(token=None)
    s.refresh(api)
    assert s.is_demo is True and s.events and api.calls == []


@pytest.mark.parametrize("mode,expect", [("refused", "server refused"), ("down", "cannot reach the server")])
def test_ES04_failures_keep_the_old_events_and_record_the_reason(mode, expect):
    s = es.EventStore()
    s.set_events([BACKEND_EVENT])
    s.refresh(FakeApi(mode=mode))
    assert expect in s.last_error and len(s.events) == 1  # the screen keeps what it had


def test_ES05_events_without_usable_times_are_dropped_and_the_rest_sorted():
    s = es.EventStore()
    late = {**BACKEND_EVENT, "id": 2, "start_time": "2026-11-12T09:00:00+07:00", "end_time": "2026-11-12T10:00:00+07:00"}
    s.set_events([late, {"title": "no time"}, {**BACKEND_EVENT, "start_time": "garbage"}, BACKEND_EVENT])
    assert [e["id"] for e in s.events] == [7, 2]


def test_ES06_by_date_groups_events_for_the_calendar_cells():
    s = es.EventStore()
    s.set_events([BACKEND_EVENT, {**BACKEND_EVENT, "id": 8, "title": "Thi AI"}])
    grouped = s.by_date()
    assert [e["id"] for e in grouped[date(2026, 11, 9)]] == [7, 8] and date(2026, 11, 10) not in grouped


def test_ES07_listeners_are_told_when_the_events_change():
    s, seen = es.EventStore(), []
    s.on_change(lambda: seen.append(len(s.events)))
    s.set_events([BACKEND_EVENT])
    s.use_demo()
    assert seen[0] == 1 and seen[1] > 1


def test_ES08_screens_read_the_store_and_never_the_mock_list_directly():
    for name in ("calendar_screen.py", "search_screen.py"):
        src = (FE_DIR / name).read_text(encoding="utf-8")
        assert "store.events" in src and "from mock_data import" not in src and "mock_events" not in src, name
    assert 'event.get("important"' not in (FE_DIR / "search_screen.py").read_text(encoding="utf-8")  # field is is_important


# ---------------- Docker status page --------------------------------------------------------------
@pytest.fixture()
def status_app(monkeypatch):
    spec = importlib.util.spec_from_file_location("status_server_under_test", DEPLOY_DIR / "frontend" / "status_server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ST01_status_page_shows_ok_when_the_backend_answers(status_app, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(status_app.httpx, "get", lambda url, timeout: httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", url)))
    html = TestClient(status_app.app).get("/").text
    assert html.count("OK") >= 2 and "DOWN" not in html and "Backend" in html


def test_ST02_status_page_shows_down_instead_of_crashing_when_the_backend_is_unreachable(status_app, monkeypatch):
    from fastapi.testclient import TestClient

    def boom(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(status_app.httpx, "get", boom)
    res = TestClient(status_app.app).get("/")
    assert res.status_code == 200 and "DOWN" in res.text and "ConnectError" in res.text


def test_ST03_status_server_has_its_own_health_endpoint(status_app):
    from fastapi.testclient import TestClient

    assert TestClient(status_app.app).get("/health").json() == {"status": "ok"}
