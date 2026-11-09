from datetime import datetime
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.textinput import TextInput
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.modalview import ModalView

# IMPORT THUẦN KIVY ĐỂ CHỐNG CRASH CHO POPUP
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton
from kivy.uix.screenmanager import SlideTransition

# Import mock data từ file mock_data.py
from api_client import api
from event_store import store

# ==============================================================================
# HẰNG SỐ MÀU SẮC
# ==============================================================================
WHITE_COLOR = [1, 1, 1, 1]
BLACK_COLOR = [0, 0, 0, 1]
GRAY_BG     = [0.95, 0.95, 0.95, 1]
GRAY_TEXT   = [0.5, 0.5, 0.5, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]

# ==============================================================================
# WIDGET DÙNG CHUNG (EventCard, NavTab)
# ==============================================================================
class EventCard(MDBoxLayout):
    def __init__(self, event, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.padding = [dp(15), dp(10), dp(15), dp(10)]
        self.spacing = dp(5)
        self.bind(minimum_height=self.setter('height'))

        bg_color = self.get_color(event.get("kind", "EVENT"))

        with self.canvas.before:
            Color(0, 0, 0, 0.25)
            self.shadow = RoundedRectangle(radius=[dp(15)])
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=[dp(15)])
            Color(*BLACK_COLOR)
            self.border_line = Line(rounded_rectangle=[0, 0, 0, 0, dp(15)], width=0.8)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)

        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event["end_time"])
        
        days_vn = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
        day_str = days_vn[start_dt.weekday()]
        date_str = start_dt.strftime("%d/%m/%Y")
        start_time_str = start_dt.strftime("%H:%M")
        end_time_str = end_dt.strftime("%H:%M")
        title = event["title"]

        is_important = " ⭐" if event.get("is_important", False) else ""

        if event["kind"] == "DEADLINE":
            lbl_deadline = MDLabel(
                text=f"[b]Deadline:[/b] {title}{is_important} - {end_time_str} ({date_str})",
                markup=True, halign='left', valign='top', color=(1,1,1,1), size_hint_y=None
            )
            lbl_deadline.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
            lbl_deadline.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1]))
            self.add_widget(lbl_deadline)
        else:
            lbl_date = MDLabel(text=f"[b]{day_str} Ngày {date_str}:[/b]", markup=True, halign='left', color=(1,1,1,1), size_hint_y=None)
            lbl_title = MDLabel(text=f"Công việc: {title}{is_important}", halign='left', color=(1,1,1,1), size_hint_y=None)
            lbl_time = MDLabel(text=f"Thời gian: {start_time_str} - {end_time_str}", halign='left', color=(1,1,1,1), size_hint_y=None)
            
            for lbl in [lbl_date, lbl_title, lbl_time]:
                lbl.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
                lbl.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1]))
                self.add_widget(lbl)

    def get_color(self, kind):
        colors = {
            "CLASS": (0.2, 0.5, 0.9, 1),
            "DEADLINE": (0.9, 0.5, 0.1, 1),
            "EVENT": (0.2, 0.7, 0.3, 1),
            "TASK": (0.6, 0.2, 1.0, 1),
            "EXAM": (0.9, 0.2, 0.2, 1)
        }
        return colors.get(kind, (0.5, 0.5, 0.5, 1))

    def update_canvas(self, *args):
        self.shadow.pos = [self.x + dp(2), self.y - dp(3)]
        self.shadow.size = self.size
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.border_line.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(15)]

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
        # Nếu active: viền xanh dương, nếu chưa active: viền đen
        border_color = BLUE_COLOR if is_active else BLACK_COLOR

        with self.canvas.before:
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=[dp(4)])
            Color(*border_color)
            # Độ dày viền luôn là 1dp cho cả nút active và chưa active
            self.line = Line(rounded_rectangle=[0, 0, 0, 0, dp(4)], width=1.15)

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
        if not app or not app.root: return
        sm = app.root
        
        if sm.current != self.target_screen:
            tab_indices = {"calendar_home": 0, "search_home": 1, "chat_home": 2}
            current_idx = tab_indices.get(sm.current, 0)
            target_idx = tab_indices.get(self.target_screen, 0)
            
            sm.transition = SlideTransition(direction='left' if target_idx > current_idx else 'right')
            sm.current = self.target_screen
