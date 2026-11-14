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
from kivymd.uix.selectioncontrol import MDCheckbox
from kivymd.app import MDApp

from api_client import api
from event_store import store
from notifier import reminder_scheduler, VN_TZ


# ==============================================================================
# 0. BỘ CHỌN GIỜ 30 PHÚT (00:00 - 23:30)
# ==============================================================================
class Time30mPickerModal(ModalView):
    """Bộ chọn giờ 30 phút từ 00:00 đến 23:30."""
    def __init__(self, title="Chọn giờ", on_select=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.85, 0.7)
        self.auto_dismiss = True
        self.on_select = on_select

        layout = MDBoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(12)]
        )
        layout.add_widget(MDLabel(
            text=title,
            bold=True,
            font_style="Title",
            role="medium",
            size_hint_y=None,
            height=dp(35),
            halign="center"
        ))

        scroll = ScrollView(size_hint=(1, 1))
        grid = MDBoxLayout(orientation='vertical', spacing=dp(4), adaptive_height=True)

        for h in range(24):
            for m in (0, 30):
                time_str = f"{h:02d}:{m:02d}"
                btn = MDButton(
                    MDButtonText(text=time_str, font_style="Body", role="medium"),
                    style="outlined",
                    size_hint_x=1,
                    size_hint_y=None,
                    height=dp(38),
                    on_release=lambda x, ts=time_str: self._choose(ts)
                )
                grid.add_widget(btn)

        scroll.add_widget(grid)
        layout.add_widget(scroll)

        btn_cancel = MDButton(
            MDButtonText(text="ĐÓNG"),
            style="text",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(40),
            on_release=self.dismiss
        )
        layout.add_widget(btn_cancel)
        self.add_widget(layout)

    def _choose(self, time_str):
        if self.on_select:
            self.on_select(time_str)
        self.dismiss()


