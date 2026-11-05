from datetime import datetime
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.textinput import TextInput
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView


from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton
from kivy.uix.screenmanager import SlideTransition

# Import mock data từ file mock_data.py
from mock_data import mock_events

# ==============================================================================
# HẰNG SỐ MÀU SẮC (Dùng chung)
# ==============================================================================
WHITE_COLOR = [1, 1, 1, 1]
BLACK_COLOR = [0, 0, 0, 1]
GRAY_BG     = [0.95, 0.95, 0.95, 1]
GRAY_TEXT   = [0.5, 0.5, 0.5, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]

# ==============================================================================
# WIDGET DÙNG CHUNG (Tái sử dụng NavTab)
# ==============================================================================
class EventCard(MDBoxLayout):
    def __init__(self, event, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = 100
        self.padding = [15, 10, 15, 10]
        self.spacing = 5

        # Quy tắc phối màu theo 'kind'
        bg_color = self.get_color(event.get("kind", "EVENT"))

        # Vẽ viền và màu nền cho thẻ
        with self.canvas.before:
            Color(*bg_color)
            self.rect = RoundedRectangle(radius=[15])
        self.bind(pos=self.update_rect, size=self.update_rect)

        # Xử lý ngày giờ
        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event["end_time"])
        
        days_vn = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
        day_str = days_vn[start_dt.weekday()]
        date_str = start_dt.strftime("%d/%m/%Y")
        start_time_str = start_dt.strftime("%H:%M")
        end_time_str = end_dt.strftime("%H:%M")
        title = event["title"]

        # Phân loại giao diện thẻ dựa theo DEADLINE hay SỰ KIỆN THƯỜNG
        if event["kind"] == "DEADLINE":
            self.height = 70
            lbl_deadline = MDLabel(
                text=f"[b]Deadline:[/b] {title} - {end_time_str} ({date_str})",
                markup=True, halign='left', valign='middle', color=(1,1,1,1)
            )
            lbl_deadline.bind(size=lbl_deadline.setter('text_size'))
            self.add_widget(lbl_deadline)
        else:
            self.height = 110
            lbl_date = MDLabel(text=f"[b]{day_str} Ngày {date_str}:[/b]", markup=True, halign='left', color=(1,1,1,1))
            lbl_title = MDLabel(text=f"Công việc: {title}", halign='left', color=(1,1,1,1))
            lbl_time = MDLabel(text=f"Thời gian: {start_time_str} - {end_time_str}", halign='left', color=(1,1,1,1))
            
            for lbl in [lbl_date, lbl_title, lbl_time]:
                lbl.bind(size=lbl.setter('text_size'))
                self.add_widget(lbl)

    def get_color(self, kind):
        # Hệ màu Kivy (R, G, B, Alpha)
        colors = {
            "CLASS": (0.2, 0.5, 0.9, 1),    # Xanh dương
            "DEADLINE": (0.9, 0.5, 0.1, 1), # Cam
            "EVENT": (0.2, 0.7, 0.3, 1),    # Xanh lá
            "EXAM": (0.9, 0.2, 0.2, 1)      # Đỏ
        }
        return colors.get(kind, (0.5, 0.5, 0.5, 1))

    def update_rect(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size
        
class NavTab(ButtonBehavior, MDBoxLayout):
    def __init__(self, text, target_screen, is_active=False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = dp(40)
        self.padding = dp(2)
        self.target_screen = target_screen

        bg_color = WHITE_COLOR if is_active else BLUE_COLOR
        txt_color = BLUE_COLOR if is_active else WHITE_COLOR
        line_color = BLUE_COLOR

        with self.canvas.before:
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=[dp(4)])
            Color(*line_color)
            self.line = Line(rounded_rectangle=[0,0,0,0, dp(4)], width=1 if is_active else 0.001)

        self.bind(pos=self.update_canvas, size=self.update_canvas)

        self.add_widget(MDLabel(
            text=text, halign="center", valign="center",
            theme_text_color="Custom", text_color=txt_color,
            font_style="Label", role="large", bold=True
        ))

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.line.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(4)]

    def on_release(self):
        app = MDApp.get_running_app()
        if not app.root: return
        sm = app.root
        
        if sm.current != self.target_screen:
            tab_indices = {"calendar_home": 0, "search_home": 1, "chat_home": 2}
            current_idx = tab_indices.get(sm.current, 0)
            target_idx = tab_indices.get(self.target_screen, 0)
            
            if target_idx > current_idx:
                sm.transition = SlideTransition(direction='left')
            else:
                sm.transition = SlideTransition(direction='right')
                
            sm.current = self.target_screen

