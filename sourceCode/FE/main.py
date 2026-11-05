from kivymd.app import MDApp
from kivy.core.window import Window
from screen_manager import AppScreenManager

class MainApp(MDApp):
    def build(self):
        # Cấu hình theme tổng thể cho app
        self.theme_cls.theme_style = "Light"
        
        # Load hệ thống quản lý màn hình đã tạo
        return AppScreenManager()

if __name__ == "__main__":
    # Giả lập kích thước màn hình điện thoại khi chạy trên máy tính
    Window.size = (360, 640)
    MainApp().run()