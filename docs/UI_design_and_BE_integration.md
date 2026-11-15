# Tài liệu Thiết kế Giao diện (FE) và Hợp đồng Tích hợp API Backend (BE)

Tài liệu này được biên soạn dành cho team Frontend (Kivy / KivyMD) nhằm mô tả chi tiết hợp đồng giao tiếp HTTP/JSON với hệ thống Backend (FastAPI / MySQL / AI), đối chiếu trực tiếp trên cấu trúc các file hiện có trong thư mục `sourceCode/FE/` (`api_client.py`, `screen_manager.py`, `auth_screen.py`, `calendar_screen.py`, `event_modals.py`, `event_store.py`, `search_screen.py`, `chat_screen.py`, `fallback.py`, `notifier.py`, `side_bar_menu.py`).

---

## Phần 1. Danh sách các điểm cần đồng bộ giữa FE hiện tại và BE mới nhất

*Ghi chú: Các mục dưới đây liệt kê những điểm chưa khớp giữa mã nguồn `sourceCode/FE/` hiện tại và `sourceCode/BE/` mới nhất, được sắp xếp theo thứ tự mức độ quan trọng cần sửa giảm dần từ trên xuống dưới (từ các điểm ảnh hưởng trực tiếp đến luồng chạy chính đến các tính năng mở rộng).*

---

### 1. Thứ tự lấy `reschedule_proposal_id` và làm mới `store` sau khi chốt lịch trong `chat_screen.py` và `fallback.py`

#### A. Điểm chưa khớp
1. **Thứ tự đọc `reschedule_proposal_id` trong `chat_screen.py` (dòng 505-516):**
   * Khi người dùng bấm nút `[Suy nghĩ thêm]` (Reschedule) trên một thẻ `ProposalCard`, biến `self.active_reschedule_proposal` giữ tham chiếu tới thẻ đề xuất đó để chờ người dùng nhập câu phản hồi tiếp theo (ví dụ: *"Đổi sang sáng thứ 7 giúp mình"*).
   * Trong hàm `ChatAssistantScreen.send_message` hiện tại:
     ```python
     # Dòng 505-507 (chat_screen.py):
     if self.active_reschedule_proposal:
         self.cancel_reschedule()  # Hàm này gán self.active_reschedule_proposal = None

     # ...
     # Dòng 514-516 (chat_screen.py):
     reschedule_id = None
     if self.active_reschedule_proposal:
         reschedule_id = self.active_reschedule_proposal.proposal.get("id")
     ```
   * Do `self.cancel_reschedule()` được gọi trước, biến `self.active_reschedule_proposal` đã bị gán về `None` trước khi đọc `id`. Hệ quả là `reschedule_id` gửi lên `POST /api/v1/assistant/understand` luôn là `None`, khiến BE hiểu đây là một yêu cầu gốc mới và hủy (`ABANDONED`) đề xuất cũ thay vì liên kết `parent_id` để tránh lặp lại khung giờ người dùng vừa từ chối.

2. **Cập nhật `event_store.store` và đồng bộ báo thức sau khi xác nhận lịch (`chat_screen.py` dòng 352 và `fallback.py` dòng 96):**
   * Khi người dùng bấm `[Xác nhận]` trên `ProposalCard` (`POST /api/v1/proposals/{id}/confirm`) hoặc bấm chọn một khung giờ trong `ManualFallbackModal` (`POST /api/v1/proposals/manual`), BE đã tạo sự kiện mới trong bảng `events` và tạo bản ghi nhắc hẹn trong bảng `reminders`.
   * Tuy nhiên, `ProposalCard.on_confirm_success` và `ManualFallbackModal._on_saved` hiện chưa gọi `store.refresh(api)` (từ `event_store.py`) và `schedule_reminders_from_confirm(res)` (từ `notifier.py`). Vì vậy khi người dùng chuyển sang tab `Lịch chính` hoặc `Tìm kiếm`, sự kiện mới chưa hiển thị ngay trên lưới lịch.

#### B. Cách sửa trong `sourceCode/FE/chat_screen.py` và `sourceCode/FE/fallback.py`
* **Tại `ChatAssistantScreen.send_message` (`sourceCode/FE/chat_screen.py`, dòng 504-525):** Lấy `reschedule_id` trước khi gọi `self.cancel_reschedule()`:
  ```python
  reschedule_id = None
  if self.active_reschedule_proposal:
      reschedule_id = self.active_reschedule_proposal.proposal.get("id")
      self.cancel_reschedule()
  ```
* **Tại `ProposalCard.on_confirm_success` (`sourceCode/FE/chat_screen.py`, dòng 352-360):**
  ```python
  from event_store import store
  from notifier import schedule_reminders_from_confirm

  def on_confirm_success(self, req, res):
      self._disable_all_buttons()
      self.btn_confirm.text = "Đã chốt lịch"
      self.btn_confirm.bg_color = [0.2, 0.7, 0.3, 1]
      self.btn_confirm.update_canvas()
      store.refresh(api)
      if isinstance(res, dict):
          schedule_reminders_from_confirm(res)
      if self.on_action_callback:
          self.on_action_callback(
              "confirm",
              f"Đã thêm '{self.proposal.get('task_title', 'Công việc')}' vào lịch chính thức.",
          )
  ```
