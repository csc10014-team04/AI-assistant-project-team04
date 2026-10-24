# Kiểm thử BE

Thư mục `sourceCode/BE/tests/` chứa các module tests và unit tests của riêng team BE, khác với thư mục `tests/` ở cấp gốc của repo (dùng để kiểm thử toàn hệ thống)

Cho đến hiện tại (24/10) các file test trong thư mục này chỉ chạy trên bộ nhớ RAM (sử dụng SQLite In-Memory `sqlite:///:memory:` và `TestClient` của FastAPI), các kịch bản test được viết để kiểm độc lập từng file, không cần chờ các thành viên khác code xong và không cần bật máy chủ MySQL cục bộ.

Tài liệu cho biết:
1. **Đối với người chạy test / người duyệt code (Reviewer):** Những vấn đề một file code (module) giải quyết được sau khi chạy file test tương ứng.
2. **Đối với người viết test (Developer & AI Assistant):** Là bộ tiêu chuẩn bắt buộc để thiết kế các hàm `<>_test` sao cho sau khi chạy xong, người đọc có đủ cơ sở khẳng định module đạt chuẩn.

---

## 1. Cấu trúc các file test & những gì cần nắm sau khi chạy

### 1.1. File `test_auth_and_validator.py`
Kiểm thử độc lập 2 cụm module: **Hệ thống Xác thực (`services/security.py`, `routers/auth.py`)** và **Bộ Kiểm tra Xung đột & Lưu Lịch (`services/validator.py`, nửa sau `routers/ingestion.py`)**.

**Những gì bạn biết chắc chắn sau khi chạy file test này (và cũng là tiêu chí bắt buộc khi viết file test này):**
1. **An toàn mật khẩu (`test_password_hashing_and_verification`):**
   * Mật khẩu gốc không bao giờ bị lưu dạng chữ thường (plaintext); chuỗi băm `bcrypt` sinh ra luôn khác chuỗi gốc.
   * Hàm kiểm tra mật khẩu trả về `True` khi đúng mật khẩu, trả về `False` khi sai mật khẩu, và không bị văng lỗi sập chương trình (`ValueError`) nếu gặp chuỗi hash hỏng định dạng.
2. **Chuẩn xác của JWT Token & Chốt chặn `get_current_user` (`test_jwt_create_and_decode`):**
   * Token sinh ra giải mã đúng `user_id` của người đăng nhập; hàm dependency `get_current_user` truy xuất đúng bản ghi `User` từ cơ sở dữ liệu.
   * Token đã hết hạn (`expires_delta < 0`) hoặc Token bị sửa đổi/sai định dạng lập tức bị chặn lại với mã lỗi `HTTP 401 Unauthorized`.
3. **Tính nguyên tử khi Đăng ký & Bảo mật Đăng nhập (`test_register_and_login_endpoints`):**
   * Khi gọi `POST /api/v1/auth/register` thành công (mã `201`), cả **3 bảng** (`users`, `auth_identities`, và `user_preferences` với `slot_step_minutes = 15`) đều được tạo đồng bộ trong cùng một giao dịch.
   * Đăng ký trùng `username` đã tồn tại bị chặn ngay bằng mã `HTTP 409 Conflict`.
   * Đăng nhập đúng tại `POST /api/v1/auth/login` trả về mã `200` kèm Bearer Token; đăng nhập sai mật khẩu bị chặn bằng mã `HTTP 401`.
4. **Chốt chặn Ràng buộc cứng Zero-Overlap (`test_check_hard_conflict`):**
   * Phát hiện chính xác khi một khung giờ dự kiến đè lên sự kiện cứng (`CLASS`, `EXAM` có `is_hard = True`).
   * **Không báo trùng nhầm** trong 3 trường hợp biên: (a) giao với sự kiện mềm (`TASK` có `is_hard = False`), (b) giao với hạn chót `DEADLINE` (vì `DEADLINE` có thời lượng bằng 0 và `blocks_availability = False`), và (c) hai khung giờ chỉ chạm mép nhau (`end_time` của ca trước bằng đúng `start_time` của ca sau).
