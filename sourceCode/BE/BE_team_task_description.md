## Giải thích chi tiết 4 Tính năng của Phase 1 

### Tính năng 1 (P1-3): Hệ thống Đăng nhập & Bảo vệ API (Local Authentication & Session Guard)
* **Mục tiêu:** Bảo vệ dữ liệu lịch cá nhân của từng sinh viên. Phase 1 chỉ dùng `username` và `password` (chưa cần nối Google/GitHub, nhưng cấu trúc bảng đã tách sẵn `users` và `auth_identities` để Phase 2 chỉ việc thêm vào).
* **Luồng hoạt động chi tiết:**
  1. **Đăng ký (`POST /api/v1/auth/register`):**
     * Nhận `username`, `password`, `display_name`.
     * Kiểm tra trong bảng `auth_identities` xem đã có dòng nào mang `provider = 'password'` và `provider_user_id == username` chưa. Nếu có rồi $\rightarrow$ trả lỗi `HTTP 409 Conflict`.
     * Nếu chưa có: Dùng thư viện `bcrypt` băm mật khẩu (kèm muối ngẫu nhiên). Tạo 1 dòng trong bảng `users`, 1 dòng trong `auth_identities` (`provider = 'password'`), và 1 dòng cấu hình mặc định trong `user_preferences` (giờ ngủ 23:30 - 06:30, nghỉ giữa giờ 15 phút).
  2. **Đăng nhập (`POST /api/v1/auth/login`):**
     * Nhận `username`, `password`. So khớp mật khẩu bằng `bcrypt.checkpw`.
     * Nếu đúng: Sinh ra một chuỗi **JWT Token** (chứa `user_id` và thời hạn `exp`), trả về cho app Android lưu giữ.
  3. **Hàm bảo vệ (`get_current_user`):**
     * Mọi API về sau (nhập lịch, xóa lịch, tìm kiếm) đều gọi hàm này để lấy ra đúng `current_user.id`, đảm bảo sinh viên A không bao giờ đọc hay xóa được lịch của sinh viên B.

---

### Tính năng 2 (P1-4): Nhập liệu Đa nguồn & Giải quyết Xung đột (`Multi-Source Schedule Ingestion & Conflict Resolution`)
Đây là tính năng lớn nhất của Phase 1. Sinh viên có thể tải lên nhiều file từ các nguồn khác nhau (ví dụ: File 1 là thời khóa biểu chính khóa của trường, File 2 là lịch đi làm thêm hoặc lịch câu lạc bộ). Hệ thống không bắt sinh viên phải tự dò mắt xem giờ làm thêm có đè lên giờ học hay không, mà xử lý qua **4 bước mạch lạc (chia đôi cho Lâm và Khôi)**:

```
[PHẦN CỦA LÂM: Bước 2.1 & 2.2]                                [PHẦN CỦA KHÔI: Bước 2.3 & 2.4]
File thô (.csv/.md/.txt)                                      Danh sách sạch: list[ParsedCsvRow]
       │                                                                     │
       ▼                                                                     ▼
1. Đọc & Kiểm tra từng dòng                                   3. So khớp tìm trùng giờ (Conflict Detection)
   - Dòng chuẩn -> valid_rows                                    - Không trùng -> Sẵn sàng lưu
   - Dòng lỗi   -> invalid_rows (cách ly, không sập)             - Bị trùng    -> Gom thành Thẻ Xung Đột (Conflict Card)
       │                                                           để User bấm chọn [Giữ A] hoặc [Giữ B]
       ▼                                                                     │
2. Màn hình Xem trước (Preview)                                              ▼
   - User sửa trực tiếp dòng lỗi hoặc bấm Bỏ qua              4. Bung các tuần học (Expand) & Lưu xuống MySQL
   - Xuất ra: list[ParsedCsvRow] sạch 100%                       - Ghi vào bảng `courses` và `events`
```

