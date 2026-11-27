from pathlib import Path
from kivy.uix.button import Button
from kivy.metrics import dp
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.uix.image import Image
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.uix.behaviors import ButtonBehavior

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText, MDTextFieldTrailingIcon
from kivymd.uix.label import MDLabel
from api_client import api
from event_store import store
from notifier import reminder_scheduler

FE_DIR = Path(__file__).resolve().parent

"""
FILE: auth_screen.py
CHỨC NĂNG:
- Hiển thị giao diện Đăng nhập, Đăng ký và Thiết lập Username cho OAuth.
- Có khả năng tự động căn giữa và giới hạn độ rộng (Responsive) trên màn hình máy tính.

CÁCH HOẠT ĐỘNG:
- Sử dụng `ScreenManager` làm container để chuyển đổi giữa 3 tab nhỏ (login, register, oauth)
  mà không cần đổi nguyên trang gốc.
- Các nút nhấn được custom từ Kivy gốc để quản lý chính xác đường viền và màu nền.
- Ẩn/Hiện mật khẩu dùng thủ thuật kiểm tra tọa độ `collide_point` ngay trên bản thân TextInput 
  để tránh xung đột MRO của KivyMD.
"""

# ==============================================================================
# 1. HẰNG SỐ MÀU SẮC
# ==============================================================================
BLUE_COLOR  = [0, 51/255, 204/255, 1]      
GRAY_COLOR  = [221/255, 221/255, 221/255, 1] 
LIGHT_GRAY  = [0.9, 0.9, 0.9, 1]           
WHITE_COLOR = [1, 1, 1, 1]                 
BLACK_COLOR = [0, 0, 0, 1]                 
RED_COLOR   = [1, 0, 0, 1]                 
DARK_GRAY   = [0.3, 0.3, 0.3, 1]           

# ==============================================================================
# 2. CÁC WIDGET TÙY CHỈNH
# ==============================================================================
class CustomTextField(MDTextField):
    def __init__(self, hint="", is_password=False, **kwargs):
        super().__init__(**kwargs)
        self.mode = "outlined"
        self.size_hint_x = None
        self.radius = [0, 0, 0, 0]
        self.password = is_password
        
        self.theme_line_color = "Custom"
        self.line_color_normal = BLUE_COLOR
        self.line_color_focus = BLUE_COLOR
        self.add_widget(MDTextFieldHintText(text=hint))

        if is_password:
            self.eye_icon = MDTextFieldTrailingIcon(icon="eye-off", theme_icon_color="Custom", icon_color=DARK_GRAY)
            self.add_widget(self.eye_icon)

    def on_touch_down(self, touch):
        """Bắt tọa độ ngón tay/chuột để xử lý tính năng bật/tắt mật khẩu"""
        if hasattr(self, 'eye_icon') and self.collide_point(*touch.pos):
            # Nếu chạm vào vùng 45dp ở bên phải (nơi đặt icon con mắt)
            if touch.x > (self.right - dp(45)):
                self.password = not self.password
                self.eye_icon.icon = "eye" if not self.password else "eye-off"
                return True 
        return super().on_touch_down(touch)