5. **Gom nhóm Xung đột theo Chuỗi lặp (`test_detect_import_conflicts_series_grouping`):**
   * Khi hai môn học 15 tuần trùng giờ nhau vào cùng một thứ trong tuần, thuật toán không sinh ra 15 cảnh báo rời rạc mà gom thành đúng **1 Thẻ Xung Đột (`ConflictCard`)** duy nhất, đồng thời tách riêng các môn không trùng vào `non_conflicting_rows`.
6. **Bung tuần học & Thay thế Lịch an toàn khi Import lại (`test_commit_resolved_import_and_safe_reimport`):**
   * Một dòng `CLASS` kéo dài nhiều tuần được bung chính xác thành từng buổi học cụ thể trong bảng `events` kèm bản ghi môn học trong bảng `courses`.
   * Khi người dùng chọn nạp lại thời khóa biểu mới (`replace_previous_imports = True`), chỉ các lịch cũ có nguồn `IMPORTED` mới bị đánh dấu xóa mềm (`deleted_at IS NOT NULL`, `replaced_by_batch_id`), còn các công việc cá nhân (`TASK`, `MANUAL`) của sinh viên được giữ nguyên 100%.

---

### 1.2. File `test_parser.py`
Kiểm thử độc lập module **Đọc file Thời khóa biểu & Xem trước Cách ly Lỗi (`services/parser.py`, 2 API đầu của `routers/ingestion.py`)**.

**Những gì người viết test phải thiết kế và người chạy test sẽ nắm được sau khi chạy:**
1. **Đa định dạng đầu vào (Multi-format Parsing):**
   * Đọc chính xác cả 3 định dạng phổ biến: chuẩn CSV 9 cột (có hoặc không có dòng tiêu đề), bảng Markdown (`| ... |` kèm dòng kẻ ngang `| --- |`), và dòng phân cách bằng dấu chấm phẩy `;` hoặc phím `Tab`.
2. **Đúng quy tắc nghiệp vụ của cả 4 loại `CsvRowKind`:**
   * `CLASS`: Bắt buộc có `weekday` (`MON`..`SUN`), `start_time < end_time`, `first_date <= last_date`.
   * `EXAM` & `EVENT`: Diễn ra trong 1 ngày duy nhất (`first_date == last_date`), `start_time < end_time`.
   * `DEADLINE`: Nếu cột `start_time` để trống thì tự động gán `start_time = end_time`; đảm bảo thời lượng bằng 0 (`start_time == end_time`) và `first_date == last_date`.
3. **Cơ chế Cách ly Lỗi (Error Isolation — Không bao giờ sập cả file):**
   * Khi một file có trộn lẫn dòng đúng và dòng lỗi (thiếu cột, sai định dạng giờ `25:99`, sai ngày `2026-13-45`, `start_time > end_time`), hàm `parse_timetable_content` tuyệt đối không văng Exception làm dừng chương trình.
   * Các dòng đúng được đưa đủ vào `valid_rows`; các dòng sai được gom vào `invalid_rows` với đúng số thứ tự dòng (`line_number`), chữ gốc (`raw_text`) và mã lỗi (`error_code`).
4. **Luồng API Xem trước & Sửa lỗi (`/parse-preview` $\rightarrow$ `/resolve-preview`):**
   * Người dùng sửa lại dòng lỗi thành hợp lệ $\rightarrow$ dòng đó được chấp nhận và gộp vào `all_valid_rows`.
   * Người dùng sửa dòng lỗi nhưng vẫn nhập sai định dạng giờ $\rightarrow$ API `/resolve-preview` trả về mã `HTTP 422` chỉ rõ dòng nào vẫn còn sai.
   * Người dùng đánh dấu bỏ qua dòng ghi chú rác (`skipped_line_numbers`) $\rightarrow$ dòng đó bị loại bỏ hoàn toàn khỏi danh sách xuất ra.

---

### 1.3. File `test_search_engine.py`
Kiểm thử độc lập module **Tìm kiếm Lịch trình Cục bộ 3 Bước & Động cơ Tìm Giờ trống `< 200ms` (`services/search_engine.py`, `routers/search.py`)**.

