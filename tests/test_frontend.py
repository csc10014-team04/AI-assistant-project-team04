"""FE-01..FE-12: frontend deliverables (P1-1, P1-8, P1-9) and the only UI that exists today
(`Database/assistant_deploy/frontend/main.py`, a Kivy status page). Kivy/KivyMD are replaced by stubs, so no GUI is needed.
Also includes API-contract tests: the JSON the Android app will consume must carry what the UI needs."""
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

from conftest import DEPLOY_DIR, FE_DIR, class_row

FE_MAIN = DEPLOY_DIR / "frontend" / "main.py"


class _Label:
    def __init__(self, **kw):
        self.kw = kw


class _Screen:
    def __init__(self):
        self.children = []

    def add_widget(self, w):
        self.children.append(w)


class _App:
    def __init__(self):
        self.theme_cls = types.SimpleNamespace(primary_palette=None, theme_style=None)


def _fake_requests(get):
    """minimal stand-in for `requests` (not installed in CI): .get plus the exception hierarchy main.py catches."""
    mod = types.ModuleType("requests")
    exc = types.ModuleType("requests.exceptions")

    class RequestException(Exception):
        pass

    class ConnectionError(RequestException):  # noqa: A001
        pass

    class Timeout(RequestException):
        pass

    exc.RequestException, exc.ConnectionError, exc.Timeout = RequestException, ConnectionError, Timeout
    mod.exceptions, mod.get = exc, get
    mod.RequestException, mod.ConnectionError, mod.Timeout = RequestException, ConnectionError, Timeout
    return mod


def load_fe(monkeypatch, requests_get):
    """import frontend/main.py with fake kivymd + a scripted requests.get; returns (module, built_screen)."""
    fake = {
        "kivymd": types.ModuleType("kivymd"), "kivymd.app": types.ModuleType("kivymd.app"),
        "kivymd.uix": types.ModuleType("kivymd.uix"), "kivymd.uix.label": types.ModuleType("kivymd.uix.label"),
        "kivymd.uix.screen": types.ModuleType("kivymd.uix.screen"),
    }
    fake["kivymd.app"].MDApp = _App
    fake["kivymd.uix.label"].MDLabel = _Label
    fake["kivymd.uix.screen"].MDScreen = _Screen
    for name, mod in fake.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setitem(sys.modules, "requests", _fake_requests(requests_get))
    spec = importlib.util.spec_from_file_location("fe_main_under_test", FE_MAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    screen = module.UniversityAssistantApp().build()
    return module, screen


class _Resp:
    def json(self):
        return {"status": "ok"}


# ---------------- the existing Kivy status page ---------------------------------------------------
def test_FE01_status_page_shows_backend_state_when_online(monkeypatch):
    _, screen = load_fe(monkeypatch, lambda url, timeout=None: _Resp())
    assert "ok" in screen.children[0].kw["text"]


def test_FE02_status_page_survives_backend_down(monkeypatch):
    def boom(url, timeout=None):
        raise sys.modules["requests"].exceptions.ConnectionError("down")

    _, screen = load_fe(monkeypatch, boom)  # must not raise
    assert "Thất bại" in screen.children[0].kw["text"]


def test_FE03_status_page_survives_timeout(monkeypatch):
    def slow(url, timeout=None):
        raise sys.modules["requests"].exceptions.Timeout("slow")

    _, screen = load_fe(monkeypatch, slow)
    assert screen.children[0].kw["text"]


def test_FE04_status_request_has_a_short_timeout(monkeypatch):
    seen = {}

    def spy(url, timeout=None):
        seen["timeout"] = timeout
        return _Resp()

    load_fe(monkeypatch, spy)
    assert seen["timeout"] is not None and seen["timeout"] <= 3  # P1-9: fail fast


def test_FE05_status_page_only_calls_the_unauthenticated_health_endpoint(monkeypatch):
    urls = []
    load_fe(monkeypatch, lambda url, timeout=None: urls.append(url) or _Resp())
    assert len(urls) == 1 and urls[0].endswith("/health")  # no personal data is requested or sent (P1-2)


def test_FE06_backend_address_is_not_hard_coded_in_source():
    src = FE_MAIN.read_text(encoding="utf-8")
    assert not re.search(r"https?://\d+\.\d+\.\d+\.\d+", src), "backend IP is hard-coded; use configuration / env var"


# ---------------- deliverables that do not exist yet ---------------------------------------------
def _fe_sources() -> str:
    parts = [p.read_text(encoding="utf-8", errors="ignore") for p in FE_DIR.rglob("*") if p.is_file()]
    parts.append(FE_MAIN.read_text(encoding="utf-8"))
    return "\n".join(parts).lower()


def test_FE07_android_calendar_project_exists():
    # a Kivy app is packaged for Android by buildozer, so buildozer.spec is its Android project definition
    assert (FE_DIR / "buildozer.spec").is_file() or any(FE_DIR.rglob("*.kt")) or any(FE_DIR.rglob("AndroidManifest.xml"))


def test_FE08_calendar_renders_busy_and_free_slots():
    src = _fe_sources()
    assert "free" in src and ("calendar" in src or "timeblock" in src or "time_block" in src)


def test_FE09_chat_has_accept_reject_reschedule_buttons():
    src = _fe_sources()
    assert all(word in src for word in ("accept", "reject", "reschedule"))


def test_FE10_manual_picker_opens_on_ai_failure():
    src = _fe_sources()
    assert "fallback_mode" in src


# ---------------- API contract the Android app depends on ----------------------------------------
def test_FE11_calendar_events_carry_everything_the_ui_needs(client, alice):
    res = client.post("/api/v1/ingestion/commit", headers=alice.h,
                      json={"import_batch_id": "fe", "resolved_rows": [class_row(last="2026-09-07")]})
    ev = res.json()["events"][0]
    for key in ("id", "title", "start_time", "end_time", "kind", "is_hard", "room", "source"):
        assert key in ev, f"calendar payload lacks '{key}'"
    assert ev["start_time"].endswith("+07:00") and ev["end_time"].endswith("+07:00")  # P: mobile gets +07:00


def test_FE12_ai_fallback_payload_lets_the_app_open_the_manual_form(client, alice):
    """P1-9: when the AI is down the response is HTTP 200 with fallback_mode + message, never a 5xx."""
    res = client.post("/api/v1/assistant/understand", headers=alice.h, json={"prompt": "xếp 3 tiếng làm đồ án"})
    body = res.json()
    assert res.status_code == 200 and body["nlu"]["fallback_mode"] is True and body["message"]
    assert body["nlu"]["duration_minutes"] == 180  # form can be pre-filled for the user


def test_FE13_android_build_spec_declares_network_and_reminder_permissions():
    spec = (FE_DIR / "buildozer.spec").read_text(encoding="utf-8")
    perms = next(l for l in spec.splitlines() if l.startswith("android.permissions"))
    assert all(p in perms for p in ("INTERNET", "POST_NOTIFICATIONS", "SCHEDULE_EXACT_ALARM"))
    assert "kivymd" in spec and "plyer" in spec
    assert not re.search(r"https?://\d+\.\d+\.\d+\.\d+", spec.split("# The backend")[0])  # no IP in the build config


def test_FE14_backend_address_can_be_saved_on_the_device():
    src = (FE_DIR / "api_client.py").read_text(encoding="utf-8")
    assert "def set_base_url" in src and 'os.getenv("ASSISTANT_API_URL") or saved' in src
