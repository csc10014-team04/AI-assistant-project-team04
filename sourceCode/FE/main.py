import time

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.label import Label
from kivy.utils import platform
from kivymd.app import MDApp

from screen_manager import AppScreenManager


class MainApp(MDApp):
    """Lớp ứng dụng chính, hỗ trợ chạy song song trên cả PC và Android."""

    def build(self):
        # Cấu hình theme tổng thể cho app
        self.theme_cls.theme_style = "Light"

        # Lưu mốc thời gian nhấn Back gần nhất để hỗ trợ "nhấn đúp để thoát"
        self._last_back_press: float = 0.0
        self._exit_toast: Label | None = None

        # Cấu hình hành vi bàn phím ảo riêng cho Android để không che ô nhập liệu
        # (AuthScreen, ChatAssistantScreen)
        if platform == "android":
            Window.softinput_mode = "below_target"

        # Khởi tạo hệ thống quản lý màn hình
        self.sm = AppScreenManager()

        # Lắng nghe sự kiện bàn phím để bắt nút Back trên Android (keycode 27)
        # và phím Esc trên PC phục vụ kiểm thử điều hướng
        Window.bind(on_keyboard=self._on_keyboard)

        return self.sm

    def _on_keyboard(self, window, key: int, scancode: int, codepoint: str, modifier: list) -> bool:
        """
        Bộ lắng nghe phím hệ thống trên Window.
        - Keycode 27 tương ứng nút Back vật lý/cử chỉ trên Android và phím Esc trên PC.
        - Trả về True để chặn hành vi thoát ứng dụng mặc định ngay lập tức của Kivy.
        """
        if key != 27:
            return False

        # Ưu tiên đóng Modal hoặc lùi màn hình thông qua AppScreenManager
        if hasattr(self, "sm") and self.sm.handle_back_button():
            return True

        # Nếu đang ở màn hình gốc (calendar_home hoặc auth_screen): yêu cầu nhấn đúp trong 2 giây để thoát
        now = time.monotonic()
        if now - self._last_back_press < 2.0:
            self._hide_exit_toast()
            self.stop()
            return True

        self._last_back_press = now
        self._show_exit_toast()
        return True

    def _show_exit_toast(self) -> None:
        """Hiển thị thông báo nhỏ ở đáy màn hình nhắc người dùng nhấn Back lần nữa để thoát."""
        self._hide_exit_toast()

        toast = Label(
            text="Nhấn Back thêm lần nữa để thoát",
            size_hint=(None, None),
            size=(dp(240), dp(40)),
            pos_hint={"center_x": 0.5, "y": 0.06},
            color=(1, 1, 1, 1),
            font_size="13sp",
            halign="center",
            valign="middle",
        )

        # Vẽ nền bo góc tối màu cho toast bằng canvas.before (100% Python thuần)
        with toast.canvas.before:
            Color(0.15, 0.15, 0.15, 0.9)
            bg_rect = RoundedRectangle(pos=toast.pos, size=toast.size, radius=[dp(20)])

        toast.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val),
        )

        self._exit_toast = toast
        Window.add_widget(toast)
        Clock.schedule_once(lambda dt: self._hide_exit_toast(), 2.0)

    def _hide_exit_toast(self) -> None:
        """Gỡ thông báo nhắc thoát khỏi Window nếu đang hiển thị."""
        if self._exit_toast is not None and self._exit_toast.parent is not None:
            Window.remove_widget(self._exit_toast)
        self._exit_toast = None


if __name__ == "__main__":
    # Chỉ ép kích thước giả lập điện thoại (360x640) khi chạy trên máy tính (PC)
    # Trên Android, ứng dụng sẽ tự động dùng toàn bộ kích thước màn hình thiết bị thật
    if platform in ("win", "linux", "macosx"):
        Window.size = (360, 640)

    MainApp().run()
