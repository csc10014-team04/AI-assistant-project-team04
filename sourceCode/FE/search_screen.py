from datetime import datetime
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.utils import platform
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.textinput import TextInput
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.modalview import ModalView
# IMPORT THUẦN KIVY ĐỂ CHỐNG CRASH CHO POPUP
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText
from kivymd.uix.progressindicator import MDCircularProgressIndicator
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
from kivy.uix.label import Label
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivy.metrics import dp
from kivy.graphics import Color, RoundedRectangle, Line
from datetime import datetime

class EventCard(ButtonBehavior, MDBoxLayout):
    """
    Thẻ hiển thị thông tin sự kiện trong danh sách kết quả tìm kiếm:
    - Bố cục ngang (horizontal): Cột trái là dấu chấm than cảnh báo (nếu có),
      cột giữa là khối nội dung văn bản (content_box), tự động xuống dòng và co dãn mượt mà.
    - Không sử dụng trigger trễ (delay) hoặc gọi texture_update cưỡng bức để loại bỏ hoàn toàn
      hiện tượng giật lag và hiện tượng thẻ bị kéo giãn 1 nhịp rồi co lại khi chuyển tab.
    """
    def __init__(self, event, **kwargs):
        super().__init__(**kwargs)
        self.event = event
        self.orientation = 'horizontal'  
        self.size_hint_y = None
        self.size_hint_x = 1
        self.padding = [dp(14), dp(10), dp(14), dp(10)]
        self.spacing = dp(10)
        
        bg_color = self.get_color(event.get("kind", "EVENT"))

        with self.canvas.before:
            Color(0, 0, 0, 0.22)
            self.shadow = RoundedRectangle(radius=[dp(12)])
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=[dp(12)])
            Color(0, 0, 0, 0.4)
            self.border_line = Line(rounded_rectangle=[0, 0, 0, 0, dp(12)], width=0.8)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)

        is_important = event.get("is_important", False)
        self.has_icon = is_important
        
        if is_important:
            self.icon_lbl = Label(
                text="!", color=[1, 0, 0, 1], outline_color=[0, 0, 0, 1], outline_width=1.15,
                bold=True, font_size=dp(24), size_hint=(None, None), size=(dp(18), dp(28)),
                pos_hint={"center_y": 0.5}
            )
            self.divider = MDBoxLayout(size_hint_x=None, width=dp(1.2), md_bg_color=(0, 0, 0, 0.25))
            self.add_widget(self.icon_lbl)
            self.add_widget(self.divider)

        # KHỐI VĂN BẢN (THÔNG TIN SỰ KIỆN)
        self.content_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(3),
            size_hint_x=1,
            adaptive_height=True
        )
        self.content_box.bind(height=self._on_content_height)

        self.labels = []
        
        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event["end_time"])
        days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_str = days_en[start_dt.weekday()]
        date_str = start_dt.strftime("%d/%m/%Y")
        start_time_str = start_dt.strftime("%H:%M")
        end_time_str = end_dt.strftime("%H:%M")
        title = event["title"]
        room = event.get("room")

        if event["kind"] == "DEADLINE":
            lbl_deadline = MDLabel(
                text=f"[b]Deadline:[/b] {title} - {end_time_str} ({date_str})",
                markup=True, halign='left', valign='top',
                theme_text_color="Custom", text_color=BLACK_COLOR,
                adaptive_height=True, size_hint_x=1
            )
            self.labels.append(lbl_deadline)
        else:
            lbl_date = MDLabel(
                text=f"[b]{day_str}, {date_str}:[/b]",
                markup=True, halign='left',
                theme_text_color="Custom", text_color=BLACK_COLOR,
                adaptive_height=True, size_hint_x=1
            )
            lbl_title = MDLabel(
                text=f"Event: {title}",
                markup=True, halign='left',
                theme_text_color="Custom", text_color=BLACK_COLOR,
                adaptive_height=True, size_hint_x=1
            )
            lbl_time = MDLabel(
                text=f"Time: {start_time_str} - {end_time_str}",
                halign='left',
                theme_text_color="Custom", text_color=BLACK_COLOR,
                adaptive_height=True, size_hint_x=1
            )
            self.labels.extend([lbl_date, lbl_title, lbl_time])

        if room and str(room).strip() and str(room).lower() not in ("none", "null"):
            lbl_room = MDLabel(
                text=f"[b]Location:[/b] {str(room).strip()}",
                markup=True, halign='left',
                theme_text_color="Custom", text_color=BLACK_COLOR,
                adaptive_height=True, size_hint_x=1
            )
            self.labels.append(lbl_room)
            
        for lbl in self.labels:
            self.content_box.add_widget(lbl)

        self.add_widget(self.content_box)
        
        # Thiết lập chiều cao khởi tạo ngay tức thì để Kivy render không bị co giật
        self.height = len(self.labels) * dp(24) + dp(20)

    def _on_content_height(self, instance, val):
        self.height = val + dp(20)

    def on_release(self):
        # Mở Modal_view chi tiết sự kiện ở trang Search
        from event_modals import EventDetailModal
        EventDetailModal(event=self.event, on_event_updated=self._on_event_updated).open()

    def _on_event_updated(self, updated_event):
        """Cập nhật lại nhãn thời gian trên thẻ sau khi người dùng sửa giờ thành công."""
        self.event = updated_event
        try:
            st = datetime.fromisoformat(updated_event["start_time"])
            et = datetime.fromisoformat(updated_event["end_time"])
            days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_str = days_en[st.weekday()]
            date_str = st.strftime("%d/%m/%Y")
            s_str = st.strftime("%H:%M")
            e_str = et.strftime("%H:%M")
            if self.event.get("kind") == "DEADLINE":
                if self.labels:
                    self.labels[0].text = f"[b]Deadline:[/b] {self.event.get('title')} - {e_str} ({date_str})"
            else:
                if len(self.labels) >= 3:
                    self.labels[0].text = f"[b]{day_str}, {date_str}:[/b]"
                    self.labels[2].text = f"Time: {s_str} - {e_str}"
        except Exception:
            pass

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
        self.border_line.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(12)]

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
        self.search_mode = "schedule"  # "schedule" hoặc "academic"
        
        self.active_filters = {
            "CLASS": True, "EXAM": True, "EVENT": True, 
            "TASK": True, "DEADLINE": True
        }
        self.filter_important_only = False

        # Phân trang lazy loading: vẽ 15 thẻ mỗi đợt khi cuộn để chống giật lag
        self._all_matching_events = []
        self._rendered_count = 0
        self._batch_size = 15
        self._is_rendering_batch = False
        self._render_queue = []
        self._render_clock_event = None

        # Đăng ký lắng nghe thay đổi từ store để tự động làm mới kết quả tìm kiếm
        store.on_change(self._on_store_changed)
        Clock.schedule_once(self.build_ui, 0)

    def _on_store_changed(self):
        """Tự động làm mới kết quả tìm kiếm khi store.events có thay đổi (sửa giờ/thêm/xóa)."""
        if hasattr(self, "txt_search") and self.search_mode == "schedule":
            if self.get_root_window():
                self.perform_search()
            else:
                self._needs_refresh = True

    def show_loading(self):
        """
        Hiển thị biểu tượng xoay tròn (loading indicator) ở chính giữa khung chứa sự kiện.
        Đồng thời hủy các tiến trình vẽ dở dang và dọn sạch các thẻ sự kiện cũ.
        """
        self._cancel_progressive_rendering()
        if hasattr(self, "results_box"):
            self.results_box.clear_widgets()
        if hasattr(self, "loading_spinner"):
            self.loading_spinner.opacity = 1
            self.loading_spinner.active = True
            self.loading_spinner.disabled = False

    def hide_loading(self):
        """Ẩn biểu tượng xoay tròn sau khi đã bắt đầu nạp sự kiện hoặc tìm kiếm xong."""
        if hasattr(self, "loading_spinner"):
            self.loading_spinner.opacity = 0
            self.loading_spinner.active = False
            self.loading_spinner.disabled = True

    def _cancel_progressive_rendering(self):
        """Hủy bỏ hàng đợi vẽ dở dang nếu người dùng tìm kiếm mới, chuyển tab hoặc rời màn hình."""
        if self._render_clock_event is not None:
            self._render_clock_event.cancel()
            self._render_clock_event = None
        self._render_queue.clear()
        self._is_rendering_batch = False

    def on_pre_enter(self, *args):
        """
        Kích hoạt ngay khi bắt đầu bấm chuyển sang tab SearchScreen:
        Thay vì vẽ ngay lập tức gây khựng hiệu ứng chuyển tab, chỉ hiển thị biểu tượng loading
        ở chính giữa khung chứa sự kiện.
        """
        self.show_loading()

    def on_enter(self, *args):
        """
        Kích hoạt sau khi chuyển động chuyển tab hoàn tất:
        Bắt đầu xử lý tìm kiếm và lần lượt vẽ các thẻ sự kiện ra màn hình.
        """
        # Trì hoãn nhẹ 0.1s sau khi kết thúc chuyển động để đảm bảo frame chuyển động hoàn toàn mượt mà
        Clock.schedule_once(lambda dt: self.perform_search(), 0.1)
        store.refresh(api, on_done=self._on_store_refresh_done)

    def on_leave(self, *args):
        """Dọn dẹp hàng đợi vẽ dở dang khi người dùng rời khỏi màn hình tìm kiếm."""
        self._cancel_progressive_rendering()

    def _on_store_refresh_done(self):
        """Cập nhật lại kết quả tìm kiếm sau khi đồng bộ nền từ server hoàn tất."""
        if hasattr(self, "txt_search") and self.search_mode == "schedule":
            if self.get_root_window() and getattr(self.parent, "current", None) == self.name:
                self.perform_search()

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
            hint_text="Search title, date (e.g. math, 26/10)...", background_color=[0, 0, 0, 0],
            foreground_color=BLACK_COLOR, multiline=False, font_size=dp(15), 
            size_hint_y=None, height=dp(30), pos_hint={"center_y": .5}
        )
        input_bg.add_widget(self.txt_search)

        btn_search = MDIconButton(
            icon="magnify", theme_icon_color="Custom", icon_color=WHITE_COLOR, 
            pos_hint={"center_y": .5}, on_release=self.perform_search
        )
        self.btn_filter = MDIconButton(
            icon="filter", theme_icon_color="Custom", icon_color=WHITE_COLOR, 
            pos_hint={"center_y": .5}, on_release=self.open_filter_modal
        )
        
        top_search_bar.add_widget(input_bg)
        top_search_bar.add_widget(btn_search)
        top_search_bar.add_widget(self.btn_filter)
        self.main_layout.add_widget(top_search_bar)

        # Thanh chuyển đổi 2 chế độ: [Tìm lịch cá nhân] và [Hỏi đáp Học vụ]
        mode_bar_outer = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(44),
            padding=[dp(15), dp(4), dp(15), dp(4)], md_bg_color=WHITE_COLOR
        )
        is_pc = (platform not in ['android', 'ios']) and (Window.width >= dp(700))
        if is_pc:
            mode_bar = MDBoxLayout(
                orientation='horizontal',
                size_hint_x=None,
                width=min(dp(440), Window.width * 0.9),
                pos_hint={"center_x": 0.5},
                spacing=dp(10)
            )
            mode_bar_outer.add_widget(Widget(size_hint_x=1))
            mode_bar_outer.add_widget(mode_bar)
            mode_bar_outer.add_widget(Widget(size_hint_x=1))
        else:
            mode_bar = MDBoxLayout(
                orientation='horizontal',
                size_hint_x=1,
                spacing=dp(10)
            )
            mode_bar_outer.add_widget(mode_bar)

        self.btn_mode_schedule = MDButton(
            MDButtonText(text="My Schedule", font_style="Label", role="small"),
            style="filled", md_bg_color=BLUE_COLOR, size_hint_x=0.5,
            on_release=lambda x: self.switch_mode("schedule")
        )
        self.btn_mode_academic = MDButton(
            MDButtonText(text="Academic Q&A", font_style="Label", role="small"),
            style="outlined", size_hint_x=0.5,
            on_release=lambda x: self.switch_mode("academic")
        )
        mode_bar.add_widget(self.btn_mode_schedule)
        mode_bar.add_widget(self.btn_mode_academic)
        self.main_layout.add_widget(mode_bar_outer)

        # Khung chứa danh sách sự kiện và biểu tượng xoay tròn loading ở chính giữa
        self.results_container = FloatLayout(size_hint=(1, 1))

        self.results_scroll = ScrollView(size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self.results_scroll.bind(scroll_y=self._on_scroll)
        self.results_box = MDBoxLayout(orientation='vertical', size_hint_y=None, padding=dp(15), spacing=dp(10))
        self.results_box.bind(minimum_height=self.results_box.setter('height'))

        self.results_scroll.add_widget(self.results_box)
        self.results_container.add_widget(self.results_scroll)

        # Biểu tượng xoay tròn (loading indicator) đặt chính giữa khung chứa sự kiện
        self.loading_spinner = MDCircularProgressIndicator(
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
            color=BLUE_COLOR
        )
        self.loading_spinner.opacity = 0
        self.loading_spinner.active = False
        self.loading_spinner.disabled = True
        self.results_container.add_widget(self.loading_spinner)

        self.main_layout.add_widget(self.results_container)

        nav_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10), md_bg_color=WHITE_COLOR
        )
        nav_bar.add_widget(NavTab(text="Calendar", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Search", target_screen="search_home", is_active=True))
        nav_bar.add_widget(NavTab(text="AI Assistant", target_screen="chat_home", is_active=False))
        self.main_layout.add_widget(nav_bar)

        self.txt_search.bind(text=self.on_text_change)
        # Khởi tạo trạng thái chờ tải khi dựng UI ban đầu
        self.show_loading()

    def switch_mode(self, mode):
        self.search_mode = mode
        if mode == "schedule":
            self.btn_mode_schedule.style = "filled"
            self.btn_mode_schedule.md_bg_color = BLUE_COLOR
            if self.btn_mode_schedule.children:
                self.btn_mode_schedule.children[0].text_color = WHITE_COLOR

            self.btn_mode_academic.style = "outlined"
            self.btn_mode_academic.md_bg_color = WHITE_COLOR
            if self.btn_mode_academic.children:
                self.btn_mode_academic.children[0].text_color = BLUE_COLOR

            self.txt_search.hint_text = "Search title, date (e.g. math, 26/10)..."
            self.btn_filter.opacity = 1
            self.btn_filter.disabled = False
        else:
            self.btn_mode_schedule.style = "outlined"
            self.btn_mode_schedule.md_bg_color = WHITE_COLOR
            if self.btn_mode_schedule.children:
                self.btn_mode_schedule.children[0].text_color = BLUE_COLOR

            self.btn_mode_academic.style = "filled"
            self.btn_mode_academic.md_bg_color = BLUE_COLOR
            if self.btn_mode_academic.children:
                self.btn_mode_academic.children[0].text_color = WHITE_COLOR

            self.txt_search.hint_text = "Ask academic KB (e.g. graduation requirements)..."
            self.btn_filter.opacity = 0
            self.btn_filter.disabled = True

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
            text="EVENT FILTERS", bold=True, color=BLACK_COLOR,
            size_hint_y=None, height=dp(30) 
        )
        modal_content.add_widget(lbl_title)
        
        grid = GridLayout(cols=2, size_hint_y=None, spacing=dp(5))
        grid.bind(minimum_height=grid.setter('height'))
        
        options = {
            "CLASS": "Class", "EXAM": "Exam", 
            "EVENT": "Event", "TASK": "Task", 
            "DEADLINE": "Deadline"
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
        
        lbl_imp = Label(text="Important", color=BLACK_COLOR, bold=True, halign="left", valign="center")
        lbl_imp.bind(size=lbl_imp.setter('text_size'))
        
        box_imp.add_widget(chk_imp)
        box_imp.add_widget(lbl_imp)
        grid.add_widget(box_imp)
        
        modal_content.add_widget(grid)
        
        btn_apply = Button(
            text="Apply & Search",
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

    def _on_scroll(self, instance, scroll_y):
        """Lắng nghe sự kiện cuộn chuột/ngón tay; khi gần tới đáy (scroll_y <= 0.15) vẽ tiếp tối đa 15 thẻ."""
        if self.search_mode == "schedule" and scroll_y <= 0.15:
            self._render_next_batch()

    def _set_search_results(self, matching_events):
        """Khởi tạo danh sách kết quả và bắt đầu vẽ mẻ đầu tiên (tối đa 15 sự kiện) lần lượt."""
        self._cancel_progressive_rendering()
        self._all_matching_events = matching_events or []
        self._rendered_count = 0
        self.results_box.clear_widgets()

        if not self._all_matching_events:
            self.hide_loading()
            self.results_box.add_widget(MDLabel(
                text="No results found!",
                halign="center", theme_text_color="Custom", text_color=GRAY_TEXT,
                font_style="Body", role="large", size_hint_y=None, height=dp(50)
            ))
            return

        self.results_scroll.scroll_y = 1.0
        # Bắt đầu vẽ mẻ đầu tiên (tối đa 15 sự kiện), vẽ lần lượt qua Clock
        self._render_next_batch()

    def _render_next_batch(self):
        """
        Vẽ mẻ tiếp theo gồm tối đa 15 sự kiện:
        Thực hiện vẽ lần lượt (progressive rendering) qua từng nhịp Clock
        để giao diện hiển thị mượt mà, không bị khựng đơ khung hình.
        """
        if getattr(self, "_is_rendering_batch", False):
            return
        if self._rendered_count >= len(self._all_matching_events):
            self.hide_loading()
            return

        self._is_rendering_batch = True
        next_end = min(self._rendered_count + self._batch_size, len(self._all_matching_events))
        items_to_render = self._all_matching_events[self._rendered_count:next_end]
        
        # Đưa các sự kiện vào hàng đợi để vẽ lần lượt
        self._render_queue.extend(items_to_render)
        self._step_render()

    def _step_render(self, *args):
        """Vẽ lần lượt từng sự kiện trong hàng đợi qua từng nhịp Clock."""
        if not self._render_queue:
            self._is_rendering_batch = False
            self.hide_loading()
            return

        # Mỗi nhịp Clock thêm 1-2 sự kiện để mắt người dùng thấy xuất hiện nối tiếp và không drop frame
        batch_slice = 2
        for _ in range(batch_slice):
            if self._render_queue:
                event = self._render_queue.pop(0)
                card = EventCard(event)
                self.results_box.add_widget(card)
                self._rendered_count += 1

        # Ẩn spinner loading khi đã bắt đầu có thẻ sự kiện hiển thị
        if self._rendered_count > 0:
            self.hide_loading()

        if self._render_queue:
            self._render_clock_event = Clock.schedule_once(self._step_render, 0.015)
        else:
            self._is_rendering_batch = False

    # --- LOGIC TÌM KIẾM ---
    def on_text_change(self, instance, value):
        if self.search_event is not None:
            self.search_event.cancel()
        self.search_event = Clock.schedule_once(lambda dt: self.perform_search(), 0.4)

    def _redirect_to(self, target_screen):
        app = MDApp.get_running_app()
        if app and app.root and hasattr(app.root, "current"):
            app.root.current = target_screen

    def _show_redirect_banner(self, message, redirect_target, redirect_label):
        self.hide_loading()
        self.results_box.clear_widgets()
        card = MDBoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            md_bg_color=WHITE_COLOR,
            radius=[dp(12)],
            size_hint_y=None,
            adaptive_height=True,
        )
        card.add_widget(MDLabel(
            text=f"[Suggestion] {message}",
            theme_text_color="Primary",
            font_style="Body",
            role="medium",
            adaptive_height=True,
        ))
        nav_btn = MDButton(
            MDButtonText(text=f"Switch to {redirect_label}", text_color=WHITE_COLOR),
            style="filled",
            md_bg_color=BLUE_COLOR,
            size_hint=(None, None),
            size=(dp(220), dp(40)),
            pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._redirect_to(redirect_target)
        )
        card.add_widget(nav_btn)
        self.results_box.add_widget(card)

    def perform_search(self, *args):
        self.show_loading()
        query = self.txt_search.text.strip()
        if self.search_mode == "academic":
            self._perform_academic_search(query)
        else:
            self._perform_schedule_search(query)

    def _perform_schedule_search(self, query):
        if query and api.access_token:
            api.search_events_query(
                query,
                on_success=self._on_schedule_search_ok,
                on_failure=lambda req, res: self._local_schedule_filter(query.lower()),
                on_error=lambda req, err: self._local_schedule_filter(query.lower()),
            )
        else:
            self._local_schedule_filter(query.lower())

    def _on_schedule_search_ok(self, req, res):
        if not isinstance(res, dict):
            self._local_schedule_filter(self.txt_search.text.strip().lower())
            return

        redirect_target = res.get("redirect_target")
        redirect_label = res.get("redirect_button_label") or "AI Assistant"
        if redirect_target:
            self._show_redirect_banner(
                res.get("message") or "You may want to schedule this task with the assistant.",
                redirect_target,
                redirect_label,
            )
            return

        events = res.get("events", [])
        matching = []
        for event in events:
            kind = event.get("kind", "EVENT")
            is_important = event.get("is_important", False)
            if not self.active_filters.get(kind, True):
                continue
            if self.filter_important_only and not is_important:
                continue
            matching.append(event)

        self._set_search_results(matching)

    def _local_schedule_filter(self, query):
        matching = []
        for event in store.events:
            kind = event.get("kind", "EVENT")
            is_important = event.get("is_important", False)
            if not self.active_filters.get(kind, True):
                continue
            if self.filter_important_only and not is_important:
                continue

            try:
                ev_start = datetime.fromisoformat(event["start_time"])
                date_full_str = ev_start.strftime("%d/%m/%Y")
                date_short_str = ev_start.strftime("%d/%m")
            except Exception:
                date_full_str = ""
                date_short_str = ""

            match_text = (
                not query or
                query in event.get("title", "").lower() or
                query in kind.lower() or
                query in date_full_str or
                query in date_short_str
            )
            if match_text:
                matching.append(event)

        self._set_search_results(matching)

    def _perform_academic_search(self, query):
        if not query:
            self.hide_loading()
            self.results_box.clear_widgets()
            hint_box = MDBoxLayout(
                orientation='vertical', padding=dp(15), spacing=dp(8),
                md_bg_color=WHITE_COLOR, radius=[dp(12)], adaptive_height=True
            )
            hint_box.add_widget(MDLabel(
                text="Academic Knowledge Base Q&A",
                bold=True, font_style="Title", role="medium", adaptive_height=True
            ))
            hint_box.add_widget(MDLabel(
                text="You can ask about:\n- Graduation requirements, credits\n- Lecturers, departments, faculties\n- Prerequisites, course descriptions\n- Academic regulations, exams",
                theme_text_color="Secondary", font_style="Body", role="medium", adaptive_height=True
            ))
            self.results_box.add_widget(hint_box)
            return

        self.show_loading()
        api.ask_academic_kb(
            query,
            on_success=self._on_academic_ok,
            on_failure=self._on_academic_error,
            on_error=self._on_academic_error,
        )

    def _on_academic_ok(self, req, res):
        self.hide_loading()
        self.results_box.clear_widgets()
        if not isinstance(res, dict):
            self.results_box.add_widget(MDLabel(
                text="Invalid response received from server.",
                theme_text_color="Error", size_hint_y=None, height=dp(40)
            ))
            return

        redirect_target = res.get("redirect_target")
        redirect_label = res.get("redirect_button_label") or "AI Assistant"
        if redirect_target:
            self._show_redirect_banner(
                res.get("message") or "You may want to schedule this task with the assistant.",
                redirect_target,
                redirect_label,
            )
            return

        # Khung hiển thị câu trả lời
        ans_box = MDBoxLayout(
            orientation='vertical', padding=dp(15), spacing=dp(10),
            md_bg_color=WHITE_COLOR, radius=[dp(12)], adaptive_height=True
        )
        ans_box.add_widget(MDLabel(
            text="Answer from Academic Assistant:",
            bold=True, theme_text_color="Primary", font_style="Title", role="small", adaptive_height=True
        ))
        ans_text = res.get("answer") or "No matching information found for this question."
        ans_box.add_widget(MDLabel(
            text=ans_text,
            font_style="Body", role="medium", adaptive_height=True
        ))
        self.results_box.add_widget(ans_box)

        # Danh sách trích dẫn nguồn (citations)
        citations = res.get("citations") or []
        if citations:
            cite_container = MDBoxLayout(
                orientation='vertical', padding=dp(12), spacing=dp(8),
                md_bg_color=[0.96, 0.96, 0.98, 1], radius=[dp(10)], adaptive_height=True
            )
            cite_container.add_widget(MDLabel(
                text="Reference citations:",
                bold=True, theme_text_color="Secondary", font_style="Label", role="large", adaptive_height=True
            ))
            for i, c in enumerate(citations, 1):
                src = c.get("source", "Academic Document")
                txt = c.get("text", "")
                cite_box = MDBoxLayout(orientation='vertical', spacing=dp(3), adaptive_height=True)
                cite_box.add_widget(MDLabel(
                    text=f"[{i}] {src}", bold=True,
                    theme_text_color="Custom", text_color=BLUE_COLOR,
                    font_style="Label", role="medium", adaptive_height=True
                ))
                cite_box.add_widget(MDLabel(
                    text=txt,
                    theme_text_color="Secondary",
                    font_style="Body", role="small", adaptive_height=True
                ))
                cite_container.add_widget(cite_box)
            self.results_box.add_widget(cite_container)

    def _on_academic_error(self, req, err):
        self.hide_loading()
        self.results_box.clear_widgets()
        err_msg = "Cannot connect to academic search server."
        if isinstance(err, dict) and err.get("detail"):
            err_msg = f"Error: {err.get('detail')}"
        elif isinstance(err, str):
            err_msg = f"Error: {err}"
        self.results_box.add_widget(MDLabel(
            text=err_msg,
            theme_text_color="Error",
            halign="center",
            size_hint_y=None,
            height=dp(50)
        ))

if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return SearchScreen(name="search_home")
    TestApp().run()