# Kiểm thử Module Backend trên MySQL 8.0 (Docker + Savepoint Isolation)

Thư mục `sourceCode/BE/tests/` chứa các bộ kiểm thử cấp module và API của riêng đội ngũ Backend, tách biệt với thư mục `tests/` ở cấp gốc của kho mã nguồn (vốn dùng cho kiểm thử tích hợp toàn hệ thống giữa Frontend, Backend, AI và Database).

Kể từ khi hạ tầng Docker (`assistant_deploy`, container `schedule_db` chạy `mysql:8.0` tại cổng `127.0.0.1:3307`) và công cụ quản trị DBeaver đi vào vận hành, toàn bộ tư duy kiểm thử tại `sourceCode/BE/tests/` đã chuyển hẳn từ mô phỏng trên RAM (`sqlite:///:memory:`) sang **kiểm thử trực tiếp trên động cơ MySQL 8.0 InnoDB thực tế kết hợp cơ chế cô lập giao dịch bằng Savepoint (`join_transaction_mode="create_savepoint"`)**.

Tài liệu này quy định:
1. **Đối với người chạy kiểm thử và người duyệt mã nguồn (Reviewer):** Kiến trúc vận hành bên dưới khi chạy `pytest` với Docker MySQL và danh mục các cam kết kỹ thuật mà mỗi module chứng minh được sau khi vượt qua bài kiểm thử.
2. **Đối với người viết kiểm thử (Developer):** Bộ tiêu chuẩn bắt buộc về cấu trúc fixture, cách thức cô lập dữ liệu và quy ước chú thích hàm (`input`, `core logic`, `output`, `typical flow`).

---

## 1. Kiến trúc Kiểm thử Mới: Real MySQL 8.0 + Savepoint Rollback (`conftest.py`)

### 1.1. Tại sao bỏ `sqlite:///:memory:` để chạy thẳng trên Docker MySQL `localhost:3307`?
SQLite chạy trên bộ nhớ trong có cú pháp và cơ chế kiểm tra kiểu dữ liệu khác biệt đáng kể so với MySQL 8.0 InnoDB. Khi chuyển sang kết nối trực tiếp vào schema `university_assistant` trên cổng `3307`, bộ kiểm thử xác thực được các hành vi mà SQLite trước đây bỏ lọt:
* Các ràng buộc `CHECK` nguyên bản của MySQL 8.0 trong `init.sql` như `chk_event_priority` (`priority BETWEEN 1 AND 3`), `chk_event_time` (`end_time >= start_time`), `chk_task_duration` (`duration_minutes > 0`).
* Kiểu `ENUM`, khóa ngoại `FOREIGN KEY`, khóa duy nhất `UNIQUE (provider, provider_user_id)` và chỉ mục tổ hợp `idx_event_lookup`.
* Chu trình lưu trữ `DATETIME` ở múi giờ chuẩn `UTC` (không gắn tzinfo trong cột MySQL) và khôi phục chính xác về múi giờ Việt Nam `+07:00` (`VN_TZ`).
* Bảng mã `utf8mb4_unicode_ci` đối với họ tên sinh viên, tên môn học và từ khóa tìm kiếm tiếng Việt có dấu.

### 1.2. Cơ chế Savepoint Isolation giúp DBeaver luôn sạch dữ liệu rác
Nếu các hàm kiểm thử ghi thẳng vào MySQL bằng `db.commit()` thông thường mà không thu hồi:
* Lần chạy `pytest` thứ hai sẽ văng lỗi trùng khóa (`409 Conflict`) hoặc lệch số đếm sự kiện.
* Ngược lại, nếu dùng lệnh xóa trắng bảng (`TRUNCATE` hoặc `DROP TABLE`) sau khi chạy test, toàn bộ dữ liệu mẫu mà thành viên đang nhập thử thủ công trên DBeaver sẽ bị xóa mất.

