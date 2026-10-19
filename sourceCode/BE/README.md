# Tài liệu Kỹ thuật & Phân công Phase 1 — Team Backend (BE)

Tài liệu này là hướng dẫn trung tâm cho 3 thành viên Team Backend (**Khôi, Lâm, P.Nguyên**). Mọi thành viên đọc kỹ tài liệu này để nắm rõ **bức tranh tổng thể của cả hệ thống**, **chi tiết nghiệp vụ của từng tính năng**, **điểm nối giữa code của 3 người**, và **quy trình làm việc theo từng chặng**.

---

## 1. Cài đặt môi trường & Các File dùng chung (Bắt buộc đọc trước khi code)

### 1.1. Lấy code về máy và khởi tạo môi trường (Python `3.12.10`)
Mỗi thành viên mở Terminal (PowerShell) và chạy đúng các lệnh sau:

```powershell
# 1. Clone repo (nếu chưa có) và di chuyển vào thư mục BE
git clone https://github.com/csc10014-team04/AI-assistant-project-team04.git
cd AI-assistant-project-team04/sourceCode/BE
git pull origin main

# 2. Tạo môi trường ảo với Python 3.12.10 và kích hoạt
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Cài đặt các thư viện cần thiết cho Phase 1
pip install fastapi uvicorn sqlalchemy pymysql cryptography bcrypt pyjwt python-multipart pytest httpx
```

### 1.2. Cấu trúc thư mục `sourceCode/BE/` và Quy tắc File Khóa cứng
```text
sourceCode/BE/
├── AGENTS.md                # [KHÓA CỨNG] Luật kiến trúc cho AI tự động đọc khi vibe code
├── models.py                # [KHÓA CỨNG] Toàn bộ Enum, Dataclass và bảng SQLAlchemy ORM
├── database.py              # [KHÓA CỨNG] Kết nối MySQL, đổi múi giờ UTC/+07:00, hàm query an toàn
├── main.py                  # Điểm khởi chạy FastAPI Server (gắn 3 router vào app)
├── routers/                 # Tầng API nhận HTTP Request từ ứng dụng Android và trả JSON
│   ├── auth.py              # (Khôi) API Đăng ký, Đăng nhập
│   ├── ingestion.py         # (Lâm + Khôi) API Upload file, Xem trước, Giải quyết trùng giờ & Lưu DB
│   └── search.py            # (P.Nguyên) API Tìm kiếm lịch trình & Tìm khung giờ trống
└── services/                # Tầng xử lý thuật toán và nghiệp vụ (tách biệt với HTTP)
    ├── security.py          # (Khôi) Băm mật khẩu bcrypt, tạo/kiểm tra JWT Token
    ├── parser.py            # (Lâm) Đọc file thời khóa biểu thô -> tách dòng đúng / dòng lỗi
    ├── validator.py         # (Khôi) Kiểm tra trùng lịch cứng, gom nhóm Conflict & Lưu xuống MySQL
    └── search_engine.py     # (P.Nguyên) Chuẩn hóa câu search, tìm kiếm MySQL & Tìm slot trống <200ms
```

> **NGUYÊN TẮC BẤT BIẾN:** Ba file `models.py`, `database.py` và `AGENTS.md` là hợp đồng chung của cả nhóm. **Không ai được tự ý sửa hoặc định nghĩa lại các class/enum đã có trong `models.py`**. Mọi file code đều phải `from models import ...` và `from database import ...`.