* **Tại `ManualFallbackModal._on_saved` (`sourceCode/FE/fallback.py`, dòng 96-100):**
  ```python
  from event_store import store
  from notifier import schedule_reminders_from_confirm

  def _on_saved(self, slot: dict, res=None) -> None:
      store.refresh(api)
      if isinstance(res, dict):
          schedule_reminders_from_confirm(res)
      self.dismiss()
      if self.on_scheduled:
          self.on_scheduled(f"Đã thêm '{self.task_title}' ({ _fmt(slot) }) vào lịch chính thức.")
  ```

---

### 2. Đồng bộ hợp đồng dữ liệu 4 bước Nhập lịch (Ingestion) và Thêm sự kiện thủ công trong `api_client.py` và `event_modals.py`

#### A. Điểm chưa khớp
1. **Bước 1 (`POST /api/v1/ingestion/parse-preview`) trong `api_client.py` (dòng 129-132):**
   * `api.parse_preview` hiện gửi JSON `payload = {"text": text_data}` với header `Content-Type: application/json`.
   * Ở phía BE (`sourceCode/BE/routers/ingestion.py`, dòng 443-446), endpoint `/api/v1/ingestion/parse-preview` nhận dữ liệu kiểu `Form` (`raw_content: Optional[str] = Form(default=None)`) hoặc `File` (`file: Optional[UploadFile] = File(default=None)`). Do đó nếu gửi JSON `{"text": ...}`, FastAPI trả về `HTTP 422`.
2. **Bước 2 (`POST /api/v1/ingestion/resolve-preview`) và Bước 3 (`POST /api/v1/ingestion/check-conflicts`) trong `event_modals.py` (dòng 240-253):**
   * Trong `ImportStep2Modal.check_conflicts` (dòng 243), FE đang gửi `payload={"valid_rows": self.preview_data["valid_rows"]}` tới `/api/v1/ingestion/check-conflicts`.
   * Ở phía BE (`routers/ingestion.py`, dòng 197-199), `CheckConflictsRequest` nhận trường `incoming_rows` (không phải `valid_rows`) và tùy chọn `replace_previous_imports: bool = False`:
     ```json
     {
       "incoming_rows": [
         {
           "line_number": 1,
           "course_code": "CSC10004",
           "title": "Cấu trúc dữ liệu",
           "kind": "CLASS",
           "start_time": "07:30",
           "end_time": "09:30",
           "first_date": "2026-09-07",
           "last_date": "2026-12-20",
           "weekday": "MON",
           "room": "F.102"
         }
       ],
       "replace_previous_imports": false
     }
     ```
   * Đồng thời, nếu ở Bước 2 người dùng có sửa các dòng vàng (`invalid_rows`) hoặc bấm bỏ qua dòng lỗi, FE gọi `POST /api/v1/ingestion/resolve-preview` trước để nhận danh sách sạch `all_valid_rows`, sau đó mới truyền `all_valid_rows` vào `incoming_rows` của `/api/v1/ingestion/check-conflicts`.
3. **Bước 4 (`POST /api/v1/ingestion/commit`) trong `api_client.py` (dòng 135-137) và `event_modals.py` (dòng 250, 287-290):**
   * `api.commit_events` hiện gửi `payload = {"events": events}`.
   * Ở phía BE (`routers/ingestion.py`, dòng 202-205), `CommitImportRequest` yêu cầu:
     ```json
     {
       "import_batch_id": "string-uuid-tu-buoc-1",
       "resolved_rows": [ ... ],
       "replace_previous_imports": false
     }
     ```
   * Sau khi `/commit` thành công, cần gọi `store.refresh(api)` để lịch mới hiện ngay trên `CalendarScreen`.
4. **Thêm sự kiện thủ công (`AddEventModal` trong `event_modals.py`, dòng 76-128):**
   * Tại dòng 89-95, `mock_row` gửi tới `/api/v1/ingestion/check-conflicts` đang truyền `start_time` và `end_time` dạng `YYYY-MM-DDTHH:MM:00` và thiếu `first_date`, `last_date`, trong khi schema `CsvRowPayload` của `/check-conflicts` yêu cầu `start_time: "HH:MM"`, `end_time: "HH:MM"`, `first_date: "YYYY-MM-DD"`, `last_date: "YYYY-MM-DD"`.
   * Khi gọi tiếp `POST /api/v1/proposals/manual` (dòng 115-128), sau khi lưu thành công (`on_success`), cần gọi `store.refresh(api)` trước khi `self.dismiss()` để sự kiện vừa tạo hiển thị ngay trên lịch.