* **Bước 2.1 — Đọc file và Cách ly dòng lỗi (Do Lâm làm trong `services/parser.py`):**
  * File đầu vào được chuẩn hóa về lược đồ 9 cột: `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`.
  * Cột `kind` có 4 giá trị hợp lệ (`CsvRowKind`):
    * `CLASS`: Buổi học lặp lại hằng tuần từ `first_date` đến `last_date` vào thứ `weekday` (`MON`..`SUN`).
    * `EXAM`: Lịch thi 1 lần duy nhất (`first_date == last_date`).
    * `EVENT`: Sự kiện cố định 1 lần (`first_date == last_date`).
    * `DEADLINE`: Hạn nộp bài chỉ có 1 thời điểm chót (`start_time == end_time`, `first_date == last_date`).
  * **Cơ chế cách ly lỗi:** Nếu trong file 50 dòng có 2 dòng bị sai định dạng giờ hoặc thiếu cột, hàm đọc file **không được văng lỗi làm hỏng cả file**, mà tách thành 2 danh sách trong `ParseBatchResult`:
    * `valid_rows`: Chứa các đối tượng `ParsedCsvRow` đã hợp lệ.
    * `invalid_rows`: Chứa các đối tượng `InvalidCsvRow` (ghi rõ dòng số mấy, chữ gốc là gì, lỗi gì).
* **Bước 2.2 — Xem trước và Xác nhận dòng lỗi (Do Lâm làm trong `routers/ingestion.py`):**
  * Trả `valid_rows` (màu xanh) và `invalid_rows` (màu vàng) về cho app Android.
  * Người dùng sửa lại ô bị thiếu trên màn hình (hoặc bấm bỏ qua dòng ghi chú rác), gửi lại lên API. Kết quả thu được là một danh sách **`list[ParsedCsvRow]` sạch 100%**. **Đây chính là điểm Lâm bàn giao dữ liệu sang cho Khôi.**
* **Bước 2.3 — Phát hiện Xung đột khi Gộp lịch (Do Khôi làm trong `services/validator.py`):**
  * **Tại sao không dùng `priority` để tự động xóa lịch trùng?** Vì lúc vừa tải file lên, người dùng chưa hề gán độ ưu tiên cho từng mục, và ứng dụng tuyệt đối không được tự ý đoán mò rồi âm thầm xóa lịch học hay lịch làm thêm của người dùng.
  * **Cách xử lý thông minh (Gom nhóm theo chuỗi lặp - Series-level Conflict Grouping):**
    * Giả sử môn *"Cấu trúc dữ liệu"* (15 tuần, sáng Thứ Hai 07:30 - 09:30) bị trùng với *"Ca làm thêm"* (15 tuần, sáng Thứ Hai 08:00 - 11:00).
    * Thay vì bắt sinh viên bấm chọn 15 lần cho 15 tuần, thuật toán phát hiện cả hai đều rơi vào `MON` và giờ `[07:30, 09:30]` giao với `[08:00, 11:00]`.
    * Hệ thống gom lại thành **1 Thẻ Xung Đột (Conflict Card)** duy nhất hỏi người dùng:
      * **Lựa chọn 1:** Giữ môn A (*Cấu trúc dữ liệu*), bỏ B (*Ca làm thêm*).
      * **Lựa chọn 2:** Giữ B (*Ca làm thêm*), bỏ A.
      * **Lựa chọn 3:** Giữ cả hai (chấp nhận hiển thị song song trên lịch).
    * Những môn không bị trùng giờ với ai thì đi thẳng, người dùng không cần chạm vào.
* **Bước 2.4 — Bung tuần học và Lưu xuống MySQL (Do Khôi làm trong `services/validator.py`):**
  * Sau khi người dùng chốt phương án cho các Thẻ Xung Đột, hàm `commit_resolved_import` sẽ:
    * Với dòng `kind = CLASS`: Tạo 1 dòng trong bảng `courses`, sau đó chạy vòng lặp từ `first_date` đến `last_date` sinh ra từng buổi học cụ thể vào bảng `events` (chép cả `title` và `room` xuống `events`, gán `is_hard = True`, `source = 'IMPORTED'`, chuyển giờ về UTC bằng `to_db_utc`).
    * Với dòng `kind = EXAM` hoặc `EVENT`: Tạo 1 dòng trong bảng `events`.
    * Với dòng `kind = DEADLINE`: Tạo 1 dòng trong bảng `events` với `start_time = end_time` (thời lượng = 0 phút để không chặn khung giờ khi tìm giờ trống).

---

### Tính năng 3 (P1-5): Hệ thống Search Lịch trình 3 bước & Động cơ Tìm giờ trống (`< 200ms`)
Tính năng này do **P.Nguyên** phụ trách trong `services/search_engine.py` và `routers/search.py`, gồm 2 phần:

#### Phần 3A: Khung Search độc lập (Read-only, tách biệt hoàn toàn với khung Chat xếp lịch)
Khung Search chỉ dùng để tra cứu lịch trình, **không bao giờ tự ý thêm/sửa/xóa sự kiện**. Quy trình chạy qua 3 bước:
1. **Bước 1 — Tối ưu hóa câu truy vấn trước khi tìm (`optimize_search_query`):**
   * Xử lý từ viết tắt, teencode, tiếng Việt không dấu (ví dụ: `"t2".."t7"`, `"cn"`, `"ctdl"` $\rightarrow$ `"Cấu trúc dữ liệu"`, `"gk"` $\rightarrow$ `"giữa kỳ"`, `"ck"` $\rightarrow$ `"cuối kỳ"`, `"dl"` $\rightarrow$ `"deadline"`).
   * Quy đổi các mốc thời gian tương đối dựa trên thời điểm hiện tại (`reference_now`): ví dụ *"ngày mai"*, *"chiều thứ 7 tuần này"*, *"tuần sau"* $\rightarrow$ tính ra cặp mốc `start_from` và `end_until` cụ thể.
2. **Bước 2 — Tìm kiếm cục bộ trong MySQL (`execute_local_search`):**
   * Chỉ truy vấn trên những sự kiện của chính người dùng đó đã tải lên trong MySQL (thông qua hàm `active_events_stmt(owner_id, start_from, end_until)` trong `database.py`).
   * Tuyệt đối không dùng AI sinh tự do ở bước này để đảm bảo **0% ảo giác (Zero Hallucination)**.
3. **Bước 3 — Kiểm chứng và Chuẩn hóa đầu ra (`verify_and_format_search_results`):**
   * Kiểm tra lại một lần nữa xem các bản ghi lấy ra có khớp đúng khoảng thời gian và loại sự kiện (`kind`) mà người dùng hỏi không; loại bỏ mọi kết quả lệch.
   * Đổi giờ từ UTC trong Database sang múi giờ Việt Nam `+07:00` (`from_db_to_vn`) theo chuẩn ISO 8601 để trả về cho giao diện.

#### Phần 3B: Động cơ tìm khung giờ trống (`find_free_slots` dưới 200ms)
* Nhận vào danh sách sự kiện hiện có của sinh viên, khoảng thời gian cần tìm (ví dụ 1 tuần hoặc cả học kỳ) và thời lượng yêu cầu (ví dụ 180 phút).
* Tự động bỏ qua các mục `DEADLINE` (nhờ thuộc tính `event.blocks_availability == False`), trừ giờ ngủ của sinh viên (`23:30 - 06:30`) và cộng khoảng nghỉ giữa giờ (`15 phút`).
* Dùng thuật toán sắp xếp và quét (Sort-and-Sweep $O(N \log N)$) để trả về danh sách các khoảng trống `list[TimeSlot]` đã làm tròn theo bội số 15 phút (`round_up_to_15m`) trong thời gian dưới 200ms.

---

### Tính năng 4 (P1-6): Bộ kiểm thực Ràng buộc cứng (`Zero-Overlap Hard Constraint Validator`)
* Do **Khôi** phụ trách trong `services/validator.py` (hàm `check_hard_conflict`).
* Đóng vai trò là chốt chặn an toàn: Trước khi bất kỳ sự kiện mới nào được thêm vào lịch, hàm này kiểm tra xem khung giờ đề xuất có giao (`TimeSlot.overlaps`) với bất kỳ sự kiện nào mang cờ `is_hard = True` (buổi học chính khóa, lịch thi) đang có trong MySQL hay không. Nếu có giao nhau, lập tức từ chối để bảo đảm 100% không bao giờ xếp lịch đè lên giờ học/giờ thi.

---

## 2. Vai trò của từng File trong `sourceCode/BE/`