File `conftest.py` giải quyết triệt để bài toán này bằng 3 fixture dùng chung cho mọi thành viên:
1. `mysql_engine` (`scope="session"`): Tự động đọc cấu hình từ `TEST_DATABASE_URL`, `sourceCode/BE/.env` hoặc `sourceCode/Database/assistant_deploy/.env` để kết nối vào `127.0.0.1:3307/university_assistant`, kiểm tra kết nối sống bằng `SELECT 1` và đảm bảo đủ 11 bảng.
2. `db_session` (`scope="function"`): Trước mỗi hàm `test_*`, fixture mở một giao dịch ngoài (`outer_tx = connection.begin()`) và khởi tạo phiên làm việc với `join_transaction_mode="create_savepoint"`. Mọi lệnh `db.commit()` bên trong API được dịch thành `SAVEPOINT` thật trên MySQL InnoDB (vẫn kiểm tra đủ 100% ràng buộc khóa ngoại, `CHECK`, `UNIQUE`), và ngay khi hàm `test_*` kết thúc, `outer_tx.rollback()` hủy toàn bộ thay đổi của bài test đó trong vài mili-giây mà không chạm tới dữ liệu sẵn có trong DBeaver.
3. `client` (`scope="function"`): Ghi đè dependency `get_db` của FastAPI sang `db_session` để mọi lời gọi HTTP qua `TestClient(app)` đi chung vào đúng phiên giao dịch cô lập của bài test hiện hành.

**Hai lưu ý thực tế khi quan sát trên DBeaver:**
* **Bộ đếm `AUTO_INCREMENT` vẫn tăng:** Trong kiến trúc MySQL InnoDB, giá trị tự tăng (`users.id`, `events.id`) được cấp phát ở tầng bộ nhớ bảng và không quay lùi khi giao dịch rollback. Vì vậy các bài kiểm thử luôn đối chiếu theo biến `user.id` động thay vì gán cứng `id == 1`.
* **Chế độ giữ lại dữ liệu để xem trực quan trên DBeaver (`PERSIST_TEST_DATA=1`):** Khi muốn kiểm tra tận mắt các dòng vừa tạo trong bảng `users`, `courses`, `events` trên giao diện DBeaver, bật biến môi trường `PERSIST_TEST_DATA=1` khi chạy lệnh (xem Mục 3). Các hàm test dùng hậu tố định danh ngẫu nhiên (`_unique_username`) nên không bị đụng độ tên đăng nhập giữa nhiều lần chạy.

---

## 2. Quy chuẩn Chú thích và Tiêu chí của Từng File Kiểm thử

Mọi hàm trong các file kiểm thử và module nghiệp vụ tuân thủ cấu trúc docstring tiếng Anh viết thường, ngắn gọn gồm 4 mục cố định:
* `input`: Tham số đầu vào và kiểu dữ liệu.
* `core logic`: Xử lý cốt lõi bên trong hàm.
* `output`: Giá trị trả về hoặc các khẳng định (`assertions`) đầu ra.
* `typical flow`: Luồng thực thi tuần tự trong trường hợp điển hình.

### 2.1. File `test_auth.py` (Khôi phụ trách)
Kiểm thử trực tiếp trên MySQL 8.0 đối với cụm module: **Hạ tầng Cơ sở dữ liệu (`database.py`)** và **Hệ thống Xác thực (`services/security.py`, `routers/auth.py`)**.

**4 kịch bản kiểm chứng:**
1. **An toàn băm mật khẩu (`test_password_hashing_and_verification`):**
   * Cùng một mật khẩu băm 2 lần bằng `bcrypt` phải sinh ra 2 chuỗi digest khác nhau (nhờ muối ngẫu nhiên) và không bao giờ trùng chuỗi gốc.
   * Xác thực đúng mật khẩu trả về `True`, sai mật khẩu trả về `False`, và gặp chuỗi hash hỏng định dạng vẫn trả về `False` an toàn thay vì làm sập tiến trình (`ValueError`).
2. **Vòng đời JWT Token & Chốt chặn `get_current_user` (`test_jwt_lifecycle_and_current_user_guard`):**
   * Lưu bản ghi `User` tiếng Việt có dấu vào MySQL, ký JWT và xác nhận `get_current_user` truy xuất đúng bản ghi từ MySQL.
   * Từ chối bằng mã `HTTP 401` đối với cả 3 trường hợp: token hết hạn (`expires_delta < 0`), token bị sửa chữ ký, và token hợp lệ nhưng `user_id` không tồn tại trong bảng `users`.
3. **Tính nguyên tử 3 bảng khi Đăng ký & Đăng nhập trên MySQL (`test_register_login_and_mysql_three_table_atomicity`):**
   * Gọi `POST /api/v1/auth/register` (mã `201`) tạo đồng bộ cả 3 bảng `users`, `auth_identities` (`provider = PASSWORD`) và `user_preferences` (`sleep_start = 23:30`, `sleep_end = 06:30`, `slot_step_minutes = 15`), bảo toàn tiếng Việt `utf8mb4`.
   * Đăng ký trùng `username` trả về `HTTP 409 Conflict`; đăng nhập đúng trả về `HTTP 200`, sai mật khẩu trả về `HTTP 401`.
