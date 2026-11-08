import calendar

from api_client import api
from event_store import store

from datetime import datetime, date, timedelta
from kivy.core.window import Window


from collections import defaultdict

from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line, Rectangle
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, SlideTransition, Screen
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.screenmanager import SlideTransition


from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText
from kivymd.uix.card import MDCard
from kivymd.uix.menu import MDDropdownMenu



# ==============================================================================
# 1. HẰNG SỐ MÀU SẮC
# ==============================================================================
WHITE_COLOR = [1, 1, 1, 1]
BLACK_COLOR = [0, 0, 0, 1]
GRAY_TEXT   = [0.5, 0.5, 0.5, 1]
LIGHT_GRAY  = [0.93, 0.93, 0.93, 1]
LIGHT_BLUE  = [0.85, 0.93, 1.0, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]
BTN_ADD_BG  = [25/255, 90/255, 220/255, 1]

# MÀU SỰ KIỆN THEO QUY TẮC "KIND"
# [CẦN BACKEND XỬ LÝ]: Đảm bảo trường "kind" trả về đúng 1 trong 4 loại này hoặc "DEADLINE"
EV_CLASS    = [0/255, 102/255, 204/255, 1]     # Lớp học
EV_EXAM     = [204/255, 0/255, 0/255, 1]       # Thi cử
EV_EVENT    = [0/255, 153/255, 51/255, 1]      # Sự kiện chung
EV_TASK     = [153/255, 51/255, 255/255, 1]    # Bài tập/Công việc
EV_DEADLINE = [255/255, 153/255, 0/255, 1]     # Hạn chót
# TỪ ĐIỂN MAP MÀU VÀ THỨ TỰ ƯU TIÊN SỰ KIỆN TRONG Ô LỊCH
KIND_COLORS = {
    "CLASS": EV_CLASS,
    "EXAM": EV_EXAM,
    "EVENT": EV_EVENT,
    "TASK": EV_TASK,
    "DEADLINE": EV_DEADLINE
}