* `models.py`: Định nghĩa toàn bộ các kiểu `Enum`, các lớp dữ liệu trung gian trong bộ nhớ (`TimeSlot`, `EventDomain`, `ParsedCsvRow`, `InvalidCsvRow`) và 11 bảng cơ sở dữ liệu SQLAlchemy ORM.
* `database.py`: Thiết lập kết nối MySQL (`get_db`), cung cấp hàm chuyển đổi múi giờ `UTC` $\leftrightarrow$ `+07:00` (`to_db_utc`, `from_db_to_vn`), hàm làm tròn lưới 15 phút và các câu truy vấn lọc sẵn `owner_id` + `deleted_at IS NULL`.
* `main.py`: Điểm khởi chạy máy chủ FastAPI, cấu hình CORS và gắn kết 3 bộ định tuyến (`auth`, `ingestion`, `search`) vào cùng một ứng dụng.
* `services/security.py`: Chứa các hàm lõi về bảo mật gồm băm/kiểm tra mật khẩu bằng `bcrypt`, ký/giải mã chuỗi JWT Token và hàm dependency `get_current_user` để xác thực người dùng hiện hành.
* `services/parser.py`: Chứa thuật toán đọc văn bản thời khóa biểu thô (`.csv`, `.md`, `.txt`), tách các dòng hợp lệ vào `valid_rows`, cách ly các dòng sai cú pháp vào `invalid_rows` và xuất danh sách sạch ra chuỗi CSV chuẩn.
* `services/validator.py`: Chứa thuật toán kiểm tra trùng giờ với lịch cứng (`check_hard_conflict`), gom nhóm các môn trùng lịch thành Thẻ Xung Đột (`detect_import_conflicts`) và bung các tuần học để lưu xuống MySQL (`commit_resolved_import`).
* `services/search_engine.py`: Chứa thuật toán chuẩn hóa câu truy vấn tìm kiếm (teencode, từ viết tắt, ngày tương đối), truy vấn sự kiện cục bộ trong MySQL, kiểm chứng kết quả đầu ra và tìm khung giờ trống dưới `200ms` (`find_free_slots`).
* `routers/auth.py`: Cổng giao tiếp HTTP cho phép ứng dụng phía người dùng gửi yêu cầu Đăng ký (`/api/v1/auth/register`) và Đăng nhập (`/api/v1/auth/login`), gọi sang `services/security.py` để xử lý và trả về JWT Token.
* `routers/ingestion.py`: Cổng điều phối HTTP dẫn dắt quy trình nhập lịch 4 bước (nhận file upload ở `/parse-preview`, nhận kết quả sửa dòng lỗi ở `/resolve-preview`, trả thẻ xung đột ở `/check-conflicts` và lưu chính thức xuống DB ở `/commit`) bằng cách nối `services/parser.py` với `services/validator.py`.
* `routers/search.py`: Cổng giao tiếp HTTP nhận từ khóa tìm kiếm sự kiện (`/api/v1/search/events`) và yêu cầu tìm giờ trống (`/api/v1/search/free-slots`), gọi sang `services/search_engine.py` và trả kết quả JSON về cho giao diện.

---

## 3. Bảng Phân công Nhiệm vụ

| Thành viên | File chịu trách nhiệm chính | Phần việc cụ thể | Điểm giao tiếp với thành viên khác |
| :--- | :--- | :--- | :--- |
| **1. Khôi** | - `services/security.py`<br>- `routers/auth.py`<br>- `services/validator.py`<br>- `routers/ingestion.py` *(nửa sau)* | 1. **P1-3:** Đăng ký, Đăng nhập, JWT, hàm `get_current_user`.<br>2. **P1-6:** Hàm `check_hard_conflict` chặn trùng lịch học cứng.<br>3. **Nửa sau P1-4:** Nhận `list[ParsedCsvRow]`, gom nhóm Thẻ Xung Đột (`detect_import_conflicts`), bung tuần học và lưu vào MySQL (`commit_resolved_import`). | - Cung cấp hàm `get_current_user` cho Lâm và P.Nguyên bảo vệ API.<br>- Nhận `list[ParsedCsvRow]` từ bước Preview của Lâm để kiểm tra Conflict và lưu DB. |
| **2. Lâm** | - `services/parser.py`<br>- `routers/ingestion.py` *(nửa đầu)* | **Nửa đầu P1-4:**<br>1. Đọc file thời khóa biểu (`.csv`, `.md`, `.txt`) ra `ParseBatchResult` (`valid_rows` và `invalid_rows`).<br>2. API tải file xem trước (`parse-preview`) và API xác nhận sửa dòng lỗi (`resolve-preview`), xuất ra `list[ParsedCsvRow]` sạch và chuỗi CSV chuẩn. | Bàn giao danh sách `list[ParsedCsvRow]` sạch cho hàm của Khôi ở bước tiếp theo. (Trong lúc code không cần đợi nhau vì kiểu `ParsedCsvRow` đã có sẵn trong `models.py`). |
| **3. P.Nguyên** | - `main.py`<br>- `services/search_engine.py`<br>- `routers/search.py`<br>- `tests/` *(tích hợp)* | 1. Quản lý `main.py` kết nối toàn bộ router.<br>2. **P1-5A:** Hệ thống Search 3 bước (Tối ưu câu hỏi teencode/ngày tương đối $\rightarrow$ Tìm trong MySQL $\rightarrow$ Kiểm chứng & chuẩn hóa giờ `+07:00`).<br>3. **P1-5B:** Thuật toán `find_free_slots` tìm khung giờ trống `< 200ms`.<br>4. Chủ trì chạy kiểm thử ghép nối tổng thể (Integration Test). | Gọi các dữ liệu sự kiện đã được module của Lâm & Khôi lưu trong MySQL thông qua hàm `active_events_stmt` trong `database.py`. |

