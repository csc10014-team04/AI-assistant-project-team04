from kivy.core.window import Window
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager, NoTransition

# Import api để kiểm tra trạng thái token đăng nhập
from api_client import api
# Import các giao diện từ các file tương ứng
from calendar_screen import CalendarHomeScreen
from chat_screen import ChatAssistantScreen
from search_screen import SearchScreen
from auth_screen import AuthScreen  # Cấu hình thêm màn hình Đăng nhập


class AppScreenManager(ScreenManager):
    """Bộ điều phối chuyển đổi giữa các màn hình chính của ứng dụng."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Tắt hiệu ứng animation mặc định của Kivy để chuyển tab mượt hơn
        self.transition = NoTransition()

        # Khởi tạo và đưa các màn hình vào hệ thống quản lý
        self.add_widget(AuthScreen(name="auth_screen"))
        self.add_widget(CalendarHomeScreen(name="calendar_home"))
        self.add_widget(SearchScreen(name="search_home"))
        self.add_widget(ChatAssistantScreen(name="chat_home"))

        # Hiển thị màn hình xác thực khi khởi động
        self.current = "auth_screen"

    def handle_back_button(self) -> bool:
        """
        Xử lý sự kiện nút Back (trên Android) hoặc phím Esc (trên PC).

        Thứ tự ưu tiên:
        1. Nếu đang có ModalView/Popup mở trên Window -> đóng modal trên cùng trước.
        2. Nếu đang ở màn hình phụ (search_home, chat_home) -> quay về calendar_home.
        3. Nếu đang ở màn hình gốc (calendar_home, auth_screen) -> trả về False
           để MainApp xử lý xác nhận thoát ứng dụng.
        """
        # Bước 1: Duyệt các widget con trên Window (từ trên xuống dưới) để tìm ModalView đang mở
        for widget in list(Window.children):
            if isinstance(widget, ModalView):
                widget.dismiss()
                return True

        # Bước 2: Điều hướng lùi từ các màn hình chức năng phụ về màn hình Lịch chính
        if self.current in ("search_home", "chat_home"):
            self.current = "calendar_home"
            return True

        # Bước 3: Đang ở màn hình gốc, nhường quyền xử lý thoát app cho MainApp
        return False