**Những gì người viết test phải thiết kế và người chạy test sẽ nắm được sau khi chạy:**
1. **Chuẩn hóa ngôn ngữ tự nhiên & Thời gian tương đối (Bước 1 — `optimize_search_query`):**
   * Dịch đúng các từ viết tắt, teencode và tiếng Việt không dấu (`"ctdl"`, `"mmt"`, `"gk"`, `"ck"`, `"dl"`, `"t2".."t7"`, `"cn"`).
   * Tính toán chính xác các cụm từ thời gian tương đối (*"hôm nay"*, *"ngày mai"*, *"chiều thứ 7 tuần này"*, *"tuần sau"*) thành cặp mốc `(start_from, end_until)` có gắn múi giờ Việt Nam `+07:00` (`VN_TZ`).
2. **Cô lập dữ liệu người dùng & Chống ảo giác 100% (Bước 2 & 3 — `execute_local_search` & `verify_and_format_search_results`):**
   * Chỉ trả về sự kiện thuộc đúng `owner_id` của người đang tìm kiếm và chưa bị xóa mềm (`deleted_at IS NULL`).
   * Sự kiện của tài khoản khác hoặc sự kiện nằm ngoài khung giờ hỏi tuyệt đối không bao giờ lọt vào kết quả.
   * Mọi mốc thời gian trả ra JSON đều mang định dạng ISO 8601 ở múi giờ `+07:00`.
3. **Độ chính xác và Hiệu năng `< 200ms` của Thuật toán Tìm Giờ trống (`find_free_slots`):**
   * Trừ đúng các khoảng giờ bận (`CLASS`, `EXAM`, `EVENT`, `TASK`), trừ đúng khung giờ ngủ của sinh viên (`23:30 - 06:30`) và cộng đúng thời gian nghỉ chuyển tiếp (`break_minutes = 15`).
   * **Không bị chặn bởi `DEADLINE`** (vì `DEADLINE` có thời lượng bằng 0).
   * Mọi khung giờ trống trả về đều có giờ bắt đầu chẵn theo lưới 15 phút (`:00`, `:15`, `:30`, `:45`).
   * **Kiểm chứng hiệu năng (Performance Benchmark):** Khi chạy trên tập dữ liệu 300 sự kiện của cả một học kỳ (15 tuần), tổng thời gian thực thi của `find_free_slots` bắt buộc nhỏ hơn `200ms`.

---

## 2. Cách Chạy Kiểm thử trong Terminal

Mở PowerShell, di chuyển vào thư mục `sourceCode/BE/` và sử dụng các lệnh sau:

```powershell
Set-Location "sourceCode/BE"

# 1. Chạy toàn bộ tất cả các file test đang có trong sourceCode/BE/tests/
python -m pytest tests/ -v

# 2. Chạy riêng file kiểm thử Auth & Validator
python -m pytest tests/test_auth_and_validator.py -v

# 3. Chạy lọc riêng 1 cụm chức năng bên trong file bằng cờ -k (ví dụ chỉ test đăng ký/đăng nhập/JWT)
python -m pytest tests/test_auth_and_validator.py -k "password or jwt or register_and_login" -v

# 4. Chạy riêng file kiểm thử Parser (khi hoàn thiện)
python -m pytest tests/test_parser.py -v

# 5. Chạy riêng file kiểm thử Search Engine (khi hoàn thiện)
python -m pytest tests/test_search_engine.py -v
```

---

## 3. Các Kết quả Có thể Xảy ra (Possible Outcomes) & Ý nghĩa Chẩn đoán

Khi thực thi lệnh `python -m pytest ...`, màn hình Terminal sẽ trả về một trong các trạng thái sau. Việc hiểu rõ bản chất từng trạng thái giúp bạn biết ngay code đang đạt chuẩn hay đang gặp vấn đề ở tầng nào:

### Trường hợp 1: `PASSED` (Màu xanh lá)
* **Hiển thị trên màn hình:**
  ```text
  tests/test_auth_and_validator.py::test_password_hashing_and_verification PASSED [ 16%]
  ...
  ============================== 6 passed in 2.40s ==============================
  ```
* **Điều này cho biết gì?**
  * Toàn bộ các hàm nghiệp vụ và API endpoint trong bài test đó đã nhận đầu vào, xử lý logic, tương tác với cơ sở dữ liệu SQLite trên RAM và trả về kết quả khớp 100% với mọi câu lệnh kiểm chứng (`assert`).
  * Module của bạn đã đủ điều kiện an toàn để commit và push lên nhánh chung mà không sợ làm hỏng phần việc của các thành viên khác.

