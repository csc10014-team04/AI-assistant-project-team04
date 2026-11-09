"""
FILE: notifier.py (duty P2-9: local notifications before flagged events)

The server never pushes notifications. After Accept / manual pick it returns, for each event, a reminder with
`fire_at` (ISO 8601, +07:00). This module turns those into local alarms on the phone and reports back:
  1. schedule(): arm a timer for fire_at and POST /reminders/{event_id}/scheduled   (audit trail P2-13)
  2. when the timer fires: show a notification and POST /reminders/{event_id}/delivered
  3. cancel(): called when an event is rescheduled or deleted, so the old alarm never fires.

Pure Python with injected dependencies (reporter, notify function, timer factory, clock), so it is unit-tested
without a phone. On a real phone the default notify function uses `plyer` when present. A timer only lives as long
as the app process; for alarms that must survive the app being killed use Android's AlarmManager
(`android_alarm()` below, requires pyjnius inside a python-for-android build and was NOT run on a device here).
"""
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
LATE_GRACE = timedelta(minutes=5)  # a reminder this much overdue is still shown (app was just opened)


def _default_timer(delay_seconds, callback):
    try:
        from kivy.clock import Clock  # inside the app: run on the UI thread

        return Clock.schedule_once(lambda dt: callback(), delay_seconds)
    except Exception:
        import threading

        t = threading.Timer(delay_seconds, callback)
        t.daemon = True
        t.start()
        return t


def _default_notify(title, message):
    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="University Life Assistant", timeout=10)
    except Exception:
        print(f"[REMINDER] {title}: {message}")  # desktop / no plyer: at least show it in the terminal


class ReminderScheduler:
    def __init__(self, reporter=None, notify=_default_notify, timer=_default_timer, now=None):
        """reporter needs report_reminder_scheduled(event_id) and report_reminder_delivered(event_id)."""
        self.reporter = reporter
        self.notify = notify
        self.timer = timer
        self.now = now or (lambda: datetime.now(VN_TZ))
        self._armed: dict[int, object] = {}

    def schedule(self, event_id: int, fire_at: str, title: str, offset_minutes: int = 30) -> bool:
        """arm an alarm; replaces an older alarm of the same event. False when it is too late to matter."""
        self.cancel(event_id)
        when = datetime.fromisoformat(fire_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=VN_TZ)
        delay = (when - self.now()).total_seconds()
        if delay < -LATE_GRACE.total_seconds():
            return False  # long gone; do not wake the user for the past
        self._armed[event_id] = self.timer(max(delay, 0), lambda: self._fire(event_id, title, offset_minutes))
        if self.reporter:
            self.reporter.report_reminder_scheduled(event_id)
        return True

    def schedule_from_confirm(self, response: dict) -> int:
        """feed the body of POST /proposals/{id}/confirm or /proposals/manual; returns how many alarms were armed."""
        titles = {e["event_id"]: e["title"] for e in response.get("events", [])}
        armed = 0
        for r in response.get("reminders", []):
            armed += self.schedule(r["event_id"], r["fire_at"], titles.get(r["event_id"], "Sự kiện"), r.get("offset_minutes", 30))
        return armed

    def cancel(self, event_id: int) -> bool:
        handle = self._armed.pop(event_id, None)
        if handle is None:
            return False
        if hasattr(handle, "cancel"):
            handle.cancel()
        return True

    def pending(self) -> list[int]:
        return sorted(self._armed)

    def _fire(self, event_id: int, title: str, offset_minutes: int) -> None:
        self._armed.pop(event_id, None)
        self.notify("Sắp đến giờ", f"{title} bắt đầu sau {offset_minutes} phút")
        if self.reporter:
            self.reporter.report_reminder_delivered(event_id)


def android_alarm(event_id: int, fire_epoch_ms: int, title: str) -> bool:
    """
    Android only: register an exact alarm with AlarmManager so it survives the app being closed. Needs a
    BroadcastReceiver declared in the build (see sourceCode/FE/buildozer.spec notes). Returns False off Android.
    NOT executed on a device in this repository's tests.
    """
    try:
        from jnius import autoclass  # type: ignore
    except Exception:
        return False
    Context = autoclass("android.content.Context")
    Intent = autoclass("android.content.Intent")
    PendingIntent = autoclass("android.app.PendingIntent")
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    activity = PythonActivity.mActivity
    intent = Intent(activity, activity.getClass())
    intent.putExtra("event_id", event_id)
    intent.putExtra("title", title)
    pending = PendingIntent.getActivity(activity, event_id, intent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)
    manager = activity.getSystemService(Context.ALARM_SERVICE)
    manager.setExactAndAllowWhileIdle(0, fire_epoch_ms, pending)  # 0 = RTC_WAKEUP
    return True