# ==============================================================================
# 1. MODAL: THÊM SỰ KIỆN THỦ CÔNG
# ==============================================================================
class AddEventModal(ModalView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.92, 0.9)
        self.auto_dismiss = False

        # Container chính
        layout = MDBoxLayout(
            orientation='vertical',
            padding=[dp(15), dp(12), dp(15), dp(12)],
            spacing=dp(8),
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
                height=dp(36),
            )
        )

        scroll = ScrollView(size_hint=(1, 1))
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(2), dp(4), dp(2), dp(4)],
            adaptive_height=True,
        )

        self.tf_title = MDTextField(MDTextFieldHintText(text="Tên sự kiện"), mode="outlined")
        self.tf_room = MDTextField(MDTextFieldHintText(text="Phòng / Địa điểm (tùy chọn)"), mode="outlined")
        self.tf_date = MDTextField(
            MDTextFieldHintText(text="Ngày (YYYY-MM-DD)"),
            text=datetime.now().strftime("%Y-%m-%d"),
            mode="outlined"
        )

        # 5 loại sự kiện theo đúng yêu cầu: Mẫu: "Nhiệm vụ" (TASK), "Lớp học" (CLASS), "Bài thi" (EXAM), "Sự kiện" (EVENT), "Hạn chót" (DEADLINE)
        self.kind_options = [
            ("Nhiệm vụ", "TASK"),
            ("Lớp học", "CLASS"),
            ("Bài thi", "EXAM"),
            ("Sự kiện", "EVENT"),
            ("Hạn chót", "DEADLINE"),
        ]
        self.selected_kind = "TASK"

        self.tf_kind = MDTextField(
            MDTextFieldHintText(text="Loại sự kiện"),
            text="Nhiệm vụ",
            mode="outlined",
            readonly=True,
        )
        self.tf_kind.bind(on_focus=self.open_kind_menu)

        menu_items = [
            {
                "text": display_name,
                "on_release": lambda d=display_name, k=k_val: self.set_kind(d, k)
            }
            for display_name, k_val in self.kind_options
        ]
        self.kind_menu = MDDropdownMenu(caller=self.tf_kind, items=menu_items, width_mult=4)

        # Bộ chọn giờ 30 phút: từ 00:00 đến 23:30 (XX:00 và XX:30)
        self.tf_start = MDTextField(
            MDTextFieldHintText(text="Giờ bắt đầu (bấm để chọn)"),
            text="08:00",
            mode="outlined",
            readonly=True,
        )
        self.tf_start.bind(on_focus=self.open_start_picker)

        self.tf_end = MDTextField(
            MDTextFieldHintText(text="Giờ kết thúc (bấm để chọn)"),
            text="09:30",
            mode="outlined",
            readonly=True,
        )
        self.tf_end.bind(on_focus=self.open_end_picker)

        # Option: Đánh dấu Quan trọng (is_important)
        imp_row = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
        )
        self.chk_important = MDCheckbox(
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
            color_active=[0, 51/255, 204/255, 1],
        )
        lbl_chk = MDLabel(
            text="Đánh dấu Quan trọng (!)",
            font_style="Body",
            role="medium",
            bold=True,
            pos_hint={'center_y': 0.5},
        )
        imp_row.add_widget(self.chk_important)
        imp_row.add_widget(lbl_chk)

        content.add_widget(self.tf_title)
        content.add_widget(self.tf_room)
        content.add_widget(self.tf_kind)
        content.add_widget(self.tf_date)
        content.add_widget(self.tf_start)
        content.add_widget(self.tf_end)
        content.add_widget(imp_row)

        scroll.add_widget(content)
        layout.add_widget(scroll)

        self.lbl_status = MDLabel(
            text="",
            theme_text_color="Error",
            adaptive_height=True,
            size_hint_y=None,
        )
        self.lbl_status.bind(width=lambda inst, val: setattr(inst, 'text_size', (val, None)))
        layout.add_widget(self.lbl_status)

        btn_box = MDBoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(45))
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

    def set_kind(self, display_name, kind_val):
        self.tf_kind.text = display_name
        self.selected_kind = kind_val
        self.kind_menu.dismiss()

    def open_start_picker(self, instance, focus):
        if focus:
            self.tf_start.focus = False
            Time30mPickerModal(
                title="Chọn giờ bắt đầu",
                on_select=lambda t: setattr(self.tf_start, 'text', t)
            ).open()

    def open_end_picker(self, instance, focus):
        if focus:
            self.tf_end.focus = False
            Time30mPickerModal(
                title="Chọn giờ kết thúc",
                on_select=lambda t: setattr(self.tf_end, 'text', t)
            ).open()

    def save_event(self, instance):
        self.lbl_status.text = ""
        title = self.tf_title.text.strip()
        room = self.tf_room.text.strip()
        date_str = self.tf_date.text.strip()
        start_str = self.tf_start.text.strip()
        end_str = self.tf_end.text.strip()
        is_imp = bool(self.chk_important.active)

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
        if duration <= 0 and self.selected_kind != "DEADLINE":
            self.lbl_status.text = "Lỗi: Giờ kết thúc phải sau giờ bắt đầu!"
            return

        # Lưu vào lịch giống như step cuối ở phương thức import lịch
        incoming_row = [{
            "line_number": 1,
            "course_code": "",
            "title": title,
            "kind": self.selected_kind,
            "start_time": start_str,
            "end_time": end_str,
            "first_date": date_str,
            "last_date": date_str,
            "room": room or None,
            "weekday": None,
        }]

        self.lbl_status.text = "Đang lưu sự kiện vào lịch..."
        self.lbl_status.theme_text_color = "Hint"

        api.commit_import(
            import_batch_id="manual",
            resolved_rows=incoming_row,
            on_success=lambda req, res: self._on_committed(res, title, is_imp, date_str, start_str),
            on_failure=lambda req, res: self._create_manual_fallback(title, duration, date_str, start_str, end_str, is_imp),
            on_error=lambda req, err: self._create_manual_fallback(title, duration, date_str, start_str, end_str, is_imp),
        )

    def _on_committed(self, res, title, is_imp, date_str, start_str):
        # Đặt báo thức nếu đánh dấu quan trọng
        if is_imp:
            fire_at = f"{date_str}T{start_str}:00+07:00"
            reminder_scheduler.schedule(0, fire_at=fire_at, title=title, offset_minutes=30)
        store.refresh(api)
        self.dismiss()

    def _create_manual_fallback(self, title, duration, date_str, start_str, end_str, is_imp):
        start_iso = f"{date_str}T{start_str}:00+07:00"
        end_iso = f"{date_str}T{end_str}:00+07:00"
        api.create_manual_event(
            title=title,
            duration_minutes=max(15, duration),
            slot_start=start_iso,
            slot_end=end_iso,
            on_success=lambda req, res: self._on_committed(res, title, is_imp, date_str, start_str),
            on_failure=lambda req, res: self._set_error("Lỗi khi lưu sự kiện"),
            on_error=lambda req, err: self._set_error("Lỗi kết nối máy chủ"),
        )

    def _set_error(self, message):
        self.lbl_status.text = f"Lỗi: {message}"
        self.lbl_status.theme_text_color = "Error"


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


