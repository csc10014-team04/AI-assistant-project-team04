from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import requests

class UniversityAssistantApp(MDApp):
    def build(self):
        # Thiết lập các tham số theme Material Design
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        
        screen = MDScreen()
        
        try:
            # Hướng tới backend đang mở trên cổng localhost 8080 của máy chủ
            response = requests.get("http://127.0.0.1:8080/health", timeout=2.0)
            status_text = f"Trạng thái Backend: {response.json().get('status')}"
        except requests.exceptions.RequestException:
            status_text = "Kết nối Backend Thất bại. Đảm bảo Docker daemon đang hoạt động."
        
        label = MDLabel(
            text=status_text,
            halign="center",
            theme_text_color="Primary"
        )
        
        screen.add_widget(label)
        return screen

if __name__ == '__main__':
    UniversityAssistantApp().run()