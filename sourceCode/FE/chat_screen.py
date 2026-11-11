import json
from datetime import date, datetime, timedelta

from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget
from kivy.uix.screenmanager import SlideTransition

from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.relativelayout import MDRelativeLayout
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText

# Import module API Client kết nối với máy chủ
from api_client import api
from fallback import is_timeout, parse_request
from notifier import ReminderScheduler
from event_store import store

reminder_scheduler = ReminderScheduler(reporter=api)  # one scheduler for the whole app (P2-9)

# ==============================================================================
# HẰNG SỐ MÀU SẮC
# ==============================================================================
WHITE_COLOR = [1, 1, 1, 1]
BLACK_COLOR = [0, 0, 0, 1]
GRAY_BG     = [0.95, 0.95, 0.95, 1]
GRAY_TEXT   = [0.5, 0.5, 0.5, 1]
BLUE_COLOR  = [0, 51/255, 204/255, 1]
BLUE_LIGHT  = [230/255, 240/255, 255/255, 1]

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
        
        self.checkbox = MDCheckbox(
            group=group_name,
            size_hint=(None, None), size=(dp(40), dp(40)),
            pos_hint={'center_y': .5},
            color_active=BLUE_COLOR, color_inactive=GRAY_TEXT
        )
        self.add_widget(self.checkbox)
        
        try:
            st = datetime.fromisoformat(slot_data["start_time"])
            et = datetime.fromisoformat(slot_data["end_time"])
            wd = WEEKDAYS_VN[st.weekday()]
            time_str = f"{wd} ({st.day}/{st.month}): {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"
        except Exception:
            time_str = str(slot_data)
        
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


