import os
from datetime import datetime, date, time
from kivy.uix.modalview import ModalView
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.filemanager import MDFileManager
from kivymd.app import MDApp

from api_client import api
from event_store import store


# ==============================================================================
# 1. MODAL: THÊM SỰ KIỆN THỦ CÔNG
# ==============================================================================
class AddEventModal(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.9, 0.8)
        self.auto_dismiss = False
        
        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(20),
            spacing=dp(15),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(12)]
        )
        layout.add_widget(
            MDLabel(
                text="Thêm Sự Kiện Mới",
                font_style="Title",
                role="large",
                bold=True,
                size_hint_y=None,
                height=dp(40),
            )
        )
        
        self.tf_title = MDTextField(MDTextFieldHintText(text="Tên sự kiện"), mode="outlined")
        self.tf_date = MDTextField(MDTextFieldHintText(text="Ngày (YYYY-MM-DD)"), mode="outlined")
        self.tf_start = MDTextField(MDTextFieldHintText(text="Giờ bắt đầu (HH:MM)"), mode="outlined")
        self.tf_end = MDTextField(MDTextFieldHintText(text="Giờ kết thúc (HH:MM)"), mode="outlined")
        
        # Dropdown chọn loại sự kiện
        self.tf_kind = MDTextField(
            MDTextFieldHintText(text="Loại sự kiện"),
            text="TASK",
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

        self.lbl_status = MDLabel(
            text="",
            theme_text_color="Error",
            adaptive_height=True,
            size_hint_y=None,
        )
        self.lbl_status.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        layout.add_widget(self.lbl_status)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        btn_save = MDButton(
            MDButtonText(text="LƯU", text_color=[1, 1, 1, 1]),
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1],
            size_hint_x=1,
            on_release=self.save_event,
        )
        btn_cancel = MDButton(
            MDButtonText(text="HỦY"),
            style="outlined",
            size_hint_x=1,
            on_release=self.dismiss,
        )
        
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
        self.lbl_status.text = ""
        title = self.tf_title.text.strip()
        date_str = self.tf_date.text.strip()
        start_str = self.tf_start.text.strip()
        end_str = self.tf_end.text.strip()

        if not title:
            self.lbl_status.text = "Lỗi: Tên sự kiện không được để trống!"
            return

        fmt = "%H:%M"
        try:
            start_t = datetime.strptime(start_str, fmt).time()
            end_t = datetime.strptime(end_str, fmt).time()
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            self.lbl_status.text = "Lỗi: Định dạng ngày (YYYY-MM-DD) hoặc giờ (HH:MM) sai!"
            return

        start_dt = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), start_t)
        end_dt = datetime.combine(datetime.strptime(date_str, "%Y-%m-%d").date(), end_t)
        duration = int((end_dt - start_dt).total_seconds() / 60)
        if duration <= 0:
            self.lbl_status.text = "Lỗi: Giờ kết thúc phải sau giờ bắt đầu!"
            return

        start_iso = f"{date_str}T{start_str}:00+07:00"
        end_iso = f"{date_str}T{end_str}:00+07:00"

        # Map kind to valid CsvRowKind for conflict checking
        raw_kind = self.tf_kind.text.strip().upper()
        check_kind = raw_kind if raw_kind in ("CLASS", "EXAM", "DEADLINE", "EVENT") else "EVENT"

        incoming_row = [{
            "line_number": 1,
            "course_code": "",
            "title": title,
            "kind": check_kind,
            "start_time": start_str,
            "end_time": end_str,
            "first_date": date_str,
            "last_date": date_str,
        }]

        # Check conflicts first
        api.check_conflicts(
            incoming_rows=incoming_row,
            on_success=lambda req, res: self.on_check_success(res, title, duration, start_iso, end_iso),
            on_failure=lambda req, res: self._create_manual(title, duration, start_iso, end_iso),
            on_error=lambda req, err: self._create_manual(title, duration, start_iso, end_iso),
        )

    def on_check_success(self, result, title, duration, start_iso, end_iso):
        conflict_cards = result.get("conflict_cards", [])
        if conflict_cards:
            self.lbl_status.text = "Lỗi: Trùng lịch với sự kiện khác!"
            return
        self._create_manual(title, duration, start_iso, end_iso)

    def _create_manual(self, title, duration, start_iso, end_iso):
        api._request(
            "/api/v1/proposals/manual",
            method="POST",
            payload={
                "title": title,
                "duration_minutes": duration,
                "slot_start": start_iso,
                "slot_end": end_iso,
            },
            on_success=self._on_saved,
            on_failure=self._on_save_failed,
            on_error=lambda req, err: self._set_error("Lỗi mạng khi lưu sự kiện"),
        )

    def _on_saved(self, req, res):
        store.refresh(api)
        self.dismiss()

    def _on_save_failed(self, req, res):
        err = "Lỗi khi lưu sự kiện"
        if isinstance(res, dict):
            detail = res.get("detail", err)
            if isinstance(detail, str):
                err = detail
        self._set_error(err)

    def _set_error(self, message):
        self.lbl_status.text = f"Lỗi: {message}"


