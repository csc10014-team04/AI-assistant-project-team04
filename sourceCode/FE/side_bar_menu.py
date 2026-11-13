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
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.scrollview import ScrollView
from kivy.uix.behaviors import ButtonBehavior
from kivy.clock import Clock

import datetime
from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.spinner import Spinner
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText
from kivymd.app import MDApp
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText


from api_client import api

WHITE_COLOR = [1, 1, 1, 1]
BLUE_COLOR = [0, 51/255, 204/255, 1]
LIGHT_GRAY = [0.95, 0.95, 0.95, 1]

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
            MDButtonText(text="Đăng xuất", text_color=[1, 0, 0, 1]),
            style="outlined", size_hint_x=1, pos_hint={"center_x": 0.5},
            opacity=0, disabled=True
        )
        self.logout_btn.bind(on_release=self.do_logout)
        self.logout_container = MDBoxLayout(size_hint_y=None, height=0, opacity=0)
        self.logout_container.add_widget(self.logout_btn)
        
        # Thông tin user
        self.info_box = MDBoxLayout(orientation='vertical')
        self.lbl_display = MDLabel(text=api.display_name or "Người dùng", bold=True, font_style="Body", role="medium")
        self.lbl_username = MDLabel(text=f"ID: {api.user_id or 'username'}", theme_text_color="Hint", font_style="Label", role="small")
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
        app = MDApp.get_running_app()
        if app.root:
            app.root.current = "auth" # Chuyển về màn hình đăng nhập



# ==============================================================================
# BỘ CHỌN GIỜ BẰNG KIVY THUẦN (Không dùng KivyMD)
# ==============================================================================
class SimpleTimePicker(Popup):
    def __init__(self, mode, callback, **kwargs):
        super().__init__(**kwargs)
        self.title = "Chọn giờ"
        self.size_hint = (0.8, 0.4)
        self.mode = mode
        self.callback = callback

        # Layout chính của Popup
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        # Khung chọn Giờ : Phút
        time_layout = BoxLayout(orientation='horizontal', spacing=10)
        
        self.hour_spinner = Spinner(
            text='12',
            values=[f"{i:02d}" for i in range(24)],
            size_hint=(0.5, 1)
        )
        self.minute_spinner = Spinner(
            text='00',
            values=[f"{i:02d}" for i in range(60)],
            size_hint=(0.5, 1)
        )
        
        time_layout.add_widget(self.hour_spinner)
        time_layout.add_widget(Label(text=":", size_hint_x=None, width=dp(20)))
        time_layout.add_widget(self.minute_spinner)
        
        layout.add_widget(time_layout)
        
        # Nút Lưu và Hủy
        btn_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=dp(40))
        btn_save = Button(text="Lưu", background_color=[0, 0.5, 1, 1])
        btn_save.bind(on_release=self.save_time)
        btn_cancel = Button(text="Hủy", background_color=[0.8, 0.2, 0.2, 1])
        btn_cancel.bind(on_release=self.dismiss)
        
        btn_layout.add_widget(btn_save)
        btn_layout.add_widget(btn_cancel)
        
        layout.add_widget(btn_layout)
        self.content = layout

    def save_time(self, instance):
        # Lấy giá trị giờ, phút và tạo object thời gian
        h = int(self.hour_spinner.text)
        m = int(self.minute_spinner.text)
        selected_time = datetime.time(hour=h, minute=m)
        
        # Gọi callback để truyền dữ liệu về màn hình chính
        if self.callback:
            self.callback(selected_time, self.mode)
        self.dismiss()
