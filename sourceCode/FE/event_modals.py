import os
from datetime import datetime
from kivy.uix.modalview import ModalView
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText
from kivymd.uix.card import MDCard
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.filemanager import MDFileManager
from kivymd.app import MDApp

from api_client import api

# ==============================================================================
# 1. MODAL: THÊM SỰ KIỆN THỦ CÔNG
# ==============================================================================
class AddEventModal(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.8)
        self.auto_dismiss = False
        
        layout = MDBoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15), md_bg_color=[1, 1, 1, 1], radius=[dp(12)])
        layout.add_widget(MDLabel(text="Thêm Sự Kiện Mới", font_style="Title", role="large", bold=True, size_hint_y=None, height=dp(40)))
        
        self.tf_title = MDTextField(MDTextFieldHintText(text="Tên sự kiện"), mode="outlined")
        self.tf_date = MDTextField(MDTextFieldHintText(text="Ngày (YYYY-MM-DD)"), mode="outlined")
        self.tf_start = MDTextField(MDTextFieldHintText(text="Giờ bắt đầu (HH:MM)"), mode="outlined")
        self.tf_end = MDTextField(MDTextFieldHintText(text="Giờ kết thúc (HH:MM)"), mode="outlined")
        
        # Dropdown chọn loại sự kiện
        self.tf_kind = MDTextField(
            MDTextFieldHintText(text="Loại sự kiện"),
            text="TASK", # Mặc định
            mode="outlined",
            readonly=True,
        )
        self.tf_kind.bind(on_focus=self.open_kind_menu)
        
        menu_items = [
            {"text": "CLASS", "on_release": lambda x="CLASS": self.set_kind(x)},
            {"text": "EXAM", "on_release": lambda x="EXAM": self.set_kind(x)},
            {"text": "EVENT", "on_release": lambda x="EVENT": self.set_kind(x)},
            {"text": "TASK", "on_release": lambda x="TASK": self.set_kind(x)},
            {"text": "DEADLINE", "on_release": lambda x="DEADLINE": self.set_kind(x)},
        ]
        self.kind_menu = MDDropdownMenu(caller=self.tf_kind, items=menu_items, width_mult=4)
        
        layout.add_widget(self.tf_title)
        layout.add_widget(self.tf_kind)
        layout.add_widget(self.tf_date)
        layout.add_widget(self.tf_start)
        layout.add_widget(self.tf_end)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        btn_save = MDButton(MDButtonText(text="LƯU", text_color=[1, 1, 1, 1]), style="filled", md_bg_color=[0, 51/255, 204/255, 1], size_hint_x=1, on_release=self.save_event)
        btn_cancel = MDButton(MDButtonText(text="HỦY"), style="outlined", size_hint_x=1, on_release=self.dismiss)
        
        btn_box.add_widget(btn_save)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        self.add_widget(layout)

    def open_kind_menu(self, instance, focus):
        if focus:
            self.kind_menu.open()
            self.tf_kind.focus = False 

    def set_kind(self, kind_text):
        self.tf_kind.text = kind_text
        self.kind_menu.dismiss()

    def save_event(self, instance):
        try:
            fmt = "%H:%M"
            start_dt = datetime.strptime(self.tf_start.text, fmt)
            end_dt = datetime.strptime(self.tf_end.text, fmt)
            duration = int((end_dt - start_dt).total_seconds() / 60)
        except ValueError:
            self.tf_title.text = "Lỗi: Sai định dạng giờ!"
            return

        start_iso = f"{self.tf_date.text}T{self.tf_start.text}:00"
        end_iso = f"{self.tf_date.text}T{self.tf_end.text}:00"

        # 1. Khởi tạo event để check xung đột
        mock_row = [{
            "title": self.tf_title.text,
            "kind": self.tf_kind.text,
            "start_time": start_iso,
            "end_time": end_iso
        }]

        # 2. Gọi kiểm tra xung đột trước
        api._request(
            "/api/v1/ingestion/check-conflicts",
            method="POST",
            payload={"valid_rows": mock_row},
            on_success=lambda req, res: self.on_check_success(res, duration, start_iso, end_iso),
            on_error=lambda req, err: print("Lỗi mạng khi check xung đột")
        )

    def on_check_success(self, result, duration, start_iso, end_iso):
        # Nếu có mảng conflict_cards thì tức là bị trùng lịch
        if result.get("conflict_cards"):
            self.tf_title.text = "LỖI: Trùng lịch!"
            # Hoặc bạn có thể tự động mở ImportStep3Modal ở đây nếu muốn
            return
            
        # 3. Nếu KHÔNG trùng lịch, đẩy thẳng vào lịch
        # Gọi trực tiếp _request để nhúng thêm trường "kind" mà hàm create_manual_event cũ đang thiếu
        api._request(
            "/api/v1/proposals/manual", 
            method="POST", 
            payload={
                "title": self.tf_title.text,
                "kind": self.tf_kind.text,
                "duration_minutes": duration,
                "slot_start": start_iso,
                "slot_end": end_iso
            },
            on_success=lambda req, res: self.dismiss(),
            on_failure=lambda req, res: print("Lỗi thêm sự kiện"),
            on_error=lambda req, err: print("Lỗi mạng")
        )