# Thứ tự vẽ vạch màu từ trên xuống dưới
KIND_ORDER = {
    "CLASS": 1,
    "EXAM": 2,
    "EVENT": 3,
    "TASK": 4,
    "DEADLINE": 5
}
# ==============================================================================
# 2. CÁC WIDGET TÙY CHỈNH (COMPONENTS)
# ==============================================================================
class EventIndicatorLine(MDBoxLayout):
    """Đường gạch ngang nhỏ thể hiện loại sự kiện trong ngày."""
    def __init__(self, color, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(3) # Độ dày của vạch
        
        # --- THÊM 3 DÒNG NÀY ĐỂ FIX LỖI TRÊN PC ---
        self.size_hint_x = None              # Tắt tính năng tự giãn ngang
        self.width = dp(25)                  # Cố định chiều dài vạch (giống Android)
        self.pos_hint = {"center_x": 0.5}    # Căn giữa vạch vào chính giữa ô ngày
        
        with self.canvas.before:
            Color(*color)
            self.bg_rect = RoundedRectangle(radius=[dp(1.5)])
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

class HoverClickLabel(MDLabel):
    """Nhãn (Label) có hiệu ứng đổi màu khi hover chuột và có thể click."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.theme_text_color = "Custom"
        self.text_color = WHITE_COLOR
        self.halign = "center"
        self.bold = True
        self.font_style = "Title"
        self.role = "medium"
        self.font_size = dp(18)
        
        self.register_event_type('on_release')
        Window.bind(mouse_pos=self.on_mouse_pos)

    def on_mouse_pos(self, window, pos):
        if not self.get_root_window(): return
        self.text_color = LIGHT_GRAY if self.collide_point(*pos) else WHITE_COLOR

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.dispatch('on_release')
            return True
        return super().on_touch_down(touch)

    def on_release(self, *args):
        pass


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


class DayNode(MDCard):
    """Ô hiển thị từng ngày trong View Lịch Tháng, bao gồm nhãn ngày và các vạch màu sự kiện."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.elevation = 1
        self.radius = [dp(6)]
        self.md_bg_color = WHITE_COLOR
        
        # Sử dụng BoxLayout chính để chia phần chữ số và phần vạch
        self.main_layout = MDBoxLayout(orientation='vertical', padding=[dp(2), dp(2), dp(2), dp(4)])
        self.add_widget(self.main_layout)
        
        self.lbl = MDLabel(text="", halign="center", theme_text_color="Custom", text_color=BLACK_COLOR)
        self.main_layout.add_widget(self.lbl)
        
        # Vùng dưới cùng chứa các vạch màu sự kiện
        self.indicator_box = MDBoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=dp(18), # Giới hạn không gian vạch
            spacing=dp(2),
            padding=[dp(6), 0, dp(6), 0]
        )
        self.main_layout.add_widget(self.indicator_box)
        
        self.day_date = None
        self.register_event_type('on_release')

    def update_data(self, day_date, is_current_month, is_today):
        self.day_date = day_date
        self.opacity = 1 
        self.lbl.text = str(day_date.day)
        
        if is_today:
            self.md_bg_color = LIGHT_BLUE
        elif not is_current_month:
            self.md_bg_color = LIGHT_GRAY
        else:
            self.md_bg_color = WHITE_COLOR

        self.lbl.text_color = BLACK_COLOR if is_current_month else GRAY_TEXT

    def set_events(self, events_list):
        """Vẽ các vạch màu ngang dưới chân Node dựa trên dữ liệu sự kiện của ngày."""
        self.indicator_box.clear_widgets()
        if not events_list:
            return
        
        # 1. Lọc các loại (kind) duy nhất có trong ngày
        unique_kinds = set(ev.get("kind", "TASK") for ev in events_list)
        
        # 2. Sắp xếp loại sự kiện theo quy tắc: Class -> Exam -> Event -> Task -> Deadline
        sorted_kinds = sorted(unique_kinds, key=lambda k: KIND_ORDER.get(k, 99))
        
        # 3. Kivy layout Vertical tự động xếp từ trên xuống dưới
        for kind in sorted_kinds:
            color = KIND_COLORS.get(kind, EV_TASK)
            self.indicator_box.add_widget(EventIndicatorLine(color=color))
            
        # 4. Spacer giúp dồn các vạch sát vào nhau ở phía trên thay vì dãn đều khung
        spacer = MDBoxLayout()
        self.indicator_box.add_widget(spacer)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.opacity > 0:
            self.dispatch('on_release')
            return True
        return super().on_touch_down(touch)

    def on_release(self, *args):
        pass


class MonthYearSelectorModal(ModalView):
    """Popup chọn Tháng/Năm nhanh."""
    def __init__(self, start_year, on_month_selected, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.8, 0.6)
        self.auto_dismiss = True
        self.current_modal_year = start_year
        self.on_month_selected = on_month_selected
        self.setup_ui()

    def setup_ui(self):
        self.clear_widgets()
        main_layout = MDBoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10))
        with main_layout.canvas.before:
            Color(*WHITE_COLOR)
            self.bg_rect = RoundedRectangle(radius=[dp(10)])
        main_layout.bind(pos=self.update_bg, size=self.update_bg)

        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50))
        btn_prev = MDIconButton(icon="chevron-left", pos_hint={"center_y": 0.5})
        btn_prev.bind(on_release=lambda x: self.change_year(-1))
        
        self.lbl_year = MDLabel(text=f"Năm {self.current_modal_year}", halign="center", bold=True, font_style="Title", role="large")
        btn_next = MDIconButton(icon="chevron-right", pos_hint={"center_y": 0.5})
        btn_next.bind(on_release=lambda x: self.change_year(1))
        
        header.add_widget(btn_prev)
        header.add_widget(self.lbl_year)
        header.add_widget(btn_next)
        main_layout.add_widget(header)

        grid = MDGridLayout(cols=2, spacing=dp(10), padding=dp(10))
        for m in range(1, 13):
            btn_month = MDButton(
                MDButtonText(text=f"Tháng {m}", theme_text_color="Custom", text_color=BLACK_COLOR),
                style="elevated", theme_bg_color="Custom", md_bg_color=WHITE_COLOR, size_hint=(1, 1)
            )
            btn_month.bind(on_release=lambda instance, m=m: self.select_month(m))
            grid.add_widget(btn_month)
            
        main_layout.add_widget(grid)
        self.add_widget(main_layout)

    def update_bg(self, instance, val):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def change_year(self, delta):
        self.current_modal_year += delta
        self.lbl_year.text = f"Năm {self.current_modal_year}"

    def select_month(self, month):
        self.on_month_selected(month, self.current_modal_year)
        self.dismiss()


