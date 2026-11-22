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

from kivy.storage.jsonstore import JsonStore
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.uix.relativelayout import MDRelativeLayout
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDIconButton, MDButton, MDButtonText

# Import module API Client kết nối với máy chủ
from api_client import api
from fallback import clip_slot_to_window, is_timeout, parse_request, slice_slots_to_duration
from notifier import ReminderScheduler
from event_store import store

# Import SideBarMenu để tích hợp tính năng menu trượt từ cạnh trái
from side_bar_menu import SideBarMenu
from chat_history_sidebar import ChatHistorySideBar

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

WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

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
            wd = WEEKDAYS_EN[st.weekday()]
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


class SelectableChatLabel(TextInput):
    """
    Widget hiển thị nội dung tin nhắn dạng văn bản cho phép người dùng:
    - Bôi đen, chọn vùng văn bản (select text region).
    - Sao chép bằng phím tắt Ctrl+C trên Desktop hoặc công cụ chọn/sao chép vùng trên mobile.
    - readonly=True: Ngăn chặn sửa đổi nội dung và không bật bàn phím ảo.
    - cursor_color=[0,0,0,0]: Ẩn con trỏ nhấp nháy, giữ giao diện sạch đẹp như nhãn văn bản thuần.
    """
    def __init__(self, text="", text_color=BLACK_COLOR, **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self.readonly = True
        self.multiline = True
        self.background_color = [0, 0, 0, 0]
        self.background_normal = ""
        self.background_active = ""
        self.foreground_color = text_color
        self.cursor_color = [0, 0, 0, 0]
        # Màu đánh dấu khi bôi đen vùng văn bản
        self.selection_color = [0.2, 0.5, 0.9, 0.4] if text_color == BLACK_COLOR else [1, 1, 1, 0.4]
        self.padding = [0, 0, 0, 0]
        self.font_size = dp(14)
        self.size_hint_y = None
        self.size_hint_x = 1
        self.do_scroll_y = False
        self.do_scroll_x = False
        self.bind(minimum_height=self._on_min_height)
        self.bind(width=self._on_width_change)
        self.height = max(dp(20), self.minimum_height)

    def _on_min_height(self, instance, val):
        self.height = max(dp(20), val)

    def _on_width_change(self, instance, val):
        Clock.schedule_once(lambda dt: setattr(self, 'height', max(dp(20), self.minimum_height)), 0)


class ChatBubble(MDBoxLayout):
    """Bong bóng chat hiển thị tin nhắn (có viền đen 1.15px, hỗ trợ chọn vùng văn bản & copy)"""
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
            self.radius = [dp(12), dp(12), 0, dp(12)]
        else:
            self.pos_hint = {"x": 0}
            bg_color = GRAY_BG
            txt_color = BLACK_COLOR
            self.radius = [dp(12), dp(12), dp(12), 0]

        with self.canvas.before:
            Color(*bg_color)
            self.bg_rect = RoundedRectangle(radius=self.radius)
            Color(*BLACK_COLOR)
            self.border_line = Line(width=1.15)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

        self.lbl = SelectableChatLabel(text=text, text_color=txt_color)
        self.lbl.bind(height=self.update_height)
        self.add_widget(self.lbl)
        self.height = self.lbl.height + dp(20)

    def update_height(self, instance, height_val):
        self.height = height_val + dp(20)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.border_line.rounded_rectangle = [self.x, self.y, self.width, self.height, *self.radius]


class ChatInputField(TextInput):
    """
    Ô nhập liệu tin nhắn chat:
    - Bấm Enter: Kích hoạt nút gửi (thực hiện gửi tin nhắn).
    - Bấm Shift + Enter hoặc bật CapsLock (hỗ trợ cho Android): Xuống hàng.
    """
    def __init__(self, on_send_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.on_send_callback = on_send_callback

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        key, key_str = keycode
        is_enter = (key in (13, 271) or key_str in ('enter', 'numpadenter'))

        if is_enter:
            mods = set(modifiers) if modifiers else set()
            # Bấm Shift + Enter hoặc khi bật CapsLock -> xuống dòng
            if 'shift' in mods or 'capslock' in mods:
                self.insert_text('\n')
                return True
            else:
                # Enter đơn lẻ -> gửi tin nhắn
                if self.on_send_callback:
                    self.on_send_callback()
                return True

        return super().keyboard_on_key_down(window, keycode, text, modifiers)

# ==============================================================================
# MODAL DỰ PHÒNG & THẺ ĐỀ XUẤT (PROPOSAL CARD)
# ==============================================================================
class ManualFallbackModal(ModalView):
    """Bảng chọn giờ Thủ công khi AI Lỗi hoặc không khớp tự động được"""
    def __init__(self, task_title, duration, available_slots, ai_busy=False, requested_window=None, on_scheduled=None, on_canceled=None, **kwargs):
        super().__init__(**kwargs)
        self.requested_window = requested_window  # ("11:00", "17:00") when the user named a clock range
        self.task_title = task_title
        self.duration = duration
        self.on_scheduled = on_scheduled
        self.on_canceled = on_canceled
        self.size_hint = (0.9, 0.7)
        self.auto_dismiss = False
        self.background_color = [0, 0, 0, 0.6]
        
        self.main_layout = MDBoxLayout(
            orientation='vertical', padding=dp(15), spacing=dp(10), 
            md_bg_color=WHITE_COLOR, radius=[dp(12)]
        )
        
        self.title_label = MDLabel(
            text=("(!) AI Assistant is busy. Please select a time slot below:" if ai_busy
                  else "Please select a suitable time slot below:"),
            theme_text_color="Custom", text_color=[0.9, 0.4, 0, 1],
            bold=True, size_hint_y=None, height=dp(40)
        )
        self.main_layout.add_widget(self.title_label)
        
        info_box = MDBoxLayout(orientation='vertical', size_hint_y=None, height=dp(50), spacing=dp(5))
        info_box.add_widget(MDLabel(text=f"Task name: [b]{task_title}[/b]", markup=True))
        info_box.add_widget(MDLabel(text=f"Duration: {duration} mins"))
        self.main_layout.add_widget(info_box)
        
        self.main_layout.add_widget(MDLabel(
            text="AVAILABLE TIME SLOTS THIS WEEK:",
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
            MDButtonText(text="CONFIRM", text_color=WHITE_COLOR, font_style="Label", role="small"),
            style="filled", md_bg_color=BLUE_COLOR, size_hint_x=0.6,
            on_release=self.on_confirm
        )
        btn_cancel = MDButton(
            MDButtonText(text="CANCEL", text_color=BLUE_COLOR, font_style="Label", role="small"),
            style="outlined", md_bg_color=WHITE_COLOR, size_hint_x=0.4,
            on_release=self.on_cancel_clicked
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
            # Server places the task within the selected slot trimmed to requested_window and duration
            slot_start, slot_end = clip_slot_to_window(
                selected_slot.get("start_time"),
                selected_slot.get("end_time"),
                self.requested_window,
                int(self.duration),
            )

            def _on_success(req, res):
                reminder_scheduler.schedule_from_confirm(res)
                store.refresh(api)
                self.dismiss()
                if self.on_scheduled:
                    events = res.get("events") if isinstance(res, dict) else None
                    confirmed_slot = (
                        events[0]
                        if events and isinstance(events[0], dict) and events[0].get("start_time")
                        else {"start_time": slot_start, "end_time": slot_end, "duration_minutes": int(self.duration)}
                    )
                    self.on_scheduled(confirmed_slot)

            api.create_manual_event(
                self.task_title, int(self.duration), slot_start, slot_end,
                on_success=_on_success,
                on_failure=lambda req, res: self._show_error(res),
                on_error=lambda req, err: self._show_error({"detail": "Server connection error."}),
            )

    def on_cancel_clicked(self, instance):
        self.dismiss()
        if self.on_canceled:
            self.on_canceled()

    def _show_error(self, res):
        detail = res.get("detail") if isinstance(res, dict) else None
        self.title_label.text = f"(!) Unable to save: {detail or 'unknown error'}"


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
            wd = WEEKDAYS_EN[st.weekday()]
            time_str = f"{wd} ({st.day}/{st.month}) | {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"
        except Exception as exc:
            print("[DEBUG PROPOSAL TIME ERROR]", type(exc).__name__, str(exc))
            print("[DEBUG PROPOSAL TIME DATA]", repr(self.proposal))
            time_str = "Unknown time"

        extra_slots = self.proposal.get("extra_slots") or []
        if extra_slots:
            parts = [f"Slot 1: {time_str}"]
            for idx, slot in enumerate(extra_slots, start=2):
                try:
                    s_dt = datetime.fromisoformat(slot["start_time"])
                    e_dt = datetime.fromisoformat(slot["end_time"])
                    parts.append(f"Slot {idx}: {s_dt.strftime('%H:%M')} - {e_dt.strftime('%H:%M')} ({s_dt.strftime('%d/%m')})")
                except (KeyError, ValueError):
                    continue
            time_str = " | ".join(parts)

        task_title = self.proposal.get('task_title', self.proposal.get('title', 'Event'))
        rationale = self.proposal.get('rationale', 'Proposed by AI Assistant.')
        reason_label = "Why this schedule was split" if extra_slots else "Why this time was chosen"

        self.add_widget(MDLabel(text=f"Schedule proposal: {task_title}", bold=True, font_style="Title", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"Time: {time_str}", font_style="Body", role="medium", adaptive_height=True))
        self.add_widget(MDLabel(text=f"{reason_label}: {rationale}", font_style="Body", role="medium", adaptive_height=True))

        self.status_lbl = MDLabel(text="", theme_text_color="Custom", text_color=BLUE_COLOR, bold=True, adaptive_height=True, opacity=0)
        self.add_widget(self.status_lbl)

    def _build_buttons_ui(self):
        self.btn_layout = MDBoxLayout(orientation='horizontal', spacing=dp(4), adaptive_height=True)
        
        btn_confirm = MDButton(MDButtonText(text="Confirm", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_confirm, size_hint_x=1)
        btn_reject = MDButton(MDButtonText(text="Reject", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_reject, size_hint_x=1)
        btn_reschedule = MDButton(MDButtonText(text="Reschedule", text_color=WHITE_COLOR, font_style="Label", role="small"), style="filled", md_bg_color=BLUE_COLOR, on_release=self.on_reschedule, size_hint_x=1)
        
        self.buttons = [btn_confirm, btn_reject, btn_reschedule]
        for btn in self.buttons: self.btn_layout.add_widget(btn)
        self.add_widget(self.btn_layout)

    def update_canvas(self, *args):
        self.bg_rect.pos = self.pos
        self.bg_rect.size = self.size
        self.border.rounded_rectangle = [self.x, self.y, self.width, self.height, dp(8)]

    def on_confirm(self, instance):
        # POST /proposals/{id}/confirm: server re-validates conflicts before creating events
        pid = self.proposal.get("id")
        api.confirm_proposal(
            pid,
            on_success=lambda req, res: (reminder_scheduler.schedule_from_confirm(res), store.refresh(api),
                                         self.disable_card("Confirmed and added to calendar")),
            on_failure=self._handle_action_failure,
            on_error=lambda req, err: self.show_status("Server connection error. Please try again."),
        )

    def on_reject(self, instance):
        api.reject_proposal(
            self.proposal.get("id"),
            on_success=lambda req, res: self.disable_card("Rejected"),
            on_failure=self._handle_action_failure,
            on_error=lambda req, err: self.show_status("Server connection error. Please try again."),
        )

    def _handle_action_failure(self, req, res):
        code = getattr(req, "resp_status", None)
        detail = (res.get("detail") if isinstance(res, dict) else "") or ""
        if code == 404 or (code == 409 and detail.lower().startswith("proposal is already")):
            self.disable_card(self._failure_text(res))
            return
        if code == 401:
            self.show_status("Session expired. Please log in again, then retry.")
            return
        self.show_status(f"{self._failure_text(res)}. You can Reschedule or Reject.")

    @staticmethod
    def _failure_text(res):
        detail = res.get("detail") if isinstance(res, dict) else None
        return f"Cannot execute: {detail}" if detail else "Error processing proposal"

    def on_reschedule(self, instance):
        self.chat_screen.trigger_reschedule_mode(self)

    def show_status(self, status_msg):
        """show feedback without permanently disabling proposal actions."""
        self.status_lbl.text = status_msg
        self.status_lbl.opacity = 1

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
        self._pending_reschedule_card = None
        self.active_cards = []
        
        # c. Quản lý trạng thái chat và lưu dữ liệu vào database cục bộ JsonStore
        self.chat_db = JsonStore("chat_history_db.json")
        self.chat_sessions = []
        self.current_session_title = "New conversation"
        self.current_session_messages = []
        self.is_current_session_saved = False
        self._load_chat_history_from_db()
        self._save_trigger = Clock.create_trigger(self._do_save_chat_history_to_db, 2.0)
        
        Clock.schedule_once(self.build_ui, 0)

    def _db_user_key(self):
        return f"user_{api.user_id or 'guest'}"

    def _load_chat_history_from_db(self):
        key = self._db_user_key()
        if self.chat_db.exists(key):
            try:
                self.chat_sessions = self.chat_db.get(key).get("sessions", [])
            except Exception:
                self.chat_sessions = []
        else:
            self.chat_sessions = []

    def _save_chat_history_to_db(self, immediate=False):
        if immediate:
            self._do_save_chat_history_to_db()
        elif hasattr(self, '_save_trigger'):
            self._save_trigger()

    def _do_save_chat_history_to_db(self, *args):
        key = self._db_user_key()
        try:
            self.chat_db.put(key, sessions=self.chat_sessions)
        except Exception as e:
            print("Lỗi lưu chat history vào database:", e)

    def on_pre_enter(self, *args):
        self._load_chat_history_from_db()

    def build_ui(self, dt):
        self.main_layout = MDBoxLayout(orientation='vertical', md_bg_color=WHITE_COLOR)
        self.add_widget(self.main_layout)
        # Khởi tạo đối tượng SideBarMenu và lưu vào thuộc tính của Screen để tái sử dụng
        self.side_menu = SideBarMenu()
        self.history_menu = ChatHistorySideBar() # Khởi tạo sidebar bên phải

        top_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(56), 
            md_bg_color=BLUE_COLOR, padding=[dp(10), dp(5), dp(10), dp(5)]
        )
        
        # Nút menu chính (bên trái)
        btn_menu = MDIconButton(icon="menu", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": .5})
        btn_menu.bind(on_release=lambda x: self.side_menu.open())
        spacer = Widget()
        
        # Nút tạo chat mới
        btn_new_chat = MDIconButton(icon="plus-circle-outline", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": .5})
        btn_new_chat.bind(on_release=self.start_new_chat)
        
        # Nút lịch sử
        btn_history = MDIconButton(icon="history", theme_icon_color="Custom", icon_color=WHITE_COLOR, pos_hint={"center_y": .5})
        btn_history.bind(on_release=lambda x: self.open_history())
               
        top_bar.add_widget(btn_menu)
        top_bar.add_widget(spacer)
        top_bar.add_widget(btn_new_chat) # Thêm nút new_chat vào
        top_bar.add_widget(btn_history) # Thêm nút lịch sử vào layout
        
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

        # b. Thêm viền đen 1.15px bo tròn hai đầu (nửa hình tròn) cho khung chat
        self.input_container = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(56),
            padding=[dp(12), dp(4), dp(12), dp(4)], md_bg_color=WHITE_COLOR
        )
        self.input_area = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(48), 
            padding=[dp(14), dp(2), dp(6), dp(2)], spacing=dp(5)
        )
        with self.input_area.canvas.before:
            Color(*GRAY_BG)
            self.input_bg = RoundedRectangle()
            Color(*BLACK_COLOR)
            self.input_border = Line(width=1.15)
        self.input_area.bind(pos=self._update_input_shape, size=self._update_input_shape)
        
        self.txt_input = ChatInputField(
            on_send_callback=self.send_message,
            multiline=True, hint_text="Type a scheduling request...", 
            background_color=[0,0,0,0], foreground_color=BLACK_COLOR,
            font_size=dp(15), padding=[dp(5), dp(10), dp(5), dp(10)]
        )
        self.txt_input.bind(minimum_height=self.auto_resize_input)
        
        self.btn_send = MDIconButton(
            icon="send", theme_icon_color="Custom", icon_color=BLUE_COLOR, pos_hint={"center_y": 0.5},
            on_release=self.send_message
        )
        
        self.input_area.add_widget(self.txt_input)
        self.input_area.add_widget(self.btn_send)
        self.input_container.add_widget(self.input_area)
        self.main_layout.add_widget(self.input_container)

        # Thanh điều hướng (Nav bar) cố định dưới cùng
        nav_bar = MDBoxLayout(
            orientation='horizontal', size_hint_y=None, height=dp(50), 
            padding=[dp(10), dp(5), dp(10), dp(5)], spacing=dp(10)
        )
        nav_bar.add_widget(NavTab(text="Calendar", target_screen="calendar_home", is_active=False))
        nav_bar.add_widget(NavTab(text="Search", target_screen="search_home", is_active=False))
        nav_bar.add_widget(NavTab(text="AI Assistant", target_screen="chat_home", is_active=True))
        self.main_layout.add_widget(nav_bar)

        if not self.current_session_messages:
            self.append_ai_message("Hello! How can I help optimize your schedule this week?")

    def _update_input_shape(self, *args):
        r = self.input_area.height / 2.0
        self.input_bg.pos = self.input_area.pos
        self.input_bg.size = self.input_area.size
        self.input_bg.radius = [r, r, r, r]
        self.input_border.rounded_rectangle = [
            self.input_area.x, self.input_area.y, self.input_area.width, self.input_area.height, r
        ]

    # ==========================================================================
    # LOGIC KẾT NỐI API SERVER VÀ XỬ LÝ NHẬN DỮ LIỆU THỰC TẾ
    # ==========================================================================
    def auto_resize_input(self, instance, min_height):
        new_height = min(max(dp(48), min_height + dp(10)), dp(120))
        self.input_area.height = new_height
        if hasattr(self, "input_container"):
            self.input_container.height = new_height + dp(8)

    def scroll_to_bottom(self, *args):
        self.chat_scroll.scroll_y = 0

    def trigger_reschedule_mode(self, card_instance):
        self.active_reschedule_proposal = card_instance
        title = card_instance.proposal.get('task_title', card_instance.proposal.get('title', 'event'))
        self.lbl_reschedule.text = f"Requesting reschedule for: {title}"
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
        
        # Đặt tiêu đề nếu là tin nhắn đầu tiên của user trong đoạn chat này
        if not any(m['is_user'] for m in self.current_session_messages):
            self.current_session_title = user_text
            
        self.current_session_messages.append({"text": user_text, "is_user": True})
        self.chat_history.add_widget(ChatBubble(text=user_text, is_user=True))
        self.save_current_session()
        self.txt_input.text = ""
        self.txt_input.focus = True
        Clock.schedule_once(self.scroll_to_bottom, 0.1)

        # 1. Keep reschedule card alive until server returns a replacement proposal
        reschedule_id = None
        self._pending_reschedule_card = None
        if self.active_reschedule_proposal:
            self._pending_reschedule_card = self.active_reschedule_proposal
            reschedule_id = self._pending_reschedule_card.proposal.get("id")
            self._pending_reschedule_card.show_status("Requesting reschedule...")
            self.reschedule_banner.height = 0
            self.reschedule_banner.opacity = 0
        else:
            for card in self.active_cards[:]:
                card.disable_card("Canceled due to topic change")

        # 2. Gửi request trực tiếp đến Backend Server
        self._last_text = user_text  # kept so a timeout can still open the manual picker
        api.understand(
            user_text,
            on_success=self.on_api_success,
            on_failure=self.on_api_failure,
            on_error=self.on_api_error,
            reschedule_proposal_id=reschedule_id,
        )

    def _redirect_to(self, target_screen):
        app = MDApp.get_running_app()
        if app and app.root and hasattr(app.root, "current"):
            app.root.current = target_screen

    def _format_slot_vn(self, slot):
        try:
            st = datetime.fromisoformat(slot["start_time"])
            et = datetime.fromisoformat(slot["end_time"])
            wd = WEEKDAYS_EN[st.weekday()]
            return f"{wd} ({st.day}/{st.month}): {st.strftime('%H:%M')} - {et.strftime('%H:%M')}"
        except Exception:
            return str(slot)

    def _trigger_fallback_ui(self, title, duration, slots, busy=True, window=None):
        slots = slice_slots_to_duration(slots or [], int(duration or 60), requested_window=window)
        # 1. Bong bóng thông báo chuyển chế độ
        self.append_ai_message("AI Assistant is busy. Please select a free slot from the table below!")

        # 2. Bong bóng chat thứ 2 ngay bên dưới hiển thị thông tin y hệt trên popup đó:
        slots_lines = [f"- {self._format_slot_vn(s)}" for s in slots[:8]]
        slots_text = "\n".join(slots_lines) if slots_lines else "- No available free time slots."
        info_bubble_text = (
            f"[TASK TO BE SCHEDULED]\n"
            f"- Task: {title}\n"
            f"- Duration: {duration} mins\n\n"
            f"AVAILABLE TIME SLOTS THIS WEEK:\n"
            f"{slots_text}"
        )
        self.append_ai_message(info_bubble_text)

        def on_scheduled(selected_slot):
            self.append_ai_message(f"[Confirmed] Selected slot {self._format_slot_vn(selected_slot)} for '{title}'.")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)

        def on_canceled():
            self.append_ai_message("[Canceled] You canceled slot selection.")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)

        ManualFallbackModal(
            task_title=title,
            duration=duration,
            available_slots=slots,
            ai_busy=busy,
            requested_window=window,
            on_scheduled=on_scheduled,
            on_canceled=on_canceled,
        ).open()
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def on_api_success(self, req, result):
        """Xử lý dữ liệu trả về từ máy chủ Backend"""
        if not result:
            self.append_ai_message("Received information but server returned no actionable content.")
            return

        # 1. Nhánh Redirect (nếu người dùng hỏi lạc sang tra cứu lịch hoặc hỏi quy chế học vụ)
        redirect_target = result.get("redirect_target")
        redirect_label = result.get("redirect_button_label") or "Switch tab"
        if redirect_target:
            msg = result.get("message") or "You may want to search schedules or query academic regulations."
            self.append_ai_message(msg)
            nav_btn = MDButton(
                MDButtonText(text=f"Switch to {redirect_label}", text_color=WHITE_COLOR),
                style="filled",
                md_bg_color=BLUE_COLOR,
                size_hint=(None, None),
                size=(dp(220), dp(40)),
                pos_hint={"center_x": 0.5},
                on_release=lambda *_: self._redirect_to(redirect_target)
            )
            self.chat_history.add_widget(nav_btn)
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        # /assistant/understand tra ve {"nlu": {...}, "abandoned_proposals": n, "message": str|None}
        nlu = result.get("nlu") or {}
        if nlu.get("fallback_mode"):
            print(f"[AI FALLBACK] {nlu.get('fallback_reason')}")

        proposal = result.get("proposal")
        print("[DEBUG FRONTEND PROPOSAL]", repr(proposal))
        pending_resched = getattr(self, "_pending_reschedule_card", None)
        if proposal:  # server found a free slot -> show the Accept / Reject / Reschedule card
            if pending_resched is not None:
                pending_resched.disable_card("Rescheduled")
                self._pending_reschedule_card = None
                self.cancel_reschedule()
            self.append_ai_message(result.get("message") or "I propose this time slot:")
            new_card = ProposalCard(proposal_data=proposal, chat_screen=self)
            self.chat_history.add_widget(new_card)
            self.active_cards.append(new_card)
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        if nlu.get("needs_clarification") and nlu.get("clarification_question"):
            if pending_resched is not None:
                pending_resched.show_status("Awaiting clarification for reschedule...")
                self.trigger_reschedule_mode(pending_resched)
                self._pending_reschedule_card = None
            self.append_ai_message(nlu["clarification_question"])
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return

        if nlu.get("fallback_mode"):
            if pending_resched is not None:
                pending_resched.show_status("AI busy; you can still Confirm, Reject, or Reschedule.")
                self._pending_reschedule_card = None
                self.cancel_reschedule()
            task_title = nlu.get("title") or "New activity"
            duration = int(nlu.get("duration_minutes") or 60)
            window = (
                (nlu["requested_start"], nlu["requested_end"])
                if nlu.get("requested_start") and nlu.get("requested_end")
                else None
            )
            precomputed_slots = result.get("available_slots") or []
            if precomputed_slots:
                self._trigger_fallback_ui(task_title, duration, precomputed_slots, busy=True, window=window)
            else:
                self._open_manual_picker(nlu)
            return

        if pending_resched is not None:
            pending_resched.show_status("No replacement slot found. You can Confirm, Reject, or Reschedule again.")
            self._pending_reschedule_card = None
            self.cancel_reschedule()
        self.append_ai_message(result.get("message") or nlu.get("clarification_question")
                               or "I could not fully understand your request. Could you please specify more details?")
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def _open_manual_picker(self, nlu):
        title = nlu.get("title") or "Activity"
        duration = nlu.get("duration_minutes") or 60
        start = nlu.get("window_start") or datetime.now().date().isoformat()
        # no explicit end (e.g. offline fallback): show a whole week of free gaps
        end = nlu.get("window_end") or (date.fromisoformat(start) + timedelta(days=6)).isoformat()
        
        busy = bool(nlu.get("fallback_mode"))
        window = (nlu["requested_start"], nlu["requested_end"]) if nlu.get("requested_start") and nlu.get("requested_end") else None

        def show(slots):
            self._trigger_fallback_ui(title, duration, slots, busy=busy, window=window)
        
        api.get_free_slots(
            f"{start}T00:00:00", f"{end}T23:59:59", max(15, min(int(duration), 720)),
            on_success=lambda r, res: show(res.get("available_slots", []) if isinstance(res, dict) else []),
            on_failure=lambda r, res: show([]),
            on_error=lambda r, err: show([]),
        )

    def on_api_failure(self, req, result):
        code = getattr(req, "resp_status", "?")
        pending_resched = getattr(self, "_pending_reschedule_card", None)
        if pending_resched is not None:
            detail = (result.get("detail") if isinstance(result, dict) else "") or ""
            if code == 404 or (code == 409 and detail.lower().startswith("proposal is already")):
                pending_resched.disable_card(pending_resched._failure_text(result))
                self.cancel_reschedule()
            else:
                pending_resched.show_status("Reschedule failed. You can still Confirm, Reject, or retry.")
            self._pending_reschedule_card = None
        text = f"Sorry, the request was rejected by the server (Status: {code})."
        if code == 401:
            text += " Session expired, please log in again."
        # Dùng .get() thay vì _error_detail nếu hàm này chưa được định nghĩa
        elif isinstance(result, dict) and result.get("detail"):
            text += f" Details: {result.get('detail')}"
            
        print(f"[API FAILURE] {getattr(req, 'url', '')} -> {code}: {result}")
        self.append_ai_message(text)
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def on_api_error(self, req, error):
        pending_resched = getattr(self, "_pending_reschedule_card", None)
        if pending_resched is not None:
            pending_resched.show_status("Connection error during reschedule. Buttons remain active.")
            self._pending_reschedule_card = None
        if is_timeout(error) and getattr(self, "_last_text", None):
            # P1-9: the AI request timed out -> go straight to the manual form with offline-parsed values
            self._open_manual_picker(parse_request(self._last_text))
            self.append_ai_message("AI Assistant response timed out. Please choose a free slot from the table above!")
            Clock.schedule_once(self.scroll_to_bottom, 0.2)
            return
        self.append_ai_message(f"Cannot connect to server ({api.base_url}). Please check your network connection.")
        Clock.schedule_once(self.scroll_to_bottom, 0.2)

    def append_ai_message(self, text):
        self.current_session_messages.append({"text": text, "is_user": False})
        self.chat_history.add_widget(ChatBubble(text=text, is_user=False))
        self.save_current_session()

    def save_current_session(self):
        """Lưu đoạn chat hiện tại vào danh sách lịch sử nếu người dùng đã nhắn tin"""
        if not any(m.get('is_user') for m in self.current_session_messages):
            return
        session_data = {
            "title": self.current_session_title,
            "messages": list(self.current_session_messages)
        }
        if getattr(self, "is_current_session_saved", False) and self.chat_sessions:
            self.chat_sessions[-1] = session_data
        else:
            self.chat_sessions.append(session_data)
            self.is_current_session_saved = True
        self._save_chat_history_to_db()

    def start_new_chat(self, *args):
        self.save_current_session()
        self._save_chat_history_to_db(immediate=True)
        
        # Reset dữ liệu và UI
        self.chat_history.clear_widgets()
        self.current_session_title = "New conversation"
        self.current_session_messages = []
        self.is_current_session_saved = False
        self.active_cards = []
        if self.active_reschedule_proposal:
            self.cancel_reschedule()
            
        self.append_ai_message("Hello! How can I help optimize your schedule this week?")

    def load_chat_session(self, index):
        """Được gọi khi người dùng bấm vào 1 đoạn chat trong sidebar"""
        self.save_current_session()
        self._save_chat_history_to_db(immediate=True)
        
        if 0 <= index < len(self.chat_sessions):
            selected = self.chat_sessions.pop(index)
            self.chat_history.clear_widgets()
            self.current_session_title = selected.get("title", "Conversation")
            self.current_session_messages = selected.get("messages", [])
            self.active_cards = []
            if self.active_reschedule_proposal:
                self.cancel_reschedule()
                
            for msg in self.current_session_messages:
                self.chat_history.add_widget(ChatBubble(text=msg["text"], is_user=msg["is_user"]))
                
            self.chat_sessions.append(selected)
            self.is_current_session_saved = True
            self._save_chat_history_to_db()
            Clock.schedule_once(self.scroll_to_bottom, 0.1)

    def delete_chat_session(self, index):
        """
        Xóa một phiên trò chuyện khỏi danh sách và cập nhật trực tiếp vào database cục bộ:
        - Xóa session tại index trong self.chat_sessions.
        - Ghi đè cập nhật vào JsonStore ('chat_history_db.json') ngay lập tức.
        - Nếu phiên bị xóa đang mở trên màn hình thì làm sạch và chuyển về màn hình chat mới.
        - Cập nhật lại giao diện danh sách lịch sử trong sidebar.
        """
        if 0 <= index < len(self.chat_sessions):
            deleted = self.chat_sessions.pop(index)
            self._save_chat_history_to_db(immediate=True)
            
            # Kiểm tra nếu phiên bị xóa chính là phiên đang hiển thị trên màn hình
            is_active_session = (
                self.is_current_session_saved and 
                (self.current_session_title == deleted.get("title") or len(self.chat_sessions) == 0)
            )
            if is_active_session:
                self.chat_history.clear_widgets()
                self.current_session_title = "New conversation"
                self.current_session_messages = []
                self.is_current_session_saved = False
                self.active_cards = []
                if self.active_reschedule_proposal:
                    self.cancel_reschedule()
                self.append_ai_message("Hello! How can I help optimize your schedule this week?")

            # Tải lại danh sách lịch sử ngay trên menu
            self.history_menu.load_history(
                self.chat_sessions,
                callback=self.load_chat_session,
                delete_callback=self.delete_chat_session
            )

    def open_history(self):
        self.save_current_session()
        self.history_menu.load_history(
            self.chat_sessions,
            callback=self.load_chat_session,
            delete_callback=self.delete_chat_session
        )
        self.history_menu.open()


if __name__ == "__main__":
    Window.size = (360, 640)
    class TestApp(MDApp):
        def build(self):
            self.theme_cls.theme_style = "Light"
            return ChatAssistantScreen(name="chat_home")
    TestApp().run()