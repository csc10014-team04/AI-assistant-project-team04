from kivy.uix.screenmanager import ScreenManager, NoTransition

# Import api để kiểm tra trạng thái token đăng nhập
from api_client import api
# Import các giao diện từ các file tương ứng
from calendar_screen import CalendarHomeScreen
from chat_screen import ChatAssistantScreen
from search_screen import SearchScreen
from auth_screen import AuthScreen  # Cấu hình thêm màn hình Đăng nhập

class AppScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Tắt hiệu ứng animation mặc định của Kivy để chuyển tab mượt hơn
        self.transition = NoTransition()

        # Khởi tạo và đưa các màn hình vào hệ thống quản lý
        self.add_widget(AuthScreen(name="auth_screen"))
        self.add_widget(CalendarHomeScreen(name="calendar_home"))
        self.add_widget(SearchScreen(name="search_home"))
        self.add_widget(ChatAssistantScreen(name="chat_home"))
        
            # Hiển thị màn hình xác thực
        self.current = "auth_screen"