#### B. Cách sửa trong `sourceCode/FE/api_client.py` và `sourceCode/FE/event_modals.py`
* **Cập nhật các hàm Ingestion trong `sourceCode/FE/api_client.py` (dòng 129-140):**
  ```python
  from urllib.parse import urlencode

  def parse_preview(self, text_data, on_success, on_failure, on_error):
      """Gửi nội dung văn bản thời khóa biểu dưới dạng application/x-www-form-urlencoded khớp với Form(raw_content)."""
      url = f"{self.base_url}/api/v1/ingestion/parse-preview"
      headers = {"Content-Type": "application/x-www-form-urlencoded"}
      if self.access_token:
          headers["Authorization"] = f"Bearer {self.access_token}"
      body = urlencode({"raw_content": text_data})
      UrlRequest(
          url,
          req_body=body,
          req_headers=headers,
          method="POST",
          on_success=on_success,
          on_failure=on_failure,
          on_error=on_error,
          timeout=10,
      )

  def resolve_preview(self, import_batch_id, valid_rows, corrected_rows, skipped_line_numbers, on_success, on_failure=None, on_error=None):
      payload = {
          "import_batch_id": import_batch_id,
          "valid_rows": valid_rows,
          "corrected_rows": corrected_rows,
          "skipped_line_numbers": skipped_line_numbers,
      }
      self._request("/api/v1/ingestion/resolve-preview", method="POST", payload=payload, on_success=on_success, on_failure=on_failure, on_error=on_error)

  def check_conflicts(self, incoming_rows, on_success, replace_previous_imports=False, on_failure=None, on_error=None):
      payload = {
          "incoming_rows": incoming_rows,
          "replace_previous_imports": replace_previous_imports,
      }
      self._request("/api/v1/ingestion/check-conflicts", method="POST", payload=payload, on_success=on_success, on_failure=on_failure, on_error=on_error)

  def commit_events(self, import_batch_id, resolved_rows, on_success, replace_previous_imports=False, on_failure=None, on_error=None):
      payload = {
          "import_batch_id": import_batch_id,
          "resolved_rows": resolved_rows,
          "replace_previous_imports": replace_previous_imports,
      }
      self._request("/api/v1/ingestion/commit", method="POST", payload=payload, on_success=on_success, on_failure=on_failure, on_error=on_error)
  ```
* **Cập nhật `AddEventModal.save_event` trong `sourceCode/FE/event_modals.py` (dòng 86-128):**
  ```python
  start_iso = f"{self.tf_date.text}T{self.tf_start.text}:00+07:00"
  end_iso = f"{self.tf_date.text}T{self.tf_end.text}:00+07:00"

  # Tạo bản ghi đúng định dạng CsvRowPayload để kiểm tra xung đột
  incoming_row = [{
      "line_number": 1,
      "course_code": "",
      "title": self.tf_title.text.strip(),
      "kind": self.tf_kind.text.strip() or "TASK",
      "start_time": self.tf_start.text.strip(),
      "end_time": self.tf_end.text.strip(),
      "first_date": self.tf_date.text.strip(),
      "last_date": self.tf_date.text.strip(),
      "weekday": None,
      "room": None,
  }]

  api.check_conflicts(
      incoming_rows=incoming_row,
      on_success=lambda req, res: self.on_check_success(res, max(duration, 15), start_iso, end_iso),
      on_error=lambda req, err: print("Lỗi mạng khi kiểm tra xung đột:", err),
  )
  ```
  Và trong `AddEventModal.on_check_success`, sau khi `POST /api/v1/proposals/manual` thành công, gọi `store.refresh(api)` rồi `self.dismiss()`.

---

### 3. Kết nối Màn hình Tìm kiếm (`search_screen.py`) với 2 Chế độ Tìm kiếm của Backend (`GET /api/v1/search/events` và `POST /api/v1/search/academic/ask`)

#### A. Điểm chưa khớp
1. **Tìm kiếm lịch cá nhân hiện đang lọc cục bộ bằng chuỗi con (`sourceCode/FE/search_screen.py`, dòng 406-449):**
   * Hiện tại hàm `SearchScreen.perform_search` duyệt qua mảng `store.events` trong RAM và kiểm tra `query in event["title"].lower() or query in event["room"].lower()`.
   * Cách lọc cục bộ này chưa gọi tới động cơ **Schedule Search (Hybrid SQL + Vector Search 2 tầng)** của BE tại `GET /api/v1/search/events?q=...` (`sourceCode/BE/routers/search.py`, dòng 107-168). Khi gọi API của BE, người dùng có thể:
     * Gõ từ viết tắt môn học (`"xstk"`, `"ctdl"`, `"mmt"`, `"ktlt"`).
     * Gõ khái niệm tổng quát (`"lịch thi các môn toán chiều tuần sau"`) và hệ thống tự động tìm ra cả *"Vi tích phân 2"*, *"Xác suất thống kê"*, *"Đại số tuyến tính"* đúng vào buổi chiều tuần sau.
2. **Chưa có chế độ Hỏi đáp Học vụ (Academic Knowledge Base RAG - Hướng 2):**
   * BE đã cung cấp sẵn endpoint `POST /api/v1/search/academic/ask` (`routers/search.py`, dòng 204-224) kết hợp kho tài liệu học vụ vector và 8 bảng cơ sở dữ liệu có cấu trúc (`kb_lecturers`, `kb_courses`, `kb_programs`, `kb_departments`, `kb_faculties`, `kb_achievements`, ...).
   * Trên `SearchScreen`, cần thêm thanh chuyển đổi giữa 2 chế độ: **`[Tìm lịch cá nhân]`** (mặc định) và **`[Hỏi đáp Học vụ]`**.

#### B. Cách sửa trong `sourceCode/FE/api_client.py` và `sourceCode/FE/search_screen.py`
* **Bổ sung 2 hàm gọi API trong `sourceCode/FE/api_client.py`:**
  ```python
  def search_events_query(self, query_text, on_success, on_failure=None, on_error=None, top_k=50):
      params = urlencode({"q": query_text, "top_k": top_k})
      self._request(
          f"/api/v1/search/events?{params}",
          method="GET",
          on_success=on_success,
          on_failure=on_failure,
          on_error=on_error,
      )

  def ask_academic_kb(self, query_text, on_success, on_failure=None, on_error=None, top_k=3):
      payload = {"query": query_text, "top_k": top_k}
      self._request(
          "/api/v1/search/academic/ask",
          method="POST",
          payload=payload,
          on_success=on_success,
          on_failure=on_failure,
          on_error=on_error,
      )
  ```
