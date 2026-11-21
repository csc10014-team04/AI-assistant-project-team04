"""
FILE: side_bar_menu.py
CHỨC NĂNG:
- Cung cấp một khung menu bên (Sidebar) có thể trượt ra từ mép trái màn hình.
- Tích hợp thông tin tài khoản cố định ở dưới cùng và nút Đăng xuất.
- Tích hợp hộp thoại tùy chọn xếp lịch (Schedule Preferences).
"""
from kivy.uix.modalview import ModalView
from kivy.utils import platform
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.animation import Animation
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.scrollview import ScrollView
from kivy.uix.behaviors import ButtonBehavior
from kivy.clock import Clock
from kivy.uix.gridlayout import GridLayout

import re
import datetime
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.dropdown import DropDown
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText
from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText


from api_client import api
from event_store import store

WHITE_COLOR = [1, 1, 1, 1]
BLUE_COLOR = [0, 51/255, 204/255, 1]
LIGHT_GRAY = [0.95, 0.95, 0.95, 1]
BLACK_COLOR = [0,0,0,1]
# ==============================================================================
# WIDGET THÔNG TIN TÀI KHOẢN (CỐ ĐỊNH DƯỚI CÙNG)
# ==============================================================================
class UserAccountWidget(ButtonBehavior, MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = dp(60)
        self.padding = dp(10)
        self.md_bg_color = LIGHT_GRAY
        
        # Nút đăng xuất (mặc định ẩn)
        self.logout_btn = MDButton(
            MDButtonText(text="Log out", text_color=[1, 0, 0, 1]),
            style="outlined", size_hint_x=1, pos_hint={"center_x": 0.5},
            opacity=0, disabled=True
        )
        self.logout_btn.bind(on_release=self.do_logout)
        self.logout_container = MDBoxLayout(size_hint_y=None, height=0, opacity=0)
        self.logout_container.add_widget(self.logout_btn)
        
        # Thông tin user
        self.info_box = MDBoxLayout(orientation='vertical')
        disp = api.display_name or getattr(api, "username", None) or "User"
        uname = getattr(api, "username", None) or (f"ID: {api.user_id}" if api.user_id else "username")
        uname_display = f"@{uname}" if not uname.startswith("ID:") else uname
        self.lbl_display = MDLabel(text=disp, bold=True, font_style="Body", role="medium")
        self.lbl_username = MDLabel(text=uname_display, theme_text_color="Hint", font_style="Label", role="small")
        self.info_box.add_widget(self.lbl_display)
        self.info_box.add_widget(self.lbl_username)
        
        self.add_widget(self.logout_container)
        self.add_widget(self.info_box)

    def on_release(self):
        # Toggle hiển thị nút Đăng xuất
        is_hidden = self.logout_container.height == 0
        self.logout_container.height = dp(40) if is_hidden else 0
        self.logout_container.opacity = 1 if is_hidden else 0
        self.logout_btn.disabled = not is_hidden
        self.logout_btn.opacity = 1 if is_hidden else 0
        self.height = dp(100) if is_hidden else dp(60)

    def do_logout(self, instance):
        api.clear_session()
        store.use_demo()
        app = MDApp.get_running_app()
        if app and app.root:
            app.root.current = "auth_screen" # Chuyển về màn hình đăng nhập



# ==============================================================================
# BỘ CHỌN GIỜ BẰNG GRID 4 CỘT (00:00 - 23:45, Bước nhảy 15 phút)
# ==============================================================================
class SimpleTimePicker(ModalView):
    """
    Bộ chọn giờ từ 00:00 đến 23:45 theo bước nhảy 15 phút (:00, :15, :30, :45) bằng Grid 4 cột.
    Thay thế Spinner cũ theo yêu cầu người dùng:
      - Cột 1: XX:00
      - Cột 2: XX:15
      - Cột 3: XX:30
      - Cột 4: XX:45
    """
    def __init__(self, mode="start", current_time="23:30", title=None, callback=None, **kwargs):
        super().__init__(**kwargs)
        is_mobile = (platform in ['android', 'ios']) or (Window.width < dp(600))
        if is_mobile:
            self.size_hint = (0.92, 0.8)
        else:
            self.size_hint = (None, 0.8)
            self.width = min(dp(480), Window.width * 0.85)
        self.auto_dismiss = True
        self.mode = mode
        self.callback = callback

        default_title = "Select Bedtime" if mode == "start" else "Select Wake-up Time"
        display_title = title or default_title

        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(14),
            spacing=dp(8),
            md_bg_color=WHITE_COLOR,
            radius=[dp(12)]
        )
        layout.add_widget(MDLabel(
            text=display_title,
            bold=True,
            font_style="Title",
            role="medium",
            adaptive_height=True,
            halign="center"
        ))

        scroll = ScrollView(size_hint=(1, 1))
        grid = GridLayout(cols=4, spacing=dp(6), size_hint_y=None)
        grid.bind(minimum_height=grid.setter('height'))

        # Dải lựa chọn từ 00:00 đến 23:45 với 4 mốc: :00, :15, :30, :45
        for h in range(24):
            for m in (0, 15, 30, 45):
                time_str = f"{h:02d}:{m:02d}"
                is_curr = (time_str == current_time)
                btn = Button(
                    text=time_str,
                    font_size=dp(13),
                    bold=is_curr,
                    background_normal='',
                    background_color=BLUE_COLOR if is_curr else [0.93, 0.94, 0.97, 1],
                    color=WHITE_COLOR if is_curr else [0.1, 0.1, 0.1, 1],
                    size_hint_y=None,
                    height=dp(36),
                    on_release=lambda _, ts=time_str: self._choose(ts)
                )
                grid.add_widget(btn)

        scroll.add_widget(grid)
        layout.add_widget(scroll)

        btn_cancel = Button(
            text="CANCEL",
            font_size=dp(13),
            background_normal='',
            background_color=[0.9, 0.9, 0.9, 1],
            color=[0.3, 0.3, 0.3, 1],
            size_hint_y=None,
            height=dp(38),
            on_release=self.dismiss
        )
        layout.add_widget(btn_cancel)
        self.add_widget(layout)

    def _choose(self, time_str):
        if self.callback:
            h, m = map(int, time_str.split(":"))
            t_obj = datetime.time(hour=h, minute=m)
            # Hỗ trợ truyền datetime.time object hoặc time string
            try:
                self.callback(t_obj, self.mode)
            except Exception:
                try:
                    self.callback(time_str, self.mode)
                except Exception:
                    pass
        self.dismiss()


