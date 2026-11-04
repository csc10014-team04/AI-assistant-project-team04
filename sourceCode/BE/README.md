# Tài liệu Kỹ thuật & Phân công — Team Backend (BE)

Tài liệu này là hướng dẫn trung tâm cho 3 thành viên Team Backend (**Khôi, Lâm, P.Nguyên**). Mọi thành viên đọc kỹ tài liệu này để nắm rõ **bức tranh tổng thể của hệ thống**, **chi tiết nghiệp vụ của từng tính năng**, **điểm nối giữa code của 3 người**, và **quy trình kiểm thử trên Docker MySQL 8.0**.

---

## 1. Cài đặt môi trường & Các File dùng chung (Bắt buộc đọc trước khi code)

### 1.1. Lấy code về máy, bật MySQL Docker và khởi tạo môi trường (Python `3.12.10`)
Mỗi thành viên mở Terminal (PowerShell) và chạy các lệnh sau:

```powershell
# 1. Clone repo (nếu chưa có) và bật container MySQL 8.0 trên cổng 3307
git clone https://github.com/csc10014-team04/AI-assistant-project-team04.git
cd AI-assistant-project-team04/sourceCode/Database/assistant_deploy
docker compose up -d db

# 2. Di chuyển vào thư mục BE, tạo môi trường ảo với Python 3.12.10 và kích hoạt
cd ../../BE
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Cài đặt các thư viện cần thiết
pip install fastapi uvicorn sqlalchemy pymysql cryptography bcrypt pyjwt python-multipart pytest httpx
```

### 1.2. Cấu trúc thư mục `sourceCode/BE/` và Quy tắc File Khóa cứng
```text
sourceCode/BE/
├── AGENTS.md                        # [KHÓA CỨNG] Luật kiến trúc chung cho toàn bộ Backend
├── models.py                        # [KHÓA CỨNG] Toàn bộ Enum, Dataclass và 11 bảng SQLAlchemy ORM
├── database.py                      # [KHÓA CỨNG] Kết nối Docker MySQL (3307), đổi múi giờ UTC/+07:00, query an toàn
├── main.py                          # Điểm khởi chạy FastAPI Server (gắn các router vào app)
├── routers/                         # Tầng API nhận HTTP Request từ Frontend và trả JSON
│   ├── auth.py                      # (Khôi) API Đăng ký, Đăng nhập
│   ├── ingestion.py                 # (Lâm + Khôi) API Upload file, Xem trước, Giải quyết trùng giờ & Lưu DB
│   └── search.py                    # (P.Nguyên) API Tìm kiếm lịch trình & Tìm khung giờ trống
├── services/                        # Tầng xử lý thuật toán và nghiệp vụ (tách biệt với HTTP)
│   ├── security.py                  # (Khôi) Băm mật khẩu bcrypt, tạo/kiểm tra JWT Token, get_current_user
│   ├── parser.py                    # (Lâm) Đọc file thời khóa biểu (.csv/.md/.pdf/ảnh), lọc edge cases & cách ly lỗi
│   ├── validator.py                 # (Khôi) Kiểm tra trùng lịch cứng, gom nhóm Conflict & Lưu xuống MySQL
│   └── search_engine.py             # (P.Nguyên) Chuẩn hóa câu search, tìm kiếm MySQL & Tìm slot trống <200ms
└── tests/                           # Kiểm thử cấp module/API chạy trực tiếp trên Docker MySQL 8.0 (port 3307)
    ├── README.md                    # Hướng dẫn kiến trúc kiểm thử Savepoint Isolation & tiêu chuẩn viết test
    ├── conftest.py                  # Fixture dùng chung nối MySQL 3307 và tự động rollback sau mỗi hàm test
    └── test_auth_and_validator.py   # Bộ kiểm thử MySQL cho Auth, Security, Timezone/CHECK và Validator
```

> **Lưu ý về Kiểm thử:**
> * **`sourceCode/BE/tests/` (nằm bên trong thư mục `BE`):** Kiểm thử độc lập từng cụm module của từng thành viên (`auth` & `validator`, `parser`, `search_engine`) **trực tiếp trên container MySQL 8.0 (`localhost:3307`, schema `university_assistant`)** thông qua cơ chế cô lập giao dịch `create_savepoint` trong `conftest.py` (kiểm tra đủ mọi ràng buộc thật của MySQL InnoDB nhưng tự động rollback để không làm bẩn dữ liệu trên DBeaver). **Mọi thành viên bắt buộc đọc `sourceCode/BE/tests/README.md` trước khi viết và chạy test.**
> * **`tests/` (nằm ở cấp gốc của repo, cùng cấp với `sourceCode/`):** Dành cho kiểm thử tích hợp toàn hệ thống (End-to-End Integration Tests) do thành viên phụ trách QA tổng thể đảm nhiệm sau khi ghép nối các phân hệ.

> **NGUYÊN TẮC BẤT BIẾN:** Ba file `models.py`, `database.py` và `AGENTS.md` là hợp đồng chung của cả nhóm. **Không ai được tự ý sửa hoặc định nghĩa lại các class/enum đã có trong `models.py`**. Mọi file code đều phải `from models import ...` và `from database import ...`.