4. **Chuẩn hóa múi giờ UTC/+07:00, Chống IDOR & Ràng buộc `CHECK` của MySQL 8.0 (`test_mysql_utc_roundtrip_check_constraints_and_owner_isolation`):**
   * Sự kiện lúc `07:30 +07:00` được lưu xuống cột `DATETIME` của MySQL thành `00:30` (UTC) và đọc ngược lên khớp đúng `07:30 +07:00`.
   * Hàm `active_events_stmt` cô lập tuyệt đối dữ liệu giữa hai tài khoản (`Sinh Viên A` và `Sinh Viên B`).
   * Ghi thử `priority = 9` vào bảng `events` bị động cơ MySQL 8.0 chặn ngay nhờ ràng buộc `chk_event_priority`.

---

### 2.2. File `test_validator.py` (Khôi phụ trách)
Kiểm thử trực tiếp trên MySQL 8.0 đối với cụm module: **Bộ Kiểm thực Xung đột & Lưu Lịch (`services/validator.py`, nửa sau `routers/ingestion.py`)**.

**3 kịch bản kiểm chứng:**
1. **Chốt chặn Ràng buộc cứng Zero-Overlap (`test_check_hard_conflict_boundary_cases`):**
   * Báo trùng chính xác khi đè lên lịch cứng (`CLASS`, `is_hard = True`).
   * Không báo trùng nhầm khi chạm đúng biên phút kết thúc (`09:30`), khi giao với công việc mềm (`TASK`, `is_hard = False`), hoặc khi giao với hạn nộp bài thời lượng bằng 0 (`DEADLINE`, `blocks_availability = False`).
2. **Gom nhóm Xung đột theo Chuỗi lặp qua API (`test_detect_import_conflicts_series_grouping_and_api`):**
   * Gửi hai môn học kéo dài 15 tuần trùng giờ sáng Thứ Hai vào `POST /api/v1/ingestion/check-conflicts`; hệ thống gom gọn thành đúng 1 `ConflictCard` kèm mô tả khoảng giao `08:30-09:30` và giữ nguyên môn Thứ Tư trong `non_conflicting_rows`.
3. **Bung tuần học & Thay thế Lịch an toàn khi Nạp lại trên MySQL (`test_commit_import_endpoint_and_safe_reimport_on_mysql`):**
   * Gọi `POST /api/v1/ingestion/commit` bung dòng `CLASS` 3 tuần kèm `EXAM` và `DEADLINE` thành 5 bản ghi `events` trả giờ `+07:00`.
   * Khi nạp lại thời khóa biểu mới với `replace_previous_imports = True`, các lịch `IMPORTED` cũ bị đánh dấu xóa mềm (`deleted_at IS NOT NULL`), trong khi sự kiện cá nhân `MANUAL` của sinh viên trong MySQL được bảo toàn 100%.

---

### 2.3. File `parser_test.py` (Lâm phụ trách)
Kiểm thử module **Đọc file Thời khóa biểu Đa định dạng (Văn bản, PDF, Ảnh) & Cách ly Lỗi Xem trước (`services/parser.py`, 2 API đầu của `routers/ingestion.py`)**.

**Các nhóm kịch bản bắt buộc phải bao phủ:**
1. **Đa định dạng văn bản cấu trúc:**
   * Đọc chính xác chuẩn CSV 9 cột, bảng Markdown (`| ... |` kèm dòng phân cách `| --- |`), và dòng phân cách bằng dấu chấm phẩy `;` hoặc phím `Tab`.
2. **Đúng quy tắc nghiệp vụ của 4 loại `CsvRowKind` (`CLASS`, `EXAM`, `EVENT`, `DEADLINE`):**
   * Tự động gán `start_time = end_time` cho `DEADLINE` khi khuyết một đầu mốc giờ; bắt lỗi chéo giữa `weekday`, khoảng giờ và khoảng ngày.
3. **Đọc tệp `.pdf` và Ảnh thời khóa biểu (`.png`, `.jpg`, `.jpeg`, `.webp`):**
   * Trích xuất bảng lịch học từ tệp PDF văn bản hoặc ảnh chụp màn hình cổng thông tin đào tạo về đúng lược đồ `ParseBatchResult` (`valid_rows` và `invalid_rows`).