# ==============================================================================
# BỘ CHỌN THỜI LƯỢNG BẰNG SPIN THỜI GIAN (SPINNER VÀ STEPPER 15 PHÚT)
# ==============================================================================
class DownwardDropDown(DropDown):
    """
    DropDown ép buộc luôn mở xổ xuống bên dưới widget gắn kèm,
    giới hạn chiều cao max_height để không bị tràn màn hình.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.max_height = dp(160)
        self.auto_width = False

    def _reposition(self, *args):
        widget = self.attach_to
        if not widget or not widget.get_root_window():
            return
        wx, wy = widget.to_window(widget.x, widget.y)
        self.x = wx
        self.width = widget.width
        # Luôn luôn mở xổ xuống bên dưới nút bấm
        self.y = wy - self.height


class DownwardSpinnerOption(SpinnerOption):
    """
    Các mục lựa chọn trong danh sách xổ xuống:
    - Nền sáng nhẹ, chữ đen rõ ràng
    - Chiều cao 38dp, viền phân cách
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = [0.95, 0.96, 0.98, 1]
        self.color = [0, 0, 0, 1]
        self.size_hint_y = None
        self.height = dp(38)
        self.font_size = dp(14)


class DurationSpinnerModal(ModalView):
    """
    Modal chọn thời lượng (phút) dạng Spin thời gian:
    - Thay thế dạng bảng Grid cũ theo yêu cầu người dùng.
    - Giữ nguyên toàn bộ các giá trị lựa chọn:
        + Break: 0 đến 120 phút, bước 15 phút (0, 15, 30, ..., 120 mins).
        + Max continuous: 30 đến 720 phút, bước 15 phút (30, 45, ..., 720 mins).
    - Cung cấp Spinner dropdown chọn nhanh xổ xuống bên dưới và 2 nút [-] / [+] để xoay/spin giá trị.
    - Nút giữa nền màu trắng chữ đen viền mảnh.
    """
    def __init__(self, title="Select Duration", current_val=30, start_min=0, max_min=120, step_min=15, on_select=None, **kwargs):
        super().__init__(**kwargs)
        is_mobile = (platform in ['android', 'ios']) or (Window.width < dp(600))
        if is_mobile:
            self.size_hint = (0.88, None)
            self.height = dp(240)
        else:
            self.size_hint = (None, None)
            self.width = min(dp(420), Window.width * 0.8)
            self.height = dp(240)
            
        self.auto_dismiss = True
        self.on_select = on_select
        self.start_min = start_min
        self.max_min = max_min
        self.step_min = step_min

        # Danh sách các mốc thời gian giữ nguyên không đổi
        self.valid_values = list(range(start_min, max_min + 1, step_min))
        try:
            curr_int = int(current_val)
        except (ValueError, TypeError):
            curr_int = start_min
        if curr_int not in self.valid_values:
            curr_int = self.valid_values[0]
        self.selected_val = curr_int

        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(16),
            spacing=dp(14),
            md_bg_color=WHITE_COLOR,
            radius=[dp(14)]
        )

        # Tiêu đề
        layout.add_widget(MDLabel(
            text=title,
            bold=True,
            font_style="Title",
            role="medium",
            adaptive_height=True,
            halign="center"
        ))

        # Khung Spin thời gian (Nút [-], Spinner dropdown xổ xuống dưới, Nút [+])
        spin_box = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(48),
            spacing=dp(10),
            padding=[dp(10), 0, dp(10), 0]
        )

        btn_minus = Button(
            text="-",
            font_size=dp(20),
            bold=True,
            background_normal='',
            background_color=[0.9, 0.92, 0.96, 1],
            color=BLUE_COLOR,
            size_hint=(None, 1),
            width=dp(48),
            on_release=self._decrement
        )

        # Nút giữa: Đổi thành màu trắng chữ đen, danh sách xổ xuống bên dưới
        self.spinner = Spinner(
            text=f"{self.selected_val} mins",
            values=[f"{v} mins" for v in self.valid_values],
            dropdown_cls=DownwardDropDown,
            option_cls=DownwardSpinnerOption,
            font_size=dp(15),
            bold=True,
            background_normal='',
            background_color=WHITE_COLOR,
            color=BLACK_COLOR,
            size_hint=(1, 1)
        )
        with self.spinner.canvas.before:
            Color(0.7, 0.7, 0.75, 1)
            self.spinner_border = Line(rounded_rectangle=[0, 0, 0, 0, dp(6)], width=1.1)
        self.spinner.bind(pos=self._update_spinner_border, size=self._update_spinner_border)
        self.spinner.bind(text=self._on_spinner_text)

        btn_plus = Button(
            text="+",
            font_size=dp(20),
            bold=True,
            background_normal='',
            background_color=[0.9, 0.92, 0.96, 1],
            color=BLUE_COLOR,
            size_hint=(None, 1),
            width=dp(48),
            on_release=self._increment
        )

        spin_box.add_widget(btn_minus)
        spin_box.add_widget(self.spinner)
        spin_box.add_widget(btn_plus)
        layout.add_widget(spin_box)

        # 2 nút hành động: Xác nhận & Hủy
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(42))
        btn_confirm = MDButton(
            MDButtonText(text="CONFIRM", text_color=WHITE_COLOR, bold=True),
            style="filled",
            md_bg_color=BLUE_COLOR,
            size_hint_x=0.5,
            on_release=self._confirm
        )
        btn_cancel = MDButton(
            MDButtonText(text="CANCEL"),
            style="outlined",
            size_hint_x=0.5,
            on_release=self.dismiss
        )
        btn_box.add_widget(btn_confirm)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)

        self.add_widget(layout)

    def _update_spinner_border(self, *args):
        self.spinner_border.rounded_rectangle = [
            self.spinner.x, self.spinner.y, self.spinner.width, self.spinner.height, dp(6)
        ]

    def _decrement(self, *args):
        idx = self.valid_values.index(self.selected_val) if self.selected_val in self.valid_values else 0
        if idx > 0:
            self.selected_val = self.valid_values[idx - 1]
            self.spinner.text = f"{self.selected_val} mins"

    def _increment(self, *args):
        idx = self.valid_values.index(self.selected_val) if self.selected_val in self.valid_values else 0
        if idx < len(self.valid_values) - 1:
            self.selected_val = self.valid_values[idx + 1]
            self.spinner.text = f"{self.selected_val} mins"

    def _on_spinner_text(self, instance, text):
        try:
            val_int = int(text.replace("mins", "").strip())
            if val_int in self.valid_values:
                self.selected_val = val_int
        except Exception:
            pass

    def _confirm(self, *args):
        if self.on_select:
            self.on_select(self.selected_val)
        self.dismiss()


