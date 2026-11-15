"""
FILE: event_store.py (the calendar and search screens read their events from here)

Before this file the calendar and the search tab displayed `mock_data.mock_events`, i.e. made-up events, even for a
logged-in student. Now:
  * logged in  -> events come from the backend (GET /api/v1/search/events) and are kept in `store.events`
  * not logged in (demo) -> the mock events are shown, and `store.is_demo` is True so the UI can say so
Pure Python (no Kivy), so it is unit-tested without a GUI.

Every event is a dict with the keys the screens already use:
  id, title, room, kind, start_time, end_time (ISO 8601 text), is_hard, is_important
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

WINDOW_DAYS_BACK = 31   # how far back a refresh looks
WINDOW_DAYS_AHEAD = 150  # about one semester ahead
MAX_EVENTS = 200        # the backend allows at most 200 per request (top_k)


def normalize(raw: dict) -> dict | None:
    """map a backend event (or a mock event) to the shape the screens use; None when it has no usable time."""
    try:
        datetime.fromisoformat(raw["start_time"])
        datetime.fromisoformat(raw["end_time"])
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "id": raw.get("id"),
        "title": raw.get("title") or "(không tên)",
        "room": raw.get("room") or "",
        "kind": raw.get("kind") or "EVENT",
        "start_time": raw["start_time"],
        "end_time": raw["end_time"],
        "is_hard": bool(raw.get("is_hard", False)),
        "is_important": bool(raw.get("is_important", raw.get("important", False))),
    }


class EventStore:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.is_demo = True
        self.last_error: str | None = None
        self._listeners: list = []

    # ---- content ----------------------------------------------------------------------------
    def set_events(self, raw_events: list[dict], demo: bool = False) -> None:
        cleaned = [e for e in (normalize(r) for r in raw_events) if e]
        self.events = sorted(cleaned, key=lambda e: e["start_time"])
        self.is_demo = demo
        for listener in list(self._listeners):
            listener()

    def use_demo(self) -> None:
        from mock_data import mock_events

        self.set_events(list(mock_events), demo=True)

    def by_date(self) -> dict[date, list[dict]]:
        """events grouped by the local date they start on (O(1) lookup per calendar cell)."""
        grouped: dict[date, list[dict]] = defaultdict(list)
        for e in self.events:
            grouped[datetime.fromisoformat(e["start_time"]).date()].append(e)
        return grouped

    def on_change(self, callback) -> None:
        """call `callback()` after every change of the event list (the screens re-draw there)."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    # ---- loading ----------------------------------------------------------------------------
    def refresh(self, api, today: date | None = None, on_done=None) -> None:
        """
        ask the backend for the events around today; fall back to the demo events when nobody is logged in.
        `api` is the APIClient (needs .access_token and .list_events); callbacks run on the UI thread.
        """
        if not getattr(api, "access_token", None):
            self.use_demo()
            if on_done:
                on_done()
            return
        today = today or date.today()
        start = datetime.combine(today - timedelta(days=WINDOW_DAYS_BACK), datetime.min.time())
        end = datetime.combine(today + timedelta(days=WINDOW_DAYS_AHEAD), datetime.max.time().replace(microsecond=0))

        def ok(_req, result):
            body = result if isinstance(result, dict) else {}
            self.last_error = None
            self.set_events(body.get("events", []), demo=False)
            if on_done:
                on_done()

        def failed(_req, result):
            detail = result.get("detail") if isinstance(result, dict) else None
            self.last_error = f"server refused the request: {detail or 'unknown error'}"
            if on_done:
                on_done()

        def error(_req, err):
            self.last_error = f"cannot reach the server: {err}"
            if on_done:
                on_done()

        api.list_events(start.isoformat(), end.isoformat(), ok, failed, error, top_k=MAX_EVENTS)


store = EventStore()
store.use_demo()  # until someone logs in