4. **Kiểm soát chặt các trường hợp biên phi thời khóa biểu (Edge Cases trên PDF/Ảnh):**
   * **Tệp sai định dạng hoặc giả mạo phần mở rộng:** Đổi tên tệp `.exe` hoặc chuỗi byte ngẫu nhiên thành `.png`/`.pdf` phải bị chặn bằng mã lỗi `HTTP 415 Unsupported Media Type` hoặc `HTTP 400` mà không làm sập máy chủ.
   * **Ảnh không chứa thời khóa biểu (ví dụ: ảnh chụp mèo, ảnh phong cảnh, ảnh trắng trơn, ảnh chụp hóa đơn):** Bộ lọc kiểm tra cấu trúc sau nhận dạng chữ (OCR Structural Gate) phát hiện không có tổ hợp mỏ neo thời khóa biểu (cặp khung giờ `HH:MM`/tiết học đi kèm thứ trong tuần hoặc ngày tháng) và trả về phản hồi từ chối tường minh (`HTTP 422` kèm mã lỗi `NO_TIMETABLE_DETECTED`), tuyệt đối không bịa ra dòng lịch ảo hay lưu rác xuống bảng tạm.
   * **Ảnh bị mờ/nhiễu cục bộ một vài dòng:** Các dòng đọc rõ vẫn vào `valid_rows`, các dòng bị nhòe mất giờ học được đẩy vào `invalid_rows` để sinh viên sửa trên màn hình Preview.
5. **Luồng API `/parse-preview` -> `/resolve-preview`:**
   * Xác thực người dùng qua `client` (kèm Bearer Token từ MySQL), sửa dòng lỗi thành hợp lệ, chặn dòng sửa vẫn sai bằng `HTTP 422`, và loại bỏ dòng nằm trong `skipped_line_numbers`.

---

### 2.4. File `test_search_engine.py` (P.Nguyên phụ trách)
Kiểm thử trực tiếp trên MySQL 8.0 đối với module **Tìm kiếm Lịch trình Cục bộ 3 Bước & Động cơ Tìm Khung giờ trống `< 200ms` (`services/search_engine.py`, `routers/search.py`)**, sử dụng `db_session` và `client` từ `conftest.py`.

**Các nhóm kịch bản bắt buộc phải bao phủ:**
1. **Chuẩn hóa truy vấn ngôn ngữ tự nhiên & Thời gian tương đối (`optimize_search_query`):**
   * Ánh xạ từ viết tắt, không dấu và teencode (`"ctdl"`, `"mmt"`, `"gk"`, `"ck"`, `"dl"`, `"t2".."t7"`, `"cn"`).
   * Quy đổi mốc thời gian tương đối (*"hôm nay"*, *"ngày mai"*, *"chiều thứ 7 tuần này"*, *"tuần sau"*) dựa trên `reference_now` thành khoảng `[start_from, end_until]` gắn múi giờ `+07:00`.
2. **Truy vấn cục bộ trên MySQL `utf8mb4` & Chống lộ dữ liệu chéo (`execute_local_search` & `verify_and_format_search_results`):**
   * Lưu dữ liệu thật vào bảng `events` qua `db_session`; xác nhận truy vấn tiếng Việt tìm đúng bản ghi thuộc `owner_id` hiện tại, bỏ qua các sự kiện đã xóa mềm (`deleted_at IS NOT NULL`) và không bao giờ trả về lịch của sinh viên khác.
   * Mọi mốc thời gian trả ra JSON mang chuẩn ISO 8601 ở múi giờ `+07:00`, cam kết 0% ảo giác do không dùng mô hình sinh tự do để trả lời trực tiếp dữ liệu lịch.
3. **Độ chính xác và Hiệu năng `< 200ms` của `find_free_slots`:**
   * Trừ đúng các khoảng bận (`CLASS`, `EXAM`, `EVENT`, `TASK`), trừ khung giờ ngủ (`UserPreference.sleep_start` tới `sleep_end`), trừ danh sách các khung giờ người dùng đã từ chối trong phiên xếp lịch (`excluded_slots`), và cộng đúng khoảng nghỉ chuyển tiếp (`min_break_minutes = 15`).
   * Không bị chặn bởi `DEADLINE` (thời lượng bằng 0, `blocks_availability = False`), làm tròn giờ bắt đầu lên lưới 15 phút (`:00`, `:15`, `:30`, `:45`).
   * **Đo kiểm hiệu năng:** Trên tập 300 sự kiện của cả học kỳ 15 tuần truy vấn từ MySQL, thời gian tính toán của `find_free_slots` bắt buộc nhỏ hơn `200ms`.

