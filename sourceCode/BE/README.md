# Tài liệu Kỹ thuật & Phân công - Team Backend (BE)

Tài liệu này là hướng dẫn trung tâm cho đội ngũ Backend (**Khôi, Lâm**) và các thành viên phối hợp liên nhóm (**FE, DB/AI-Host**). Mọi thành viên đọc kỹ tài liệu này để nắm rõ cấu trúc thư mục, cách khởi tạo môi trường, phân công phụ trách từng file và đường dẫn tới các tài liệu đặc tả tính năng chi tiết.

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
├── AGENTS.md                           # [KHÓA CỨNG] Luật kiến trúc chung cho toàn bộ Backend
├── models.py                           # [KHÓA CỨNG] Toàn bộ Enum, Dataclass và 11 bảng SQLAlchemy ORM
├── database.py                         # [KHÓA CỨNG] Kết nối Docker MySQL (3307), đổi múi giờ UTC/+07:00, query an toàn
├── main.py                             # Điểm khởi chạy FastAPI Server (gắn các router vào app)
├── BE_team_task_description.md         # Bản đồ phân công Person-in-Charge (PIC) & Logic Parse / Conflict Resolution
├── feature_information_searching.md    # Đặc tả chi tiết Tính năng Tìm kiếm Thông tin (SQL+Vector 2 tầng & RAG 6 bước)
├── feature_scheduling_with_ai.md       # Đặc tả chi tiết Tính năng Xếp lịch cùng AI (NLU, Memory, Scorer 35 điểm)
├── routers/                            # Tầng API nhận HTTP Request từ Frontend và trả JSON
│   ├── auth.py                         # (Khôi) API Đăng ký, Đăng nhập, Đổi tên đăng nhập
│   ├── ingestion.py                    # (Lâm + Khôi) API Upload file, Xem trước, Giải quyết trùng giờ & Lưu DB
│   ├── search.py                       # (Khôi + Lâm) API Tìm kiếm lịch trình, Hỏi đáp học vụ (RAG) & Tìm giờ trống
│   ├── assistant.py                    # (DB/AI-Host + Khôi) API NLU xếp lịch, Điều hướng chéo & Nạp chỉ mục
│   └── reminders.py                    # (DB/AI-Host) API đồng bộ nhắc hẹn sự kiện
├── services/                           # Tầng xử lý thuật toán và nghiệp vụ (tách biệt với HTTP)
│   ├── security.py                     # (Khôi) Băm mật khẩu bcrypt, tạo/kiểm tra JWT Token, get_current_user
│   ├── parser.py                       # (Lâm) Đọc file thời khóa biểu (.csv/.md/.pdf/ảnh), lọc edge cases & cách ly lỗi
│   ├── validator.py                    # (Khôi) Kiểm tra trùng lịch cứng, gom nhóm Conflict & Lưu xuống MySQL
│   ├── search_engine.py                # (Khôi + Lâm) Tìm kiếm lai SQL & Vector 2 tầng, 6-bước RAG học vụ & Quét slot trống <200ms
│   └── nlu.py                          # (DB/AI-Host + Khôi) Trích xuất ý định/thực thể/deadline_hint kèm Fallback quy tắc
└── tests/                              # Kiểm thử cấp module/API chạy trực tiếp trên Docker MySQL 8.0 (port 3307)
    ├── README.md                       # Hướng dẫn kiến trúc kiểm thử Savepoint Isolation & tiêu chuẩn viết test
    ├── conftest.py                     # Fixture dùng chung nối MySQL 3307 và tự động rollback sau mỗi hàm test
    ├── test_auth.py                    # (Khôi) Bộ kiểm thử Đăng ký, Đăng nhập, JWT, UTC/+07:00 và ràng buộc MySQL
    ├── test_validator.py               # (Khôi) Bộ kiểm thử Kiểm tra xung đột cứng, gom ConflictCard và lưu MySQL
    ├── parser_test.py                  # (Lâm) Bộ kiểm thử Đọc thời khóa biểu, PDF/ảnh OCR và cách ly lỗi
    └── ingestion_test.py               # (Lâm) Bộ kiểm thử Xác thực sơ bộ các hàm xem trước và chuẩn hóa dữ liệu
```

---

## 2. Hệ thống Tài liệu Đặc tả của Team Backend

1. **Phân công Nhân sự & Logic Nền tảng (`Parse` + `Conflict Resolution`):**
   * Đọc [`BE_team_task_description.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/BE_team_task_description.md) để nắm rõ ai là PIC của từng file/phân vùng (`# [pic: khoi]`, `# [pic: lam]`) và những logic nghiệp vụ nào người đó cần nắm.
2. **Đặc tả Tính năng 1 - Tìm kiếm Thông tin (`Information Searching`):**
   * Đọc [`feature_information_searching.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/feature_information_searching.md) để xem khung tóm tắt thuyết trình, phân luồng Bước 0 trên UI, quy trình Hướng 1 (Hybrid SQL + Vector Search 2 tầng không gọi LLM), Hướng 2 (Academic Knowledge Base RAG 6 bước), điều hướng chéo sang Trợ lý AI và 2 thang chấm điểm 30 điểm kèm ví dụ minh họa.
3. **Đặc tả Tính năng 2 - Xếp lịch Thông minh cùng AI (`Scheduling with AI`):**
   * Đọc [`feature_scheduling_with_ai.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/feature_scheduling_with_ai.md) để xem khung tóm tắt thuyết trình, ranh giới AI và thuật toán tất định, vai trò của `deadline_hint` trong `NluResult`, cơ chế bộ nhớ từ chối `excluded_slots`, điều hướng chéo sang Tìm kiếm và thang chấm điểm 35 điểm kèm ví dụ minh họa.
4. **Quy chuẩn Kiểm thử trên Docker MySQL 8.0 (`localhost:3307`):**
   * Đọc [`tests/README.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/tests/README.md) để nắm cách dùng fixture `db_session`, `client` (cô lập giao dịch bằng `create_savepoint`, không làm bẩn DBeaver) và các tiêu chí kiểm thử bắt buộc của từng module.

> **NGUYÊN TẮC BẤT BIẾN:** Ba file [`models.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/models.py), [`database.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/database.py) và [`AGENTS.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/AGENTS.md) là hợp đồng chung của cả nhóm. **Không ai được tự ý sửa hoặc định nghĩa lại các class/enum đã có trong `models.py`**. Mọi file code đều phải `from models import ...` và `from database import ...`.