# ==============================================================================
# HỘP THOẠI TÙY CHỌN XẾP LỊCH
# ==============================================================================
class SchedulePreferencesDialog(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.8)
        self.background_color = [0, 0, 0, 0.6]
        
        layout = MDBoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15), md_bg_color=WHITE_COLOR, radius=[dp(12)])
        
        layout.add_widget(MDLabel(text="Tùy chọn xếp lịch", font_style="Title", role="large", bold=True, size_hint_y=None, height=dp(40)))
        
        scroll = ScrollView(size_hint=(1, 1))
        content = MDBoxLayout(orientation='vertical', spacing=dp(20), adaptive_height=True)
        
        # 1. Giờ đi ngủ
        bedtime_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))
        self.btn_start_sleep = MDButton(MDButtonText(text="Ngủ: 23:30"), on_release=lambda x: self.show_time_picker("start"))
        self.btn_end_sleep = MDButton(MDButtonText(text="Dậy: 06:30"), on_release=lambda x: self.show_time_picker("end"))
        bedtime_box.add_widget(self.btn_start_sleep)
        bedtime_box.add_widget(self.btn_end_sleep)
        content.add_widget(bedtime_box)
        
        # 2. Thời gian nghỉ đệm
        self.tf_break = MDTextField(MDTextFieldHintText(text="Nghỉ giữa ca (30 - 60 phút)"), text="30", mode="outlined")
        content.add_widget(self.tf_break)
        
        # 3. Thời lượng tối đa
        self.tf_max_duration = MDTextField(MDTextFieldHintText(text="Làm việc liên tục tối đa (phút)"), text="180", mode="outlined")
        content.add_widget(self.tf_max_duration)
        
        # 4. Thói quen (Natural language)
        self.tf_habits = MDTextField(
            MDTextFieldHintText(text="Thói quen (VD: Thích học sáng, không xếp lịch sau 21h)"),
            multiline=True, mode="outlined", size_hint_y=None, height=dp(100)
        )
        content.add_widget(self.tf_habits)
        
        scroll.add_widget(content)
        layout.add_widget(scroll)
        
        # Nút lưu
        btn_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))
        btn_save = MDButton(MDButtonText(text="LƯU TÙY CHỌN", text_color=WHITE_COLOR), style="filled", md_bg_color=BLUE_COLOR, size_hint_x=1, on_release=self.save_preferences)
        btn_cancel = MDButton(MDButtonText(text="HỦY"), style="outlined", size_hint_x=1, on_release=self.dismiss)
        btn_box.add_widget(btn_save)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        
        self.add_widget(layout)

    def show_time_picker(self, mode):
        # Dùng bộ chọn giờ Kivy thuần thay cho MDTimePicker
        picker = SimpleTimePicker(mode=mode, callback=self.on_time_save)
        picker.open()

    def on_time_save(self, time_obj, mode):
        if mode == "start":
            self.btn_start_sleep.children[0].text = f"Ngủ: {time_obj.strftime('%H:%M')}"
        else:
            self.btn_end_sleep.children[0].text = f"Dậy: {time_obj.strftime('%H:%M')}"


    #Ghi chú: Kết nối phần này với backend cho chuẩn
    def save_preferences(self, instance):
        payload = {
            "sleep_schedule": f"{self.btn_start_sleep.children[0].text} - {self.btn_end_sleep.children[0].text}",
            "min_break_minutes": self.tf_break.text,
            "max_continuous_minutes": self.tf_max_duration.text,
            "natural_language_preference": self.tf_habits.text
        }
        # Gọi API cập nhật user_preferences
        api._request("/api/v1/user/preferences", method="POST", payload=payload)
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

        # 1. NÚT BẤM TRỞ VỀ (Header)
        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), padding=dp(10))
        btn_back = MDIconButton(icon="arrow-left", pos_hint={"center_y": 0.5})
        btn_back.bind(on_release=lambda x: self.dismiss())
        header.add_widget(btn_back)
        
        # 2. MENU CUỘN
        self.scroll = ScrollView(size_hint=(1, 1))
        self.menu_list = MDBoxLayout(orientation='vertical', adaptive_height=True, padding=dp(10), spacing=dp(10))
        
        btn_schedule_prefs = MDButton(
            MDButtonText(text="Tùy chọn xếp lịch"), style="elevated", size_hint_x=1,
            on_release=lambda x: SchedulePreferencesDialog().open()
        )
        self.menu_list.add_widget(btn_schedule_prefs)
        self.scroll.add_widget(self.menu_list)

        # 3. THÔNG TIN TÀI KHOẢN (Cố định dưới cùng)
        self.user_widget = UserAccountWidget()
        
        self.main_container.add_widget(header)
        self.main_container.add_widget(self.scroll)
        self.main_container.add_widget(self.user_widget)

        self.add_widget(self.main_container)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.main_container.pos
        self.bg_rect.size = self.main_container.size

    def open(self, *args, **kwargs):
        self._is_animating_close = False
        self.main_container.x = -self.menu_width
        # Cập nhật lại thông tin user mỗi lần mở menu
        self.user_widget.lbl_display.text = api.display_name or "Người dùng"
        self.user_widget.lbl_username.text = f"ID: {api.user_id or 'username'}"
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
                MDButtonText(text="Mở Menu Sidebar"),
                pos_hint={"center_x": 0.5, "center_y": 0.5},
                on_release=lambda x: SideBarMenu().open()
            )
            screen.add_widget(btn)
            return screen

    TestApp().run()