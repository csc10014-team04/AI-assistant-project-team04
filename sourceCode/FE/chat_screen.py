import json
from datetime import datetime


from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.screenmanager import Screen
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.screenmanager import SlideTransition


from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.relativelayout import MDRelativeLayout
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText
from kivymd.uix.card import MDCard

# ==============================================================================
# HẰNG SỐ MÀU SẮC
# ==============================================================================
WHITE_COLOR = [1, 1, 1, 1]
BLACK_COLOR = [0, 0, 0, 1]
GRAY_BG     = [0.95, 0.95, 0.95, 1]
GRAY_TEXT   = [0.5, 0.5, 0.5, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]
BLUE_LIGHT  = [230/255, 240/255, 255/255, 1]

# Từ điển ánh xạ Thứ
WEEKDAYS_VN = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]

# ==============================================================================
# WIDGET DÙNG CHUNG
# ==============================================================================
class SlotSelectionItem(MDBoxLayout):
    """Một dòng khung giờ trống cho phép chọn bằng Checkbox"""
    def __init__(self, slot_data, group_name, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        self.size_hint_y = None
        self.height = dp(45)
        self.spacing = dp(10)
        self.slot_data = slot_data
        
        # Nút chọn (Checkbox dùng group để hoạt động như Radio Button)
        self.checkbox = MDCheckbox(
            group=group_name,
            size_hint=(None, None), size=(dp(40), dp(40)),
            pos_hint={'center_y': .5},
            color_active=BLUE_COLOR, color_inactive=GRAY_TEXT
        )
        self.add_widget(self.checkbox)
        
        # Nhãn hiển thị thời gian
        st = datetime.fromisoformat(slot_data["start_time"])
        et = datetime.fromisoformat(slot_data["end_time"])
        wd = WEEKDAYS_VN[st.weekday()]
        time_str = f"{wd} ({st.day}/{st.month}): {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"
        
        self.lbl = MDLabel(
            text=time_str, pos_hint={'center_y': .5},
            font_style="Body", role="medium"
        )
        self.add_widget(self.lbl)
class NavTab(ButtonBehavior, MDBoxLayout):
    def __init__(self, text, target_screen, is_active=False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.height = dp(40)
        self.padding = dp(2)
        self.target_screen = target_screen # Lưu tên màn hình đích

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
        sm = app.root
        
        if sm.current != self.target_screen:
            # 1. Định nghĩa thứ tự các tab (từ trái qua phải)
            tab_indices = {
                "calendar_home": 0,
                "search_home": 1,
                "chat_home": 2
            }
            
            # Lấy vị trí của tab hiện tại và tab sắp chuyển tới
            current_idx = tab_indices.get(sm.current, 0)
            target_idx = tab_indices.get(self.target_screen, 0)
            
            # 2. Gán hiệu ứng trượt và hướng trượt
            if target_idx > current_idx:
                # Qua phải trên menu -> Màn hình mới đẩy từ phải sang trái
                sm.transition = SlideTransition(direction='left')
            else:
                # Qua trái trên menu -> Màn hình mới đẩy từ trái sang phải
                sm.transition = SlideTransition(direction='right')
                
            # 3. Chuyển trang
            sm.current = self.target_screen

class ChatBubble(MDBoxLayout):
    """Bong bóng chat của AI hoặc User"""
    def __init__(self, text, is_user=False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.size_hint_x = 0.8
        self.padding = dp(10)
        
        # Căn lề trái/phải tùy thuộc người gửi
        if is_user:
            self.pos_hint = {"right": 1}
            bg_color = BLUE_COLOR
            txt_color = WHITE_COLOR
            radius = [dp(12), dp(12), 0, dp(12)]
        else:
            self.pos_hint = {"x": 0}
            bg_color = GRAY_BG
            txt_color = BLACK_COLOR
            radius = [dp(12), dp(12), dp(12), 0]

        with self.canvas.before:
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=radius)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

        self.lbl = MDLabel(
            text=text, theme_text_color="Custom", text_color=txt_color,
            font_style="Body", role="medium"
        )
        self.lbl.bind(texture_size=self.update_height)
        self.add_widget(self.lbl)

    def update_height(self, instance, size):
        self.height = size[1] + dp(20)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size

# ==============================================================================
# MODAL DỰ PHÒNG & THẺ ĐỀ XUẤT (PROPOSAL CARD)
# ==============================================================================
class ManualFallbackModal(ModalView):
    """Bảng chọn giờ Thủ công khi AI Lỗi hoặc Timeout"""
    def __init__(self, task_title, duration, available_slots, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.7)
        self.auto_dismiss = False # Bắt buộc phải bấm Xác nhận hoặc Hủy
        self.background_color = [0, 0, 0, 0.6]
        
        # Khung nền trắng bo góc
        self.main_layout = MDBoxLayout(
            orientation='vertical', padding=dp(15), spacing=dp(10), 
            md_bg_color=WHITE_COLOR, radius=[dp(12)]
        )
        
        # 1. Tiêu đề cảnh báo
        self.main_layout.add_widget(MDLabel(
            text="(!) Trợ lý AI đang bận. Bạn hãy chọn nhanh khung giờ dưới:",
            theme_text_color="Custom", text_color=[0.9, 0.4, 0, 1], # Màu cam cảnh báo
            bold=True, size_hint_y=None, height=dp(40)
        ))
        
        # 2. Thông tin sự kiện
        info_box = MDBoxLayout(orientation='vertical', size_hint_y=None, height=dp(50), spacing=dp(5))
        info_box.add_widget(MDLabel(text=f"Tên hoạt động: [b]{task_title}[/b]", markup=True))
        info_box.add_widget(MDLabel(text=f"Thời lượng: {duration} phút"))
        self.main_layout.add_widget(info_box)
        
        # 3. Danh sách khung giờ trống (Scrollable)
        self.main_layout.add_widget(MDLabel(
            text="CÁC KHUNG GIỜ CÒN TRỐNG TRONG TUẦN:",
            theme_text_color="Custom", text_color=GRAY_TEXT,
            bold=True, size_hint_y=None, height=dp(30)
        ))
        
        self.scroll = ScrollView(size_hint=(1, 1))
        self.slots_box = MDBoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        self.slots_box.bind(minimum_height=self.slots_box.setter('height'))
        self.scroll.add_widget(self.slots_box)
        self.main_layout.add_widget(self.scroll)
        
        # Đổ dữ liệu các khung giờ trống vào ScrollView
        self.slot_items = []
        for i, slot in enumerate(available_slots):
            item = SlotSelectionItem(slot_data=slot, group_name="fallback_slots")
            # Mặc định tick chọn slot đầu tiên
            if i == 0:
                item.checkbox.active = True
            self.slots_box.add_widget(item)
            self.slot_items.append(item)
            
        # 4. Khu vực Nút bấm
        btn_box = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(45), spacing=dp(10))
        
        btn_confirm = MDButton(
            MDButtonText(text="XÁC NHẬN THÊM", text_color=WHITE_COLOR, font_style="Label", role="small"),
            style="filled", md_bg_color=BLUE_COLOR, size_hint_x=0.6,
            on_release=self.on_confirm
        )
        btn_cancel = MDButton(
            MDButtonText(text="HỦY BỎ", text_color=BLUE_COLOR, font_style="Label", role="small"),
            style="outlined", md_bg_color=WHITE_COLOR, size_hint_x=0.4,
            on_release=self.dismiss
        )
        
        btn_box.add_widget(btn_confirm)
        btn_box.add_widget(btn_cancel)
        self.main_layout.add_widget(btn_box)
        
        self.add_widget(self.main_layout)

    def on_confirm(self, instance):
        # Lấy khung giờ đang được check
        selected_slot = None
        for item in self.slot_items:
            if item.checkbox.active:
                selected_slot = item.slot_data
                break
                
        if selected_slot:
            print("\n[FE API CALL] -> POST /api/v1/events (TẠO SỰ KIỆN THỦ CÔNG)")
            print(f"Payload: source='MANUAL', start_time={selected_slot['start_time']}")
            
            # TODO: Cập nhật lại Lịch trên FE sau khi BE báo thành công
            
            self.dismiss()


class ProposalCard(MDBoxLayout):
    def __init__(self, proposal_data, chat_screen, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_x = 0.95
        self.pos_hint = {"center_x": 0.5}
        self.padding = dp(12)
        self.spacing = dp(8)
        self.adaptive_height = True # Tự động giãn khung theo nội dung
        
        self.proposal = proposal_data
        self.chat_screen = chat_screen
        self.buttons = []
        
        with self.canvas.before:
            Color(*WHITE_COLOR)
            self.bg_rect = RoundedRectangle(radius=[dp(8)])
            Color(*BLUE_COLOR)
            self.border = Line(rounded_rectangle=[0,0,0,0, dp(8)], width=1.2)
            
        self.bind(pos=self.update_canvas, size=self.update_canvas)
        self._build_info_ui()
        self._build_buttons_ui()

    def _build_info_ui(self):
        st = datetime.fromisoformat(self.proposal["start_time"])
        et = datetime.fromisoformat(self.proposal["end_time"])
        wd = WEEKDAYS_VN[st.weekday()]
        time_str = f"{wd} ({st.day}/{st.month}) | {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"

        # Thêm adaptive_height=True để chữ không bị dính vào nhau
        self.add_widget(MDLabel(text=f"Đề xuất xếp lịch: {self.proposal['task_title']}", bold=True, font_style="Title", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"Thời gian: {time_str}", font_style="Body", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"Lý do: {self.proposal['rationale']}", font_style="Body", role="medium", adaptive_height=True))

        self.status_lbl = MDLabel(text="", theme_text_color="Custom", text_color=BLUE_COLOR, bold=True, adaptive_height=True, opacity=0)
        self.add_widget(self.status_lbl)

    def _build_buttons_ui(self):
        # Bọc nút trong một layout, dùng size_hint_x=1 để nút tự chia đều không gian
        self.btn_layout = MDBoxLayout(orientation='horizontal', spacing=dp(4), adaptive_height=True)
        
        btn_confirm = MDButton(MDButtonText(text="Xác nhận", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_confirm, size_hint_x=1)
        btn_reject = MDButton(MDButtonText(text="Từ chối", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_reject, size_hint_x=1)
        btn_reschedule = MDButton(MDButtonText(text="Suy nghĩ thêm", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_reschedule, size_hint_x=1)
        
        self.buttons = [btn_confirm, btn_reject, btn_reschedule]
        for btn in self.buttons: self.btn_layout.add_widget(btn)
        self.add_widget(self.btn_layout)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.border.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(8)]

    # --- HÀNH VI 3 NÚT ---
    def on_confirm(self, instance):
        print(f"API CALL: POST /api/v1/proposals/{self.proposal['id']}/confirm")
        self.disable_card("Đã xác nhận thêm vào lịch")

    def on_reject(self, instance):
        print(f"API CALL: POST /api/v1/proposals/{self.proposal['id']}/reject")
        self.disable_card("Đã từ chối")

    def on_reschedule(self, instance):
        self.chat_screen.trigger_reschedule_mode(self)

    def disable_card(self, status_msg):
        self.btn_layout.opacity = 0
        self.btn_layout.height = 0
        self.status_lbl.text = status_msg
        self.status_lbl.opacity = 1
        for btn in self.buttons: btn.disabled = True
        if self in self.chat_screen.active_cards:
            self.chat_screen.active_cards.remove(self)


# ==============================================================================
# MÀN HÌNH CHÍNH (CHAT ASSISTANT SCREEN)
# ==============================================================================
class ChatAssistantScreen(MDScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.md_bg_color = WHITE_COLOR
        self.active_reschedule_proposal = None # Ghim thẻ đang cần đổi giờ
        self.active_cards = []                 # Các Thẻ đề xuất đang mở (chưa bấm nút nào)
        
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        self.main_layout = MDBoxLayout(orientation='vertical', md_bg_color=WHITE_COLOR)
        self.add_widget(self.main_layout)

        # 0. THANH TOP MENU MÀU XANH
        top_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(56), 
            md_bg_color=BLUE_COLOR, padding=[dp(10), dp(5), dp(15), dp(5)]
        )
        btn_menu = MDIconButton(icon="menu", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": .5})
        spacer = Widget() # Khung trống để đẩy các widget sang 2 bên
        logo_bg = MDRelativeLayout(
            size_hint=(None, None), 
            size=(dp(42), dp(42)),     # Kích thước vòng tròn trắng
            pos_hint={"center_y": .5},
            md_bg_color=WHITE_COLOR,   # Nền trắng
            radius=[dp(21)]            # Bo tròn hoàn toàn (bán kính = 1/2 kích thước)
        )
        logo = Image(
            source="assets/logo.png", 
            size_hint=(None, None), 
            size=(dp(34), dp(34)),     # Logo nhỏ hơn viền trắng một chút
            pos_hint={"center_x": .5, "center_y": .5}
        )
        logo_bg.add_widget(logo)
        
        top_bar.add_widget(btn_menu)
        top_bar.add_widget(spacer)
        top_bar.add_widget(logo_bg)    # Thêm cụm vòng tròn chứa logo vào Top Menu
        self.main_layout.add_widget(top_bar)
        # 1. KHUNG STREAM CHAT
        self.chat_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.chat_history = MDBoxLayout(
            orientation='vertical', size_hint_y=None, spacing=dp(15), padding=dp(10)
        )
        self.chat_history.bind(minimum_height=self.chat_history.setter('height'))
        self.chat_scroll.add_widget(self.chat_history)
        self.main_layout.add_widget(self.chat_scroll)

        # 2. BANNER RESCHEDULE (Mặc định ẩn)
        self.reschedule_banner = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=0, opacity=0, 
            md_bg_color=BLUE_LIGHT, padding=[dp(10), 0, dp(5), 0]
        )
        self.lbl_reschedule = MDLabel(text="", font_style="Label", role="medium", theme_text_color="Custom", text_color=BLUE_COLOR)
        btn_cancel_reschedule = MDIconButton(icon="close", theme_icon_color="Custom", icon_color=BLUE_COLOR, on_release=self.cancel_reschedule)
        
        self.reschedule_banner.add_widget(self.lbl_reschedule)
        self.reschedule_banner.add_widget(btn_cancel_reschedule)
        self.main_layout.add_widget(self.reschedule_banner)

        # 3. KHUNG NHẬP CHAT (Tự động kéo dài chiều cao)
        self.input_area = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            md_bg_color=GRAY_BG, padding=[dp(10), dp(5), dp(5), dp(5)], spacing=dp(5)
        )
        
        self.txt_input = TextInput(
            multiline=True, hint_text="Nhập yêu cầu xếp lịch...", 
            background_color=[0,0,0,0], foreground_color=BLACK_COLOR,
            font_size=dp(16), padding=[dp(5), dp(10), dp(5), dp(10)]
        )
        # Bắt sự kiện thay đổi chiều cao để mở rộng khung tối đa 6 dòng
        self.txt_input.bind(minimum_height=self.auto_resize_input)
        
        self.btn_send = MDIconButton(
            icon="send", theme_icon_color="Custom", icon_color=BLUE_COLOR, pos_hint={"center_y": 0.5},
            on_release=self.send_message
        )
        
        self.input_area.add_widget(self.txt_input)
        self.input_area.add_widget(self.btn_send)
        self.main_layout.add_widget(self.input_area)

        # 4. THANH MENU DƯỚI CÙNG
        nav_bar = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10))
        nav_bar.add_widget(NavTab(text="Lịch chính", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Tìm kiếm", target_screen="search_home", is_active=False)) # Giả định
        nav_bar.add_widget(NavTab(text="Trợ lý AI", target_screen="chat_home", is_active=True))
        self.main_layout.add_widget(nav_bar)

        self.append_ai_message("Chào bạn, mình có thể giúp gì để tối ưu lịch trình tuần này của bạn?")

    # ==========================================================================
    # LOGIC XỬ LÝ CHAT & API
    # ==========================================================================
    def auto_resize_input(self, instance, min_height):
        # Tính toán chiều cao (1 dòng ~ 20dp). Tối đa ~6 dòng = 120dp.
        new_height = min(max(dp(50), min_height + dp(10)), dp(120))
        self.input_area.height = new_height

    def scroll_to_bottom(self, *args):
        self.chat_scroll.scroll_y = 0

    def trigger_reschedule_mode(self, card_instance):
        """Bật chế độ ghim sửa giờ"""
        self.active_reschedule_proposal = card_instance
        self.lbl_reschedule.text = f"Đang yêu cầu đổi giờ cho: {card_instance.proposal['task_title']}"
        self.reschedule_banner.height = dp(35)
        self.reschedule_banner.opacity = 1
        self.txt_input.focus = True

    def cancel_reschedule(self, *args):
        """Hủy ghim sửa giờ"""
        self.active_reschedule_proposal = None
        self.reschedule_banner.height = 0
        self.reschedule_banner.opacity = 0

    def send_message(self, *args):
        user_text = self.txt_input.text.strip()
        if not user_text: return
        
        # 1. In câu chat của User lên màn hình
        self.chat_history.add_widget(ChatBubble(text=user_text, is_user=True))
        self.txt_input.text = ""
        Clock.schedule_once(self.scroll_to_bottom, 0.1)

        # 2. Xử lý Logic ID Hủy/Reschedule
        payload = {"prompt": user_text, "reschedule_proposal_id": None}
        
        if self.active_reschedule_proposal:
            # Gửi kèm ID để BE biết đang sửa thẻ nào
            payload["reschedule_proposal_id"] = self.active_reschedule_proposal.proposal["id"]
            self.active_reschedule_proposal.disable_card("Đã yêu cầu đổi giờ")
            self.cancel_reschedule() # Reset cờ ghim
        else:
            # Gửi tin nhắn hoàn toàn mới -> TỰ ĐỘNG HỦY (ABANDON) toàn bộ thẻ cũ đang mở
            for card in self.active_cards[:]: # Tạo bản sao list để xóa an toàn
                card.disable_card("Đã hủy do chuyển chủ đề")

        # 3. Giả lập Gọi API (Loading)
        print("API PAYLOAD TO BACKEND:", json.dumps(payload, ensure_ascii=False))
        Clock.schedule_once(self.mock_api_response, 1.5)

    def mock_api_response(self, dt):
        """[CẦN BACKEND XỬ LÝ]: Nơi nhận Response từ Bot Backend"""
        
        # Fake JSON Response từ Backend
        mock_response = {
            "fallback_mode": False,
            "ai_reply": "Mình thấy chiều thứ 4 bạn đang rảnh sau giờ Triết học. Đề xuất này có ổn không?",
            "proposal": {
                "id": 12,
                "task_id": 5,
                "task_title": "Làm đồ án CTDL",
                "start_time": "2026-10-21T13:30:00+07:00",
                "end_time": "2026-10-21T16:30:00+07:00",
                "rationale": "Chiều Thứ 4 bạn đang trống 4 tiếng sau giờ Triết học.",
                "status": "PROPOSED"
            }
        }
        
        mock_response = {
            "fallback_mode": True, 
            "task_title": "Làm đồ án CTDL",
            "duration": 180,
            "available_slots": [
                {"start_time": "2026-10-20T08:00:00+07:00", "end_time": "2026-10-20T11:00:00+07:00"},
                {"start_time": "2026-10-21T13:30:00+07:00", "end_time": "2026-10-21T16:30:00+07:00"},
                {"start_time": "2026-10-23T09:00:00+07:00", "end_time": "2026-10-23T12:00:00+07:00"}
            ]
        }

        # Xử lý Logic Fallback
        if mock_response.get("fallback_mode", False):
            # Mở ngay Modal Dự phòng
            ManualFallbackModal(
                task_title=mock_response.get("task_title", "Không rõ"),
                duration=mock_response.get("duration", 0),
                available_slots=mock_response.get("available_slots", [])
            ).open()
            
            self.append_ai_message("Xin lỗi, hệ thống xếp lịch tự động đang gặp lỗi hoặc hết giờ. Mình đã tìm được vài khung giờ trống, bạn hãy chọn thủ công trên màn hình nhé!")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        # In câu reply của AI
        if "ai_reply" in mock_response:
            self.append_ai_message(mock_response["ai_reply"])
            
        # Nếu có Proposal -> Vẽ Thẻ
        if mock_response.get("proposal"):
            new_card = ProposalCard(proposal_data=mock_response["proposal"], chat_screen=self)
            self.chat_history.add_widget(new_card)
            self.active_cards.append(new_card) # Đưa vào danh sách theo dõi chưa xử lý
            
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def append_ai_message(self, text):
        self.chat_history.add_widget(ChatBubble(text=text, is_user=False))

# ==============================================================================
# KHỐI CHẠY TEST
# ==============================================================================
if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return ChatAssistantScreen(name="chat_home")
    TestApp().run()