# ==============================================================================
# 2. MODAL: IMPORT LỊCH - BƯỚC 1 (Chọn & Tải File .csv, .txt, .png, .jpeg)
# ==============================================================================
class ImportStep1Modal(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.92, 0.55)
        self.auto_dismiss = False
        
        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(20),
            spacing=dp(12),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(12)]
        )
        layout.add_widget(
            MDLabel(
                text="Import Lịch (Bước 1/3)",
                font_style="Title",
                role="large",
                bold=True,
                size_hint_y=None,
                height=dp(35),
            )
        )
        layout.add_widget(
            MDLabel(
                text="Hỗ trợ file: .csv, .txt, .md, .png, .jpg, .jpeg",
                theme_text_color="Hint",
                size_hint_y=None,
                height=dp(22),
            )
        )
        
        self.lbl_file = MDLabel(
            text="Chưa chọn file nào",
            theme_text_color="Hint",
            halign="center",
            adaptive_height=True,
            size_hint_y=None,
        )
        self.lbl_file.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        layout.add_widget(self.lbl_file)
        
        btn_select = MDButton(
            MDButtonText(text="CHỌN FILE (.csv, .txt, .png, .jpeg)"),
            style="elevated",
            size_hint_x=1,
            on_release=self.open_file_manager,
        )
        layout.add_widget(btn_select)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        self.btn_analyze_text = MDButtonText(text="PHÂN TÍCH", text_color=[1, 1, 1, 1])
        self.btn_analyze = MDButton(
            self.btn_analyze_text,
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1],
            size_hint_x=1,
            on_release=self.analyze_data,
            disabled=True,
        )
        btn_cancel = MDButton(
            MDButtonText(text="HỦY"),
            style="outlined",
            size_hint_x=1,
            on_release=self.dismiss,
        )
        
        btn_box.add_widget(self.btn_analyze)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        self.add_widget(layout)

        # Cấu hình File Manager hỗ trợ cả CSV/TXT và ảnh PNG/JPEG/JPG
        self.file_manager = MDFileManager(
            exit_manager=self.exit_manager,
            select_path=self.select_path,
            preview=True,
        )
        self.file_manager.ext = [
            ".csv", ".txt", ".md", ".png", ".jpg", ".jpeg",
            ".CSV", ".TXT", ".MD", ".PNG", ".JPG", ".JPEG",
        ]
        self.selected_path = None

    def open_file_manager(self, instance):
        start_dir = os.path.expanduser("~")
        if not os.path.exists(start_dir):
            start_dir = "."
        self.file_manager.show(start_dir)

    def select_path(self, path: str):
        if not path or os.path.isdir(path):
            return
        self.selected_path = path
        filename = os.path.basename(path)
        self.lbl_file.text = f"Đã chọn: {filename}"
        self.lbl_file.theme_text_color = "Primary"
        self.btn_analyze.disabled = False
        self.btn_analyze_text.text = "PHÂN TÍCH"
        self.exit_manager()

    def exit_manager(self, *args):
        self.file_manager.close()

    def analyze_data(self, instance):
        if not self.selected_path or not os.path.isfile(self.selected_path):
            self.lbl_file.text = "Lỗi: File không tồn tại hoặc chưa chọn file!"
            self.lbl_file.theme_text_color = "Error"
            return
            
        self.lbl_file.text = "Đang tải lên và phân tích file..."
        self.lbl_file.theme_text_color = "Hint"
        self.btn_analyze.disabled = True
        self.btn_analyze_text.text = "ĐANG PHÂN TÍCH..."

        api.upload_timetable_file(
            file_path=self.selected_path,
            on_success=self.on_parse_success,
            on_failure=self.on_parse_failure,
            on_error=self.on_parse_error,
        )
        
    def on_parse_success(self, req, result):
        self.btn_analyze.disabled = False
        self.btn_analyze_text.text = "PHÂN TÍCH"
        try:
            self.dismiss()
            ImportStep2Modal(preview_data=result).open()
        except Exception as e:
            self.lbl_file.text = f"Lỗi hiển thị dữ liệu: {e}"
            self.lbl_file.theme_text_color = "Error"

    def on_parse_failure(self, req, res):
        self.btn_analyze.disabled = False
        self.btn_analyze_text.text = "PHÂN TÍCH"
        error_msg = "Không thể phân tích file"
        if isinstance(res, dict):
            detail = res.get("detail", error_msg)
            if isinstance(detail, dict):
                error_msg = detail.get("message", str(detail))
            elif isinstance(detail, str):
                error_msg = detail
        elif isinstance(res, str):
            error_msg = res

        # Thông báo thân thiện tiếng Việt nếu máy chủ thiếu Tesseract OCR
        if "Tesseract OCR engine is not installed" in error_msg:
            error_msg = "Máy chủ chưa cài Tesseract OCR để đọc ảnh PNG/JPEG. Vui lòng import file .csv/.txt hoặc liên hệ admin cài Tesseract."

        self.lbl_file.text = f"Lỗi: {error_msg}"
        self.lbl_file.theme_text_color = "Error"

    def on_parse_error(self, req, err):
        self.btn_analyze.disabled = False
        self.btn_analyze_text.text = "PHÂN TÍCH"
        self.lbl_file.text = f"Lỗi: {err}"
        self.lbl_file.theme_text_color = "Error"


