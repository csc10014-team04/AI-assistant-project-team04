# Phân công Trách nhiệm & Bản đồ Module - Team Backend (BE)

Tài liệu này quy định rõ **Người phụ trách chính (Person-in-Charge - PIC)** cho từng file trong `sourceCode/BE/`, phạm vi các logic mà mỗi thành viên bắt buộc nắm vững khi đọc/sửa code, cùng phần mô tả nền tảng cho quy trình **Nhập liệu & Giải quyết xung đột (Ingestion & Conflict Resolution)**.

Chi tiết kiến trúc, luồng xử lý, công thức chấm điểm và hợp đồng Input/Output của hai tính năng trọng tâm đã được tách riêng thành 2 tài liệu độc lập:
* **Tính năng 1 - Tìm kiếm Thông tin (Information Searching):** Xem [`feature_information_searching.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/feature_information_searching.md).
* **Tính năng 2 - Xếp lịch Thông minh cùng AI (Scheduling with AI):** Xem [`feature_scheduling_with_ai.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/feature_scheduling_with_ai.md).

---

## 1. Bảng Phân công Person-in-Charge (PIC) & Logic Cần Nắm theo Từng File

Do mã nguồn trong `sourceCode/BE/` được tổ chức theo **kiến trúc phân tầng (`routers/` và `services/`)**, một số file dùng chung được đánh dấu rõ phân vùng bằng nhãn `# [pic: khoi]` và `# [pic: lam]` để mỗi thành viên biết chính xác khu vực mình phụ trách:

| Thành viên (PIC) | Các File & Phân vùng Phụ trách | Các Logic Cốt lõi Cần Nắm Vững |
| :--- | :--- | :--- |
| **1. Khôi** | - [`services/security.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/security.py) & [`routers/auth.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/auth.py)<br>- [`services/validator.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/validator.py) & nửa sau [`routers/ingestion.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/ingestion.py)<br>- [`services/search_engine.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/search_engine.py) *(Section 1 & Section 2: `# [pic: khoi]`)*<br>- [`routers/search.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/search.py) *(Section 1: `# [pic: khoi]`)*<br>- Phối hợp tầng NLU/Scheduling: [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) & [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py)<br>- Kiểm thử: [`tests/test_auth.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/tests/test_auth.py), [`tests/test_validator.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/tests/test_validator.py) | 1. **Xác thực & Bảo vệ phiên (`P1-3`):** Băm mật khẩu `bcrypt`, cấp/kiểm tra JWT Token, hàm `get_current_user` chống truy cập chéo (`IDOR`).<br>2. **Kiểm thực trùng lịch & Lưu DB (`P1-6` & nửa sau `P1-4`):** Hàm `check_hard_conflict`, gom nhóm xung đột theo chuỗi tuần `detect_import_conflicts`, bung các tuần học `commit_resolved_import`.<br>3. **Tính năng Information Searching (`P1-5A` & RAG Học vụ):**<br>   - *Hướng 1 (Schedule Search):* Chuẩn hóa câu hỏi, lọc SQL kết hợp Vector Search 2 tầng (`SEMANTIC_CONCEPT_CLUSTERS` + Neural Fallback), hậu kiểm giờ `+07:00`.<br>   - *Hướng 2 (Academic KB):* Quy trình RAG 6 bước trên kho chỉ mục mã hóa `data/rag/academic_kb` + Fallback trả trích dẫn gốc.<br>4. **Điều hướng chéo & Ràng buộc `deadline_hint` trong `Scheduling with AI`.** |
| **2. Lâm** | - [`services/parser.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/parser.py)<br>- Nửa đầu [`routers/ingestion.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/ingestion.py) (`/parse-preview` & `/resolve-preview`)<br>- [`services/search_engine.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/search_engine.py) *(Section 3: `# [pic: lam]`)*<br>- [`routers/search.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/search.py) *(Section 2: `# [pic: lam]`)*<br>- Kiểm thử: [`tests/parser_test.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/tests/parser_test.py), [`tests/ingestion_test.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/tests/ingestion_test.py) | 1. **Đọc Thời khóa biểu Đa định dạng & Lọc Edge Cases (Nửa đầu `P1-4`):**<br>   - Phân tích cú pháp `.csv`, `.md`, `.txt`, `.pdf` và ảnh chụp thời khóa biểu (qua OCR).<br>   - Chặn các tệp phi thời khóa biểu (ảnh mèo, ảnh phong cảnh, tệp rỗng) và cách ly từng dòng lỗi vào `invalid_rows` mà không làm sập các dòng đúng (`valid_rows`).<br>   - Cho phép `course_code: Optional[str] = None` đối với các hoạt động ngoại khóa/câu lạc bộ không có mã môn.<br>2. **Thuật toán Tìm Khung giờ Trống dưới 200ms (`P1-5B`):**<br>   - Thuật toán `sort-and-sweep` $O(N \log N)$ trong `find_free_slots` và `find_user_free_slots`.<br>   - Trừ khoảng bận (`blocks_availability`), trừ giờ ngủ (`sleep_start..sleep_end`), cộng khoảng nghỉ đệm (`min_break_minutes`), và căn lưới bội số `15` phút (`_align_up_to_step`, `_align_down_to_step`). |
| **3. Nhóm DB / AI-Host** *(Phối hợp hạ tầng)* | - [`models.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/models.py), [`database.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/database.py)<br>- `services/rag.py`, `services/normalizer.py`, `services/temporal.py`, `services/privacy.py`, `services/inference_queue.py`, `services/ai_logging.py`, `services/telemetry.py` | - Quản lý 11 bảng MySQL 8.0 (cổng Docker `3307`), hàng đợi suy luận tuần tự FIFO `broker`, máy chủ `vLLM` nội bộ (`Meta-Llama-3.1-8B-Instruct-AWQ-INT4`), kho mã hóa Fernet và ghi nhật ký lỗi AI (`ai_error_logs`). |

---

## 2. Vai trò Từng File trong `sourceCode/BE/`

* [`models.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/models.py): **[KHÓA CỨNG]** Định nghĩa toàn bộ `Enum`, các lớp dữ liệu miền trong bộ nhớ (`TimeSlot`, `EventDomain`, `ParsedCsvRow`, `InvalidCsvRow`, `ParseBatchResult`) và 11 bảng cơ sở dữ liệu SQLAlchemy ORM.
* [`database.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/database.py): **[KHÓA CỨNG]** Thiết lập kết nối MySQL (`get_db`), chuyển đổi múi giờ `UTC` <-> `+07:00` (`to_db_utc`, `from_db_to_vn`), làm tròn lưới 15 phút và cung cấp các hàm truy vấn an toàn lọc sẵn `owner_id` + `deleted_at IS NULL` (`active_events_stmt`, `active_courses_stmt`, `abandon_pending_proposals`).
* [`main.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/main.py): Điểm khởi chạy máy chủ FastAPI, cấu hình CORS và gắn kết 5 bộ định tuyến (`auth`, `assistant`, `reminders`, `ingestion`, `search`).
* [`services/security.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/security.py) & [`routers/auth.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/auth.py): **(Khôi)** Băm/kiểm tra mật khẩu `bcrypt`, ký/giải mã JWT Token, dependency `get_current_user`, API Đăng ký (`/register`), Đăng nhập (`/login`) và Đổi tên đăng nhập (`/username`).
* [`services/parser.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/parser.py): **(Lâm)** Đọc dữ liệu thời khóa biểu từ văn bản (`.csv`, `.md`, `.txt`), tệp `.pdf` và ảnh chụp màn hình (OCR); kiểm tra cổng cấu trúc để từ chối ảnh phi thời khóa biểu; tách dòng đúng vào `valid_rows` và cô lập dòng lỗi vào `invalid_rows`.
* [`services/validator.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/validator.py): **(Khôi)** Kiểm tra trùng giờ với lịch cứng (`check_hard_conflict`), gom nhóm các môn trùng giờ thành Thẻ Xung Đột cấp chuỗi tuần (`detect_import_conflicts`) và bung tuần học lưu xuống MySQL (`commit_resolved_import`).
* [`routers/ingestion.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/ingestion.py): **(Lâm + Khôi)** Điều phối quy trình nhập lịch 4 bước: Lâm phụ trách Bước 1-2 (`/parse-preview`, `/resolve-preview`); Khôi phụ trách Bước 3-4 (`/check-conflicts`, `/commit`).
* [`services/search_engine.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/search_engine.py) & [`routers/search.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/search.py): **(Khôi + Lâm)**
  * *Phân vùng của Khôi (`# [pic: khoi]`):* Tìm kiếm lịch trình lai SQL + Vector 2 tầng (`optimize_search_query`, `execute_local_search`, `verify_and_format_search_results`, `GET /api/v1/search/events`) và Hỏi đáp học vụ RAG 6 bước (`ingest_academic_document`, `ask_academic_knowledge_base`, `POST /api/v1/search/academic/ask`).
  * *Phân vùng của Lâm (`# [pic: lam]`):* Động cơ tìm khung giờ trống dưới `200ms` (`find_free_slots`, `find_user_free_slots`, `POST /api/v1/search/free-slots`).

---

## 3. Logic Nền tảng: Nhập liệu Đa nguồn, Xử lý Input & Giải quyết Xung đột (`P1-4` & `P1-6`)

Quy trình nhập thời khóa biểu (từ cổng đào tạo, lịch làm thêm hoặc lịch câu lạc bộ) được chia làm 4 bước nối tiếp giữa **Lâm** và **Khôi**:

```text
[PHẦN CỦA LÂM: Bước 1 & Bước 2]                              [PHẦN CỦA KHÔI: Bước 3 & Bước 4]
Tệp .csv / .md / .pdf / Ảnh chụp                             Danh sách sạch: list[ParsedCsvRow]
       |                                                                    |
       v                                                                    v
1. Trích xuất & Kiểm tra từng dòng (/parse-preview)          3. Phát hiện trùng giờ (/check-conflicts)
   - Chặn ảnh rác/phi thời khóa biểu                            - Không trùng -> non_conflicting_rows
   - Dòng hợp lệ -> valid_rows                                  - Bị trùng    -> Gom theo chuỗi tuần thành
   - Dòng lỗi    -> invalid_rows (cô lập, không sập)              ConflictCard để User chọn [Giữ A / B / Cả hai]
       |                                                                    |
       v                                                                    v
2. Xem trước & Sửa lỗi (/resolve-preview)                    4. Bung tuần học & Lưu DB (/commit)
   - User sửa dòng vàng hoặc bấm Bỏ qua                         - Ghi vào bảng courses và events (giờ UTC)
   - Xuất ra: list[ParsedCsvRow] sạch 100%                      - Hỗ trợ xóa mềm lịch IMPORTED cũ khi nạp lại
```

### 3.1. Xử lý Input & Cách ly lỗi khi Parse (PIC: Lâm - `services/parser.py`)
* **Lược đồ 9 cột chuẩn hóa:** `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`.
* **Quy định về `course_code` (`Optional[str] = None`):**
  * Chỉ các buổi học chính khóa (`kind == CLASS`) hoặc lịch thi học phần mới có mã môn học; đối với lịch họp câu lạc bộ, ca làm thêm hoặc sự kiện cá nhân (`EVENT`, `DEADLINE`), `course_code` được phép để trống (`None` hoặc `""`).
* **Bốn phân loại `CsvRowKind`:**
  * `CLASS`: Lặp lại hằng tuần vào thứ `weekday` (`MON..SUN`) từ `first_date` đến `last_date` (`start_time < end_time`).
  * `EXAM` & `EVENT`: Diễn ra 1 lần duy nhất (`first_date == last_date`, `start_time < end_time`).
  * `DEADLINE`: Mốc hạn chót thời lượng bằng 0 (`start_time == end_time`, `first_date == last_date`; nếu khuyết `start_time` thì tự động gán bằng `end_time`).
* **Xử lý tệp `.pdf`, Ảnh chụp và Các trường hợp biên (Edge Cases):**
  * Nếu người dùng tải lên tệp nhị phân giả mạo hoặc ảnh không chứa cấu trúc thời khóa biểu (ví dụ: ảnh mèo, ảnh phong cảnh, hóa đơn), bộ lọc cấu trúc sau OCR phát hiện thiếu tổ hợp mỏ neo (khung giờ `HH:MM` đi kèm thứ/ngày) và từ chối ngay với `HTTP 422` (`NO_TIMETABLE_DETECTED`), không sinh dữ liệu rác.
  * Nếu trong bảng thời khóa biểu 50 dòng có vài dòng bị nhòe chữ hoặc sai định dạng giờ, hàm `parse_timetable_content` cô lập riêng những dòng đó vào `invalid_rows` kèm mã lỗi cụ thể, giữ nguyên các dòng đúng trong `valid_rows` để người dùng chỉnh sửa trên màn hình Preview.

### 3.2. Phát hiện Xung đột Chuỗi lặp & Bung tuần học (PIC: Khôi - `services/validator.py`)
* **Gom nhóm xung đột cấp chuỗi lặp (`detect_import_conflicts`):**
  * Khi gộp 2 nguồn lịch (ví dụ: môn học 15 tuần sáng Thứ Hai `07:30 - 09:30` trùng với ca làm thêm 15 tuần sáng Thứ Hai `08:00 - 11:00`), thay vì báo 15 lỗi rời rạc cho 15 tuần, thuật toán gom lại thành **1 Thẻ Xung Đột (`ConflictCard`)** duy nhất để sinh viên chọn 1 lần (`KEEP_A`, `KEEP_B`, hoặc `KEEP_BOTH`).
* **Bung tuần học & Bảo toàn lịch cá nhân khi nạp lại (`commit_resolved_import`):**
  * Bung từng dòng `CLASS` từ `first_date` đến `last_date` thành các bản ghi cụ thể trong bảng `events` (`is_hard = True`, `source = IMPORTED`, chuyển giờ sang UTC qua `to_db_utc`).
  * Với `DEADLINE`, lưu `start_time = end_time` (`blocks_availability = False`) để hiển thị nhắc hạn trên đầu ngày nhưng không chặn thuật toán tìm giờ trống của Lâm.
  * Khi người dùng chọn nạp đè thời khóa biểu mới (`replace_previous_imports = True`), hệ thống chỉ đánh dấu xóa mềm (`deleted_at = now`) các sự kiện mang nguồn `IMPORTED`, bảo toàn 100% các sự kiện cá nhân (`MANUAL` và `AI_CREATED`).
* **Chốt chặn Ràng buộc cứng (`check_hard_conflict`):**
  * Được gọi trước mọi thao tác xác nhận đề xuất của AI hoặc tạo sự kiện mới nhằm đảm bảo không có bất kỳ công việc mới nào đè lên các sự kiện mang cờ `is_hard = True`.
