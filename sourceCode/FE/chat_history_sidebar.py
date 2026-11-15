"""
FILE: chat_history_sidebar.py
"""
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.animation import Animation
from kivy.graphics import Color, RoundedRectangle
from kivy.utils import platform  # Thêm import platform để nhận diện thiết bị
from kivy.clock import Clock     # Hỗ trợ đếm thời gian cho thao tác nhấn giữ (Long press)

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton

WHITE_COLOR = [1, 1, 1, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]

class HistoryItem(MDBoxLayout):
    """
    Widget hiển thị 1 mục trò chuyện trong danh sách lịch sử:
    - Bấm nhanh (tap): Mở lại nội dung cuộc trò chuyện đó.
    - Nhấn giữ lâu (long press >= 0.5s): Hiển thị nút xóa (icon thùng rác đỏ) và đổi màu nền cảnh báo.
    - Bấm nút xóa: Xóa cuộc trò chuyện khỏi danh sách và xóa trong database cục bộ.
    - Bấm ra ngoài khi đang ở chế độ xóa: Tự động hủy chế độ xóa và trở về trạng thái bình thường.
    """
    def __init__(self, text, index, callback, delete_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(56)
        self.padding = [dp(12), dp(4), dp(8), dp(4)]
        self.spacing = dp(8)
        
        self.index = index
        self.callback = callback
        self.delete_callback = delete_callback
        
        # Quản lý sự kiện chạm và nhấn giữ
        self.is_delete_mode = False
        self._long_press_event = None
        self._touch_down_pos = None

        # Nền bo góc: Mặc định xám nhạt, khi kích hoạt xóa sẽ chuyển sang hồng nhạt
        with self.canvas.before:
            self.canvas_color = Color(0.95, 0.95, 0.95, 1)
            self.bg_rect = RoundedRectangle(radius=[dp(8)])
        self.bind(pos=self.update_canvas, size=self.update_canvas)
        
        # Nhãn hiển thị tiêu đề cuộc trò chuyện
        self.lbl_title = MDLabel(
            text=text, 
            theme_text_color="Custom",
            text_color=[0, 0, 0, 1],
            shorten=True,
            shorten_from="right",
            font_style="Body",
            role="medium",
            size_hint_x=1,
            pos_hint={"center_y": 0.5}
        )
        self.add_widget(self.lbl_title)
        
        # Nút xóa (mặc định ẩn đi, chỉ hiện khi người dùng nhấn giữ)
        self.btn_delete = MDIconButton(
            icon="trash-can-outline",
            theme_icon_color="Custom",
            icon_color=[0.85, 0.1, 0.1, 1],
            pos_hint={"center_y": 0.5},
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            opacity=0,
            disabled=True
        )
        self.btn_delete.bind(on_release=self._on_delete_press)
        self.add_widget(self.btn_delete)

    def update_canvas(self, *args):
        """Đồng bộ vị trí và kích thước nền bo góc"""
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

    def _trigger_long_press(self, dt):
        """Kích hoạt khi người dùng nhấn giữ đủ thời gian (0.5 giây)"""
        self._long_press_event = None
        self.enable_delete_mode()

    def enable_delete_mode(self):
        """Bật chế độ xóa: Hiện icon thùng rác và chuyển màu nền sang hồng nhạt"""
        self.is_delete_mode = True
        self.canvas_color.rgba = [1.0, 0.92, 0.92, 1]
        self.btn_delete.opacity = 1
        self.btn_delete.disabled = False

    def disable_delete_mode(self):
        """Tắt chế độ xóa: Ẩn icon thùng rác và trả lại màu nền xám mặc định"""
        self.is_delete_mode = False
        self.canvas_color.rgba = [0.95, 0.95, 0.95, 1]
        self.btn_delete.opacity = 0
        self.btn_delete.disabled = True

    def _on_delete_press(self, *args):
        """Xử lý khi người dùng nhấn nút xóa"""
        if self.delete_callback:
            self.delete_callback(self.index)

    def on_touch_down(self, touch):
        # Nếu chạm ngoài vùng widget này
        if not self.collide_point(*touch.pos):
            if self.is_delete_mode:
                self.disable_delete_mode()
            return super().on_touch_down(touch)

        # Nếu chạm vào chính nút xóa khi đang ở chế độ xóa
        if self.is_delete_mode and self.btn_delete.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        # Bắt đầu theo dõi nhấn giữ
        self._touch_down_pos = touch.pos
        self._cancel_long_press()
        self._long_press_event = Clock.schedule_once(self._trigger_long_press, 0.5)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            # Nếu người dùng di chuyển ngón tay (cuộn màn hình), hủy bỏ hẹn giờ nhấn giữ
            if self._touch_down_pos:
                dx = abs(touch.x - self._touch_down_pos[0])
                dy = abs(touch.y - self._touch_down_pos[1])
                if dx > dp(10) or dy > dp(10):
                    self._cancel_long_press()
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            had_timer = self._long_press_event is not None
            self._cancel_long_press()

            # Nếu timer vẫn còn (người dùng nhả tay trước 0.5s => Chạm ngắn)
            if had_timer:
                if self.is_delete_mode:
                    # Nếu đang hiện nút xóa mà chạm vào thân mục => Ẩn nút xóa
                    self.disable_delete_mode()
                else:
                    # Chạm mở cuộc trò chuyện
                    if self.collide_point(*touch.pos) and self.callback:
                        self.callback(self.index)
            return True
        return super().on_touch_up(touch)

    def _cancel_long_press(self):
        """Hủy bỏ bộ đếm thời gian nhấn giữ nếu chưa hết giờ"""
        if self._long_press_event:
            Clock.unschedule(self._long_press_event)
            self._long_press_event = None


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
        
        # --- BLOCK MÀU XANH Ở TRÊN CÙNG (Nút trở về & Tiêu đề) ---
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
            self.header_bg = RoundedRectangle(radius=[dp(15), 0, 0, 0])
        self.header.bind(pos=self._update_header_canvas, size=self._update_header_canvas)

        btn_close = MDIconButton(
            icon="arrow-left",
            theme_icon_color="Custom",
            icon_color=WHITE_COLOR,
            pos_hint={"center_y": 0.5}
        )
        btn_close.bind(on_release=lambda x: self.dismiss())
        
        lbl_title = MDLabel(
            text="Lịch sử",
            bold=True,
            font_style="Title",
            role="medium",
            theme_text_color="Custom",
            text_color=WHITE_COLOR,
            pos_hint={"center_y": 0.5}
        )
        self.header.add_widget(btn_close)
        self.header.add_widget(lbl_title)
        self.main_container.add_widget(self.header)

        # --- DANH SÁCH LỊCH SỬ ---
        self.scroll = ScrollView(size_hint=(1, 1))
        self.history_list = MDBoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5), padding=dp(10))
        self.history_list.bind(minimum_height=self.history_list.setter('height'))
        self.scroll.add_widget(self.history_list)
        
        self.main_container.add_widget(self.scroll)
        self.add_widget(self.main_container)
        
        self.callback = None
        self.delete_callback = None

    def update_canvas(self, *args):
        self.bg_rect.pos = self.main_container.pos
        self.bg_rect.size = self.main_container.size

    def _update_header_canvas(self, *args):
        if hasattr(self, 'header_bg') and hasattr(self, 'header'):
            self.header_bg.pos = self.header.pos
            self.header_bg.size = self.header.size

    def load_history(self, sessions, callback=None, delete_callback=None):
        """
        Nạp danh sách các đoạn chat vào thanh menu bên phải:
        - sessions: Danh sách các session chat lấy từ database cục bộ.
        - callback: Hàm callback xử lý khi người dùng chọn mở 1 phiên chat.
        - delete_callback: Hàm callback xử lý khi người dùng nhấn nút xóa 1 phiên chat.
        """
        self.history_list.clear_widgets()
        self.callback = callback
        self.delete_callback = delete_callback
        
        if not sessions:
            lbl_empty = MDLabel(
                text="Chưa có cuộc trò chuyện nào",
                theme_text_color="Hint",
                halign="center",
                font_style="Body",
                role="medium",
                size_hint_y=None,
                height=dp(80)
            )
            self.history_list.add_widget(lbl_empty)
            return

        for i, session in enumerate(sessions):
            title = session.get("title", f"Trò chuyện {i+1}") if isinstance(session, dict) else str(session)
            item = HistoryItem(
                text=title,
                index=i,
                callback=self.on_item_select,
                delete_callback=self.on_item_delete
            )
            self.history_list.add_widget(item)

    def on_item_delete(self, index):
        """Xử lý sự kiện khi người dùng xác nhận xóa 1 cuộc trò chuyện"""
        if self.delete_callback:
            self.delete_callback(index)

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