# ==============================================================================
# 2. MODAL: IMPORT LỊCH - BƯỚC 1 (Chỉ Import File)
# ==============================================================================
class ImportStep1Modal(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.45)
        self.auto_dismiss = False
        
        layout = MDBoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15), md_bg_color=[1, 1, 1, 1], radius=[dp(12)])
        layout.add_widget(MDLabel(text="Import Lịch (Bước 1/3)", font_style="Title", role="large", bold=True, size_hint_y=None, height=dp(40)))
        
        self.lbl_file = MDLabel(text="Chưa chọn file nào", theme_text_color="Hint", halign="center")
        layout.add_widget(self.lbl_file)
        
        btn_select = MDButton(MDButtonText(text="CHỌN FILE LỊCH (.txt, .csv)"), style="elevated", size_hint_x=1, on_release=self.open_file_manager)
        layout.add_widget(btn_select)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        self.btn_analyze = MDButton(MDButtonText(text="PHÂN TÍCH", text_color=[1, 1, 1, 1]), style="filled", md_bg_color=[0, 51/255, 204/255, 1], size_hint_x=1, on_release=self.analyze_data, disabled=True)
        btn_cancel = MDButton(MDButtonText(text="HỦY"), style="outlined", size_hint_x=1, on_release=self.dismiss)
        
        btn_box.add_widget(self.btn_analyze)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        self.add_widget(layout)

        # Cấu hình File Manager của KivyMD
        self.file_manager = MDFileManager(
            exit_manager=self.exit_manager,
            select_path=self.select_path,
        )
        self.selected_path = None

    def open_file_manager(self, instance):
        # Mở thư mục gốc của thiết bị (mặc định)
        self.file_manager.show(os.path.expanduser("~"))

    def select_path(self, path: str):
        self.selected_path = path
        self.lbl_file.text = f"Đã chọn: {os.path.basename(path)}"
        self.btn_analyze.disabled = False
        self.exit_manager()

    def exit_manager(self, *args):
        self.file_manager.close()

    def analyze_data(self, instance):
        if not self.selected_path:
            return
            
        try:
            with open(self.selected_path, 'r', encoding='utf-8') as f:
                raw_text = f.read()
        except Exception as e:
            self.lbl_file.text = "Lỗi: Không thể đọc file!"
            return

        # Gửi dữ liệu text đọc được từ file xuống API
        api.parse_preview(
            text_data=raw_text,
            on_success=self.on_parse_success,
            on_failure=lambda req, res: print("Phân tích lỗi:", res),
            on_error=lambda req, err: print("Lỗi mạng:", err)
        )
        
    def on_parse_success(self, req, result):
        self.dismiss()
        ImportStep2Modal(preview_data=result).open()

