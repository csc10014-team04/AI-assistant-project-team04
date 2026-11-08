from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
import os

import requests

# backend address comes from the environment (inside Docker the service name resolves); never hard-code an IP
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080").rstrip("/")

class UniversityAssistantApp(MDApp):
    def build(self):
        # Thiết lập các tham số theme Material Design
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        
        screen = MDScreen()
        
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=2.0)
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