# ==============================================================================
# 3. MODAL: IMPORT LỊCH - BƯỚC 2 (Review & Fix Lỗi)
# Dùng MDBoxLayout thay cho MDCard để tránh lỗi FBO crash trên GPU OpenGL
# ==============================================================================
class ImportStep2Modal(ModalView):
    def __init__(self, preview_data, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.95, 0.9)
        self.auto_dismiss = False
        self.preview_data = preview_data or {}
        
        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(12)]
        )
        layout.add_widget(
            MDLabel(
                text="Xem trước & Xử lý (Bước 2/3)",
                font_style="Title",
                bold=True,
                size_hint_y=None,
                height=dp(35),
            )
        )

        valid_rows = self.preview_data.get("valid_rows", [])
        invalid_rows = self.preview_data.get("invalid_rows", [])
        layout.add_widget(
            MDLabel(
                text=f"Hợp lệ: {len(valid_rows)} sự kiện | Không hợp lệ: {len(invalid_rows)} dòng",
                theme_text_color="Hint",
                size_hint_y=None,
                height=dp(25),
            )
        )
        
        scroll = ScrollView()
        self.list_layout = MDBoxLayout(orientation='vertical', spacing=dp(10), adaptive_height=True)
        
        # Render Thẻ Xanh (Hợp lệ) bằng MDBoxLayout (tránh FBO ripple crash)
        for row in valid_rows:
            card = MDBoxLayout(
                orientation='vertical',
                md_bg_color=[0.9, 1.0, 0.9, 1.0],
                size_hint_y=None,
                adaptive_height=True,
                padding=dp(10),
                spacing=dp(4),
                radius=[dp(8)],
            )
            title_text = f"✅ [{row.get('kind', 'CLASS')}] {row.get('course_code', '')} {row.get('title', '')}".strip()
            time_text = f"🕒 {row.get('weekday') or ''} {row.get('start_time')} - {row.get('end_time')} | Phòng: {row.get('room') or 'Chưa rõ'}"
            date_text = f"📅 Từ {row.get('first_date')} đến {row.get('last_date')}"
            
            card.add_widget(MDLabel(text=title_text, bold=True, size_hint_y=None, height=dp(24)))
            card.add_widget(MDLabel(text=time_text, theme_text_color="Secondary", size_hint_y=None, height=dp(20)))
            card.add_widget(MDLabel(text=date_text, theme_text_color="Hint", size_hint_y=None, height=dp(18)))
            self.list_layout.add_widget(card)
            
        # Render Thẻ Vàng (Lỗi) bằng MDBoxLayout
        for row in invalid_rows:
            card = MDBoxLayout(
                orientation='vertical',
                md_bg_color=[1.0, 0.95, 0.85, 1.0],
                size_hint_y=None,
                adaptive_height=True,
                padding=dp(10),
                spacing=dp(4),
                radius=[dp(8)],
            )
            card.add_widget(
                MDLabel(
                    text=f"⚠️ Dòng {row.get('line_number')}: {row.get('error_message')}",
                    bold=True,
                    text_color=[0.8, 0.5, 0, 1],
                    size_hint_y=None,
                    height=dp(24),
                )
            )
            card.add_widget(
                MDLabel(
                    text=f"Dữ liệu gốc: {row.get('raw_text')}",
                    theme_text_color="Hint",
                    size_hint_y=None,
                    height=dp(22),
                )
            )
            self.list_layout.add_widget(card)

        if not valid_rows and not invalid_rows:
            empty_card = MDBoxLayout(
                orientation='vertical',
                md_bg_color=[1.0, 0.95, 0.95, 1.0],
                size_hint_y=None,
                adaptive_height=True,
                padding=dp(12),
                radius=[dp(8)],
            )
            empty_card.add_widget(
                MDLabel(
                    text="⚠️ Không phát hiện được sự kiện nào trong file.\nVui lòng kiểm tra lại định dạng file hoặc hình ảnh.",
                    theme_text_color="Error",
                    halign="center",
                    size_hint_y=None,
                    height=dp(45),
                )
            )
            self.list_layout.add_widget(empty_card)
            
        scroll.add_widget(self.list_layout)
        layout.add_widget(scroll)

        self.lbl_status = MDLabel(
            text="",
            theme_text_color="Error",
            adaptive_height=True,
            size_hint_y=None,
        )
        self.lbl_status.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        layout.add_widget(self.lbl_status)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(50))
        self.btn_next = MDButton(
            MDButtonText(text="TIẾP TỤC KIỂM TRA TRÙNG LỊCH", text_color=[1, 1, 1, 1]),
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1],
            size_hint_x=0.7,
            on_release=self.check_conflicts,
            disabled=(len(valid_rows) == 0),
        )
        btn_cancel = MDButton(
            MDButtonText(text="HỦY"),
            style="outlined",
            size_hint_x=0.3,
            on_release=self.dismiss,
        )
        btn_box.add_widget(self.btn_next)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        self.add_widget(layout)

    def check_conflicts(self, instance):
        valid_rows = self.preview_data.get("valid_rows", [])
        if not valid_rows:
            self.lbl_status.text = "Không có dòng hợp lệ nào để kiểm tra trùng!"
            return

        self.btn_next.disabled = True
        self.lbl_status.text = "Đang kiểm tra trùng lịch..."
        self.lbl_status.theme_text_color = "Hint"

        api.check_conflicts(
            incoming_rows=valid_rows,
            on_success=self.on_check_success,
            on_failure=self.on_check_failure,
            on_error=self.on_check_error,
        )

    def on_check_success(self, req, result):
        self.dismiss()
        batch_id = self.preview_data.get("import_batch_id", "")
        conflict_cards = result.get("conflict_cards", [])

        if not conflict_cards:
            # Không có xung đột -> commit trực tiếp các dòng hợp lệ vào DB
            api.commit_import(
                import_batch_id=batch_id,
                resolved_rows=result.get("non_conflicting_rows", []),
                on_success=self.on_commit_success,
                on_failure=lambda r, res: print("Lỗi commit:", res),
                on_error=lambda r, err: print("Lỗi mạng commit:", err),
            )
        else:
            # Có xung đột -> chuyển sang Bước 3
            try:
                ImportStep3Modal(conflict_data=result, import_batch_id=batch_id).open()
            except Exception as e:
                print("Lỗi mở Bước 3:", e)

    def on_commit_success(self, req, res):
        store.refresh(api)

    def on_check_failure(self, req, res):
        self.btn_next.disabled = False
        err = "Lỗi khi kiểm tra trùng lịch"
        if isinstance(res, dict):
            detail = res.get("detail", err)
            if isinstance(detail, str):
                err = detail
        self.lbl_status.text = f"Lỗi: {err}"
        self.lbl_status.theme_text_color = "Error"

    def on_check_error(self, req, err):
        self.btn_next.disabled = False
        self.lbl_status.text = f"Lỗi mạng: {err}"
        self.lbl_status.theme_text_color = "Error"