class CustomButton(Button):
    def __init__(self, text="", bg_color=None, txt_color=None, is_outlined=False, **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.size_hint_x = None
        self.size_hint_y = None
        self.height = dp(45)
        self.background_normal = ''
        self.background_down = ''
        
        self.color = txt_color if txt_color else WHITE_COLOR
        self.bold = True
        
        if is_outlined:
            self.background_color = WHITE_COLOR
            self.color = BLACK_COLOR
            with self.canvas.before:
                Color(*BLACK_COLOR)
                self.line = Line(width=1.2)
            self.bind(pos=self.update_border, size=self.update_border)
        else:
            self.background_color = bg_color if bg_color else BLUE_COLOR

    def update_border(self, *args):
        self.line.rectangle = (self.x, self.y, self.width, self.height)


class ServerConfigModal(ModalView):
    """
    Hộp thoại cho phép người dùng đổi địa chỉ IP / URL của Backend FastAPI
    trực tiếp trên điện thoại mà không cần biên dịch lại APK.
    """

    def __init__(self, on_saved=None, **kwargs):
        super().__init__(**kwargs)
        self.on_saved = on_saved
        self.size_hint = (0.9, None)
        self.height = dp(265)
        self.background_color = [0, 0, 0, 0]
        self.auto_dismiss = True

        container = MDBoxLayout(
            orientation="vertical",
            padding=dp(18),
            spacing=dp(12),
            md_bg_color=WHITE_COLOR,
        )
        with container.canvas.before:
            Color(*WHITE_COLOR)
            self._bg = RoundedRectangle(pos=container.pos, size=container.size, radius=[dp(14)])
        container.bind(
            pos=lambda inst, val: setattr(self._bg, "pos", val),
            size=lambda inst, val: setattr(self._bg, "size", val),
        )

        title = MDLabel(
            text="Server Settings (Backend URL)",
            bold=True,
            font_style="Title",
            role="medium",
            size_hint_y=None,
            height=dp(28),
        )
        hint = MDLabel(
            text="Example: LAN: http://192.168.1.10:8080\nEmulator: http://10.0.2.2:8080",
            theme_text_color="Hint",
            font_style="Body",
            role="small",
            size_hint_y=None,
            height=dp(34),
        )

        self.url_field = MDTextField(
            MDTextFieldHintText(text="http://<server-ip>:8080"),
            mode="outlined",
            text=api.base_url,
            size_hint_x=1,
        )

        self.err_lbl = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=RED_COLOR,
            font_style="Body",
            role="small",
            size_hint_y=None,
            height=dp(18),
        )

        btn_row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(42))
        btn_save = CustomButton(text="SAVE", bg_color=BLUE_COLOR, size_hint_x=0.5)
        btn_save.bind(on_release=self._save_url)
        btn_cancel = CustomButton(text="CANCEL", is_outlined=True, size_hint_x=0.5)
        btn_cancel.bind(on_release=lambda *_: self.dismiss())
        btn_row.add_widget(btn_save)
        btn_row.add_widget(btn_cancel)

        container.add_widget(title)
        container.add_widget(hint)
        container.add_widget(self.url_field)
        container.add_widget(self.err_lbl)
        container.add_widget(btn_row)
        self.add_widget(container)

    def _save_url(self, *args):
        """Kiểm tra định dạng URL hợp lệ rồi lưu vào api_client (auth_session.json)."""
        new_url = (self.url_field.text or "").strip().rstrip("/")
        if not new_url.startswith(("http://", "https://")) or len(new_url) <= 8:
            self.err_lbl.text = "URL start with http:// or https://"
            return
        api.set_base_url(new_url)
        if callable(self.on_saved):
            self.on_saved(api.base_url)
        self.dismiss()


