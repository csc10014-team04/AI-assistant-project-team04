from kivy.uix.button import Button
from kivy.metrics import dp
from kivy.graphics import Color, Line
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivy.uix.image import Image
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.uix.behaviors import ButtonBehavior


from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText, MDTextFieldTrailingIcon
from kivymd.uix.label import MDLabel
from api_client import api

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
            spacing=dp(20), pos_hint={"center_y": 0.55} 
        )
        anchor.add_widget(self.main_container)
        self.bind(width=self.update_main_container_width)

        logo = Image(source="assets/logo.png", size_hint=(None, None), size=(dp(120), dp(120)), pos_hint={"center_x": 0.5})
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

        self.update_main_container_width()

    def on_enter(self, *args):
        self.update_main_container_width()

    def setup_login_tab(self):
        login_screen = MDScreen(name="login_tab")
        self.login_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(12), pos_hint={"center_x": 0.5, "top": 1})
        self.login_container.bind(minimum_height=self.login_container.setter('height'))
        self.sm.bind(width=self.login_container.setter('width'))
        
        login_username = CustomTextField(hint="Tên đăng nhập")
        login_password = CustomTextField(hint="Mật khẩu", is_password=True)
        btn_login = CustomButton(text="ĐĂNG NHẬP", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_login.bind(on_release=lambda x: self.do_login(login_username.text, login_password.text))
        
        btn_google = CustomButton(text="Tài khoản Google", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_google.bind(on_release=lambda x: self.simulate_oauth_login("Google"))
        
        btn_github = CustomButton(text="Tài khoản Github", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_github.bind(on_release=lambda x: self.simulate_oauth_login("Github"))
        
        btn_switch = CustomButton(text="CHUYỂN QUA TẠO TÀI KHOẢN", txt_color=BLACK_COLOR, is_outlined=True)
        btn_switch.bind(on_release=lambda x: self.switch_tab("register_tab", "left"))
        
        widgets = [login_username, login_password, btn_login, btn_google, btn_github, btn_switch]
        for w in widgets:
            self.login_container.bind(width=w.setter('width'))
            self.login_container.add_widget(w)
            
        login_screen.add_widget(self.login_container)
        self.sm.add_widget(login_screen)

    def setup_register_tab(self):
        reg_screen = MDScreen(name="register_tab")
        self.register_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(12), pos_hint={"center_x": 0.5, "top": 1})
        self.register_container.bind(minimum_height=self.register_container.setter('height'))
        self.sm.bind(width=self.register_container.setter('width'))
        
        reg_username = CustomTextField(hint="Tên đăng nhập")
        reg_displayname = CustomTextField(hint="Họ tên hiển thị")
        reg_password = CustomTextField(hint="Mật khẩu", is_password=True)
        
        btn_register = CustomButton(text="TẠO TÀI KHOẢN", bg_color=GRAY_COLOR, txt_color=BLACK_COLOR)
        btn_register.bind(on_release=lambda x: self.do_register(reg_username.text, reg_displayname.text, reg_password.text))
        
        btn_google = CustomButton(text="Tài khoản Google", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_google.bind(on_release=lambda x: self.simulate_oauth_login("Google"))
        
        btn_github = CustomButton(text="Tài khoản Github", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_github.bind(on_release=lambda x: self.simulate_oauth_login("Github"))
        
        btn_switch = CustomButton(text="CHUYỂN QUA ĐĂNG NHẬP", txt_color=BLACK_COLOR, is_outlined=True)
        btn_switch.bind(on_release=lambda x: self.switch_tab("login_tab", "right"))
        
        widgets = [reg_username, reg_displayname, reg_password, btn_register, btn_google, btn_github, btn_switch]
        for w in widgets:
            self.register_container.bind(width=w.setter('width'))
            self.register_container.add_widget(w)
            
        reg_screen.add_widget(self.register_container)
        self.sm.add_widget(reg_screen)

    def setup_oauth_tab(self):
        oauth_screen = MDScreen(name="oauth_tab")
        self.oauth_container = BoxLayout(orientation='vertical', size_hint_x=None, size_hint_y=None, spacing=dp(15), pos_hint={"center_x": 0.5, "top": 1})
        self.oauth_container.bind(minimum_height=self.oauth_container.setter('height'))
        self.sm.bind(width=self.oauth_container.setter('width'))
        
        lbl_info = MDLabel(text="Liên kết thành công!\nVui lòng tạo Username cho tài khoản:", halign="center", theme_text_color="Custom", text_color=BLACK_COLOR, size_hint_y=None, height=dp(50))
        self.oauth_username = CustomTextField(hint="Username")
        btn_confirm = CustomButton(text="Xác nhận", bg_color=BLUE_COLOR, txt_color=WHITE_COLOR)
        btn_confirm.bind(on_release=self.confirm_oauth_username)
        btn_cancel = CustomButton(text="HỦY (QUAY LẠI)", txt_color=BLACK_COLOR, is_outlined=True)
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
        self.error_label.text = message
        self.error_label.texture_update()
        self.error_label.height = self.error_label.texture_size[1]
        self.error_label.opacity = 1

    def clear_error(self):
        self.error_label.text = ""
        self.error_label.height = 0
        self.error_label.opacity = 0

    def simulate_oauth_login(self, provider):
        """
        [CẦN BACKEND XỬ LÝ]
        Hiện tại hàm này chỉ mô phỏng việc xác thực OAuth (Đợi 0.5s rồi chuyển qua màn nhập Username).
        Thực tế:
        - Cần mở trình duyệt (Webview/DeepLink) trỏ đến API OAuth của Backend.
        - Sau khi Backend báo thành công, lấy thông tin trả về, nếu user mới -> Chuyển sang màn 'oauth_tab'.
        """
        self.clear_error()
        Clock.schedule_once(lambda dt: self.switch_tab("oauth_tab", "left"), 0.5)

    def confirm_oauth_username(self, instance):
        """
        [CẦN BACKEND XỬ LÝ]
        Gửi Username do người dùng nhập xuống Backend để hoàn tất việc tạo tài khoản OAuth.
        Cần gọi api_client.finalize_oauth(...) (hiện chưa có trong api_client).
        """
        username = self.oauth_username.text
        if not username:
            self.show_error("Vui lòng nhập Username để hoàn tất liên kết.")
            return
        
        # Mô phỏng việc API trả về OK -> Chuyển thẳng vào Home Screen
        print(f"Xác nhận OAuth Username: {username} -> Chuyển vào App")
        app = MDApp.get_running_app()
        if app.root and hasattr(app.root, 'current'):
            app.root.current = "calendar_home"

    def do_register(self, username, display_name, password):
        self.clear_error()
        if not username or not display_name or not password:
            self.show_error("Vui lòng nhập đầy đủ các trường thông tin.")
            return

        api.register(
            username, display_name, password, "", 
            on_success=self.on_register_success, on_failure=self.on_register_failure, on_error=self.on_network_error
        )

    def on_register_success(self, req, result):
        print("Tạo tài khoản thành công! Trở về màn đăng nhập...")
        self.clear_error()
        self.switch_tab("login_tab", "right")

    def on_register_failure(self, req, result):
        # [CẦN BACKEND XỬ LÝ]: Backend phải đảm bảo trả về mã 409 nếu trùng lặp username.
        status_code = req.resp_status
        if status_code == 409:
            self.show_error("Tên đăng nhập đã tồn tại")
        else:
            self.show_error(f"Lỗi hệ thống ({status_code}). Vui lòng thử lại sau.")

    def do_login(self, username, password):
        self.clear_error()
        if not username or not password:
            self.show_error("Vui lòng nhập đầy đủ Tên đăng nhập và Mật khẩu.")
            return

        api.login(
            username, password,
            on_success=self.on_login_success, on_failure=self.on_login_failure, on_error=self.on_network_error
        )

    def on_login_success(self, req, result):
        # [CẦN BACKEND XỬ LÝ]: Backend phải đảm bảo trả về cấu trúc JSON đúng chuẩn chứa {access_token, user_id, display_name}
        app = MDApp.get_running_app()
        api.save_session(
            token=result.get("access_token"),
            user_id=result.get("user_id"),
            display_name=result.get("display_name")
        )
        print(f"Đăng nhập thành công! Chào {api.display_name}")
        if app.root and hasattr(app.root, 'current'):
            app.root.current = "calendar_home"

    def on_login_failure(self, req, result):
        # [CẦN BACKEND XỬ LÝ]: Backend phải đảm bảo trả về mã 401 khi sai mật khẩu.
        status_code = req.resp_status
        if status_code == 401:
            self.show_error("Sai tên đăng nhập hoặc mật khẩu!")
        else:
            self.show_error(f"Đăng nhập thất bại ({status_code})")

    def on_network_error(self, req, error):
        self.show_error("Không thể kết nối đến máy chủ. Vui lòng kiểm tra mạng.")

if __name__ == "__main__":
    from kivy.core.window import Window
    Window.size = (360, 640) 

    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            self.theme_cls.primary_palette = "Blue"
            return AuthScreen(name="auth")

    TestApp().run()