---

## 4. Workflow gợi ý cho Phase 1

### Chặng 1 (4 - 5 ngày đầu): Code lõi độc lập & Unit Test riêng
* **Khôi:** Hoàn thành P1-3 (`security.py`, `routers/auth.py`), test đăng ký/đăng nhập và push lên nhánh `main` sớm để 2 bạn có `get_current_user`.
* **Lâm:** Hoàn thành `services/parser.py`, viết test đọc file có cả dòng đúng lẫn dòng sai định dạng giờ.
* **P.Nguyên:** Hoàn thành `services/search_engine.py` (cả hàm tối ưu câu hỏi search, hàm tìm kiếm MySQL và hàm `find_free_slots` < 200ms), viết test độc lập.

### Chặng 2 (4 - 5 ngày tiếp theo): Hoàn thiện Conflict/Merge & Nối các Router API
* **Khôi:** Hoàn thành `services/validator.py` (kiểm tra trùng lịch P1-6, gom nhóm Thẻ Xung Đột và lưu xuống MySQL) + viết 2 API cuối trong `routers/ingestion.py` (`/check-conflicts` và `/commit`). *(Lưu ý: Khôi tạo sẵn vài dòng `ParsedCsvRow` mẫu để tự test mà không cần chờ Lâm).*
* **Lâm:** Hoàn thành 2 API đầu trong `routers/ingestion.py` (`/parse-preview` và `/resolve-preview`).
* **P.Nguyên:** Hoàn thành các API trong `routers/search.py` (`/events` và `/free-slots`) và kiểm tra toàn bộ các route trên giao diện `http://localhost:8000/docs`.

### Chặng 3: Kiểm thử tổng thể

   * Bước 1: Đăng ký & Đăng nhập tài khoản qua API của Khôi $\rightarrow$ lấy JWT Token.
   * Bước 2: Dùng Token tải lên 2 file thời khóa biểu (1 file trường + 1 file làm thêm có dòng lỗi và có môn trùng giờ) qua API Preview của Lâm.
   * Bước 3: Sửa dòng lỗi $\rightarrow$ Gọi API phát hiện Conflict của Khôi $\rightarrow$ Chọn giữ môn học và lưu xuống MySQL.
   * Bước 4: Gọi API Search của P.Nguyên với câu truy vấn có từ viết tắt/teencode $\rightarrow$ Xác nhận kết quả trả về khớp 100% với dữ liệu vừa nạp.

---

## 5. Prompt mẫu cho bước đầu

