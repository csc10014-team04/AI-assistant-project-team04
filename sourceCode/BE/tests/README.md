# Kiểm thử Module Backend trên MySQL 8.0 (Docker + Savepoint Isolation)

Thư mục `sourceCode/BE/tests/` chứa các bộ kiểm thử cấp module và API của riêng đội ngũ Backend, tách biệt với thư mục `tests/` ở cấp gốc của kho mã nguồn (vốn dùng cho kiểm thử tích hợp toàn hệ thống giữa Frontend, Backend, AI và Database).

Kể từ khi hạ tầng Docker (`assistant_deploy`, container `schedule_db` chạy `mysql:8.0` tại cổng `127.0.0.1:3307`) và công cụ quản trị DBeaver đi vào vận hành, toàn bộ kiểm thử tại `sourceCode/BE/tests/` chạy trực tiếp trên động cơ MySQL 8.0 InnoDB thật kết hợp cơ chế cô lập giao dịch bằng Savepoint (`conftest.py`).

Tài liệu này quy định:
1. **Hướng dẫn sử dụng các Fixture dùng chung trong `conftest.py`:** Cách thức các thành viên Backend khai báo và sử dụng `db_session`, `client` trong hàm test của mình.
2. **Quy chuẩn chú thích và tiêu chí kiểm chứng của từng file:** Chi tiết các kịch bản kiểm thử bắt buộc cho `test_auth.py`, `test_validator.py`, `parser_test.py`, và `test_search_engine.py`.
3. **Cách thức thực thi và chẩn đoán lỗi trong PowerShell:** Các lệnh chạy kiểm thử và cách khắc phục khi gặp lỗi.

---

## 1. Hướng dẫn Sử dụng Fixture Kiểm thử (`conftest.py`)

File `conftest.py` chứa các công cụ dùng chung do `pytest` tự động nạp. Các thành viên khi viết test cho module của mình **không cần khởi tạo kết nối database thủ công**, mà chỉ cần truyền tên fixture vào tham số của hàm test.

### 1.1. Ba Fixture có sẵn và Khi nào cần dùng

| Tên Fixture | Kiểu dữ liệu | Phạm vi (`scope`) | Mục đích & Khi nào sử dụng |
| :--- | :--- | :--- | :--- |
| `mysql_engine` | `sqlalchemy.Engine` | `session` (toàn đợt chạy) | Tự động kết nối cổng `3307`, kiểm tra `SELECT 1` và tạo sẵn 11 bảng. Thường chỉ dùng nội bộ trong `conftest.py`, thành viên ít khi cần gọi trực tiếp. |
| `db_session` | `sqlalchemy.orm.Session` | `function` (từng bài test) | **Dùng khi cần truy vấn, thêm, sửa, xóa dữ liệu MySQL trực tiếp bằng SQLAlchemy ORM.** Mỗi bài test được bọc trong một giao dịch độc lập, tự động rollback khi test xong nên không làm bẩn DBeaver. |
| `client` | `fastapi.testclient.TestClient` | `function` (từng bài test) | **Dùng khi cần giả lập gửi request HTTP (`client.post`, `client.get`) vào các API Router.** `client` này đã được gắn sẵn với `db_session` cô lập ở trên. |

---

### 1.2. Hướng dẫn Cụ thể cho Thành viên Viết Test

#### Trường hợp 1: Hàm test logic thuần (không đụng tới Database hay API)
Không cần truyền bất kỳ fixture nào vào tham số:
```python
def test_password_hashing():
    # kiểm tra hàm băm mật khẩu hoặc thuật toán thuần python
    digest = hash_password("MyPassword123")
    assert verify_password("MyPassword123", digest) is True
```

#### Trường hợp 2: Hàm test cần thao tác trực tiếp với bảng trong MySQL
Khai báo tham số `db_session: Session`:
```python
from sqlalchemy.orm import Session
from models import User

def test_create_user_directly(db_session: Session):
    # tạo và lưu trực tiếp qua ORM
    new_user = User(display_name="Trần Văn A")
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    # kiểm tra dữ liệu đã vào MySQL
    assert new_user.id is not None
    # khi hàm test này kết thúc, giao dịch tự động rollback, dòng trên biến mất khỏi DBeaver
```

#### Trường hợp 3: Hàm test gọi qua đường API HTTP (FastAPI Endpoints)
Khai báo tham số `client: TestClient`:
```python
from fastapi.testclient import TestClient

def test_login_api(client: TestClient):
    # gửi request json qua client
    res = client.post("/api/v1/auth/login", json={"username": "test_user", "password": "123"})
    assert res.status_code in (200, 401)
```

#### Trường hợp 4: Hàm test vừa gọi API vừa cần kiểm tra bảng MySQL
Khai báo cả hai tham số `client: TestClient, db_session: Session`:
```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from models import User

def test_register_and_verify_database(client: TestClient, db_session: Session):
    # 1. Gọi API đăng ký
    res = client.post("/api/v1/auth/register", json={
        "username": "sinhvien_01",
        "password": "Password@123",
        "display_name": "Nguyễn Văn B"
    })
    assert res.status_code == 201
    user_id = res.json()["user_id"]

    # 2. Dùng db_session truy vấn trực tiếp vào MySQL để kiểm tra tính toàn vẹn
    saved_user = db_session.scalar(select(User).where(User.id == user_id))
    assert saved_user is not None
    assert saved_user.display_name == "Nguyễn Văn B"
```