class WeekTimeSlotRow(MDBoxLayout):
    """Một hàng trong timeline Lịch Tuần (mỗi 30 phút)."""
    def __init__(self, hour, minute, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(60)
        
        is_hour = (minute == 0)
        time_str = f"{hour:02d}:{minute:02d}"

        self.lbl_time = MDLabel(
            text=time_str, size_hint_x=None, width=dp(50),
            halign="center", valign="top",
            theme_text_color="Custom", text_color=BLACK_COLOR if is_hour else GRAY_TEXT,
            font_style="Label", role="large" if is_hour else "medium", bold=is_hour
        )
        self.add_widget(self.lbl_time)
        
        self.days_area = MDGridLayout(cols=7)
        for i in range(7):
            cell = MDBoxLayout()
            with cell.canvas.before:
                Color(*LIGHT_GRAY)
                line_width = 1.2 if is_hour else 0.5
                cell.bottom_line = Line(points=[0, 0, 0, 0], width=line_width)
                cell.vertical_line = Line(points=[0, 0, 0, 0], width=1)
                
            def update_lines(instance, val, c=cell):
                x, y = instance.pos
                w, h = instance.size
                c.bottom_line.points = [x, y, x + w, y]
                c.vertical_line.points = [x, y, x, y + h]
                
            cell.bind(pos=update_lines, size=update_lines)
            self.days_area.add_widget(cell)
            
        self.add_widget(self.days_area)


# ==============================================================================
# 3. WIDGET SỰ KIỆN & DEADLINE BANNER (QUY TẮC BE)
# ==============================================================================
class EventBlock(ButtonBehavior, MDBoxLayout):
    """
    Khối hiển thị sự kiện trên Timeline (Ví dụ: Lớp học, Tập Gym).
    Đã được nâng cấp giao diện để nổi bật (3D-like, Accent line).
    """
    def __init__(self, event_data, col_index, **kwargs):
        super().__init__(**kwargs)
        self.event_data = event_data
        self.col_index = col_index
        self.orientation = 'vertical'
        self.padding = [dp(6), dp(4), dp(2), dp(2)] # Lùi trái một chút cho đường dải màu
        
        self.kind = event_data.get("kind", "TASK")
        self.title = event_data.get("title", "Sự kiện")
        self.is_hard = (self.kind in ["CLASS", "EXAM"])
        
        if self.kind == "CLASS": base_color = EV_CLASS
        elif self.kind == "EXAM": base_color = EV_EXAM
        elif self.kind == "EVENT": base_color = EV_EVENT
        else: base_color = EV_TASK

        # Làm nhạt màu nền và giữ màu đậm cho viền trái (Accent)
        bg_color = [base_color[0], base_color[1], base_color[2], 0.85]
        
        with self.canvas.before:
            # 1. Đổ bóng giả (Shadow mờ nhẹ dịch xuống góc phải)
            Color(0, 0, 0, 0.2)
            self.shadow = RoundedRectangle(radius=[dp(4)])
            
            # 2. Nền chính của thẻ
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=[dp(4)])
            
            # 3. Dải màu nhấn đậm bên trái (Accent Line)
            Color(*base_color[:3], 1.0)
            self.accent_line = RoundedRectangle(radius=[dp(4), 0, 0, dp(4)])
            
            # 4. Viền mỏng bao quanh để tách biệt với nền sáng
            Color(0, 0, 0, 0.5)
            self.border = Line(width=1.1)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)

        self.add_widget(MDLabel(
            text=self.title, 
            theme_text_color="Custom", 
            text_color=WHITE_COLOR,
            font_style="Label",
            role="small",
            bold=True, 
            halign="left", 
            valign="top"
        ))

    def update_canvas(self, *args):
        # Đổ bóng dịch lệch một chút
        self.shadow.pos = [self.x + dp(2), self.y - dp(2)]
        self.shadow.size = self.size
        
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        
        # Dải màu nhấn rộng 4dp
        self.accent_line.pos = self.pos
        self.accent_line.size = [dp(4), self.height]
        
        self.border.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(4)]

    def on_release(self):
        # [CẦN BACKEND XỬ LÝ]: Khi bấm vào, có thể gọi API lấy chi tiết sự kiện
        print(f"Bấm sự kiện: {self.title} | Loại: {self.kind}")