* **Trên `SearchScreen` (`sourceCode/FE/search_screen.py`):**
  * Thêm biến trạng thái `self.search_mode = "schedule"` (`"schedule"` hoặc `"academic"`) và một hàng gồm 2 nút chọn chế độ đặt ngay dưới thanh `search_bar_container`:
    * Chế độ `"schedule"` (`[Tìm lịch cá nhân]`): Khi người dùng nhập từ khóa (hoặc bấm Enter/nút tìm), gọi `api.search_events_query(query, on_success=self._on_schedule_search_ok, ...)`. Nếu đang ở chế độ chưa đăng nhập (`store.is_demo == True`) hoặc mất mạng thì giữ nguyên nhánh lọc cục bộ trên `store.events` làm phương án dự phòng.
    * Chế độ `"academic"` (`[Hỏi đáp Học vụ]`): Hiển thị nút gửi câu hỏi học vụ; khi người dùng gửi câu hỏi (ví dụ: *"Điều kiện tốt nghiệp ngành CNTT là gì?"*, *"Thầy dạy môn Cấu trúc dữ liệu thuộc bộ môn nào?"*), gọi `api.ask_academic_kb(query, on_success=self._on_academic_ask_ok, ...)` và hiển thị thẻ câu trả lời (`result["answer"]`) kèm danh sách trích dẫn nguồn (`result["citations"]`).

---

### 4. Hiển thị Nút Điều hướng Chéo (`redirect_target` và `redirect_button_label`) giữa `chat_screen.py` và `search_screen.py`

#### A. Điểm chưa khớp
* Theo thiết kế phân tách rõ 2 tính năng trọng tâm:
  1. Nếu người dùng đứng ở màn hình **Trợ lý AI (`chat_home`)** nhưng lại gõ câu hỏi tra cứu lịch hoặc hỏi quy chế học vụ (ví dụ: *"Thứ 6 tuần này mình có tiết học nào không?"*), endpoint `POST /api/v1/assistant/understand` trả về:
     ```json
     {
       "message": "It seems bạn đang muốn tra cứu lịch trình hoặc hỏi đáp học vụ. Khung 'Trợ lý AI' chỉ dùng để xếp lịch công việc mới; bạn hãy bấm nút 'Tìm kiếm' để chuyển sang trang Tra cứu nhé.",
       "redirect_target": "search_home",
       "redirect_button_label": "Tìm kiếm"
     }
     ```
  2. Ngược lại, nếu người dùng đứng ở màn hình **Tìm kiếm (`search_home`)** nhưng lại gõ câu lệnh yêu cầu xếp lịch (ví dụ: *"Xếp cho mình 2 tiếng làm bài tập vào tối mai"*), cả 2 endpoint `GET /api/v1/search/events` và `POST /api/v1/search/academic/ask` đều trả về:
     ```json
     {
       "message": "It seems bạn đang muốn yêu cầu xếp lịch công việc. Trang 'Tìm kiếm' chỉ dùng để tra cứu lịch trình và hỏi đáp học vụ; bạn hãy bấm nút 'Trợ lý AI' để chuyển sang khung xếp lịch thông minh nhé.",
       "redirect_target": "chat_home",
       "redirect_button_label": "Trợ lý AI"
     }
     ```
* Hiện tại `ChatAssistantScreen.on_api_success` (`chat_screen.py`, dòng 548-589) chỉ mới hiển thị chuỗi `message` vào bong bóng chat mà chưa đọc `redirect_target` và `redirect_button_label` để tạo nút chuyển màn hình.

#### B. Cách sửa trong `sourceCode/FE/chat_screen.py` (và tương tự trên `search_screen.py`)
* Trong `ChatAssistantScreen.on_api_success` (`sourceCode/FE/chat_screen.py`, dòng 583-589), sau khi thêm `ChatBubble` chứa `msg`, kiểm tra nếu có `redirect_target` thì gắn thêm một nút bấm điều hướng ngay bên dưới:
  ```python
  msg = result.get("message") or "Đã nhận yêu cầu."
  self.add_message_bubble(msg, is_user=False)

  redirect_target = result.get("redirect_target")
  redirect_label = result.get("redirect_button_label") or "Chuyển trang"
  if redirect_target:
      nav_btn = RoundedButton(
          text=f"Chuyển sang {redirect_label}",
          bg_color= PRIMARY_BLUE,
          color=WHITE_COLOR,
          bold=True,
          size_hint=(None, None),
          size=(dp(200), dp(38)),
      )
      nav_btn.bind(on_release=lambda *_: setattr(MDApp.get_running_app().root, "current", redirect_target))
      self.chat_list.add_widget(nav_btn)
  ```

---

### 5. Tận dụng trực tiếp `available_slots` khi Fallback và hiển thị `extra_slots` cho công việc chia nhỏ trong `chat_screen.py`

#### A. Điểm chưa khớp
1. **Dùng ngay `available_slots` từ phản hồi `/api/v1/assistant/understand` khi `fallback_mode == True` (`chat_screen.py`, dòng 550-580):**
   * Khi mô hình AI bận hoặc quá thời gian chờ, BE (`routers/assistant.py`, dòng 75-102) đã tự động chạy thuật toán tìm giờ trống tất định và đính kèm sẵn mảng `available_slots` (tối đa 20 khung giờ trống đầu tiên) ngay bên trong phản hồi của `POST /api/v1/assistant/understand`.
   * Hiện tại hàm `ChatAssistantScreen._open_manual_picker` (dòng 558-580) luôn gửi thêm một request thứ hai tới `POST /api/v1/search/free-slots`.