# ==============================================================================
# MÀN HÌNH CHÍNH (SEARCH SCREEN)
# ==============================================================================
class SearchScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = GRAY_BG
        self.search_event = None
        
        self.active_filters = {
            "CLASS": True, "EXAM": True, "EVENT": True, 
            "TASK": True, "DEADLINE": True
        }
        self.filter_important_only = False
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        self.main_layout = MDBoxLayout(orientation='vertical')
        self.add_widget(self.main_layout)

        top_search_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(70), 
            md_bg_color=BLUE_COLOR, padding=[dp(15), dp(15), dp(15), dp(15)], spacing=dp(10)
        )
        
        input_bg = MDBoxLayout(
            orientation='horizontal', md_bg_color=WHITE_COLOR, 
            radius=[dp(20)], padding=[dp(15), 0, dp(10), 0]
        )
        with input_bg.canvas.after:
            Color(*BLACK_COLOR)
            input_bg.border_line = Line(rounded_rectangle=[0, 0, 0, 0, dp(20)], width=0.8)
            
        def update_input_border(*args):
            input_bg.border_line.rounded_rectangle = [input_bg.x, input_bg.y, input_bg.width, input_bg.height, dp(20)]
        input_bg.bind(pos=update_input_border, size=update_input_border)
        
        self.txt_search = TextInput(
            hint_text="Nhập tên, ngày (vd: 26/10)...", background_color=[0, 0, 0, 0],
            foreground_color=BLACK_COLOR, multiline=False, font_size=dp(15), 
            size_hint_y=None, height=dp(30), pos_hint={"center_y": .5}
        )
        input_bg.add_widget(self.txt_search)

        btn_search = MDIconButton(
            icon="magnify", theme_icon_color="Custom", icon_color=WHITE_COLOR, 
            pos_hint={"center_y": .5}, on_release=self.perform_search
        )
        btn_filter = MDIconButton(
            icon="filter", theme_icon_color="Custom", icon_color=WHITE_COLOR, 
            pos_hint={"center_y": .5}, on_release=self.open_filter_modal
        )
        
        top_search_bar.add_widget(input_bg)
        top_search_bar.add_widget(btn_search)
        top_search_bar.add_widget(btn_filter)
        self.main_layout.add_widget(top_search_bar)

        self.results_scroll = ScrollView(size_hint=(1, 1))
        self.results_box = MDBoxLayout(orientation='vertical', size_hint_y=None, padding=dp(15), spacing=dp(10))
        self.results_box.bind(minimum_height=self.results_box.setter('height'))

        self.results_scroll.add_widget(self.results_box)
        self.main_layout.add_widget(self.results_scroll)

        nav_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10), md_bg_color=WHITE_COLOR
        )
        nav_bar.add_widget(NavTab(text="Lịch chính", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Tìm kiếm", target_screen="search_home", is_active=True))
        nav_bar.add_widget(NavTab(text="Trợ lý AI", target_screen="chat_home", is_active=False))
        self.main_layout.add_widget(nav_bar)

        self.txt_search.bind(text=self.on_text_change)
        self.perform_search()

    
    # --- POPUP BỘ LỌC ---
    # --- POPUP BỘ LỌC ---
    def open_filter_modal(self, *args):
        self.filter_modal = ModalView(
            size_hint=(0.9, None), height=dp(250), 
            background_color=[0, 0, 0, 0.5], auto_dismiss=True
        )
        
        modal_content = BoxLayout(
            orientation='vertical', 
            padding=[dp(20), dp(20), dp(20), dp(20)], 
            spacing=dp(10)
        )
        
        with modal_content.canvas.before:
            # Màu nền
            Color(228/255, 228/255, 235/255, 1)
            modal_content.bg_rect = RoundedRectangle(radius=[dp(15)])
            
            # --- CẬP NHẬT Ở ĐÂY ---
            # Viền đậm hơn (0.5 thay vì 0.8) và dày hơn (width=2.0)
            Color(0.5, 0.5, 0.5, 1)
            modal_content.border_line = Line(rounded_rectangle=[0, 0, 0, 0, dp(15)], width=2.0)
            
        def update_modal_bg(inst, val):
            inst.bg_rect.pos = inst.pos
            inst.bg_rect.size = inst.size
            inst.border_line.rounded_rectangle = [inst.x, inst.y, inst.width, inst.height, dp(15)]
        modal_content.bind(pos=update_modal_bg, size=update_modal_bg)
        
        lbl_title = Label(
            text="BỘ LỌC SỰ KIỆN", bold=True, color=BLACK_COLOR,
            size_hint_y=None, height=dp(30) 
        )
        modal_content.add_widget(lbl_title)
        
        grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(5))
        grid.bind(minimum_height=grid.setter('height'))
        
        options = {
            "CLASS": "Lớp học", "EXAM": "Bài thi", 
            "EVENT": "Sự kiện", "TASK": "Nhiệm vụ", 
            "DEADLINE": "Hạn chót"
        }
        
        def update_filter(key):
            return lambda inst, val: self.active_filters.update({key: val})
            
        for key, text_val in options.items():
            box = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(35))
            chk = CheckBox(
                active=self.active_filters.get(key, True), 
                size_hint=(None, None), size=(dp(35), dp(35)), color=BLUE_COLOR
            )
            chk.bind(active=update_filter(key))
            
            lbl_item = Label(text=text_val, color=BLACK_COLOR, halign="left", valign="center")
            lbl_item.bind(size=lbl_item.setter('text_size'))
            
            box.add_widget(chk)
            box.add_widget(lbl_item)
            grid.add_widget(box)
            
        box_imp = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(35))
        chk_imp = CheckBox(
            active=getattr(self, 'filter_important_only', False), 
            size_hint=(None, None), size=(dp(35), dp(35)), color=BLUE_COLOR
        )
        chk_imp.bind(active=lambda inst, val: setattr(self, 'filter_important_only', val))
        
        lbl_imp = Label(text="Quan trọng", color=BLACK_COLOR, bold=True, halign="left", valign="center")
        lbl_imp.bind(size=lbl_imp.setter('text_size'))
        
        box_imp.add_widget(chk_imp)
        box_imp.add_widget(lbl_imp)
        grid.add_widget(box_imp)
        
        modal_content.add_widget(grid)
        
        btn_apply = Button(
            text="Áp dụng & Tìm kiếm",
            background_normal='', background_color=BLUE_COLOR, color=WHITE_COLOR, bold=True,
            size_hint=(None, None), size=(dp(180), dp(40)), pos_hint={"center_x": 0.5} 
        )
        with btn_apply.canvas.before:
            Color(*BLUE_COLOR)
            btn_apply.bg_rect = RoundedRectangle(radius=[dp(8)])
        def update_btn_bg(inst, val):
            inst.bg_rect.pos = inst.pos
            inst.bg_rect.size = inst.size
        btn_apply.bind(pos=update_btn_bg, size=update_btn_bg)
        
        btn_apply.bind(on_release=self.apply_filters)
        modal_content.add_widget(btn_apply)
        
        self.filter_modal.add_widget(modal_content)
        self.filter_modal.open()

    def apply_filters(self, *args):
        self.filter_modal.dismiss()
        self.perform_search()

    def on_pre_enter(self, *args):
        """load the user's real events when the tab opens, then repeat the current search."""
        store.refresh(api, on_done=lambda: self.perform_search() if hasattr(self, "txt_search") else None)

    # --- LOGIC TÌM KIẾM ---
    def on_text_change(self, instance, value):
        if self.search_event is not None:
            self.search_event.cancel()
        self.search_event = Clock.schedule_once(lambda dt: self.perform_search(), 0.3)

    def perform_search(self, *args):
        query = self.txt_search.text.strip().lower()
        self.results_box.clear_widgets()
        count = 0
        MAX_RESULTS = 30
        
        for event in store.events:
            if count >= MAX_RESULTS:
                self.results_box.add_widget(MDLabel(
                    text=f"Đã hiển thị {MAX_RESULTS} kết quả...", 
                    halign="center", theme_text_color="Custom", text_color=GRAY_TEXT,
                    font_style="Body", role="medium", size_hint_y=None, height=dp(40)
                ))
                break
                
            kind = event.get("kind", "EVENT")
            is_important = event.get("is_important", False)
            
            if not self.active_filters.get(kind, True):
                continue
            if self.filter_important_only and not is_important:
                continue

            ev_start = datetime.fromisoformat(event["start_time"])
            date_full_str = ev_start.strftime("%d/%m/%Y")
            date_short_str = ev_start.strftime("%d/%m")
            
            match_text = (
                query in event["title"].lower() or 
                query in kind.lower() or
                query in date_full_str or 
                query in date_short_str
            )
            
            if match_text:
                self.results_box.add_widget(EventCard(event))
                count += 1
        
        if count == 0:
            self.results_box.add_widget(MDLabel(
                text="Không tìm thấy kết quả nào!", 
                halign="center", theme_text_color="Custom", text_color=GRAY_TEXT,
                font_style="Body", role="large", size_hint_y=None, height=dp(50)
            ))

if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return SearchScreen(name="search_home")
    TestApp().run()