---

## 3. Cách Chạy Kiểm thử trong PowerShell

### Bước 0: Đảm bảo container MySQL đang chạy
Kiểm tra trên Docker Desktop thấy stack `assistant_deploy` (container `schedule_db` gắn cổng `3307`) đang ở trạng thái xanh (`Running`). Nếu chưa bật, chạy:
```powershell
Set-Location "sourceCode/Database/assistant_deploy"
docker compose up -d db
```

### Bước 1: Chạy kiểm thử ở chế độ chuẩn (Tự động Rollback, giữ sạch DBeaver)
Mở PowerShell tại thư mục `sourceCode/BE/` và chạy:
```powershell
Set-Location "sourceCode/BE"

# 1. Chạy toàn bộ các bài kiểm thử trong sourceCode/BE/tests/
python -m pytest tests/ -v

# 2. Chạy riêng kiểm thử Auth & Security
python -m pytest tests/test_auth.py -v

# 3. Chạy riêng kiểm thử Validator & Xung đột lịch
python -m pytest tests/test_validator.py -v

# 4. Lọc riêng một nhóm kịch bản bằng cờ -k
python -m pytest tests/test_auth.py -k "register_login or mysql_utc" -v

# 5. Chạy riêng file kiểm thử Parser (của Lâm) hoặc Search Engine (của P.Nguyên)
python -m pytest tests/parser_test.py -v
python -m pytest tests/test_search_engine.py -v
```

### Bước 2 (Tùy chọn): Chạy kiểm thử và giữ lại dữ liệu để quan sát trên DBeaver
Nếu muốn các dòng dữ liệu tạo ra trong lúc test được lưu thật xuống ổ cứng để bấm Refresh (F5) xem trực tiếp trên DBeaver:
```powershell
$env:PERSIST_TEST_DATA="1"
python -m pytest tests/test_auth.py tests/test_validator.py -v
Remove-Item Env:PERSIST_TEST_DATA
```

---

## 4. Chẩn đoán Kết quả Thực thi

### Trường hợp 1: `PASSED`
* Toàn bộ hàm nghiệp vụ, ràng buộc MySQL 8.0 InnoDB và API endpoint khớp 100% với các câu lệnh `assert`, đồng thời giao dịch thử nghiệm đã được rollback sạch sẽ. Module đạt chuẩn để tạo Pull Request hoặc đẩy lên nhánh chung.

### Trường hợp 2: `FAILED` (Sai lệch logic nghiệp vụ)
* Mã nguồn chạy không văng lỗi hệ thống nhưng giá trị trả về khác kỳ vọng (ví dụ `assert 200 == 409` hoặc sai lệch múi giờ). Xem số dòng báo lỗi trong `tests/test_*.py` để đối chiếu lại điều kiện xử lý tại `services/` hoặc `routers/`.

### Trường hợp 3: `ERROR` hoặc `Failed: cannot connect to docker mysql` (Lỗi môi trường / kết nối)
1. **Không kết nối được MySQL (`OperationalError: (2003, "Can't connect to MySQL server on '127.0.0.1'"`):**
   * Container `schedule_db` chưa bật hoặc cổng `3307` chưa sẵn sàng. Mở Docker Desktop khởi động lại `assistant_deploy`.
2. **Sai thông tin đăng nhập DB (`OperationalError: (1045, "Access denied for user ..."`):**
   * Kiểm tra thông số `DB_USER` và `DB_PASSWORD` trong `sourceCode/Database/assistant_deploy/.env` (hoặc biến `DATABASE_URL` trong `sourceCode/BE/.env` nếu có tạo riêng) xem có khớp với thông số bạn đã dùng để kết nối thành công trên DBeaver hay không.
3. **Thiếu gói thư viện Python (`ModuleNotFoundError` hoặc thiếu `cryptography` khi nối MySQL 8.0):**
   * MySQL 8.0 sử dụng cơ chế xác thực `caching_sha2_password` nên `pymysql` bắt buộc cần gói `cryptography`. Chạy lệnh cài đặt đầy đủ:
     `python -m pip install fastapi uvicorn sqlalchemy pymysql cryptography bcrypt pyjwt python-multipart pytest httpx`

### Trường hợp 4: `DESELECTED` / `SKIPPED`
* Xuất hiện khi dùng cờ `-k` để chỉ lọc chạy một vài hàm kiểm thử đang cần gỡ lỗi nhanh; các hàm còn lại được tạm bỏ qua theo đúng chủ đích của người chạy.