### 5.1. Prompt dành cho LÂM
```text
Read `AGENTS.md`, `models.py`, `database.py`, `services/parser.py`, and `routers/ingestion.py` in `sourceCode/BE/`.
Do NOT modify `models.py`, `database.py`, or `AGENTS.md`. Target runtime is Python 3.12.10.

Your task is to implement the First Half of P1-4 (Timetable File Parser & Human-in-the-Loop Preview Isolation) in `services/parser.py` and `routers/ingestion.py`, plus unit tests in `tests/test_parser.py`.

1. In `services/parser.py`, implement:
   - `parse_timetable_content(raw_content: str, filename: str = "") -> ParseBatchResult`:
     * Generate a unique `import_batch_id` (e.g., `uuid.uuid4().hex[:16]`).
     * Support parsing standard CSV (`course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`), Markdown tables, and structured text lines.
     * Validate each row against `CsvRowKind` (`CLASS`, `EXAM`, `DEADLINE`, `EVENT`), 24-hour time `HH:MM`, and date `YYYY-MM-DD`.
     * For `DEADLINE`, set `start_time = end_time` if `start_time` is empty, and require `start_time == end_time` and `first_date == last_date`.
     * For `CLASS`, require `weekday` (`Weekday` enum), `start_time < end_time`, and `first_date <= last_date`.
     * For `EXAM` and `EVENT`, require `start_time < end_time` and `first_date == last_date`.
     * Never crash the whole batch on malformed lines: valid lines become `ParsedCsvRow` in `valid_rows`; malformed lines become `InvalidCsvRow(line_number, raw_text, error_code, error_message)` in `invalid_rows`.
   - `export_valid_rows_to_csv(rows: list[ParsedCsvRow]) -> str`:
     * Serialize `list[ParsedCsvRow]` into a UTF-8 CSV string with header `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`.

2. In `routers/ingestion.py`, implement:
   - `POST /api/v1/ingestion/parse-preview`: Accepts an uploaded file or raw text JSON, calls `parse_timetable_content`, and returns `import_batch_id`, `valid_rows`, and `invalid_rows`.
   - `POST /api/v1/ingestion/resolve-preview`: Accepts `import_batch_id`, `valid_rows`, user-corrected rows, and explicitly skipped line numbers; validates and returns the unified `list[ParsedCsvRow]` and exported CSV string ready for conflict detection.

3. Create `tests/test_parser.py` with `pytest` covering valid CSV/Markdown rows for all 4 `CsvRowKind` types and error isolation on malformed rows.
```

### 5.2. Prompt dành cho P.NGUYÊN
```text
Read `AGENTS.md`, `models.py`, `database.py`, `services/search_engine.py`, and `routers/search.py` in `sourceCode/BE/`.
Do NOT modify `models.py`, `database.py`, or `AGENTS.md`. Target runtime is Python 3.12.10.

Your task is to implement P1-5 (3-Step Local Schedule Search Pipeline & <200ms Deterministic Availability Engine) in `services/search_engine.py` and `routers/search.py`, plus unit tests in `tests/test_search_engine.py`.

1. In `services/search_engine.py`, implement:
   - `optimize_search_query(raw_query: str, reference_now: datetime) -> dict`:
     * Enforce `ensure_aware(reference_now)` and convert to `VN_TZ` (`from database import VN_TZ`).
     * Normalize Vietnamese teencode, abbreviations, and non-diacritic terms (`"t2".."t7"`, `"cn"`, `"ctdl"`, `"mmt"`, `"gk"`, `"ck"`, `"dl"`).
     * Resolve relative dates (`"hom nay"`, `"ngay mai"`, `"tuan nay"`, `"tuan sau"`, `"sang"`, `"chieu"`, `"toi"`, `"chieu t7 tuan nay"`) into `start_from` and `end_until`.
     * Return `{"keywords": list[str], "start_from": datetime | None, "end_until": datetime | None, "kind": EventKind | None, "room": str | None, "normalized_query": str}`.
   - `execute_local_search(db: Session, owner_id: int, structured_filters: dict) -> list[EventDomain]`:
     * Strictly query local MySQL using `active_events_stmt(owner_id, start_from, end_until)` from `database.py` (ensuring `owner_id` isolation and `deleted_at IS NULL`). Filter by `kind`, `room`, and keywords, returning `list[EventDomain]`.
   - `verify_and_format_search_results(results: list[EventDomain], structured_filters: dict) -> list[dict]`:
     * Verify every result matches the time window and `kind` constraints, and format `start_time`/`end_time` to `+07:00` ISO 8601 using `from_db_to_vn()`.
   - `find_free_slots(existing_events: list[EventDomain], window_start: datetime, window_end: datetime, duration_minutes: int, ...) -> list[TimeSlot]`:
     * Deterministic $O(N \log N)$ sort-and-sweep availability engine completing 1 semester in `< 200ms`. Ignore events where `event.blocks_availability` is `False` (`DEADLINE`), respect sleep hours and break buffers, and align slots to 15-minute boundaries via `round_up_to_15m`.

2. In `routers/search.py`, implement:
   - `GET /api/v1/search/events`: Runs the 3-step search pipeline and returns verified results.
   - `POST /api/v1/search/free-slots`: Loads active events from MySQL, runs `find_free_slots`, and returns candidate free slots with execution time in milliseconds.

3. Create `tests/test_search_engine.py` with `pytest` testing teencode/relative date normalization, `DEADLINE` non-blocking behavior, and a `< 200ms` benchmark on 300 semester events.
```
