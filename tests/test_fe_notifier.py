"""NT-01..NT-08: local reminder scheduling on the phone (P2-9), with fake timers and a fake notifier."""
import sys
from datetime import datetime, timedelta, timezone

from conftest import FE_DIR

sys.path.insert(0, str(FE_DIR))
import notifier  # noqa: E402

VN = timezone(timedelta(hours=7))
NOW = datetime(2026, 11, 9, 8, 0, tzinfo=VN)


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay, self.callback, self.cancelled = delay, callback, False

    def cancel(self):
        self.cancelled = True


class Harness:
    def __init__(self):
        self.timers, self.shown, self.sched, self.deliv = [], [], [], []
        self.s = notifier.ReminderScheduler(reporter=self, notify=lambda t, m: self.shown.append((t, m)),
                                            timer=self._timer, now=lambda: NOW)

    def _timer(self, delay, cb):
        t = FakeTimer(delay, cb)
        self.timers.append(t)
        return t

    def report_reminder_scheduled(self, event_id):
        self.sched.append(event_id)

    def report_reminder_delivered(self, event_id):
        self.deliv.append(event_id)


def iso(minutes_from_now):
    return (NOW + timedelta(minutes=minutes_from_now)).isoformat()


def test_NT01_future_reminder_is_armed_with_the_right_delay_and_audited():
    h = Harness()
    assert h.s.schedule(7, iso(90), "Làm đồ án") is True
    assert h.timers[0].delay == 90 * 60 and h.s.pending() == [7] and h.sched == [7]


def test_NT02_firing_shows_a_notification_and_reports_delivery():
    h = Harness()
    h.s.schedule(7, iso(10), "Làm đồ án", offset_minutes=30)
    h.timers[0].callback()
    assert h.shown == [("Sắp đến giờ", "Làm đồ án bắt đầu sau 30 phút")] and h.deliv == [7] and h.s.pending() == []


def test_NT03_rescheduling_cancels_the_old_alarm():
    h = Harness()
    h.s.schedule(7, iso(60), "A")
    h.s.schedule(7, iso(120), "A")
    assert h.timers[0].cancelled is True and h.timers[1].cancelled is False and h.s.pending() == [7]


def test_NT04_cancel_removes_the_alarm_and_unknown_cancel_is_harmless():
    h = Harness()
    h.s.schedule(7, iso(60), "A")
    assert h.s.cancel(7) is True and h.timers[0].cancelled and h.s.cancel(7) is False


def test_NT05_recently_overdue_fires_now_but_long_past_is_skipped():
    h = Harness()
    assert h.s.schedule(1, iso(-2), "late") is True and h.timers[0].delay == 0  # app opened 2 minutes late
    assert h.s.schedule(2, iso(-60), "ancient") is False and h.s.pending() == [1]


def test_NT06_confirm_response_arms_one_alarm_per_block_with_event_titles():
    h = Harness()
    body = {"events": [{"event_id": 1, "title": "Học bài"}, {"event_id": 2, "title": "Học bài"}],
            "reminders": [{"event_id": 1, "offset_minutes": 30, "fire_at": iso(60)},
                          {"event_id": 2, "offset_minutes": 15, "fire_at": iso(300)}]}
    assert h.s.schedule_from_confirm(body) == 2 and h.s.pending() == [1, 2] and h.sched == [1, 2]
    h.timers[1].callback()
    assert h.shown[0][1] == "Học bài bắt đầu sau 15 phút"


def test_NT07_naive_fire_at_is_treated_as_vietnam_time():
    h = Harness()
    h.s.schedule(3, (NOW + timedelta(minutes=30)).replace(tzinfo=None).isoformat(), "x")
    assert h.timers[0].delay == 30 * 60


def test_NT08_android_alarm_is_a_safe_noop_off_device_and_api_reports_use_device_time():
    assert notifier.android_alarm(1, 0, "x") is False
    src = (FE_DIR / "api_client.py").read_text(encoding="utf-8")
    assert "report_reminder_scheduled" in src and "_device_time" in src  # body is required by the server