2. **Hiển thị các ca làm việc chia nhỏ `extra_slots` trên `ProposalCard` (`chat_screen.py`, dòng 287-302):**
   * Khi người dùng yêu cầu một công việc có thời lượng vượt quá giới hạn làm việc liên tục (mặc định `> 180` phút, ví dụ 240 phút), BE tự động chia công việc thành nhiều ca (Split Task). Ca thứ nhất nằm trong `proposal["start_time"]` và `proposal["end_time"]`; các ca tiếp theo nằm trong danh sách `proposal["extra_slots"]` (`[{"start_time": "...", "end_time": "..."}, ...]`).
   * Hiện tại `ProposalCard._build_info_ui` chỉ mới hiển thị khung giờ của ca thứ nhất.

#### B. Cách sửa trong `sourceCode/FE/chat_screen.py`
* **Tại `ChatAssistantScreen.on_api_success` (dòng 550-556):** Truyền luôn `result.get("available_slots")` vào `_open_manual_picker`:
  ```python
  if nlu.get("fallback_mode"):
      self.add_message_bubble(
          result.get("message") or "Trợ lý AI đang bận. Chuyển sang chế độ chọn lịch trực tiếp.",
          is_user=False,
      )
      precomputed_slots = result.get("available_slots") or []
      if precomputed_slots:
          ManualFallbackModal(
              task_title=nlu.get("title") or "Công việc mới",
              duration_minutes=int(nlu.get("duration_minutes") or 60),
              slots=precomputed_slots,
              on_scheduled=lambda confirm_msg: self.add_message_bubble(confirm_msg, is_user=False),
          ).open()
      else:
          self._open_manual_picker(
              title=nlu.get("title") or "Công việc mới",
              duration=int(nlu.get("duration_minutes") or 60),
          )
      return
  ```
* **Tại `ProposalCard._build_info_ui` (dòng 287-302):** Nếu `self.proposal.get("extra_slots")` khác rỗng, hiển thị thêm các dòng thời gian cho Ca 2, Ca 3,... ngay dưới dòng thời gian chính:
  ```python
  extra_slots = self.proposal.get("extra_slots") or []
  if extra_slots:
      parts = [f"Ca 1: {time_str}"]
      for idx, slot in enumerate(extra_slots, start=2):
          try:
              s_dt = datetime.fromisoformat(slot["start_time"])
              e_dt = datetime.fromisoformat(slot["end_time"])
              parts.append(f"Ca {idx}: {s_dt.strftime('%H:%M')} - {e_dt.strftime('%H:%M')} ({s_dt.strftime('%d/%m')})")
          except (KeyError, ValueError):
              continue
      time_str = " | ".join(parts)
  ```

---

### 6. Tên màn hình khi Đăng xuất và Lưu Tùy chọn Xếp lịch trong `side_bar_menu.py`

#### A. Điểm chưa khớp
1. **Tên màn hình trong `UserAccountWidget.do_logout` (`sourceCode/FE/side_bar_menu.py`, dòng 79-83):**
   * Dòng 83 đang gán `app.root.current = "auth"`, trong khi `AppScreenManager` (`sourceCode/FE/screen_manager.py`, dòng 26) đặt tên màn hình đăng nhập là `"auth_screen"`. Khi bấm nút Đăng xuất, Kivy sẽ phát sinh ngoại lệ `ScreenManagerException: No screen with name "auth"`.
2. **Đường dẫn API trong `SchedulePreferencesDialog.save_preferences` (`sourceCode/FE/side_bar_menu.py`, dòng 209-219):**
   * Hàm `save_preferences` đang gọi `api._request("/api/v1/user/preferences", method="POST", payload=payload)`. Hiện tại phía BE chưa mở endpoint `/api/v1/user/preferences` (bảng `user_preferences` được khởi tạo tự động với cấu hình mặc định `23:30 - 06:30` khi đăng ký tài khoản tại `routers/auth.py`).

#### B. Cách sửa trong `sourceCode/FE/side_bar_menu.py`
* **Tại `UserAccountWidget.do_logout` (dòng 79-84):** Đổi `"auth"` thành `"auth_screen"`, đóng `SideBarMenu` đang mở và chuyển `event_store.store` về chế độ demo:
  ```python
  from event_store import store

  def do_logout(self, instance):
      api.clear_session()
      store.use_demo()
      app = MDApp.get_running_app()
      if app and app.root:
          app.root.current = "auth_screen"
  ```
* **Tại `SchedulePreferencesDialog.save_preferences` (dòng 209-219):** Bổ sung `on_failure` và `on_error` nhẹ nhàng hoặc lưu tạm vào `api.store` (`session.json`) để không báo lỗi kết nối khi người dùng bấm Lưu tùy chọn.

---

### 7. Chi tiết Sự kiện / Chỉnh giờ Nhắc hẹn (`PUT /api/v1/reminders/{event_id}`) và Đăng nhập OAuth2 (Tính năng mở rộng Mức 3)