# ==============================================================================
# 3. LỚP MÀN HÌNH CHÍNH
# ==============================================================================
class AuthScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = WHITE_COLOR
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        anchor = AnchorLayout(anchor_x='center', anchor_y='center')
        self.add_widget(anchor)

        self.main_container = MDBoxLayout(
            orientation='vertical', size_hint_x=None, adaptive_height=True,
            spacing=dp(20), padding=[0, dp(15), 0, dp(10)], pos_hint={"center_y": 0.58} 
        )
        anchor.add_widget(self.main_container)
        self.bind(width=self.update_main_container_width)

        logo = Image(source=str(FE_DIR / "assets" / "logo.png"), size_hint=(None, None), size=(dp(120), dp(120)), pos_hint={"center_x": 0.5})
        self.main_container.add_widget(logo)

        self.error_label = MDLabel(text="", halign="center", theme_text_color="Custom", text_color=RED_COLOR, size_hint_y=None, height=0, opacity=0)
        self.main_container.add_widget(self.error_label)

        self.sm = ScreenManager(size_hint_x=None, size_hint_y=None, transition=SlideTransition())
        self.main_container.bind(width=self.sm.setter('width'))
        self.main_container.add_widget(self.sm)

        self.setup_login_tab()
        self.setup_register_tab()
        self.setup_oauth_tab()

        self.sm.bind(current=self.update_sm_height)
        self.login_container.bind(minimum_height=self.update_sm_height)
        self.register_container.bind(minimum_height=self.update_sm_height)
        self.oauth_container.bind(minimum_height=self.update_sm_height)

        # Nhãn hiển thị URL Backend hiện tại ngay dưới form đăng nhập
        self.server_url_label = MDLabel(
            text=f"Server: {api.base_url}",
            halign="center",
            theme_text_color="Hint",
            font_style="Body",
            role="small",
            size_hint_y=None,
            height=dp(20),
        )
        self.main_container.add_widget(self.server_url_label)

        # Nút bánh răng ở góc trên phải để mở hộp thoại đổi IP Server
        top_right = AnchorLayout(anchor_x="right", anchor_y="top", padding=[dp(8), dp(8)])
        btn_server = MDIconButton(
            icon="cog-outline",
            theme_icon_color="Custom",
            icon_color=DARK_GRAY,
            on_release=self.open_server_config,
        )
        top_right.add_widget(btn_server)
        self.add_widget(top_right)

        self.update_main_container_width()

    def open_server_config(self, *args):
        """Mở hộp thoại cấu hình IP/URL Backend."""
        ServerConfigModal(on_saved=self._on_server_saved).open()

    def _on_server_saved(self, new_url: str):
        """Cập nhật nhãn hiển thị URL sau khi người dùng lưu cấu hình mới."""
        if hasattr(self, "server_url_label"):
            self.server_url_label.text = f"Server: {new_url}"

    def on_enter(self, *args):
        self.clear_error()
        self._reset_inputs()
        self.update_main_container_width()

    def _reset_inputs(self):
        """clear previous credentials and re-mask password fields."""
        for attr in ("login_username", "login_password", "reg_username", "reg_displayname", "reg_password", "oauth_username"):
            field = getattr(self, attr, None)
            if field is not None:
                field.text = ""
        for pwd_attr in ("login_password", "reg_password"):
            pwd_field = getattr(self, pwd_attr, None)
            if pwd_field is not None:
                pwd_field.password = True
                if hasattr(pwd_field, "eye_icon"):
                    pwd_field.eye_icon.icon = "eye-off"

    def setup_login_tab(self):
        login_screen = MDScreen(name="login_tab")
        self.login_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(12), padding=[0, dp(12), 0, dp(6)], pos_hint={"center_x": 0.5, "top": 1})
        self.login_container.bind(minimum_height=self.login_container.setter('height'))
        self.sm.bind(width=self.login_container.setter('width'))
        
        self.login_username = CustomTextField(hint="Username")
        self.login_password = CustomTextField(hint="Password", is_password=True)
        btn_login = CustomButton(text="LOG IN", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_login.bind(on_release=lambda x: self.do_login(self.login_username.text, self.login_password.text))
        
        btn_google = CustomButton(text="Google Account", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_google.bind(on_release=lambda x: self.simulate_oauth_login("Google"))
        
        btn_github = CustomButton(text="GitHub Account", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_github.bind(on_release=lambda x: self.simulate_oauth_login("Github"))
        
        btn_switch = CustomButton(text="SWITCH TO REGISTER", txt_color=BLACK_COLOR, is_outlined=True)
        btn_switch.bind(on_release=lambda x: self.switch_tab("register_tab", "left"))
        
        widgets = [self.login_username, self.login_password, btn_login, btn_google, btn_github, btn_switch]
        for w in widgets:
            self.login_container.bind(width=w.setter('width'))
            self.login_container.add_widget(w)
            
        login_screen.add_widget(self.login_container)
        self.sm.add_widget(login_screen)

    def setup_register_tab(self):
        reg_screen = MDScreen(name="register_tab")
        self.register_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(12), padding=[0, dp(12), 0, dp(6)], pos_hint={"center_x": 0.5, "top": 1})
        self.register_container.bind(minimum_height=self.register_container.setter('height'))
        self.sm.bind(width=self.register_container.setter('width'))
        
        self.reg_username = CustomTextField(hint="Username")
        self.reg_displayname = CustomTextField(hint="Display Name")
        self.reg_password = CustomTextField(hint="Password", is_password=True)
        
        btn_register = CustomButton(text="CREATE ACCOUNT", bg_color=GRAY_COLOR, txt_color=BLACK_COLOR)
        btn_register.bind(on_release=lambda x: self.do_register(self.reg_username.text, self.reg_displayname.text, self.reg_password.text))
        
        btn_google = CustomButton(text="Google Account", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_google.bind(on_release=lambda x: self.simulate_oauth_login("Google"))
        
        btn_github = CustomButton(text="GitHub Account", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_github.bind(on_release=lambda x: self.simulate_oauth_login("Github"))
        
        btn_switch = CustomButton(text="SWITCH TO LOGIN", txt_color=BLACK_COLOR, is_outlined=True)
        btn_switch.bind(on_release=lambda x: self.switch_tab("login_tab", "right"))
        
        widgets = [self.reg_username, self.reg_displayname, self.reg_password, btn_register, btn_google, btn_github, btn_switch]
        for w in widgets:
            self.register_container.bind(width=w.setter('width'))
            self.register_container.add_widget(w)
            
        reg_screen.add_widget(self.register_container)
        self.sm.add_widget(reg_screen)

    def setup_oauth_tab(self):
        oauth_screen = MDScreen(name="oauth_tab")
        self.oauth_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(15), padding=[0, dp(12), 0, dp(6)], pos_hint={"center_x": 0.5, "top": 1})
        self.oauth_container.bind(minimum_height=self.oauth_container.setter('height'))
        self.sm.bind(width=self.oauth_container.setter('width'))
        
        lbl_info = MDLabel(text="Linked successfully!\nPlease create a Username for your account:", halign="center", theme_text_color="Custom", text_color=BLACK_COLOR, size_hint_y=None, height=dp(50))
        self.oauth_username = CustomTextField(hint="Username")
        btn_confirm = CustomButton(text="Confirm", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_confirm.bind(on_release=self.confirm_oauth_username)
        btn_cancel = CustomButton(text="CANCEL (GO BACK)", txt_color=BLACK_COLOR, is_outlined=True)
        btn_cancel.bind(on_release=lambda x: self.switch_tab("login_tab", "right"))

        widgets = [lbl_info, self.oauth_username, btn_confirm, btn_cancel]
        for w in widgets:
            if isinstance(w, CustomTextField) or isinstance(w, CustomButton):
                self.oauth_container.bind(width=w.setter('width'))
            self.oauth_container.add_widget(w)
            
        oauth_screen.add_widget(self.oauth_container)
        self.sm.add_widget(oauth_screen)

    # -------------------------------------------------------------------------
    # HÀM LOGIC API & CHUYỂN TRANG
    # -------------------------------------------------------------------------
    def update_main_container_width(self, *args):
        # Kiểm tra xem thuộc tính main_container đã được tạo hay chưa để tránh lỗi AttributeError
        if hasattr(self, 'main_container'):
            form_width = min(dp(400), self.width - dp(40))
            self.main_container.width = form_width

    def update_sm_height(self, *args):
        if self.sm.current == "login_tab": self.sm.height = self.login_container.height
        elif self.sm.current == "register_tab": self.sm.height = self.register_container.height
        elif self.sm.current == "oauth_tab": self.sm.height = self.oauth_container.height

    def switch_tab(self, tab_name, direction):
        self.clear_error()
        self.sm.transition.direction = direction
        self.sm.current = tab_name

    def show_error(self, message):
        if not hasattr(self, "error_label"):
            return
        self.error_label.text = message
        self.error_label.texture_update()
        self.error_label.height = self.error_label.texture_size[1]
        self.error_label.opacity = 1

    def clear_error(self):
        if not hasattr(self, "error_label"):
            return
        self.error_label.text = ""
        self.error_label.height = 0
        self.error_label.opacity = 0

    def simulate_oauth_login(self, provider):
        """block unconfigured OAuth sign-in from entering app screens without a valid JWT."""
        self.clear_error()
        self.show_error("OAuth sign-in is not configured on this server. Please log in with Username and Password.")

    def confirm_oauth_username(self, instance):
        if not getattr(api, "access_token", None):
            self.show_error("OAuth sign-in is not configured on this server. Please log in with Username and Password.")
            return
        username = (self.oauth_username.text or "").strip()
        if not username:
            self.show_error("Please enter a Username to complete linking.")
            return
        app = MDApp.get_running_app()
        if app and app.root and hasattr(app.root, 'current'):
            app.root.current = "calendar_home"

    def do_register(self, username, display_name, password):
        self.clear_error()
        username = (username or "").strip()
        display_name = (display_name or "").strip()
        password = password or ""
        if not username or not display_name or not password:
            self.show_error("Please fill in all fields.")
            return
        if len(username) < 3:
            self.show_error("Username must be at least 3 characters.")
            return
        if len(password) < 6:
            self.show_error("Password must be at least 6 characters.")
            return

        api.register(
            username, display_name, password,
            on_success=self.on_register_success, on_failure=self.on_register_failure, on_error=self.on_network_error
        )

    def on_register_success(self, req, result):
        self.clear_error()
        self._reset_inputs()
        self.switch_tab("login_tab", "right")

    def on_register_failure(self, req, result):
        status_code = req.resp_status
        if status_code == 409:
            self.show_error("Username already exists")
        elif status_code == 422 and isinstance(result, dict):
            detail = result.get("detail")
            if isinstance(detail, list) and detail:
                msg = detail[0].get("msg") if isinstance(detail[0], dict) else str(detail[0])
                self.show_error(str(msg or "Invalid registration input."))
            else:
                self.show_error(str(detail or "Invalid registration input."))
        else:
            detail = result.get("detail") if isinstance(result, dict) else None
            self.show_error(str(detail) if detail else f"System error ({status_code}). Please try again later.")

    def do_login(self, username, password):
        self.clear_error()
        username = (username or "").strip()
        password = password or ""
        if not username or not password:
            self.show_error("Please enter both Username and Password.")
            return

        self._login_username = username
        api.login(
            username, password,
            on_success=self.on_login_success, on_failure=self.on_login_failure, on_error=self.on_network_error
        )

    def on_login_success(self, req, result):
        # Lưu phiên đăng nhập: lấy display_name và username từ response hoặc từ form đăng nhập
        app = MDApp.get_running_app()
        username_val = result.get("username") or getattr(self, "_login_username", None) or ""
        display_name_val = result.get("display_name") or username_val or "User"
        api.save_session(
            token=result.get("access_token"),
            user_id=result.get("user_id"),
            display_name=display_name_val,
            username=username_val
        )
        store.set_events([], demo=False)
        store.refresh(api, on_done=lambda: reminder_scheduler.sync_from_backend(api, store.events))
        self._reset_inputs()
        if app and app.root and hasattr(app.root, 'current'):
            app.root.current = "calendar_home"

    def on_login_failure(self, req, result):
        # [CẦN BACKEND XỬ LÝ]: Backend phải đảm bảo trả về mã 401 khi sai mật khẩu.
        status_code = req.resp_status
        if status_code == 401:
            self.show_error("Invalid username or password!")
        else:
            self.show_error(f"Login failed ({status_code})")

    def on_network_error(self, req, error):
        self.show_error("Cannot connect to server. Please check your network connection.")

if __name__ == "__main__":
    from kivy.core.window import Window
    Window.size = (360, 640) 

    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            self.theme_cls.primary_palette = "Blue"
            return AuthScreen(name="auth")

    TestApp().run()