# Alias tương thích ngược
DurationGridPickerModal = DurationSpinnerModal


# ==============================================================================
# HỘP THOẠI TÙY CHỌN XẾP LỊCH
# ==============================================================================
class SchedulePreferencesDialog(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.8)
        self.background_color = [0, 0, 0, 0.6]

        self.break_minutes = 30
        self.max_continuous_minutes = 180

        layout = MDBoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15), md_bg_color=WHITE_COLOR, radius=[dp(12)])
        layout.add_widget(MDLabel(text="Scheduling Preferences", font_style="Title", role="large", bold=True, size_hint_y=None, height=dp(40)))

        scroll = ScrollView(size_hint=(1, 1))
        content = MDBoxLayout(orientation='vertical', spacing=dp(20), adaptive_height=True)

        # 1. Giờ đi ngủ & thức dậy (Grid 4 cột 15 phút)
        bedtime_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))
        self.btn_start_sleep = MDButton(MDButtonText(text="Sleep: 23:30"), style="outlined", size_hint_x=0.5, on_release=lambda x: self.show_time_picker("start"))
        self.btn_end_sleep = MDButton(MDButtonText(text="Wake: 06:30"), style="outlined", size_hint_x=0.5, on_release=lambda x: self.show_time_picker("end"))
        bedtime_box.add_widget(self.btn_start_sleep)
        bedtime_box.add_widget(self.btn_end_sleep)
        content.add_widget(bedtime_box)

        # 2. Thời gian nghỉ giữa ca (Grid 5 cột: 0 - 120 phút)
        self.btn_break = MDButton(
            MDButtonText(text=f"Break: {self.break_minutes} mins"),
            style="outlined",
            size_hint_x=1,
            on_release=self.show_break_picker
        )
        content.add_widget(self.btn_break)

        # 3. Thời lượng liên tục tối đa (Grid 5 cột: 30 - 720 phút)
        self.btn_max_duration = MDButton(
            MDButtonText(text=f"Max block: {self.max_continuous_minutes} mins"),
            style="outlined",
            size_hint_x=1,
            on_release=self.show_max_duration_picker
        )
        content.add_widget(self.btn_max_duration)

        scroll.add_widget(content)
        layout.add_widget(scroll)

        # Nút lưu & hủy
        btn_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))
        btn_save = MDButton(MDButtonText(text="SAVE PREFERENCES", text_color=WHITE_COLOR), style="filled", md_bg_color=BLUE_COLOR, size_hint_x=1, on_release=self.save_preferences)
        btn_cancel = MDButton(MDButtonText(text="CANCEL"), style="outlined", size_hint_x=1, on_release=self.dismiss)
        btn_box.add_widget(btn_save)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)

        self.add_widget(layout)

    @property
    def tf_break(self):
        class _TfProxy:
            def __init__(proxy_self, parent):
                proxy_self.parent = parent
            @property
            def text(proxy_self):
                return str(proxy_self.parent.break_minutes)
            @text.setter
            def text(proxy_self, val):
                try:
                    proxy_self.parent.break_minutes = int(val)
                    if hasattr(proxy_self.parent, "btn_break") and proxy_self.parent.btn_break.children:
                        proxy_self.parent.btn_break.children[0].text = f"Break: {val} mins"
                except Exception:
                    pass
        return _TfProxy(self)

    @property
    def tf_max_duration(self):
        class _TfProxy:
            def __init__(proxy_self, parent):
                proxy_self.parent = parent
            @property
            def text(proxy_self):
                return str(proxy_self.parent.max_continuous_minutes)
            @text.setter
            def text(proxy_self, val):
                try:
                    proxy_self.parent.max_continuous_minutes = int(val)
                    if hasattr(proxy_self.parent, "btn_max_duration") and proxy_self.parent.btn_max_duration.children:
                        proxy_self.parent.btn_max_duration.children[0].text = f"Max block: {val} mins"
                except Exception:
                    pass
        return _TfProxy(self)

    def show_time_picker(self, mode):
        btn = self.btn_start_sleep if mode == "start" else self.btn_end_sleep
        btn_text = btn.children[0].text if btn.children else ""
        match = re.search(r"(\d{1,2}:\d{2})", btn_text)
        curr_time = match.group(1) if match else ("23:30" if mode == "start" else "06:30")
        picker = SimpleTimePicker(
            mode=mode,
            current_time=curr_time,
            title="Select Bedtime" if mode == "start" else "Select Wake-up Time",
            callback=self.on_time_save
        )
        picker.open()

    def on_time_save(self, time_obj, mode):
        time_str = time_obj.strftime("%H:%M") if hasattr(time_obj, "strftime") else str(time_obj)
        if mode == "start":
            self.btn_start_sleep.children[0].text = f"Sleep: {time_str}"
        else:
            self.btn_end_sleep.children[0].text = f"Wake: {time_str}"

    def show_break_picker(self, instance):
        picker = DurationGridPickerModal(
            title="Break duration between sessions (mins)",
            current_val=self.break_minutes,
            start_min=0,
            max_min=120,
            step_min=15,
            on_select=self.on_break_save
        )
        picker.open()

    def on_break_save(self, val):
        self.break_minutes = int(val)
        if hasattr(self, 'btn_break') and self.btn_break.children:
            self.btn_break.children[0].text = f"Break: {self.break_minutes} mins"

    def show_max_duration_picker(self, instance):
        picker = DurationGridPickerModal(
            title="Max continuous session (mins)",
            current_val=self.max_continuous_minutes,
            start_min=30,
            max_min=720,
            step_min=15,
            on_select=self.on_max_duration_save
        )
        picker.open()

    def on_max_duration_save(self, val):
        self.max_continuous_minutes = int(val)
        if hasattr(self, 'btn_max_duration') and self.btn_max_duration.children:
            self.btn_max_duration.children[0].text = f"Max block: {self.max_continuous_minutes} mins"

    def save_preferences(self, instance):
        start_txt = self.btn_start_sleep.children[0].text if self.btn_start_sleep.children else "Sleep: 23:30"
        end_txt = self.btn_end_sleep.children[0].text if self.btn_end_sleep.children else "Wake: 06:30"
        payload = {
            "sleep_schedule": f"{start_txt} - {end_txt}",
            "min_break_minutes": self.break_minutes,
            "max_continuous_minutes": self.max_continuous_minutes,
        }
        try:
            api.store.put("user_preferences", **payload)
        except Exception:
            pass
        api._request(
            "/api/v1/user/preferences",
            method="POST",
            payload=payload,
            on_success=lambda req, res: print("Đã lưu tùy chọn thành công:", res),
            on_failure=lambda req, res: print("Server chưa hỗ trợ lưu preferences online, đã lưu cục bộ."),
            on_error=lambda req, err: print("Lỗi mạng khi lưu tùy chọn, đã lưu cục bộ."),
        )
        print("Đã gửi yêu cầu lưu tùy chọn:", payload)
        self.dismiss()