# ==============================================================================
# MÀN HÌNH CHÍNH (SEARCH SCREEN)
# ==============================================================================
class SearchScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = GRAY_BG
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        self.main_layout = MDBoxLayout(orientation='vertical')
        self.add_widget(self.main_layout)

        # 1. THANH TÌM KIẾM MÀU XANH TRÊN CÙNG
        top_search_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(70), 
            md_bg_color=BLUE_COLOR, padding=[dp(15), dp(15), dp(15), dp(15)], spacing=dp(10)
        )
        
        # Ô text input nền trắng bo góc
        input_bg = MDBoxLayout(
            orientation='horizontal', md_bg_color=WHITE_COLOR, 
            radius=[dp(20)], padding=[dp(15), 0, dp(10), 0]
        )
        
        self.txt_search = TextInput(
            hint_text="Nhập sự kiện, môn học, deadline...",
            background_color=[0, 0, 0, 0],
            foreground_color=BLACK_COLOR,
            multiline=False,
            font_size=dp(16),
            size_hint_y=None, height=dp(30),
            pos_hint={"center_y": .5}
        )
        input_bg.add_widget(self.txt_search)

        # Nút tìm kiếm: biểu tượng kính lúp màu trắng
        btn_search = MDIconButton(
            icon="magnify", 
            theme_icon_color="Custom", 
            icon_color=WHITE_COLOR, 
            pos_hint={"center_y": .5},
            on_release=self.perform_search
        )
        
        top_search_bar.add_widget(input_bg)
        top_search_bar.add_widget(btn_search)
        self.main_layout.add_widget(top_search_bar)

        # 2. KHU VỰC HIỂN THỊ KẾT QUẢ TÌM KIẾM
        self.results_scroll = ScrollView(size_hint=(1, 1))
        self.results_box = MDBoxLayout(
            orientation='vertical', size_hint_y=None, padding=dp(15), spacing=dp(10)
        )
        self.results_box.bind(minimum_height=self.results_box.setter('height'))

        # (Đã xóa các dòng add_widget bị lặp lại ở đây)
        self.results_scroll.add_widget(self.results_box)
        self.main_layout.add_widget(self.results_scroll)

        # 3. THANH MENU DƯỚI CÙNG (Tab Tìm kiếm được Active)
        nav_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10), md_bg_color=WHITE_COLOR
        )
        nav_bar.add_widget(NavTab(text="Lịch chính", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Tìm kiếm", target_screen="search_home", is_active=True))
        nav_bar.add_widget(NavTab(text="Trợ lý AI", target_screen="chat_home", is_active=False))
        self.main_layout.add_widget(nav_bar)

        # ==========================================
        # CHỈ GỌI VÀ BIND DUY NHẤT 1 LẦN Ở ĐÂY
        # ==========================================
        self.txt_search.bind(text=self.perform_search)
        self.perform_search() # Tải toàn bộ dữ liệu lần đầu


    def perform_search(self, instance=None, value=None):
        query = self.txt_search.text.strip().lower()
        self.results_box.clear_widgets()
        
        # Lọc danh sách theo từ khóa (Nếu ô tìm kiếm trống, sẽ hiển thị tất cả)
        filtered_events = [
            event for event in mock_events 
            if query in event["title"].lower()
        ]
        
        # Nếu không có kết quả nào
        if not filtered_events:
            self.results_box.add_widget(MDLabel(
                text="Không tìm thấy kết quả nào!", 
                halign="center", theme_text_color="Custom", text_color=[0.5, 0.5, 0.5, 1],
                font_style="Body", role="large", size_hint_y=None, height=dp(50)
            ))
            return
            
        # Render các thẻ kết quả
        for event in filtered_events:
            self.results_box.add_widget(EventCard(event))

# ==============================================================================
# CHẠY TEST ĐỘC LẬP
# ==============================================================================
if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return SearchScreen(name="search_home")
    TestApp().run()