# ==============================================================================
# 4. MODAL: IMPORT LỊCH - BƯỚC 3 (Giải quyết xung đột)
# Dùng MDBoxLayout thay cho MDCard để tránh lỗi FBO crash trên GPU OpenGL
# ==============================================================================
class ImportStep3Modal(ModalView):
    def __init__(self, conflict_data, import_batch_id=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.95, 0.9)
        self.auto_dismiss = False
        self.conflict_data = conflict_data or {}
        self.import_batch_id = import_batch_id or self.conflict_data.get("import_batch_id", "")
        
        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(12)]
        )
        layout.add_widget(
            MDLabel(
                text="Giải quyết trùng lịch (Bước 3/3)",
                font_style="Title",
                bold=True,
                size_hint_y=None,
                height=dp(35),
            )
        )

        conflict_cards = self.conflict_data.get("conflict_cards", [])
        non_conflicting = self.conflict_data.get("non_conflicting_rows", [])
        layout.add_widget(
            MDLabel(
                text=f"Phát hiện {len(conflict_cards)} sự kiện trùng | {len(non_conflicting)} sự kiện an toàn",
                theme_text_color="Hint",
                size_hint_y=None,
                height=dp(25),
            )
        )
        
        scroll = ScrollView()
        self.list_layout = MDBoxLayout(orientation='vertical', spacing=dp(10), adaptive_height=True)
        
        for conf in conflict_cards:
            card = MDBoxLayout(
                orientation='vertical',
                md_bg_color=[1.0, 0.92, 0.92, 1.0],
                size_hint_y=None,
                adaptive_height=True,
                padding=dp(10),
                spacing=dp(4),
                radius=[dp(8)],
            )
            card.add_widget(
                MDLabel(
                    text=f"🚨 {conf.get('overlap_description')}",
                    bold=True,
                    text_color=[0.9, 0.1, 0.1, 1],
                    size_hint_y=None,
                    height=dp(24),
                )
            )
            opt_a = conf.get('option_a', {})
            opt_b = conf.get('option_b', {})
            card.add_widget(
                MDLabel(
                    text=f"A (Môn mới): {opt_a.get('title')} ({opt_a.get('start_time')} - {opt_a.get('end_time')})",
                    size_hint_y=None,
                    height=dp(20),
                )
            )
            card.add_widget(
                MDLabel(
                    text=f"B (Lịch hiện có): {opt_b.get('title')} ({opt_b.get('start_time')} - {opt_b.get('end_time')})",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(20),
                )
            )
            self.list_layout.add_widget(card)
            
        scroll.add_widget(self.list_layout)
        layout.add_widget(scroll)

        self.lbl_status = MDLabel(
            text="",
            theme_text_color="Error",
            adaptive_height=True,
            size_hint_y=None,
        )
        self.lbl_status.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        layout.add_widget(self.lbl_status)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(8), size_hint_y=None, height=dp(50))
        btn_safe = MDButton(
            MDButtonText(text="LƯU MÔN KHÔNG TRÙNG", text_color=[1, 1, 1, 1]),
            style="filled",
            md_bg_color=[0, 153/255, 76/255, 1],
            size_hint_x=0.45,
            on_release=self.commit_safe,
        )
        btn_all = MDButton(
            MDButtonText(text="LƯU TẤT CẢ", text_color=[1, 1, 1, 1]),
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1],
            size_hint_x=0.35,
            on_release=self.commit_all,
        )
        btn_cancel = MDButton(
            MDButtonText(text="HỦY"),
            style="outlined",
            size_hint_x=0.2,
            on_release=self.dismiss,
        )
        
        btn_box.add_widget(btn_safe)
        btn_box.add_widget(btn_all)
        btn_box.add_widget(btn_cancel)
        layout.add_widget(btn_box)
        self.add_widget(layout)

    def commit_safe(self, instance):
        rows = self.conflict_data.get("non_conflicting_rows", [])
        self._do_commit(rows)

    def commit_all(self, instance):
        rows = list(self.conflict_data.get("non_conflicting_rows", []))
        for card in self.conflict_data.get("conflict_cards", []):
            opt_a = card.get("option_a", {})
            if opt_a.get("option_type") == "incoming_row":
                row_copy = dict(opt_a)
                row_copy.pop("option_type", None)
                rows.append(row_copy)
        self._do_commit(rows)

    def _do_commit(self, rows):
        if not rows:
            self.lbl_status.text = "Không có sự kiện nào để lưu!"
            return

        self.lbl_status.text = "Đang lưu lịch vào hệ thống..."
        self.lbl_status.theme_text_color = "Hint"

        api.commit_import(
            import_batch_id=self.import_batch_id,
            resolved_rows=rows,
            on_success=self.on_commit_success,
            on_failure=self.on_commit_failure,
            on_error=self.on_commit_error,
        )

    def on_commit_success(self, req, res):
        store.refresh(api)
        self.dismiss()

    def on_commit_failure(self, req, res):
        err = "Lỗi khi lưu lịch"
        if isinstance(res, dict):
            detail = res.get("detail", err)
            if isinstance(detail, str):
                err = detail
        self.lbl_status.text = f"Lỗi: {err}"
        self.lbl_status.theme_text_color = "Error"

    def on_commit_error(self, req, err):
        self.lbl_status.text = f"Lỗi mạng: {err}"
        self.lbl_status.theme_text_color = "Error"