# ==============================================================================
# LỚP SIDEBAR CHÍNH
# ==============================================================================
class SideBarMenu(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._is_animating_close = False
        self.bind(on_pre_dismiss=self.animate_close)
        self.background = "" 
        self.background_color = [0, 0, 0, 0.5]
        self.size_hint = (1, 1) 
        
        # Giá trị mặc định cho cấu hình xếp lịch
        self.break_minutes = 30
        self.max_continuous_minutes = 180 
        
        is_mobile_mode = (platform in ['android', 'ios']) or (Window.width < dp(800))
        self.menu_width = Window.width * 0.8 if is_mobile_mode else Window.width * 0.25

        # Khung nội dung chính
        self.main_container = MDBoxLayout(
            orientation='vertical',
            md_bg_color=WHITE_COLOR,
            size_hint=(None, 1),
            width=self.menu_width
        )
        
        with self.main_container.canvas.before:
            Color(*WHITE_COLOR)
            self.bg_rect = RoundedRectangle(radius=[0, dp(15), dp(15), 0])
        self.main_container.bind(pos=self.update_canvas, size=self.update_canvas)

        # 1. BLOCK MÀU XANH Ở TRÊN CÙNG (Nút trở về & Tiêu đề "Menu")
        self.header = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(56),
            padding=[dp(6), dp(4), dp(12), dp(4)],
            spacing=dp(8),
            md_bg_color=BLUE_COLOR,
        )
        with self.header.canvas.before:
            Color(*BLUE_COLOR)
            self.header_bg = RoundedRectangle(radius=[0, dp(15), 0, 0])
        self.header.bind(pos=self._update_header_canvas, size=self._update_header_canvas)

        btn_back = MDIconButton(
            icon="arrow-left",
            theme_icon_color="Custom",
            icon_color=WHITE_COLOR,
            pos_hint={"center_y": 0.5}
        )
        btn_back.bind(on_release=lambda x: self.dismiss())
        
        lbl_title = MDLabel(
            text="Menu",
            bold=True,
            font_style="Title",
            role="medium",
            theme_text_color="Custom",
            text_color=WHITE_COLOR,
            pos_hint={"center_y": 0.5}
        )
        self.header.add_widget(btn_back)
        self.header.add_widget(lbl_title)
        
        # 2. MENU CUỘN - TÙY CHỌN XẾP LỊCH XỔ XUỐNG TRỰC TIẾP
        self.scroll = ScrollView(size_hint=(1, 1))
        self.menu_list = MDBoxLayout(orientation='vertical', adaptive_height=True, padding=dp(12), spacing=dp(10))
        
        # Ô chức năng: Thời gian báo lại (chỉ cho phép nhập số, gồm 2 ô: Giờ và Phút)
        snooze_title = MDLabel(
            text="Snooze Time",
            bold=True,
            font_style="Title",
            role="small",
            theme_text_color="Custom",
            text_color=BLUE_COLOR,
            size_hint_y=None,
            height=dp(28)
        )
        self.menu_list.add_widget(snooze_title)

        snooze_row = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(48), spacing=dp(8))
        self.tf_snooze_h = MDTextField(
            MDTextFieldHintText(text="Hours"),
            text="0",
            mode="outlined",
            size_hint_x=0.5,
            input_filter="int"
        )
        self.tf_snooze_m = MDTextField(
            MDTextFieldHintText(text="Mins"),
            text="5",
            mode="outlined",
            size_hint_x=0.5,
            input_filter="int"
        )
        self.tf_snooze_h.bind(text=self._on_snooze_changed)
        self.tf_snooze_m.bind(text=self._on_snooze_changed)
        snooze_row.add_widget(self.tf_snooze_h)
        snooze_row.add_widget(self.tf_snooze_m)
        self.menu_list.add_widget(snooze_row)

        # Header Tùy chọn xếp lịch
        pref_title = MDLabel(
            text="Scheduling Preferences",
            bold=True,
            font_style="Title",
            role="small",
            theme_text_color="Custom",
            text_color=BLUE_COLOR,
            size_hint_y=None,
            height=dp(30)
        )
        self.menu_list.add_widget(pref_title)

        # 1. Giờ đi ngủ & thức dậy
        self.menu_list.add_widget(MDLabel(
            text="Sleep Schedule:",
            font_style="Body",
            role="small",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(20)
        ))
        bedtime_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(42), spacing=dp(8))
        self.btn_start_sleep = MDButton(
            MDButtonText(text="Sleep: 23:30"),
            style="outlined",
            size_hint_x=0.5,
            on_release=lambda x: self.show_time_picker("start")
        )
        self.btn_end_sleep = MDButton(
            MDButtonText(text="Wake: 06:30"),
            style="outlined",
            size_hint_x=0.5,
            on_release=lambda x: self.show_time_picker("end")
        )
        bedtime_box.add_widget(self.btn_start_sleep)
        bedtime_box.add_widget(self.btn_end_sleep)
        self.menu_list.add_widget(bedtime_box)

        # 2. Thời gian nghỉ đệm (Grid 5 cột: 0 - 120 phút)
        self.menu_list.add_widget(MDLabel(
            text="Break between sessions:",
            font_style="Body",
            role="small",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(20)
        ))
        self.btn_break = MDButton(
            MDButtonText(text=f"{self.break_minutes} mins"),
            style="outlined",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(42),
            on_release=self.show_break_picker
        )
        self.menu_list.add_widget(self.btn_break)

        # 3. Thời lượng liên tục tối đa (Grid 5 cột: 30 - 720 phút)
        self.menu_list.add_widget(MDLabel(
            text="Max continuous session:",
            font_style="Body",
            role="small",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(20)
        ))
        self.btn_max_duration = MDButton(
            MDButtonText(text=f"{self.max_continuous_minutes} mins"),
            style="outlined",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(42),
            on_release=self.show_max_duration_picker
        )
        self.menu_list.add_widget(self.btn_max_duration)

        # Trạng thái lưu
        self.lbl_pref_status = MDLabel(
            text="",
            font_style="Label",
            role="small",
            theme_text_color="Custom",
            text_color=[0, 0.6, 0, 1],
            size_hint_y=None,
            height=dp(20)
        )
        self.menu_list.add_widget(self.lbl_pref_status)

        # Nút Lưu
        btn_save = MDButton(
            MDButtonText(text="SAVE PREFERENCES", text_color=WHITE_COLOR),
            style="filled",
            md_bg_color=BLUE_COLOR,
            size_hint_x=1,
            size_hint_y=None,
            height=dp(42),
            on_release=self.save_preferences
        )
        self.menu_list.add_widget(btn_save)
        self.scroll.add_widget(self.menu_list)

        # 3. THÔNG TIN TÀI KHOẢN (Cố định dưới cùng)
        self.user_widget = UserAccountWidget()
        
        self.main_container.add_widget(self.header)
        self.main_container.add_widget(self.scroll)
        self.main_container.add_widget(self.user_widget)

        self.add_widget(self.main_container)

    def _update_header_canvas(self, *args):
        if hasattr(self, 'header_bg') and hasattr(self, 'header'):
            self.header_bg.pos = self.header.pos
            self.header_bg.size = self.header.size

    def _on_snooze_changed(self, instance, value):
        from notifier import set_snooze_interval
        try:
            h = int(self.tf_snooze_h.text.strip() or 0)
        except ValueError:
            h = 0
        try:
            m = int(self.tf_snooze_m.text.strip() or 0)
        except ValueError:
            m = 5
        total_mins = max(1, h * 60 + m)
        set_snooze_interval(total_mins)
        # Lưu vào local store vĩnh viễn để ghi nhớ thời gian báo lại
        try:
            api.store.put("snooze_settings", hours=h, minutes=m, total_mins=total_mins)
        except Exception:
            pass

    @property
    def tf_break(self):
        """Proxy thuộc tính để đảm bảo tương thích ngược nếu có code cũ gọi self.tf_break.text."""
        class _TfProxy:
            def __init__(proxy_self, parent):
                proxy_self.parent = parent
            @property
            def text(proxy_self):
                return str(proxy_self.parent.break_minutes)
            @text.setter
            def text(proxy_self, val):
                try:
                    proxy_self.parent.break_minutes = int(val)
                    if hasattr(proxy_self.parent, "btn_break") and proxy_self.parent.btn_break.children:
                        proxy_self.parent.btn_break.children[0].text = f"{val} mins"
                except Exception:
                    pass
        return _TfProxy(self)

    @property
    def tf_max_duration(self):
        """Proxy thuộc tính để đảm bảo tương thích ngược nếu có code cũ gọi self.tf_max_duration.text."""
        class _TfProxy:
            def __init__(proxy_self, parent):
                proxy_self.parent = parent
            @property
            def text(proxy_self):
                return str(proxy_self.parent.max_continuous_minutes)
            @text.setter
            def text(proxy_self, val):
                try:
                    proxy_self.parent.max_continuous_minutes = int(val)
                    if hasattr(proxy_self.parent, "btn_max_duration") and proxy_self.parent.btn_max_duration.children:
                        proxy_self.parent.btn_max_duration.children[0].text = f"{val} mins"
                except Exception:
                    pass
        return _TfProxy(self)

    def show_time_picker(self, mode):
        """Mở modal chọn giờ (Grid 4 cột 15 phút: :00, :15, :30, :45)."""
        btn = self.btn_start_sleep if mode == "start" else self.btn_end_sleep
        btn_text = btn.children[0].text if btn.children else ""
        match = re.search(r"(\d{1,2}:\d{2})", btn_text)
        curr_time = match.group(1) if match else ("23:30" if mode == "start" else "06:30")
        picker = SimpleTimePicker(
            mode=mode,
            current_time=curr_time,
            title="Select Bedtime" if mode == "start" else "Select Wake-up Time",
            callback=self.on_time_save
        )
        picker.open()

    def on_time_save(self, time_obj, mode):
        """Cập nhật nhãn nút giờ ngủ / thức dậy sau khi người dùng chọn mốc thời gian."""
        time_str = time_obj.strftime("%H:%M") if hasattr(time_obj, "strftime") else str(time_obj)
        if mode == "start":
            self.btn_start_sleep.children[0].text = f"Sleep: {time_str}"
        else:
            self.btn_end_sleep.children[0].text = f"Wake: {time_str}"

    def show_break_picker(self, *args):
        """Mở modal chọn thời gian nghỉ giữa ca (Grid 5 cột: 0 - 120 phút, scale 15 phút)."""
        picker = DurationGridPickerModal(
            title="Break duration between sessions (mins)",
            current_val=self.break_minutes,
            start_min=0,
            max_min=120,
            step_min=15,
            on_select=self.on_break_save
        )
        picker.open()

    def on_break_save(self, val):
        """Lưu giá trị thời gian nghỉ giữa ca được chọn."""
        self.break_minutes = int(val)
        if hasattr(self, 'btn_break') and self.btn_break.children:
            self.btn_break.children[0].text = f"{self.break_minutes} mins"

    def show_max_duration_picker(self, *args):
        """Mở modal chọn thời lượng liên tục tối đa (Grid 5 cột: 30 - 720 phút, scale 15 phút)."""
        picker = DurationGridPickerModal(
            title="Max continuous session (mins)",
            current_val=self.max_continuous_minutes,
            start_min=30,
            max_min=720,
            step_min=15,
            on_select=self.on_max_duration_save
        )
        picker.open()

    def on_max_duration_save(self, val):
        """Lưu giá trị thời lượng liên tục tối đa được chọn."""
        self.max_continuous_minutes = int(val)
        if hasattr(self, 'btn_max_duration') and self.btn_max_duration.children:
            self.btn_max_duration.children[0].text = f"{self.max_continuous_minutes} mins"

    def save_preferences(self, instance):
        """Lưu cấu hình xếp lịch vào Local Store và gửi cập nhật lên Backend Server."""
        start_txt = self.btn_start_sleep.children[0].text if self.btn_start_sleep.children else "Sleep: 23:30"
        end_txt = self.btn_end_sleep.children[0].text if self.btn_end_sleep.children else "Wake: 06:30"
        payload = {
            "sleep_schedule": f"{start_txt} - {end_txt}",
            "min_break_minutes": self.break_minutes,
            "max_continuous_minutes": self.max_continuous_minutes,
        }
        try:
            api.store.put("user_preferences", **payload)
        except Exception:
            pass

        def on_ok(req, res):
            self.lbl_pref_status.text = "Preferences saved successfully!"
            Clock.schedule_once(lambda dt: setattr(self.lbl_pref_status, "text", ""), 3)

        api._request(
            "/api/v1/user/preferences",
            method="POST",
            payload=payload,
            on_success=on_ok,
            on_failure=lambda req, res: on_ok(None, None),
            on_error=lambda req, err: on_ok(None, None),
        )

    def load_preferences(self):
        """Tải cấu hình xếp lịch từ Local Store dự phòng và đồng bộ với Backend Server."""
        try:
            if api.store.exists("user_preferences"):
                data = api.store.get("user_preferences")
                sched = data.get("sleep_schedule", "")
                if " - " in sched:
                    parts = sched.split(" - ")
                    if len(parts) == 2 and self.btn_start_sleep.children and self.btn_end_sleep.children:
                        self.btn_start_sleep.children[0].text = parts[0]
                        self.btn_end_sleep.children[0].text = parts[1]
                if data.get("min_break_minutes") is not None:
                    self.break_minutes = int(data["min_break_minutes"])
                    if hasattr(self, 'btn_break') and self.btn_break.children:
                        self.btn_break.children[0].text = f"{self.break_minutes} mins"
                if data.get("max_continuous_minutes") is not None:
                    self.max_continuous_minutes = int(data["max_continuous_minutes"])
                    if hasattr(self, 'btn_max_duration') and self.btn_max_duration.children:
                        self.btn_max_duration.children[0].text = f"{self.max_continuous_minutes} mins"
        except Exception:
            pass

        # Đồng bộ từ Backend Server nếu đã có token đăng nhập
        def on_server_pref(req, res):
            if isinstance(res, dict):
                s_start = res.get("sleep_start", "23:30")
                s_end = res.get("sleep_end", "06:30")
                if self.btn_start_sleep.children:
                    self.btn_start_sleep.children[0].text = f"Sleep: {s_start}"
                if self.btn_end_sleep.children:
                    self.btn_end_sleep.children[0].text = f"Wake: {s_end}"
                if "min_break_minutes" in res and res["min_break_minutes"] is not None:
                    self.break_minutes = int(res["min_break_minutes"])
                    if hasattr(self, 'btn_break') and self.btn_break.children:
                        self.btn_break.children[0].text = f"{self.break_minutes} mins"
                if "max_block_minutes" in res and res["max_block_minutes"] is not None:
                    self.max_continuous_minutes = int(res["max_block_minutes"])
                    if hasattr(self, 'btn_max_duration') and self.btn_max_duration.children:
                        self.btn_max_duration.children[0].text = f"{self.max_continuous_minutes} mins"

        if getattr(api, "token", None):
            api._request(
                "/api/v1/user/preferences",
                method="GET",
                on_success=on_server_pref,
                on_failure=lambda req, res: None,
                on_error=lambda req, err: None,
            )

    def update_canvas(self, *args):
        self.bg_rect.pos = self.main_container.pos
        self.bg_rect.size = self.main_container.size

    def open(self, *args, **kwargs):
        self._is_animating_close = False
        self.main_container.x = -self.menu_width
        # Cập nhật lại thông tin user & preferences mỗi lần mở menu
        self.load_preferences()
        if api.store.exists("snooze_settings"):
            try:
                s_data = api.store.get("snooze_settings")
                self.tf_snooze_h.text = str(s_data.get("hours", 0))
                self.tf_snooze_m.text = str(s_data.get("minutes", 5))
            except Exception:
                pass
        disp = api.display_name or getattr(api, "username", None) or "User"
        uname = getattr(api, "username", None) or (f"ID: {api.user_id}" if api.user_id else "username")
        uname_display = f"@{uname}" if not uname.startswith("ID:") else uname
        self.user_widget.lbl_display.text = disp
        self.user_widget.lbl_username.text = uname_display
        self.user_widget.logout_container.height = 0
        self.user_widget.logout_container.opacity = 0
        self.user_widget.logout_btn.disabled = True
        self.user_widget.height = dp(60)

        super().open(*args, **kwargs)
        anim = Animation(x=0, duration=0.25, t='out_quad')
        anim.start(self.main_container)

    def animate_close(self, instance):
        if self._is_animating_close:
            return False 
        self._is_animating_close = True
        anim = Animation(x=-self.menu_width, duration=0.2, t='in_quad')
        anim.bind(on_complete=lambda *args: self.dismiss())
        anim.start(self.main_container)
        return True 

    def on_touch_down(self, touch):
        # Tự động gập nút Đăng xuất nếu bấm ra ngoài vùng UserAccountWidget
        if not self.user_widget.collide_point(*touch.pos):
            self.user_widget.logout_container.height = 0
            self.user_widget.logout_container.opacity = 0
            self.user_widget.logout_btn.disabled = True
            self.user_widget.height = dp(60)
        return super().on_touch_down(touch)

# ==============================================================================
# HÀM TEST ĐỘC LẬP
# ==============================================================================
if __name__ == "__main__":
    from kivymd.uix.screen import MDScreen
    Window.size = (360, 640)

    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            screen = MDScreen(md_bg_color=[0.9, 0.9, 0.9, 1])
            btn = MDButton(
                MDButtonText(text="Open Sidebar Menu"),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
                on_release=lambda x: SideBarMenu().open()
            )
            screen.add_widget(btn)
            return screen

    TestApp().run()