from kivy.uix.screenmanager import ScreenManager, NoTransition



# Import các giao diện từ các file tương ứng của bạn
# (Lưu ý: Sửa lại tên file import cho khớp với cấu trúc thư mục thực tế của bạn)
from calendar_screen import CalendarHomeScreen
from chat_screen import ChatAssistantScreen
from search_screen import SearchScreen

class AppScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Tắt hiệu ứng animation mặc định của Kivy để chuyển tab mượt hơn, giống app thực tế
        self.transition = NoTransition()

        # Khởi tạo và đưa các màn hình vào hệ thống quản lý
        self.add_widget(CalendarHomeScreen(name="calendar_home"))
        self.add_widget(SearchScreen(name="search_home"))
        self.add_widget(ChatAssistantScreen(name="chat_home"))
        # Đặt màn hình mặc định khi vừa mở app lên
        self.current = "calendar_home"