class DeadlineBanner(ButtonBehavior, MDBoxLayout):
    """
    Banner nhỏ hiển thị Deadline, neo phía trên cùng của mỗi cột ngày.
    """
    def __init__(self, title, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(22)
        self.padding = [dp(2), 0, dp(2), 0]
        
        with self.canvas.before:
            Color(*EV_DEADLINE)
            self.bg_rect = RoundedRectangle(radius=[dp(4)])
            Color(0,0,0, 0.3)
            self.border = Line(width=1)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)
        
        self.add_widget(MDLabel(
            text=f"⏰ {title}", 
            theme_text_color="Custom", 
            text_color=WHITE_COLOR,
            font_style="Label",
            role="small",
            bold=True, 
            halign="center"
        ))

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.border.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(4)]


# ==============================================================================
# 4. MÀN HÌNH CHÍNH: CALENDAR HOME SCREEN
# ==============================================================================
class CalendarHomeScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = WHITE_COLOR
        self.today = date.today()
        self.display_month = self.today.month
        self.display_year = self.today.year
        self.current_week_start = self.today - timedelta(days=self.today.weekday())
        
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        """Khởi tạo toàn bộ khung giao diện của ứng dụng."""
        self.main_layout = MDBoxLayout(orientation='vertical')
        self.add_widget(self.main_layout)

        # --- A. THANH MENU CHỨC NĂNG TRÊN CÙNG ---
        self.top_menu = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(56),
            md_bg_color=BLUE_COLOR, padding=dp(10)
        )
        
        self.btn_menu = MDIconButton(icon="menu", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": 0.5})
        self.btn_menu.bind(on_release=self.on_menu_or_back)
        
        center_nav = MDBoxLayout(orientation='horizontal', size_hint_x=1, spacing=dp(5))
        self.btn_prev = MDIconButton(icon="chevron-left", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": 0.5})
        self.btn_prev.bind(on_release=lambda x: self.change_time_period(-1))
        
        self.lbl_month_year = HoverClickLabel()
        self.lbl_month_year.bind(on_release=self.open_month_selector)
        
        self.btn_next = MDIconButton(icon="chevron-right", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": 0.5})
        self.btn_next.bind(on_release=lambda x: self.change_time_period(1))
        
        center_nav.add_widget(self.btn_prev)
        center_nav.add_widget(self.lbl_month_year)
        center_nav.add_widget(self.btn_next)
        
        self.btn_add_box = MDBoxLayout(size_hint=(None, None), size=(dp(36), dp(36)), pos_hint={"center_y": 0.5})
        with self.btn_add_box.canvas.before:
            Color(*BTN_ADD_BG)
            self.add_bg_rect = RoundedRectangle(radius=[dp(6)])
        self.btn_add_box.bind(pos=self.update_add_btn_bg, size=self.update_add_btn_bg)
            
        self.btn_add = MDIconButton(icon="plus", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_x": 0.5, "center_y": 0.5})
        self.btn_add.bind(on_release=self.open_add_menu)
        self.btn_add_box.add_widget(self.btn_add)
        
        self.top_menu.add_widget(self.btn_menu)
        self.top_menu.add_widget(center_nav)
        self.top_menu.add_widget(self.btn_add_box)
        
        self.main_layout.add_widget(self.top_menu)

        menu_items = [
            {"text": "Thêm sự kiện", "on_release": lambda x="Thêm sự kiện": self.add_menu_callback(x)},
            {"text": "Import lịch", "on_release": lambda x="Import lịch": self.add_menu_callback(x)}
        ]
        self.add_menu = MDDropdownMenu(caller=self.btn_add_box, items=menu_items, width_mult=4)

        # --- B. CONTENT (Sử dụng ScreenManager) ---
        self.content_sm = ScreenManager(size_hint_y=1, transition=SlideTransition())
        
        # B.1 LỊCH THÁNG
        self.month_screen = Screen(name="month_view")
        self.month_layout = MDBoxLayout(orientation='vertical', padding=[dp(10), dp(15), dp(10), dp(10)], spacing=dp(5))
        
        days_header = MDGridLayout(cols=7, size_hint_y=None, height=dp(30))
        for wd in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]:
            days_header.add_widget(MDLabel(text=wd, halign="center", bold=True, theme_text_color="Custom", text_color=GRAY_TEXT))
        self.month_layout.add_widget(days_header)
        
        self.days_grid = MDGridLayout(cols=7, spacing=dp(5))
        self.day_nodes = []
        for _ in range(42):
            node = DayNode()
            node.bind(on_release=self.on_day_selected)
            self.days_grid.add_widget(node)
            self.day_nodes.append(node)

        self.month_layout.add_widget(self.days_grid)
        self.month_screen.add_widget(self.month_layout)
        
        # B.2 LỊCH TUẦN
        self.week_screen = Screen(name="week_view")
        self.week_layout = MDBoxLayout(orientation='vertical')
        
        self.week_header_container = RelativeLayout(size_hint_y=None, height=dp(70))
        self.week_days_box = MDBoxLayout(orientation='horizontal', padding=[dp(50), dp(5), 0, dp(5)])
        self.week_day_labels = []
        self.deadline_boxes = []
        
        for i in range(7):
            col = MDBoxLayout(orientation='vertical')
            lbl = MDLabel(text="", halign="center", theme_text_color="Custom", text_color=BLACK_COLOR, size_hint_y=None, height=dp(35))
            dl_box = MDBoxLayout(orientation='vertical', spacing=dp(2))
            self.week_day_labels.append(lbl)
            self.deadline_boxes.append(dl_box)
            col.add_widget(lbl)
            col.add_widget(dl_box)
            self.week_days_box.add_widget(col)
            
        self.week_header_container.add_widget(self.week_days_box)
        
        self.btn_week_prev = MDIconButton(icon="chevron-left", pos_hint={"center_y": 0.5, "x": 0})
        self.btn_week_prev.bind(on_release=lambda x: self.shift_week_view_by_day(-1))
        self.week_header_container.add_widget(self.btn_week_prev)
        
        self.btn_week_next = MDIconButton(icon="chevron-right", pos_hint={"center_y": 0.5, "right": 1})
        self.btn_week_next.md_bg_color = [1, 1, 1, 0.7]
        self.btn_week_next.bind(on_release=lambda x: self.shift_week_view_by_day(1))
        self.week_header_container.add_widget(self.btn_week_next)
        
        self.week_layout.add_widget(self.week_header_container)
        
        # TIMELINE SCRoLL OVERLAY
        self.timeline_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True)
        self.timeline_height = dp(2880)
        self.timeline_container = RelativeLayout(size_hint_y=None, height=self.timeline_height)
        
        self.timeline_grid = MDBoxLayout(orientation='vertical', size_hint=(1, 1))
        for h in range(24):
            for m in (0, 30):
                self.timeline_grid.add_widget(WeekTimeSlotRow(hour=h, minute=m))
                
        self.event_overlay = FloatLayout(size_hint=(1, 1))
        self.event_overlay.bind(size=self.recalculate_event_positions)
        
        self.timeline_container.add_widget(self.timeline_grid)
        self.timeline_container.add_widget(self.event_overlay)
        
        self.timeline_scroll.add_widget(self.timeline_container)
        self.week_layout.add_widget(self.timeline_scroll)
        self.week_screen.add_widget(self.week_layout)
        
        self.content_sm.add_widget(self.month_screen)
        self.content_sm.add_widget(self.week_screen)
        self.main_layout.add_widget(self.content_sm)

        # --- C. THANH ĐIỀU HƯỚNG DƯỚI ---
        nav_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10)
        )
        # Tab Lịch đang active nên is_active=True
        nav_bar.add_widget(NavTab(text="Lịch chính", target_screen="calendar_home", is_active=True))
        nav_bar.add_widget(NavTab(text="Tìm kiếm", target_screen="search_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Trợ lý AI", target_screen="chat_home", is_active=False))
        
        self.main_layout.add_widget(nav_bar) # Đảm bảo main_layout của bạn là khung chứa chính
        self.render_month_view()

    # ==========================================================================
    # 5. HÀM XỬ LÝ LOGIC & DỮ LIỆU
    # ==========================================================================
    def update_add_btn_bg(self, instance, val):
        self.add_bg_rect.pos = instance.pos
        self.add_bg_rect.size = instance.size

    def open_add_menu(self, *args):
        self.add_menu.open()
        
    def add_menu_callback(self, action):
        # [CẦN BACKEND XỬ LÝ]: Tích hợp luồng gọi API thêm Event hoặc Upload File
        print(f"Gọi luồng: {action}")
        self.add_menu.dismiss()

    def update_top_title(self):
        if self.content_sm.current == "month_view":
            self.lbl_month_year.text = f"Tháng {self.display_month}, Năm {self.display_year}"
        else:
            if hasattr(self, 'current_week_start'):
                end_date = self.current_week_start + timedelta(days=6)
                if self.current_week_start.year == end_date.year:
                    self.lbl_month_year.text = f"{self.current_week_start.day}/{self.current_week_start.month} -> {end_date.day}/{end_date.month} / {self.current_week_start.year}"
                else:
                    self.lbl_month_year.text = f"{self.current_week_start.day}/{self.current_week_start.month}/{self.current_week_start.year} -> {end_date.day}/{end_date.month}/{end_date.year}"

    # ---- events come from the backend (event_store.py) -------------------------------------
    def on_pre_enter(self, *args):
        store.refresh(api, on_done=self._redraw_events)

    def _redraw_events(self):
        if not hasattr(self, "day_nodes") or not hasattr(self, "content_sm"):
            return  # the widgets are built a moment after the screen is created
        if self.content_sm.current == "week_view":
            self.render_week_view()
        else:
            self.render_month_view()


    def on_menu_or_back(self, *args):
        if self.content_sm.current == "week_view":
            self.content_sm.transition.direction = 'right'
            self.content_sm.current = "month_view"
            self.btn_menu.icon = "menu"
            self.update_top_title()

    def on_day_selected(self, instance):
        if instance.day_date:
            self.current_week_start = instance.day_date - timedelta(days=instance.day_date.weekday())
            self.render_week_view()
            self.content_sm.transition.direction = 'left'
            self.content_sm.current = "week_view"
            self.btn_menu.icon = "arrow-left"

    def render_month_view(self):
        self.update_top_title()
        cal = calendar.Calendar(firstweekday=0) 
        month_days = cal.monthdatescalendar(self.display_year, self.display_month)
        flat_days = [day_date for week in month_days for day_date in week]

        # [TÍNH TOÁN DỮ LIỆU] Nhóm toàn bộ mốc thời gian sự kiện theo ngày
        events_by_date = {}
        for ev in store.events:
            ev_date = datetime.fromisoformat(ev["start_time"]).date()
            if ev_date not in events_by_date:
                events_by_date[ev_date] = []
            events_by_date[ev_date].append(ev)

        # Đẩy dữ liệu hiển thị vào Node
        for i, node in enumerate(self.day_nodes):
            if i < len(flat_days):
                day_date = flat_days[i]
                node.update_data(day_date, day_date.month == self.display_month, day_date == self.today)
                
                # Gọi hàm set_events để Node vẽ các vạch ngang
                day_events = events_by_date.get(day_date, [])
                node.set_events(day_events)
            else:
                node.opacity = 0
                node.set_events([]) # Xóa vạch nếu ô Lịch bị ẩn đi

    def render_week_view(self):
        for i in range(7):
            current_day = self.current_week_start + timedelta(days=i)
            lbl = self.week_day_labels[i]
            wd_str = "CN" if current_day.isoweekday() == 7 else f"T{current_day.isoweekday() + 1}"
            
            lbl.text = f"{wd_str}\n{current_day.day}"
            lbl.text_color = BLUE_COLOR if current_day == self.today else BLACK_COLOR
            lbl.bold = (current_day == self.today)
                
        self.update_top_title()
        self.load_week_events()

    def load_week_events(self):
        """Draw the events of the displayed week. They come from event_store.store (the backend, or demo events when nobody is logged in)."""
        # Xóa sạch các widget sự kiện cũ trên UI trước khi vẽ tuần mới
        self.event_overlay.clear_widgets()
        for dl_box in self.deadline_boxes:
            dl_box.clear_widgets()
            
        # --- LỌC & XỬ LÝ CHUYỂN ĐỔI DỮ LIỆU ---
        for raw_ev in store.events:
            start_dt = datetime.fromisoformat(raw_ev["start_time"])
            end_dt = datetime.fromisoformat(raw_ev["end_time"])

            # Tính vị trí cột dựa trên khoảng cách giữa ngày sự kiện và ngày bắt đầu tuần (Thứ 2) của UI
            col_index = (start_dt.date() - self.current_week_start).days

            # [QUAN TRỌNG NHẤT]: Bỏ qua sự kiện nếu ngày của nó không nằm trong tuần hiện tại (0 -> 6)
            if not (0 <= col_index <= 6):
                continue

            # Tính toán giờ và thời lượng để vẽ UI
            start_h = start_dt.hour
            start_m = start_dt.minute
            duration = int((end_dt - start_dt).total_seconds() / 60)

            # Gắn các thông số tính toán được
            processed_ev = raw_ev.copy()
            processed_ev["col"] = col_index
            processed_ev["start_h"] = start_h
            processed_ev["start_m"] = start_m
            processed_ev["duration"] = duration

            # Vẽ lên Timeline hoặc gắn vào Banner Deadline
            if processed_ev["kind"] == "DEADLINE":
                self.deadline_boxes[col_index].add_widget(DeadlineBanner(title=processed_ev["title"]))
            else:
                self.event_overlay.add_widget(EventBlock(event_data=processed_ev, col_index=col_index))
                
        # Gọi UI tính toán lại toạ độ Y và chiều cao sau khi render
        Clock.schedule_once(lambda dt: self.recalculate_event_positions(self.event_overlay, self.event_overlay.size), 0)



        
    def recalculate_event_positions(self, instance, size):
        """Tính toán toạ độ (x, y) và size cho các widget EventBlock trong lưới Timeline."""
        total_width = size[0]
        col_width = (total_width - dp(50)) / 7.0 
        pixels_per_min = dp(2)
        
        for child in self.event_overlay.children:
            if isinstance(child, EventBlock):
                ev = child.event_data
                child.size_hint = (None, None)
                child.width = col_width - dp(4) # Bớt 4dp để tạo khoảng trống giữa các cột
                child.x = dp(50) + (child.col_index * col_width) + dp(2)
                child.height = ev["duration"] * pixels_per_min
                
                # Tính toạ độ Y từ dưới lên theo kiến trúc toạ độ của Kivy
                start_min_from_midnight = ev["start_h"] * 60 + ev["start_m"]
                y_from_top = start_min_from_midnight * pixels_per_min
                child.y = self.timeline_height - y_from_top - child.height

    def change_time_period(self, delta):
        if self.content_sm.current == "month_view":
            self.change_month(delta)
        else:
            if hasattr(self, 'current_week_start'):
                self.current_week_start += timedelta(days=7 * delta)
                self.render_week_view()

    def shift_week_view_by_day(self, delta_days):
        if hasattr(self, 'current_week_start'):
            self.current_week_start += timedelta(days=delta_days)
            self.render_week_view()

    def change_month(self, delta):
        new_month = self.display_month + delta
        if new_month > 12:
            self.display_month, self.display_year = 1, self.display_year + 1
        elif new_month < 1:
            self.display_month, self.display_year = 12, self.display_year - 1
        else:
            self.display_month = new_month
        self.render_month_view()

    def open_month_selector(self, *args):
        MonthYearSelectorModal(self.display_year, self.on_month_selected_from_modal).open()

    def on_month_selected_from_modal(self, selected_month, selected_year):
        self.display_month = selected_month
        self.display_year = selected_year
        self.render_month_view()


if __name__ == "__main__":
    Window.size = (360, 640)

    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            self.theme_cls.primary_palette = "Blue"
            return CalendarHomeScreen(name="calendar_home")

    TestApp().run()