#### A. Điểm chưa khớp
1. **Bấm vào sự kiện trên lưới lịch (`EventBlock.on_release` trong `sourceCode/FE/calendar_screen.py`, dòng 447):**
   * Hiện tại hàm `on_release` chỉ in ra console `print(f"Bấm sự kiện: {self.event['title']}")`.
   * BE đã có sẵn API cài đặt thời gian nhắc hẹn trước cho từng sự kiện tại `PUT /api/v1/reminders/{event_id}` (body: `{"offset_minutes": 30}`) và API xóa mềm công việc linh hoạt tại `DELETE /api/v1/tasks/{task_id}`.
2. **Đăng nhập OAuth2 Google / GitHub (`sourceCode/FE/auth_screen.py`, dòng 254-280):**
   * Hai nút Google và GitHub trong `auth_screen.py` hiện đang gọi `simulate_oauth_login` (giả lập sau 1 giây). Trong khi đó `api_client.py` (dòng 56-75) đã viết sẵn các phương thức `oauth_start`, `oauth_exchange` và `update_username` tương ứng với `GET /api/v1/auth/oauth/{provider}/start`, `POST /api/v1/auth/oauth/{provider}/exchange` và `PATCH /api/v1/auth/username` của BE.

#### B. Cách sửa (khi còn thời gian sau khi hoàn tất luồng MVP)
* Khi bấm vào `EventBlock` trên `CalendarScreen`, có thể mở một `ModalView` nhỏ hiển thị thông tin sự kiện (`title`, `room`, `start_time`, `end_time`, `kind`) kèm ô nhập số phút báo trước và nút `[Cập nhật nhắc hẹn]` gọi `api._request(f"/api/v1/reminders/{event['id']}", method="PUT", payload={"offset_minutes": offset})`.

---

## Phần 2. Quy ước Giao tiếp Chung giữa Kivy (FE) và FastAPI (BE)