# ==============================================================================
# 3. MODAL: IMPORT LỊCH - BƯỚC 2 (Review & Fix Lỗi)
# ==============================================================================
class ImportStep2Modal(ModalView):
    def __init__(self, preview_data, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.95, 0.9)
        self.auto_dismiss = False
        self.preview_data = preview_data
        
        layout = MDBoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10), md_bg_color=[1, 1, 1, 1], radius=[dp(12)])
        layout.add_widget(MDLabel(text="Xem trước & Xử lý (Bước 2/3)", font_style="Title", bold=True, size_hint_y=None, height=dp(40)))
        
        scroll = ScrollView()
        self.list_layout = MDBoxLayout(orientation='vertical', spacing=dp(10), adaptive_height=True)
        
        # Render Thẻ Xanh (Hợp lệ)
        for row in self.preview_data.get("valid_rows", []):
            card = MDCard(md_bg_color=[0.9, 1, 0.9, 1], size_hint_y=None, height=dp(60), padding=dp(10))
            card.add_widget(MDLabel(text=f"✅ {row.get('title')} ({row.get('start_time')} - {row.get('end_time')})"))
            self.list_layout.add_widget(card)
            
        # Render Thẻ Vàng (Lỗi)
        for row in self.preview_data.get("invalid_rows", []):
            card = MDCard(orientation='vertical', md_bg_color=[1, 0.95, 0.8, 1], size_hint_y=None, height=dp(100), padding=dp(10))
            card.add_widget(MDLabel(text=f"⚠️ Dòng {row.get('line_number')}: {row.get('error_message')}", bold=True, text_color=[0.8, 0.5, 0, 1]))
            card.add_widget(MDLabel(text=row.get('raw_text'), theme_text_color="Hint"))
            # Khu vực nút bấm sửa/bỏ qua (Giản lược UI cho ví dụ)
            card.add_widget(MDLabel(text="[Bấm để Sửa trực tiếp hoặc Bỏ qua - Cần ghép UI Form]", font_style="Label"))
            self.list_layout.add_widget(card)
            
        scroll.add_widget(self.list_layout)
        layout.add_widget(scroll)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        btn_next = MDButton(MDButtonText(text="TIẾP TỤC KIỂM TRA TRÙNG LỊCH", text_color=[1, 1, 1, 1]), style="filled", md_bg_color=[0, 51/255, 204/255, 1], size_hint_x=1, on_release=self.check_conflicts)
        btn_box.add_widget(btn_next)
        layout.add_widget(btn_box)
        self.add_widget(layout)

    def check_conflicts(self, instance):
        # (Tích hợp logic BE resolve-preview ở đây, lấy danh sách sạch gửi lên)
        # Tạm gọi API giả định check_conflicts
        api._request("/api/v1/ingestion/check-conflicts", method="POST", payload={"valid_rows": self.preview_data["valid_rows"]},
                     on_success=self.on_check_success, on_error=lambda r,e: print("Lỗi"))

    def on_check_success(self, req, result):
        self.dismiss()
        if not result.get("conflict_cards"):
            # Gọi thẳng commit nếu không có trùng
            api.commit_events(events=result.get("non_conflicting_rows"), on_success=lambda r, res: print("Lưu thành công!"), on_failure=None, on_error=None)
        else:
            ImportStep3Modal(conflict_data=result).open()

# ==============================================================================
# 4. MODAL: IMPORT LỊCH - BƯỚC 3 (Giải quyết xung đột)
# ==============================================================================
class ImportStep3Modal(ModalView):
    def __init__(self, conflict_data, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.95, 0.9)
        self.auto_dismiss = False
        self.conflict_data = conflict_data
        
        layout = MDBoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10), md_bg_color=[1, 1, 1, 1], radius=[dp(12)])
        layout.add_widget(MDLabel(text="Giải quyết trùng lịch (Bước 3/3)", font_style="Title", bold=True, size_hint_y=None, height=dp(40)))
        
        scroll = ScrollView()
        self.list_layout = MDBoxLayout(orientation='vertical', spacing=dp(10), adaptive_height=True)
        
        for conf in self.conflict_data.get("conflict_cards", []):
            card = MDCard(orientation='vertical', md_bg_color=[1, 0.9, 0.9, 1], size_hint_y=None, height=dp(140), padding=dp(10))
            card.add_widget(MDLabel(text=f"🚨 {conf.get('overlap_description')}", bold=True, text_color=[1, 0, 0, 1]))
            card.add_widget(MDLabel(text=f"A (Lịch học): {conf.get('option_a', {}).get('title')}"))
            card.add_widget(MDLabel(text=f"B (Lịch cá nhân): {conf.get('option_b', {}).get('title')}"))
            # UI chọn Radio Button (A, B, or Both) điền vào đây
            self.list_layout.add_widget(card)
            
        scroll.add_widget(self.list_layout)
        layout.add_widget(scroll)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        btn_commit = MDButton(MDButtonText(text="LƯU CHÍNH THỨC VÀO LỊCH", text_color=[1, 1, 1, 1]), style="filled", md_bg_color=[0, 51/255, 204/255, 1], size_hint_x=1, on_release=self.commit_final)
        btn_box.add_widget(btn_commit)
        layout.add_widget(btn_box)
        self.add_widget(layout)

    def commit_final(self, instance):
        # Gom các sự kiện đã quyết định và non_conflicting_rows
        final_events = self.conflict_data.get("non_conflicting_rows", [])
        api.commit_events(events=final_events, on_success=lambda r, res: self.dismiss(), on_failure=None, on_error=None)