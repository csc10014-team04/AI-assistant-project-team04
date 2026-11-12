"""
FILE: chat_history_sidebar.py
"""
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.animation import Animation
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, RoundedRectangle
from kivy.utils import platform  # Thêm import platform để nhận diện thiết bị

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton

WHITE_COLOR = [1, 1, 1, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]

class HistoryItem(ButtonBehavior, MDBoxLayout):
    """Nút bấm hiển thị 1 đoạn chat trong lịch sử"""
    def __init__(self, text, index, callback, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = dp(60)
        self.padding = dp(10)
        
        self.index = index
        self.callback = callback
        
        with self.canvas.before:
            Color(0.95, 0.95, 0.95, 1)
            self.bg_rect = RoundedRectangle(radius=[dp(8)])
        self.bind(pos=self.update_canvas, size=self.update_canvas)
        
        self.add_widget(MDLabel(
            text=text, 
            theme_text_color="Custom", text_color=[0, 0, 0, 1],
            shorten=True, shorten_from="right", font_style="Body", role="medium"
        ))

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def on_release(self):
        if self.callback:
            self.callback(self.index)


class ChatHistorySideBar(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._is_animating_close = False
        self.bind(on_pre_dismiss=self.animate_close)
        
        self.background = "" 
        self.background_color = [0, 0, 0, 0.5]
        self.size_hint = (1, 1)
        
        # --- LOGIC ĐIỀU CHỈNH KÍCH THƯỚC RESPONSIVE ---
        is_mobile_mode = (platform in ['android', 'ios']) or (Window.width < dp(800))
        self.menu_width = Window.width * 0.8 if is_mobile_mode else Window.width * 0.25

        # Khung chứa chính trượt từ bên phải
        self.main_container = MDBoxLayout(
            orientation='vertical',
            md_bg_color=WHITE_COLOR,
            size_hint=(None, 1),
            width=self.menu_width
        )
        
        # Nền cong góc bên trái
        with self.main_container.canvas.before:
            Color(*WHITE_COLOR)
            self.bg_rect = RoundedRectangle(radius=[dp(15), 0, 0, dp(15)])
        self.main_container.bind(pos=self.update_canvas, size=self.update_canvas)
        
        # --- NÚT ĐÓNG & TIÊU ĐỀ ---
        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), padding=dp(10))
        btn_close = MDIconButton(icon="close", pos_hint={"center_y": 0.5})
        btn_close.bind(on_release=lambda x: self.dismiss())
        
        header.add_widget(btn_close)
        header.add_widget(MDLabel(
            text="Lịch sử", 

            bold=True, 
            halign="center", 
            size_hint_y=None, 
            height=dp(50)
        ))
        self.main_container.add_widget(header)

        # --- DANH SÁCH LỊCH SỬ ---
        self.scroll = ScrollView(size_hint=(1, 1))
        self.history_list = MDBoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5), padding=dp(10))
        self.history_list.bind(minimum_height=self.history_list.setter('height'))
        self.scroll.add_widget(self.history_list)
        
        self.main_container.add_widget(self.scroll)
        self.add_widget(self.main_container)
        
        self.callback = None

    def update_canvas(self, *args):
        self.bg_rect.pos = self.main_container.pos
        self.bg_rect.size = self.main_container.size

    def load_history(self, sessions, callback=None):
        self.history_list.clear_widgets()
        self.callback = callback
        
        for i, session in enumerate(sessions):
            title = session.get("title", f"Trò chuyện {i+1}") if isinstance(session, dict) else str(session)
            item = HistoryItem(text=title, index=i, callback=self.on_item_select)
            self.history_list.add_widget(item)

    def on_item_select(self, index):
        if self.callback:
            self.callback(index)
        self.dismiss()

    def open(self, *args, **kwargs):
        self._is_animating_close = False
        
        # Khởi tạo vị trí nằm ở sát mép phải, ẩn đi ngoài màn hình
        self.main_container.x = Window.width
        super().open(*args, **kwargs)
        
        # Anim trượt sang trái vào trong khung hình, phụ thuộc tự động vào self.menu_width
        anim = Animation(x=Window.width - self.menu_width, duration=0.25, t='out_quad')
        anim.start(self.main_container)

    def animate_close(self, instance):
        if self._is_animating_close:
            return False 
            
        self._is_animating_close = True
        
        # Trượt ngược ra lại phía phải
        anim = Animation(x=Window.width, duration=0.2, t='in_quad')
        anim.bind(on_complete=lambda *args: self.dismiss())
        anim.start(self.main_container)
        
        return True