---

### 1.3. Hai Lưu ý Quan trọng khi Chạy Test trên MySQL Thật

1. **Bộ đếm `AUTO_INCREMENT` vẫn tăng:**
   Trong cơ chế của MySQL InnoDB, số tự tăng (`id`) được cấp phát độc lập ở bộ nhớ bảng để tối ưu hiệu năng và không quay lùi khi rollback. Do đó, khi viết câu lệnh `assert`, **luôn so sánh theo biến `saved_user.id` động**, không được gán cứng giả định `assert saved_user.id == 1`.
2. **Cách giữ lại dữ liệu để mở DBeaver xem trực quan:**
   Mặc định sau khi test xong, dữ liệu tự hủy để giữ sạch database. Nếu bạn muốn giữ lại dữ liệu vừa test để bấm F5 trên DBeaver xem tận mắt các dòng được ghi thế nào:
   * Trên PowerShell, gõ: `$env:PERSIST_TEST_DATA="1"` trước khi chạy `pytest`.
   * Xem xong, xóa biến môi trường: `Remove-Item Env:PERSIST_TEST_DATA`.

---

## 2. Quy chuẩn Chú thích và Tiêu chí của Từng File Kiểm thử

Mọi hàm trong các file kiểm thử và module nghiệp vụ tuân thủ cấu trúc docstring tiếng Anh viết thường, ngắn gọn gồm 4 mục cố định:
* `input`: Tham số đầu vào và kiểu dữ liệu.
* `core logic`: Xử lý cốt lõi bên trong hàm.
* `output`: Giá trị trả về hoặc các khẳng định (`assertions`) đầu ra.
* `typical flow`: Luồng thực thi tuần tự trong trường hợp điển hình.

### 2.1. File `test_auth.py` (Khôi phụ trách)
Kiểm thử trực tiếp trên MySQL 8.0 đối với cụm module: **Hạ tầng Cơ sở dữ liệu (`database.py`)** và **Hệ thống Xác thực (`services/security.py`, `routers/auth.py`)**.

**5 kịch bản kiểm chứng:**
1. **An toàn băm mật khẩu (`test_password_hashing_and_verification`):**
   * Cùng một mật khẩu băm 2 lần bằng `bcrypt` phải sinh ra 2 chuỗi digest khác nhau (nhờ muối ngẫu nhiên) và không bao giờ trùng chuỗi gốc.
   * Xác thực đúng mật khẩu trả về `True`, sai mật khẩu trả về `False`, và gặp chuỗi hash hỏng định dạng vẫn trả về `False` an toàn thay vì làm sập tiến trình (`ValueError`).
2. **Vòng đời JWT Token & Chốt chặn `get_current_user` (`test_jwt_lifecycle_and_current_user_guard`):**
   * Lưu bản ghi `User` tiếng Việt có dấu vào MySQL, ký JWT và xác nhận `get_current_user` truy xuất đúng bản ghi từ MySQL.
   * Từ chối bằng mã `HTTP 401` đối với cả 3 trường hợp: token hết hạn (`expires_delta < 0`), token bị sửa chữ ký, và token hợp lệ nhưng `user_id` không tồn tại trong bảng `users`.
3. **Tính nguyên tử 3 bảng khi Đăng ký & Đăng nhập trên MySQL (`test_register_login_and_mysql_three_table_atomicity`):**
   * Gọi `POST /api/v1/auth/register` (mã `201`) tạo đồng bộ cả 3 bảng `users`, `auth_identities` (`provider = PASSWORD`) và `user_preferences` (`sleep_start = 23:30`, `sleep_end = 06:30`, `slot_step_minutes = 15`), bảo toàn tiếng Việt `utf8mb4`.
   * Người dùng tự đặt `username` nguyên bản, hệ thống không tự ý gắn thêm bất kỳ tiền tố nào (`prefix`).
   * Đăng ký trùng `username` trả về `HTTP 409 Conflict`; đăng nhập đúng trả về `HTTP 200`, sai mật khẩu trả về `HTTP 401`.
4. **Đổi username bên trong app & Ràng buộc không trùng lặp (`test_update_username_and_uniqueness`):**
   * Gọi `PATCH /api/v1/auth/username` để đổi username sau khi đã đăng nhập.
   * Đổi sang tên chưa ai dùng thành công (mã `200`); đổi sang tên đã thuộc về tài khoản khác bị chặn ngay bằng mã `HTTP 409 Conflict`.
5. **Chuẩn hóa múi giờ UTC/+07:00, Chống IDOR & Ràng buộc `CHECK` của MySQL 8.0 (`test_mysql_utc_roundtrip_check_constraints_and_owner_isolation`):**
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