### 2.1. Địa chỉ Máy chủ và Xác thực JWT
* **Địa chỉ cơ sở (`BASE_URL`):** Mặc định là `http://127.0.0.1:8080` (được cấu hình qua biến môi trường `BACKEND_URL` trong `sourceCode/FE/api_client.py`).
* **Lưu trữ phiên đăng nhập:** `APIClient` lưu `access_token`, `user_id`, `display_name` trong tệp `session.json` thông qua `kivy.storage.jsonstore.JsonStore`.
* **Header xác thực:** Mọi request sau khi đăng nhập đều đính kèm header:
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```

### 2.2. Quy ước Múi giờ và Lưới thời gian 15 phút
* **Múi giờ hiển thị và giao tiếp (`+07:00`):** Toàn bộ chuỗi thời gian `start_time`, `end_time`, `fire_at` do BE trả về đều ở định dạng ISO 8601 có gắn múi giờ Việt Nam `+07:00` (ví dụ: `"2026-09-07T07:30:00+07:00"`). Hàm `datetime.fromisoformat(...)` của Python 3.10+ đọc trực tiếp được chuỗi này.
* **Lưới thời gian 15 phút:** Mọi sự kiện và đề xuất từ BE luôn có số phút chia hết cho `15` (`:00`, `:15`, `:30`, `:45`), tương thích trực tiếp với trục tung 24 giờ trên `CalendarScreen`.

### 2.3. Bảng phân loại Sự kiện (`kind`) và Quy tắc hiển thị trên Lịch
Bảng `EVENT_STYLES` trong `sourceCode/FE/calendar_screen.py` (dòng 35-41) đã định nghĩa đầy đủ 5 loại `kind` khớp với `EventKind` của BE:
* `CLASS`: Lịch học cố định (`is_hard = True`).
* `EXAM`: Lịch thi cử (`is_hard = True`).
* `EVENT`: Sự kiện / ngoại khóa / ca làm thêm.
* `TASK`: Công việc cá nhân hoặc ca học tự xếp qua AI (`is_hard = False`).
* `DEADLINE`: Mốc hạn chót có `start_time == end_time` (thời lượng bằng `0`). Trong `CalendarScreen.update_events_display` (dòng 949-951), cần kiểm tra `if e["kind"] == "DEADLINE":` trước để đẩy vào dải `deadline_banner_box` phía trên đỉnh cột ngày thay vì vẽ khối `EventBlock` có chiều cao bằng 0 trên lưới giờ.

---

## Phần 3. Hợp đồng API Chi tiết theo từng Màn hình của FE

### 3.1. Màn hình Xác thực (`sourceCode/FE/auth_screen.py`)

#### 1. Đăng ký tài khoản mới (`POST /api/v1/auth/register`)
* **Request Body:**
  ```json
  {
    "username": "sv_khoi",
    "password": "password123",
    "display_name": "Anh Khoi"
  }
  ```
* **Response (`201 Created`):**
  ```json
  {
    "user_id": 1,
    "username": "sv_khoi",
    "display_name": "Anh Khoi",
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
  }
  ```
* **Mã lỗi cần xử lý trên UI:** `409 Conflict` (`"username is already registered"`), `422 Unprocessable Entity` (mật khẩu ngắn hơn 6 ký tự hoặc `username` ngắn hơn 3 ký tự).

#### 2. Đăng nhập bằng mật khẩu (`POST /api/v1/auth/login`)
* **Request Body:**
  ```json
  {
    "username": "sv_khoi",
    "password": "password123"
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "user_id": 1
  }
  ```
* **Hành động trên FE sau khi nhận Token:** Lưu phiên qua `api.save_session(...)`, gọi `store.refresh(api)` để tải lịch thực tế của người dùng từ MySQL, và chuyển `self.manager.current = "calendar_home"`.

---

### 3.2. Màn hình Lịch chính (`calendar_screen.py`, `event_store.py`, `event_modals.py`)

#### 1. Tải danh sách sự kiện lên Lịch (`GET /api/v1/search/events`)
* Được gọi tự động bởi `event_store.store.refresh(api)` thông qua `api.list_events(start_iso, end_iso, ...)`:
  ```http
  GET /api/v1/search/events?start_from=2026-08-01T00:00:00&end_until=2027-02-01T23:59:59&top_k=200
  ```
* **Response (`200 OK`):**
  ```json
  {
    "query": "",
    "normalized_query": "",
    "keywords": "",
    "total": 2,
    "events": [
      {
        "id": 101,
        "owner_id": 1,
        "course_id": 5,
        "task_id": null,
        "proposal_id": null,
        "title": "Cấu trúc dữ liệu & Giải thuật",
        "room": "F.102",
        "kind": "CLASS",
        "source": "IMPORTED",
        "start_time": "2026-09-07T07:30:00+07:00",
        "end_time": "2026-09-07T09:30:00+07:00",
        "is_hard": true,
        "priority": 1,
        "is_important": false,
        "similarity_score": 1.0
      }
    ],
    "message": null,
    "redirect_target": null,
    "redirect_button_label": null
  }
  ```

#### 2. Quy trình 4 bước Nhập Thời khóa biểu (`ImportStep1Modal` -> `ImportStep2Modal` -> `ImportStep3Modal`)
* **Bước 1 (`POST /api/v1/ingestion/parse-preview`):**
  * Gửi form field `raw_content` (hoặc multipart `file` cho `.csv`, `.txt`, `.md`, `.pdf`, ảnh chụp).
  * **Response (`200 OK`):**
    ```json
    {
      "import_batch_id": "9f8c2a10-4b3d-4e1a-9c11-0123456789ab",
      "valid_count": 5,
      "invalid_count": 1,
      "valid_rows": [
        {
          "line_number": 1,
          "course_code": "CSC10004",
          "title": "Cấu trúc dữ liệu",
          "kind": "CLASS",
          "start_time": "07:30",
          "end_time": "09:30",
          "first_date": "2026-09-07",
          "last_date": "2026-12-20",
          "weekday": "MON",
          "room": "F.102"
        }
      ],
      "invalid_rows": [
        {
          "line_number": 2,
          "raw_text": "CSC10006,Hệ cơ sở dữ liệu,TUE,25:00,09:30,E.201,2026-09-08,2026-12-20,CLASS",
          "error_code": "INVALID_START_TIME",
          "error_message": "Invalid start_time '25:00'. Expected 24-hour HH:MM format."
        }
      ]
    }
    ```
* **Bước 2 (`POST /api/v1/ingestion/resolve-preview`):**
  * Gửi `import_batch_id`, `valid_rows`, `corrected_rows` (các dòng vàng người dùng đã sửa) và `skipped_line_numbers` (các dòng lỗi người dùng chọn bỏ qua).
  * **Response (`200 OK`):** Trả về `all_valid_rows` (danh sách sạch 100%).
* **Bước 3 (`POST /api/v1/ingestion/check-conflicts`):**
  * **Request Body:**
    ```json
    {
      "incoming_rows": [ ... ],
      "replace_previous_imports": false
    }
    ```
  * **Response (`200 OK`):**
    ```json
    {
      "non_conflicting_rows": [ ... ],
      "conflict_cards": [
        {
          "conflict_id": "conf_1",
          "option_a": {
            "option_type": "incoming_row",
            "line_number": 3,
            "course_code": "",
            "title": "Ca làm thêm quán cà phê",
            "kind": "EVENT",
            "start_time": "08:00:00",
            "end_time": "11:00:00",
            "first_date": "2026-09-07",
            "last_date": "2026-12-20",
            "weekday": "MON",
            "room": "Quận 5"
          },
          "option_b": {
            "option_type": "existing_event",
            "id": 101,
            "title": "Cấu trúc dữ liệu",
            "start_time": "2026-09-07T07:30:00+07:00",
            "end_time": "2026-09-07T09:30:00+07:00",
            "kind": "CLASS",
            "room": "F.102"
          },
          "overlap_description": "Trùng lịch vào Thứ Hai hàng tuần (08:00 - 09:30)"
        }
      ]
    }
    ```
* **Bước 4 (`POST /api/v1/ingestion/commit`):**
  * **Request Body:**
    ```json
    {
      "import_batch_id": "9f8c2a10-4b3d-4e1a-9c11-0123456789ab",
      "resolved_rows": [ ... ],
      "replace_previous_imports": false
    }
    ```
  * **Lưu ý về biến `replace_previous_imports`:**
    * Mặc định gửi `false`: BE kích hoạt cơ chế **Smart Diff & Subject-Scoped Upsert**, chỉ cập nhật đúng những môn học có trong file mới (giữ nguyên các buổi không đổi, giữ nguyên các môn khác không nằm trong file mới, và không xóa lịch làm thêm khi nạp lịch học hoặc ngược lại).
    * Chỉ gửi `true` nếu người dùng chủ động tích vào ô *"Xóa toàn bộ thời khóa biểu học kỳ cũ trước khi nạp"*.

---

### 3.3. Màn hình Tìm kiếm 2 Chế độ (`sourceCode/FE/search_screen.py`)

#### 1. Chế độ A - Tìm kiếm Lịch trình Cá nhân (`GET /api/v1/search/events`)
* **Request:** `GET /api/v1/search/events?q=lich+thi+cac+mon+toan+tuan+sau&top_k=50`
* **Response (`200 OK`):** Trả về đối tượng `ScheduleSearchResponse` gồm mảng `events` đã được lọc theo thời gian, phòng học, loại sự kiện và xếp hạng độ tương đồng ngữ nghĩa `similarity_score`. Nếu người dùng gõ nhầm câu lệnh xếp lịch, mảng `events` sẽ rỗng kèm `message`, `redirect_target = "chat_home"` và `redirect_button_label = "Trợ lý AI"`.

#### 2. Chế độ B - Hỏi đáp Học vụ 6-Step RAG (`POST /api/v1/search/academic/ask`)
* **Request Body:**
  ```json
  {
    "query": "Cho mình hỏi giảng viên phụ trách môn Cấu trúc dữ liệu và điều kiện tiên quyết của môn này?",
    "top_k": 3
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "query": "Cho mình hỏi giảng viên phụ trách môn Cấu trúc dữ liệu và điều kiện tiên quyết của môn này?",
    "normalized_query": "cho minh hoi giang vien phu trach mon cau truc du lieu va dieu kien tien quyet cua mon nay?",
    "answer": "Môn Cấu trúc dữ liệu và Giải thuật (CSC10004 - 4 tín chỉ) thuộc Bộ môn Khoa học Máy tính...",
    "citations": [
      {
        "source": "structured_kb:courses",
        "text": "[Học phần] CSC10004 - Cấu trúc dữ liệu và Giải thuật (4 tín chỉ) | Bộ môn: Khoa học Máy tính...",
        "score": 0.95
      },
      {
        "source": "so_tay_sinh_vien_2026.pdf#chunk_4",
        "text": "Sinh viên cần hoàn thành môn Kỹ thuật lập trình trước khi đăng ký Cấu trúc dữ liệu...",
        "score": 0.78
      }
    ],
    "fallback_mode": false,
    "redirect_target": null,
    "redirect_button_label": null
  }
  ```

---

### 3.4. Màn hình Trợ lý AI Xếp lịch (`sourceCode/FE/chat_screen.py` và `sourceCode/FE/fallback.py`)

#### 1. Gửi câu lệnh ngôn ngữ tự nhiên (`POST /api/v1/assistant/understand`)
* **Request Body:**
  ```json
  {
    "prompt": "Xếp cho mình 2 tiếng ôn tập Xác suất thống kê vào chiều thứ 5 tuần này, né buổi tối ra nhé",
    "reschedule_proposal_id": null
  }
  ```
  *(Khi người dùng bấm `[Suy nghĩ thêm]` trên một thẻ đề xuất rồi gõ yêu cầu đổi giờ, truyền `id` của đề xuất đó vào `reschedule_proposal_id`).*
* **Response (`200 OK`):**
  ```json
  {
    "nlu": {
      "intent": "schedule_task",
      "title": "Ôn tập Xác suất thống kê",
      "duration_minutes": 120,
      "priority": 2,
      "preferred_time_of_day": "afternoon",
      "avoid_time_of_day": "evening",
      "date_hint": "thứ 5",
      "deadline_hint": null,
      "window_start": "2026-11-12",
      "window_end": "2026-11-12",
      "deadline": null,
      "needs_clarification": false,
      "clarification_question": null,
      "fallback_mode": false
    },
    "abandoned_proposals": 0,
    "message": "Mình đề xuất khung giờ này, bạn xác nhận nhé.",
    "proposal": {
      "id": 42,
      "task_id": 18,
      "parent_id": null,
      "task_title": "Ôn tập Xác suất thống kê",
      "duration_minutes": 120,
      "start_time": "2026-11-12T13:30:00+07:00",
      "end_time": "2026-11-12T15:30:00+07:00",
      "rationale": "Khung giờ chiều phù hợp với ưu tiên của bạn và còn trống 180 phút.",
      "status": "PROPOSED",
      "extra_slots": []
    },
    "available_slots": [],
    "redirect_target": null,
    "redirect_button_label": null
  }
  ```
* **4 Nhánh xử lý phản hồi trên `ChatAssistantScreen.on_api_success`:**
  1. **Nhánh Redirect (`result.get("redirect_target") is not None`):** Hiển thị bong bóng `message` kèm nút bấm chuyển sang màn hình `search_home`.
  2. **Nhánh Làm rõ thông tin (`nlu["needs_clarification"] == True`):** Hiển thị `nlu["clarification_question"]` để sinh viên trả lời bổ sung ngày/giờ.
  3. **Nhánh Fallback (`nlu["fallback_mode"] == True`):** Hiển thị thông báo chuyển sang chế độ chọn lịch trực tiếp và mở `ManualFallbackModal` với danh sách `result["available_slots"]`.
  4. **Nhánh Đề xuất thành công (`result.get("proposal") is not None`):** Hiển thị `message` và thẻ `ProposalCard` với 3 nút:
     * `[Xác nhận]` -> `POST /api/v1/proposals/{id}/confirm` -> gọi `store.refresh(api)` + `schedule_reminders_from_confirm(res)`.
     * `[Suy nghĩ thêm]` -> bật thanh trạng thái Reschedule, giữ `active_reschedule_proposal` để lần gửi tin nhắn kế tiếp đính kèm `reschedule_proposal_id`.
     * `[Từ chối]` -> `POST /api/v1/proposals/{id}/reject`.