# ==============================================================================
# 5. MODAL: CHI TIẾT SỰ KIỆN & MENU CHỨC NĂNG (EventDetailModal)
# ==============================================================================
class EventDetailModal(ModalView):
    """
    Modal chi tiết sự kiện khi bấm vào EventBlock (tuần), DeadlineBanner, hoặc EventCard (tìm kiếm).
    Hiển thị tên, phòng, giờ bắt đầu - kết thúc, loại sự kiện.
    List 3 nút chức năng:
      1. Nút [Sửa giờ] (chỉ bật khi is_hard == False) -> Mở bộ chọn giờ 30 phút, gọi PATCH /api/v1/events/{id}
      2. Nút [Xóa sự kiện] -> Gọi DELETE /api/v1/events/{id}
      3. Nút bật/tắt [Đánh dấu Quan trọng] -> App đặt lịch hẹn báo thức cục bộ và gọi API lưu vết Audit
    """
    def __init__(self, event, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (0.92, 0.78)
        self.auto_dismiss = True
        self.event = dict(event or {})
        self.event_id = self.event.get("id")
        self.is_hard = bool(self.event.get("is_hard", False) or self.event.get("kind") in ("CLASS", "EXAM"))
        self.is_important = bool(self.event.get("is_important", False))

        layout = MDBoxLayout(
            orientation='vertical',
            padding=[dp(16), dp(16), dp(16), dp(16)],
            spacing=dp(10),
            md_bg_color=[1, 1, 1, 1],
            radius=[dp(14)]
        )

        # Header: Tên sự kiện
        header_box = MDBoxLayout(orientation='vertical', size_hint_y=None, adaptive_height=True, spacing=dp(4))
        self.lbl_title = MDLabel(
            text=f"📌 {self.event.get('title', 'Sự kiện')}",
            bold=True,
            font_style="Title",
            role="medium",
            adaptive_height=True,
        )
        kind_map = {
            "CLASS": "Lớp học (CLASS)",
            "EXAM": "Bài thi (EXAM)",
            "EVENT": "Sự kiện (EVENT)",
            "TASK": "Nhiệm vụ (TASK)",
            "DEADLINE": "Hạn chót (DEADLINE)"
        }
        kind_name = kind_map.get(self.event.get("kind"), self.event.get("kind", "TASK"))
        self.lbl_kind = MDLabel(
            text=f"Phân loại: {kind_name}",
            theme_text_color="Hint",
            font_style="Label",
            role="large",
            adaptive_height=True,
        )
        header_box.add_widget(self.lbl_title)
        header_box.add_widget(self.lbl_kind)
        layout.add_widget(header_box)

        # Thông tin phòng và thời gian
        info_scroll = ScrollView(size_hint=(1, 1))
        info_content = MDBoxLayout(orientation='vertical', spacing=dp(8), adaptive_height=True)

        room = self.event.get("room")
        room_display = room.strip() if (room and str(room).strip() and str(room).lower() not in ("none", "null")) else "Không có"
        self.lbl_room = MDLabel(
            text=f"📍 Địa điểm / Phòng: {room_display}",
            font_style="Body",
            role="medium",
            adaptive_height=True,
        )
        info_content.add_widget(self.lbl_room)

        # Format thời gian
        self.lbl_time = MDLabel(
            text=self._format_time_str(),
            font_style="Body",
            role="medium",
            adaptive_height=True,
        )
        info_content.add_widget(self.lbl_time)

        # Trạng thái quan trọng
        self.lbl_imp_status = MDLabel(
            text="⭐ Sự kiện Quan trọng: " + ("ĐÃ BẬT (!)" if self.is_important else "TẮT"),
            theme_text_color="Custom",
            text_color=[0.9, 0.4, 0, 1] if self.is_important else [0.5, 0.5, 0.5, 1],
            bold=True,
            font_style="Label",
            role="large",
            adaptive_height=True,
        )
        info_content.add_widget(self.lbl_imp_status)

        self.lbl_status = MDLabel(
            text="",
            theme_text_color="Hint",
            font_style="Label",
            role="medium",
            adaptive_height=True,
        )
        info_content.add_widget(self.lbl_status)

        info_scroll.add_widget(info_content)
        layout.add_widget(info_scroll)

        # LIST 3 NÚT CHỨC NĂNG
        btn_box = MDBoxLayout(orientation='vertical', spacing=dp(8), size_hint_y=None, adaptive_height=True)

        # 1. Nút Sửa giờ (chỉ bật khi is_hard == False)
        edit_text = "SỬA GIỜ (30 PHÚT)" if not self.is_hard else "SỬA GIỜ (LỊCH CỐ ĐỊNH - KHÓA)"
        self.btn_edit_time = MDButton(
            MDButtonText(
                text=edit_text,
                text_color=[1, 1, 1, 1] if not self.is_hard else [0.5, 0.5, 0.5, 1],
                font_style="Label", role="small"
            ),
            style="filled",
            md_bg_color=[0, 51/255, 204/255, 1] if not self.is_hard else [0.88, 0.88, 0.88, 1],
            size_hint_x=1,
            size_hint_y=None,
            height=dp(38),
            disabled=self.is_hard,
            on_release=self.open_edit_time_picker,
        )
        btn_box.add_widget(self.btn_edit_time)

        # 2. Nút Bật/Tắt Đánh dấu Quan trọng (Nhắc nhở Local Notification)
        imp_btn_text = "TẮT ĐÁNH DẤU QUAN TRỌNG" if self.is_important else "BẬT ĐÁNH DẤU QUAN TRỌNG (!)"
        self.btn_toggle_important = MDButton(
            MDButtonText(text=imp_btn_text, text_color=[1, 1, 1, 1], font_style="Label", role="small"),
            style="filled",
            md_bg_color=[0.9, 0.45, 0, 1] if not self.is_important else [0.5, 0.5, 0.5, 1],
            size_hint_x=1,
            size_hint_y=None,
            height=dp(38),
            on_release=self.toggle_important,
        )
        btn_box.add_widget(self.btn_toggle_important)

        # 3. Nút Xóa sự kiện
        self.btn_delete = MDButton(
            MDButtonText(text="XÓA SỰ KIỆN", text_color=[1, 0, 0, 1], font_style="Label", role="small"),
            style="outlined",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(38),
            on_release=self.delete_event,
        )
        btn_box.add_widget(self.btn_delete)

        # Nút Đóng
        btn_close = MDButton(
            MDButtonText(text="ĐÓNG"),
            style="text",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(32),
            on_release=self.dismiss,
        )
        btn_box.add_widget(btn_close)

        layout.add_widget(btn_box)
        self.add_widget(layout)

    def _format_time_str(self):
        try:
            st = datetime.fromisoformat(self.event["start_time"])
            et = datetime.fromisoformat(self.event["end_time"])
            return f"🕒 {st.strftime('%H:%M')} - {et.strftime('%H:%M')}  ({st.strftime('%d/%m/%Y')})"
        except Exception:
            return f"🕒 {self.event.get('start_time')} - {self.event.get('end_time')}"

    def open_edit_time_picker(self, instance):
        if self.is_hard:
            return
        Time30mPickerModal(
            title="Chọn Giờ bắt đầu mới",
            on_select=self._on_start_time_chosen
        ).open()

    def _on_start_time_chosen(self, start_t_str):
        self._new_start_time = start_t_str
        Time30mPickerModal(
            title="Chọn Giờ kết thúc mới",
            on_select=self._on_end_time_chosen
        ).open()

    def _on_end_time_chosen(self, end_t_str):
        new_start_t = self._new_start_time
        new_end_t = end_t_str
        try:
            st_orig = datetime.fromisoformat(self.event["start_time"])
            date_str = st_orig.strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.now().strftime("%Y-%m-%d")

        new_start_iso = f"{date_str}T{new_start_t}:00+07:00"
        new_end_iso = f"{date_str}T{new_end_t}:00+07:00"

        self.lbl_status.text = "Đang cập nhật giờ..."
        self.lbl_status.theme_text_color = "Hint"

        # Cập nhật cục bộ trước
        self.event["start_time"] = new_start_iso
        self.event["end_time"] = new_end_iso
        self.lbl_time.text = self._format_time_str()

        # Gọi API PATCH /api/v1/events/{id}
        if self.event_id:
            api.patch_event(
                self.event_id,
                payload={"start_time": new_start_iso, "end_time": new_end_iso},
                on_success=lambda req, res: (store.refresh(api), setattr(self.lbl_status, "text", "Đã lưu giờ mới!")),
                on_failure=lambda req, res: setattr(self.lbl_status, "text", "Đã cập nhật giờ cục bộ"),
                on_error=lambda req, err: setattr(self.lbl_status, "text", "Đã cập nhật giờ cục bộ"),
            )
        else:
            self.lbl_status.text = "Đã cập nhật giờ cục bộ!"

    def toggle_important(self, instance):
        self.is_important = not self.is_important
        self.event["is_important"] = self.is_important

        if self.is_important:
            self.lbl_imp_status.text = "⭐ Sự kiện Quan trọng: ĐÃ BẬT (!)"
            self.lbl_imp_status.text_color = [0.9, 0.4, 0, 1]
            self.btn_toggle_important.children[0].text = "TẮT ĐÁNH DẤU QUAN TRỌNG"
            self.btn_toggle_important.md_bg_color = [0.5, 0.5, 0.5, 1]

            # Đặt lịch hẹn báo thức cục bộ trên thiết bị
            fire_at = self.event.get("start_time")
            title = self.event.get("title", "Sự kiện")
            if fire_at:
                reminder_scheduler.schedule(self.event_id or 0, fire_at=fire_at, title=title, offset_minutes=30)

            # Gọi API báo về cho BE lưu vết Audit
            if self.event_id:
                api.audit_reminder(
                    self.event_id,
                    offset_minutes=30,
                    scheduled_on_device_at=datetime.now(VN_TZ).isoformat(),
                    on_success=lambda req, res: (store.refresh(api), setattr(self.lbl_status, "text", "Đã bật báo thức & lưu audit!")),
                    on_failure=lambda req, res: setattr(self.lbl_status, "text", "Đã bật báo thức cục bộ."),
                    on_error=lambda req, err: setattr(self.lbl_status, "text", "Đã bật báo thức cục bộ."),
                )
            else:
                self.lbl_status.text = "Đã bật báo thức cục bộ."
        else:
            self.lbl_imp_status.text = "⭐ Sự kiện Quan trọng: TẮT"
            self.lbl_imp_status.text_color = [0.5, 0.5, 0.5, 1]
            self.btn_toggle_important.children[0].text = "BẬT ĐÁNH DẤU QUAN TRỌNG (!)"
            self.btn_toggle_important.md_bg_color = [0.9, 0.45, 0, 1]

            # Hủy báo thức cục bộ
            reminder_scheduler.cancel(self.event_id or 0)

            # Gửi API cập nhật
            if self.event_id:
                api.patch_event(
                    self.event_id,
                    payload={"is_important": False},
                    on_success=lambda req, res: (store.refresh(api), setattr(self.lbl_status, "text", "Đã tắt đánh dấu quan trọng.")),
                    on_failure=lambda req, res: setattr(self.lbl_status, "text", "Đã tắt cục bộ."),
                    on_error=lambda req, err: setattr(self.lbl_status, "text", "Đã tắt cục bộ."),
                )
            else:
                self.lbl_status.text = "Đã tắt cục bộ."

    def delete_event(self, instance):
        # Hủy báo thức nếu có
        if self.event_id:
            reminder_scheduler.cancel(self.event_id)
            api.delete_event(
                self.event_id,
                on_success=lambda req, res: (self._remove_from_local_store(), self.dismiss()),
                on_failure=lambda req, res: (self._remove_from_local_store(), self.dismiss()),
                on_error=lambda req, err: (self._remove_from_local_store(), self.dismiss()),
            )
        else:
            self._remove_from_local_store()
            self.dismiss()

    def _remove_from_local_store(self):
        if self.event_id:
            remaining = [e for e in store.events if e.get("id") != self.event_id]
            store.set_events(remaining, demo=store.is_demo)
