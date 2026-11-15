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
from kivy.uix.modalview import ModalView
from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDButton, MDButtonText
from kivy.clock import Clock

VN_TZ = timezone(timedelta(hours=7))
LATE_GRACE = timedelta(minutes=5)  # a reminder this much overdue is still shown (app was just opened)

# Cấu hình thời gian báo lại (Snooze interval) mặc định là 5 phút
DEFAULT_SNOOZE_MINUTES = 5
current_snooze_minutes = DEFAULT_SNOOZE_MINUTES


def get_snooze_interval() -> int:
    """Lấy số phút báo lại hiện tại (mặc định 5 phút hoặc cấu hình từ Sidebar)."""
    return current_snooze_minutes


def set_snooze_interval(minutes: int) -> None:
    """Cập nhật số phút báo lại từ Sidebar (chỉ nhận số nguyên dương >= 1)."""
    global current_snooze_minutes
    current_snooze_minutes = max(1, int(minutes))


class DeviceNotificationModal(ModalView):
    """
    Thông báo từ hệ thống của thiết bị hiện ra khi thời gian của sự kiện quan trọng đến.
    Nội dung: "({Địa điểm}) - {tên sự kiện}: Lúc {Start_time}"
    Hai nút:
      - "Xác nhận": ngừng thông báo, đã nhận được thông báo.
      - "Báo lại": báo lại sau số phút cấu hình (mặc định 5 phút).
    Tự động: Nếu không bấm trong vòng 1 phút (60s), mặc định kích hoạt nút "Báo lại".
    """
    def __init__(self, event_id, title, room="", start_time_str="", offset_minutes=30, on_confirm=None, on_snooze=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.88, None)
        self.height = dp(240)
        self.auto_dismiss = False

        self.event_id = event_id
        self.title = title
        self.room = room
        self.start_time_str = start_time_str
        self.offset_minutes = offset_minutes
        self.on_confirm = on_confirm
        self.on_snooze = on_snooze

        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(18),
            spacing=dp(10),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(14)]
        )

        # Tiêu đề thông báo
        layout.add_widget(MDLabel(
            text="THÔNG BÁO SỰ KIỆN",
            bold=True,
            font_style="Title",
            role="medium",
            theme_text_color="Primary",
            halign="center",
            adaptive_height=True
        ))

        # Định dạng nội dung: "({Địa điểm}) - {tên sự kiện}: Lúc {Start_time}"
        room_clean = str(room).strip() if (room and str(room).strip() and str(room).lower() not in ("none", "null")) else ""
        if room_clean:
            msg_text = f"({room_clean}) - {title}: Lúc {start_time_str}"
        else:
            msg_text = f"{title}: Lúc {start_time_str}"

        self.lbl_msg = MDLabel(
            text=msg_text,
            font_style="Body",
            role="large",
            bold=True,
            theme_text_color="Primary",
            halign="center",
            adaptive_height=True
        )
        layout.add_widget(self.lbl_msg)

        # Nhãn đếm ngược tự động báo lại sau 60 giây
        self.remaining_seconds = 60
        self.lbl_timer = MDLabel(
            text=f"Tự động báo lại sau: {self.remaining_seconds}s",
            font_style="Label",
            role="small",
            theme_text_color="Hint",
            halign="center",
            adaptive_height=True
        )
        layout.add_widget(self.lbl_timer)

        # 2 nút hệ thống: Xác nhận và Báo lại
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(42))
        btn_confirm = MDButton(
            MDButtonText(text="Xác nhận", text_color=[1, 1, 1, 1]),
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1],
            size_hint_x=0.5,
            on_release=self.confirm_action
        )
        btn_snooze = MDButton(
            MDButtonText(text="Báo lại"),
            style="outlined",
            size_hint_x=0.5,
            on_release=self.snooze_action
        )
        btn_box.add_widget(btn_confirm)
        btn_box.add_widget(btn_snooze)
        layout.add_widget(btn_box)

        self.add_widget(layout)

        # Bộ đếm 1 giây cập nhật nhãn đếm ngược; nếu quá 60s tự động bấm Báo lại
        self._countdown_event = Clock.schedule_interval(self._tick, 1.0)

    def _tick(self, dt):
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            if self._countdown_event:
                self._countdown_event.cancel()
                self._countdown_event = None
            self.snooze_action(None)
        else:
            self.lbl_timer.text = f"Tự động báo lại sau: {self.remaining_seconds}s"

    def confirm_action(self, instance=None):
        if self._countdown_event:
            self._countdown_event.cancel()
            self._countdown_event = None
        self.dismiss()
        if self.on_confirm:
            self.on_confirm(self.event_id)

    def snooze_action(self, instance=None):
        if self._countdown_event:
            self._countdown_event.cancel()
            self._countdown_event = None
        self.dismiss()
        if self.on_snooze:
            self.on_snooze(self.event_id, self.title, self.room, self.start_time_str)


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

    def schedule(self, event_id: int, fire_at: str, title: str, room: str = "", start_time_str: str = "", offset_minutes: int = 30) -> bool:
        """arm an alarm; replaces an older alarm of the same event. False when it is too late to matter."""
        self.cancel(event_id)
        when = datetime.fromisoformat(fire_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=VN_TZ)
        delay = (when - self.now()).total_seconds()
        if delay < -LATE_GRACE.total_seconds():
            return False  # long gone; do not wake the user for the past
        self._armed[event_id] = self.timer(max(delay, 0), lambda: self._fire(event_id, title, room, start_time_str, offset_minutes))
        if self.reporter:
            try:
                self.reporter.report_reminder_scheduled(event_id)
            except Exception:
                pass
        return True

    def schedule_snooze(self, event_id: int, title: str, room: str = "", start_time_str: str = "", snooze_minutes: int | None = None) -> None:
        """Lên lịch báo lại sau số phút cấu hình."""
        mins = snooze_minutes if snooze_minutes is not None else get_snooze_interval()
        delay_seconds = mins * 60
        self.cancel(event_id)
        self._armed[event_id] = self.timer(delay_seconds, lambda: self._fire(event_id, title, room, start_time_str, offset_minutes=mins))

    def schedule_from_confirm(self, response: dict) -> int:
        """feed the body of POST /proposals/{id}/confirm or /proposals/manual; returns how many alarms were armed."""
        titles = {e["event_id"]: e["title"] for e in response.get("events", [])}
        armed = 0
        for r in response.get("reminders", []):
            armed += self.schedule(r["event_id"], r["fire_at"], titles.get(r["event_id"], "Sự kiện"), offset_minutes=r.get("offset_minutes", 30))
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

    def _fire(self, event_id: int, title: str, room: str, start_time_str: str, offset_minutes: int) -> None:
        self._armed.pop(event_id, None)
        room_clean = str(room).strip() if (room and str(room).strip() and str(room).lower() not in ("none", "null")) else ""
        if room_clean:
            msg_text = f"({room_clean}) - {title}: Lúc {start_time_str}"
        else:
            msg_text = f"{title}: Lúc {start_time_str}"

        # Báo thông báo hệ thống qua plyer
        self.notify("Sắp đến giờ", msg_text)

        # Mở popup thông báo trực quan trên giao diện ứng dụng (với 2 nút Xác nhận và Báo lại)
        try:
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: DeviceNotificationModal(
                event_id=event_id,
                title=title,
                room=room,
                start_time_str=start_time_str,
                offset_minutes=offset_minutes,
                on_confirm=self._on_confirmed,
                on_snooze=self._on_snoozed,
            ).open(), 0)
        except Exception:
            pass

    def _on_confirmed(self, event_id: int) -> None:
        """Người dùng bấm Xác nhận: báo về BE là đã delivered."""
        if self.reporter:
            try:
                self.reporter.report_reminder_delivered(event_id)
            except Exception:
                pass

    def _on_snoozed(self, event_id: int, title: str, room: str, start_time_str: str) -> None:
        """Người dùng bấm Báo lại (hoặc hết 1 phút tự động): lên lịch báo lại."""
        self.schedule_snooze(event_id, title, room, start_time_str)


# Khởi tạo scheduler dùng chung
reminder_scheduler = ReminderScheduler()

# Tự động liên kết APIClient làm reporter nếu có sẵn
try:
    from api_client import api
    reminder_scheduler.reporter = api
except Exception:
    pass


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