---

### Trường hợp 2: `FAILED` (Màu đỏ — Lỗi sai lệch Logic hoặc Kết quả đầu ra)
* **Hiển thị trên màn hình:**
  `pytest` sẽ đánh dấu `FAILED` cạnh tên hàm test, đồng thời in ra đoạn code bị sai kèm ký hiệu `>` (dòng lệnh đang chạy) và chữ `E` (Error — giá trị thực tế bị lệch so với giá trị kỳ vọng):
  ```text
  >       assert dup_res.status_code == 409
  E        assert 201 == 409
  ```
* **Điều này cho biết gì?**
  * Code Python của bạn **không bị lỗi cú pháp và vẫn chạy được**, nhưng **kết quả trả về bị sai so với thiết kế kỹ thuật**.
  * *Ví dụ với dòng `assert 201 == 409` ở trên:* Bài test mong đợi khi đăng ký trùng tên tài khoản thì API phải chặn lại và trả về mã lỗi `409 Conflict`, nhưng code của bạn lại vẫn cho tạo tài khoản mới và trả về `201 Created`.
* **Cách xử lý:** Nhìn vào số dòng báo lỗi trong file test để biết điều kiện nào bị vi phạm, sau đó mở file trong `services/` hoặc `routers/` tương ứng để sửa lại câu lệnh `if` hoặc điều kiện lọc truy vấn.

---

### Trường hợp 3: `ERROR` (Màu đỏ — Lỗi Môi trường, Thiếu Thư viện hoặc Sai Đường dẫn Import)
* **Hiển thị trên màn hình:**
  Xuất hiện thông báo `ERROR collecting tests/...` hoặc `ERROR at setup of test_...` ngay trước khi bài test kịp chạy vào bên trong hàm `test_*`.
* **Điều này cho biết gì?**
  Lỗi này **không phải do thuật toán của bạn tính sai**, mà do môi trường chạy hoặc cấu trúc ghép file bị thiếu thành phần. Các nguyên nhân phổ biến nhất gồm:
  1. **`ModuleNotFoundError: No module named '...'` hoặc `RuntimeError: Form data requires "python-multipart" to be installed`:**
     * *Ý nghĩa:* Máy tính của bạn đang thiếu một thư viện cài qua `pip` (ví dụ FastAPI cần gói `python-multipart` để đọc `UploadFile`/`Form` trong `routers/ingestion.py`, hoặc `TestClient` cần gói `httpx`).
     * *Cách khắc phục:* Chạy lệnh `python -m pip install fastapi uvicorn sqlalchemy pymysql cryptography bcrypt pyjwt python-multipart pytest httpx`.
  2. **`ImportError: cannot import name '...' from 'services...'`:**
     * *Ý nghĩa:* Tên hàm viết trong file `services/` hoặc `routers/` bị đặt lệch tên so với tên hàm chuẩn được quy định trong hợp đồng thiết kế (ví dụ đề bài yêu cầu hàm tên `parse_timetable_content` nhưng trong code lại đặt tên là `parse_file`).
     * *Cách khắc phục:* Đổi lại tên hàm và tên tham số khớp 100% với đặc tả trong `BE_team_task_description.md`.
  3. **`ModuleNotFoundError: No module named 'models'`:**
     * *Ý nghĩa:* Bạn đang đứng sai thư mục khi gõ lệnh `pytest` (ví dụ đang đứng ở thư mục gốc của repo thay vì đứng trong `sourceCode/BE/`).
     * *Cách khắc phục:* Chạy `cd sourceCode/BE` trước khi gõ `python -m pytest`.

---

### Trường hợp 4: `DESELECTED` / `SKIPPED` (Màu vàng)
* **Hiển thị trên màn hình:**
  `======================= 3 passed, 3 deselected in 2.33s =======================`
* **Điều này cho biết gì?**
  * Khi bạn dùng cờ `-k` (ví dụ `-k "password or jwt"`), `pytest` tự động chọn ra các bài test có tên khớp với từ khóa để chạy (`3 passed`) và tạm bỏ qua các bài test không khớp (`3 deselected`). Đây là hành vi bình thường giúp bạn kiểm tra nhanh đúng phần mình đang sửa.