class ChatBubble(MDBoxLayout):
    """Bong bóng chat hiển thị tin nhắn"""
    def __init__(self, text, is_user=False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.size_hint_x = 0.8
        self.padding = dp(10)
        
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
    """Bảng chọn giờ Thủ công khi AI Lỗi hoặc không khớp tự động được"""
    def __init__(self, task_title, duration, available_slots, ai_busy=False, **kwargs):
        super().__init__(**kwargs)
        self.task_title = task_title
        self.duration = duration
        self.size_hint = (0.9, 0.7)
        self.auto_dismiss = False
        self.background_color = [0, 0, 0, 0.6]
        
        self.main_layout = MDBoxLayout(
            orientation='vertical', padding=dp(15), spacing=dp(10), 
            md_bg_color=WHITE_COLOR, radius=[dp(12)]
        )
        
        self.title_label = MDLabel(
            text=("(!) Trợ lý AI đang bận. Bạn hãy chọn nhanh khung giờ dưới:" if ai_busy
                  else "Hãy chọn khung giờ phù hợp bên dưới:"),
            theme_text_color="Custom", text_color=[0.9, 0.4, 0, 1],
            bold=True, size_hint_y=None, height=dp(40)
        )
        self.main_layout.add_widget(self.title_label)
        
        info_box = MDBoxLayout(orientation='vertical', size_hint_y=None, height=dp(50), spacing=dp(5))
        info_box.add_widget(MDLabel(text=f"Tên hoạt động: [b]{task_title}[/b]", markup=True))
        info_box.add_widget(MDLabel(text=f"Thời lượng: {duration} phút"))
        self.main_layout.add_widget(info_box)
        
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
        
        self.slot_items = []
        for i, slot in enumerate(available_slots):
            item = SlotSelectionItem(slot_data=slot, group_name="fallback_slots")
            if i == 0:
                item.checkbox.active = True
            self.slots_box.add_widget(item)
            self.slot_items.append(item)
            
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
        selected_slot = None
        for item in self.slot_items:
            if item.checkbox.active:
                selected_slot = item.slot_data
                break
                
        if selected_slot:
            # Server dat cong viec o dau khung gio da chon (khong lay ca khung trong)
            api.create_manual_event(
                self.task_title, int(self.duration),
                selected_slot.get("start_time"), selected_slot.get("end_time"),
                on_success=lambda req, res: (reminder_scheduler.schedule_from_confirm(res), store.refresh(api), self.dismiss()),
                on_failure=lambda req, res: self._show_error(res),
                on_error=lambda req, err: self._show_error({"detail": "Lỗi kết nối Server."}),
            )

    def _show_error(self, res):
        detail = res.get("detail") if isinstance(res, dict) else None
        self.title_label.text = f"(!) Không thể lưu: {detail or 'lỗi không xác định'}"


class ProposalCard(MDBoxLayout):
    def __init__(self, proposal_data, chat_screen, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_x = 0.95
        self.pos_hint = {"center_x": 0.5}
        self.padding = dp(12)
        self.spacing = dp(8)
        self.adaptive_height = True
        
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
        try:
            st = datetime.fromisoformat(self.proposal["start_time"])
            et = datetime.fromisoformat(self.proposal["end_time"])
            wd = WEEKDAYS_VN[st.weekday()]
            time_str = f"{wd} ({st.day}/{st.month}) | {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"
        except Exception:
            time_str = "Không rõ thời gian"

        task_title = self.proposal.get('task_title', self.proposal.get('title', 'Sự kiện'))
        rationale = self.proposal.get('rationale', 'Đề xuất từ trợ lý AI.')

        self.add_widget(MDLabel(text=f"Đề xuất xếp lịch: {task_title}", bold=True, font_style="Title", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"Thời gian: {time_str}", font_style="Body", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"Lý do: {rationale}", font_style="Body", role="medium", adaptive_height=True))

        self.status_lbl = MDLabel(text="", theme_text_color="Custom", text_color=BLUE_COLOR, bold=True, adaptive_height=True, opacity=0)
        self.add_widget(self.status_lbl)

    def _build_buttons_ui(self):
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

    def on_confirm(self, instance):
        # POST /proposals/{id}/confirm: server kiem tra lai xung dot roi moi tao su kien
        pid = self.proposal.get("id")
        api.confirm_proposal(
            pid,
            on_success=lambda req, res: (reminder_scheduler.schedule_from_confirm(res), store.refresh(api),
                                         self.disable_card("Đã xác nhận thêm vào lịch")),
            on_failure=lambda req, res: self.disable_card(self._failure_text(res)),
            on_error=lambda req, err: self.disable_card("Lỗi kết nối máy chủ"),
        )

    def on_reject(self, instance):
        api.reject_proposal(
            self.proposal.get("id"),
            on_success=lambda req, res: self.disable_card("Đã từ chối"),
            on_failure=lambda req, res: self.disable_card(self._failure_text(res)),
            on_error=lambda req, err: self.disable_card("Lỗi kết nối máy chủ"),
        )

    @staticmethod
    def _failure_text(res):
        detail = res.get("detail") if isinstance(res, dict) else None
        return f"Không thực hiện được: {detail}" if detail else "Lỗi khi xử lý đề xuất"

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
        self.active_reschedule_proposal = None
        self.active_cards = []
        
        Clock.schedule_once(self.build_ui, 0)

    def build_ui(self, dt):
        self.main_layout = MDBoxLayout(orientation='vertical', md_bg_color=WHITE_COLOR)
        self.add_widget(self.main_layout)

        top_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(56), 
            md_bg_color=BLUE_COLOR, padding=[dp(10), dp(5), dp(15), dp(5)]
        )
        btn_menu = MDIconButton(icon="menu", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": .5})
        spacer = Widget()
               
        top_bar.add_widget(btn_menu)
        top_bar.add_widget(spacer)
        
        self.main_layout.add_widget(top_bar)

        self.chat_scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False)
        self.chat_history = MDBoxLayout(
            orientation='vertical', size_hint_y=None, spacing=dp(15), padding=dp(10)
        )
        self.chat_history.bind(minimum_height=self.chat_history.setter('height'))
        self.chat_scroll.add_widget(self.chat_history)
        self.main_layout.add_widget(self.chat_scroll)

        self.reschedule_banner = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=0, opacity=0, 
            md_bg_color=BLUE_LIGHT, padding=[dp(10), 0, dp(5), 0]
        )
        self.lbl_reschedule = MDLabel(text="", font_style="Label", role="medium", theme_text_color="Custom", text_color=BLUE_COLOR)
        btn_cancel_reschedule = MDIconButton(icon="close", theme_icon_color="Custom", icon_color=BLUE_COLOR, on_release=self.cancel_reschedule)
        
        self.reschedule_banner.add_widget(self.lbl_reschedule)
        self.reschedule_banner.add_widget(btn_cancel_reschedule)
        self.main_layout.add_widget(self.reschedule_banner)

        self.input_area = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            md_bg_color=GRAY_BG, padding=[dp(10), dp(5), dp(5), dp(5)], spacing=dp(5)
        )
        
        self.txt_input = TextInput(
            multiline=True, hint_text="Nhập yêu cầu xếp lịch...", 
            background_color=[0,0,0,0], foreground_color=BLACK_COLOR,
            font_size=dp(16), padding=[dp(5), dp(10), dp(5), dp(10)]
        )
        self.txt_input.bind(minimum_height=self.auto_resize_input)
        
        self.btn_send = MDIconButton(
            icon="send", theme_icon_color="Custom", icon_color=BLUE_COLOR, pos_hint={"center_y": 0.5},
            on_release=self.send_message
        )
        
        self.input_area.add_widget(self.txt_input)
        self.input_area.add_widget(self.btn_send)
        self.main_layout.add_widget(self.input_area)

        nav_bar = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10))
        nav_bar.add_widget(NavTab(text="Lịch chính", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Tìm kiếm", target_screen="search_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Trợ lý AI", target_screen="chat_home", is_active=True))
        self.main_layout.add_widget(nav_bar)

        self.append_ai_message("Chào bạn, mình có thể giúp gì để tối ưu lịch trình tuần này của bạn?")

    # ==========================================================================
    # LOGIC KẾT NỐI API SERVER VÀ XỬ LÝ NHẬN DỮ LIỆU THỰC TẾ
    # ==========================================================================
    def auto_resize_input(self, instance, min_height):
        new_height = min(max(dp(50), min_height + dp(10)), dp(120))
        self.input_area.height = new_height

    def scroll_to_bottom(self, *args):
        self.chat_scroll.scroll_y = 0

    def trigger_reschedule_mode(self, card_instance):
        self.active_reschedule_proposal = card_instance
        title = card_instance.proposal.get('task_title', card_instance.proposal.get('title', 'sự kiện'))
        self.lbl_reschedule.text = f"Đang yêu cầu đổi giờ cho: {title}"
        self.reschedule_banner.height = dp(35)
        self.reschedule_banner.opacity = 1
        self.txt_input.focus = True

    def cancel_reschedule(self, *args):
        self.active_reschedule_proposal = None
        self.reschedule_banner.height = 0
        self.reschedule_banner.opacity = 0

    def send_message(self, *args):
        user_text = self.txt_input.text.strip()
        if not user_text: return
        
        # 1. Hiển thị câu hỏi của người dùng
        self.chat_history.add_widget(ChatBubble(text=user_text, is_user=True))
        self.txt_input.text = ""
        Clock.schedule_once(self.scroll_to_bottom, 0.1)

        # Hủy bỏ/Disable các thẻ cũ nếu không trong chế độ sửa giờ
        if self.active_reschedule_proposal:
            self.active_reschedule_proposal.disable_card("Đã yêu cầu đổi giờ")
            self.cancel_reschedule()
        else:
            for card in self.active_cards[:]:
                card.disable_card("Đã hủy do chuyển chủ đề")

        # 2. Gửi request trực tiếp đến Backend Server
        self._last_text = user_text  # kept so a timeout can still open the manual picker
        reschedule_id = None
        if self.active_reschedule_proposal:
            reschedule_id = self.active_reschedule_proposal.proposal.get("id")
        api.understand(
            user_text,
            on_success=self.on_api_success,
            on_failure=self.on_api_failure,
            on_error=self.on_api_error,
            reschedule_proposal_id=reschedule_id,
        )

    def on_api_success(self, req, result):
        """Xử lý dữ liệu trả về từ máy chủ Backend"""
        if not result:
            self.append_ai_message("Đã nhận được thông tin nhưng máy chủ không trả về nội dung xử lý.")
            return

        # /assistant/understand tra ve {"nlu": {...}, "abandoned_proposals": n, "message": str|None}
        nlu = result.get("nlu") or {}
        print("[DEBUG FRONTEND]",nlu.get("duration_minutes"),nlu.get("needs_clarification"),nlu.get("intent"),"proposal:",bool(result.get("proposal")),"message:",result.get("message"))
        if nlu.get("fallback_mode"):
            print(f"[AI FALLBACK] {nlu.get('fallback_reason')}")

        proposal = result.get("proposal")
        if proposal:  # server found a free slot -> show the Accept / Reject / Reschedule card
            self.append_ai_message(result.get("message") or "Mình đề xuất khung giờ này:")
            new_card = ProposalCard(proposal_data=proposal, chat_screen=self)
            self.chat_history.add_widget(new_card)
            self.active_cards.append(new_card)
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        if nlu.get("needs_clarification") and nlu.get("clarification_question"):
            self.append_ai_message(nlu["clarification_question"])
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        if nlu.get("fallback_mode") and nlu.get("intent") == "schedule_task":
            # AI khong kha dung: bang chon gio thu cong voi cac khung trong that
            self._open_manual_picker(nlu)
            self.append_ai_message("Bạn vui lòng chọn khung giờ trống ở bảng trên nhé!")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        self.append_ai_message(result.get("message") or nlu.get("clarification_question")
                               or "Mình chưa hiểu rõ yêu cầu, bạn thử nói cụ thể hơn nhé.")
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def _open_manual_picker(self, nlu):
        title = nlu.get("title") or "Hoạt động"
        duration = nlu.get("duration_minutes") or 60
        start = nlu.get("window_start") or datetime.now().date().isoformat()
        # no explicit end (e.g. offline fallback): show a whole week of free gaps
        end = nlu.get("window_end") or (date.fromisoformat(start) + timedelta(days=6)).isoformat()
        
        busy = bool(nlu.get("fallback_mode"))

        def show(slots):
            ManualFallbackModal(task_title=title, duration=duration, available_slots=slots, ai_busy=busy).open()
        
        api.get_free_slots(
            f"{start}T00:00:00", f"{end}T23:59:59", max(15, min(int(duration), 720)),
            on_success=lambda r, res: show(res.get("available_slots", []) if isinstance(res, dict) else []),
            on_failure=lambda r, res: show([]),
            on_error=lambda r, err: show([]),
        )

    def on_api_failure(self, req, result):
        code = getattr(req, "resp_status", "?")
        text = f"Rất tiếc, yêu cầu bị từ chối bởi máy chủ (Mã lỗi: {code})."
        if code == 401:
            text += " Phiên đăng nhập đã hết hạn, bạn hãy đăng nhập lại."
        # Dùng .get() thay vì _error_detail nếu hàm này chưa được định nghĩa
        elif isinstance(result, dict) and result.get("detail"):
            text += f" Chi tiết: {result.get('detail')}"
            
        print(f"[API FAILURE] {getattr(req, 'url', '')} -> {code}: {result}")
        self.append_ai_message(text)
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def on_api_error(self, req, error):
        if is_timeout(error) and getattr(self, "_last_text", None):
            # P1-9: the AI request timed out -> go straight to the manual form with offline-parsed values
            self._open_manual_picker(parse_request(self._last_text))
            self.append_ai_message("Trợ lý AI phản hồi quá chậm. Bạn hãy chọn khung giờ trống ở bảng trên nhé!")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return
        self.append_ai_message(f"Không thể kết nối tới Server ({api.base_url}). Vui lòng kiểm tra lại đường truyền mạng.")
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def append_ai_message(self, text):
        self.chat_history.add_widget(ChatBubble(text=text, is_user=False))


if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return ChatAssistantScreen(name="chat_home")
    TestApp().run()