# Tài liệu Kỹ thuật & Phân công Toàn diện (Phase 1 & Phase 2) - Team Backend (BE)

Tài liệu này là hướng dẫn trung tâm cho đội ngũ Backend (**Khôi, Lâm**) và các thành viên phối hợp liên nhóm (**FE, DB/AI-Host**). Mọi thành viên đọc kỹ tài liệu này để nắm rõ cấu trúc thư mục đầy đủ từ Phase 1 đến hết Phase 2, cách khởi tạo môi trường, phân công Person-in-Charge (PIC) của từng file và đường dẫn tới các tài liệu đặc tả tính năng chi tiết.

> **QUY TẮC TRÁCH NHIỆM PIC & BẢO TOÀN NHÃN `# [pic: ...]`:**
> * **Một người là PIC của một file hoặc một module sẽ chịu trách nhiệm đọc và hiểu toàn bộ mã nguồn nếu file đó không cần chỉnh sửa thêm, hoặc trực tiếp chỉnh sửa nếu phát hiện vấn đề/điểm chưa hợp lý và tiếp tục chịu trách nhiệm đến cùng cho phần mã nguồn mình đã chỉnh sửa.**
> * Mọi file và phân vùng trong `sourceCode/BE/` đều đã được đánh dấu bằng comment `# [pic: khoi]` hoặc `# [pic: lam]`. Các công cụ AI hỗ trợ lập trình tuyệt đối **không được xóa hoặc ghi đè các nhãn `# [pic: ...]` này**.

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
pip install fastapi uvicorn sqlalchemy pymysql cryptography bcrypt pyjwt python-multipart pytest httpx psutil
```

### 1.2. Cấu trúc thư mục `sourceCode/BE/` đầy đủ (Phase 1 & Phase 2)
```text
sourceCode/BE/
├── AGENTS.md                           # [KHÓA CỨNG] Luật kiến trúc chung & Quy tắc bảo toàn nhãn PIC (# [pic: ...])
├── models.py                           # [KHÓA CỨNG] Toàn bộ Enum, Dataclass và 11 bảng SQLAlchemy ORM xếp lịch
├── database.py                         # [KHÓA CỨNG] Kết nối Docker MySQL (3307), đổi múi giờ UTC/+07:00, query an toàn
├── main.py                             # (PIC: Lâm) Điểm khởi chạy FastAPI, CORS, Telemetry lifespan, /health & /health/db
├── BE_team_task_description.md         # Bản đồ phân công Person-in-Charge (PIC) Phase 1 + Phase 2 & Logic nền tảng
├── feature_information_searching.md    # Đặc tả chi tiết Tính năng Tìm kiếm Thông tin (SQL+Vector 2 tầng & RAG 6 bước)
├── feature_scheduling_with_ai.md       # Đặc tả chi tiết Tính năng Xếp lịch cùng AI (NLU, Memory, Scorer 35 điểm)
├── routers/                            # Tầng API nhận HTTP Request từ Frontend và trả JSON
│   ├── auth.py                         # (PIC: Khôi) API Đăng ký (/register), Đăng nhập (/login), Đổi username (/username)
│   ├── oauth.py                        # (PIC: Khôi) API Đăng nhập Google & GitHub OAuth2 (authorization-code + state)
│   ├── ingestion.py                    # (PIC: Lâm Bước 1-2 + Khôi Bước 3-4) Upload, Xem trước, Xung đột & Lưu DB
│   ├── search.py                       # (PIC: Khôi Section 1 + Lâm Section 2) Tìm lịch, RAG học vụ & Tìm giờ trống
│   ├── assistant.py                    # (PIC: Khôi) API NLU xếp lịch (/understand), Điều hướng chéo & Nạp file (/index-file)
│   ├── proposals.py                    # (PIC: Lâm) API Vòng đời đề xuất (/confirm, /reject, /{id}) & Chọn lịch thủ công (/manual)
│   ├── tasks.py                        # (PIC: Lâm) API Công việc linh hoạt CRUD, Hàng đợi ưu tiên & Xếp lịch hàng loạt (/schedule)
│   └── reminders.py                    # (PIC: Lâm) API Cài đặt nhắc hẹn, Đồng bộ báo thức thiết bị & Nhật ký kiểm toán (/audit)
├── services/                           # Tầng xử lý thuật toán và nghiệp vụ (tách biệt với HTTP)
│   ├── security.py                     # (PIC: Khôi) Băm mật khẩu bcrypt, tạo/kiểm tra JWT Token, get_current_user
│   ├── privacy.py                      # (PIC: Khôi) Khử PII (sanitize_prompt), chặn IP ngoại mạng & Mã hóa Fernet
│   ├── validator.py                    # (PIC: Khôi) Kiểm tra trùng lịch cứng, gom nhóm ConflictCard & Lưu xuống MySQL
│   ├── normalizer.py                   # (PIC: Khôi) Chuẩn hóa tiếng Việt không dấu, bung từ điển teencode & lọc từ tục
│   ├── rag.py                          # (PIC: Khôi) Cắt đoạn bảo toàn dòng, nhúng vector 512 chiều & Kho VectorIndex mã hóa
│   ├── kb_models.py                    # (PIC: Khôi) 8 bảng SQLAlchemy ORM (kb_*) cho Cơ sở tri thức học vụ công khai
│   ├── nlu.py                          # (PIC: Khôi) Trích xuất ý định/thực thể/deadline_hint qua vLLM kèm Fallback quy tắc
│   ├── search_engine.py                # (PIC: Khôi Section 1-2 + Lâm Section 3) Search SQL+Vector, RAG 6 bước & Slot trống <200ms
│   ├── parser.py                       # (PIC: Lâm) Đọc file thời khóa biểu (.csv/.md/.pdf/ảnh OCR), lọc edge cases & cách ly lỗi
│   ├── temporal.py                     # (PIC: Lâm) Quy đổi ngày tương đối sang cửa sổ [start, end] (+07:00) & hỏi làm rõ
│   ├── proposals.py                    # (PIC: Lâm) Chấm điểm chọn slot, chia nhỏ việc dài (split_task), Proposal & Priority Queue
│   ├── inference_queue.py              # (PIC: Lâm) Hàng đợi tuần tự FIFO (InferenceBroker) chống quá tải GPU/VRAM
│   ├── ai_logging.py                   # (PIC: Lâm) Phân loại 9 mã lỗi AI và ghi nhật ký gỡ lỗi ra logs/ai_errors.jsonl
│   └── telemetry.py                    # (PIC: Lâm) Luồng thu thập định kỳ độ trễ p50/p95, RAM, GPU VRAM vào MySQL
└── tests/                              # Kiểm thử cấp module/API chạy trực tiếp trên Docker MySQL 8.0 (port 3307)
    ├── README.md                       # Hướng dẫn kiến trúc kiểm thử Savepoint Isolation & tiêu chuẩn viết test
    ├── conftest.py                     # (PIC: Khôi) Fixture dùng chung nối MySQL 3307 (hoặc SQLite fallback) và tự động rollback
    ├── test_auth.py                    # (PIC: Khôi) Bộ kiểm thử Đăng ký, Đăng nhập, JWT, UTC/+07:00 và ràng buộc MySQL
    ├── test_validator.py               # (PIC: Khôi) Bộ kiểm thử Kiểm tra xung đột cứng, gom ConflictCard và lưu MySQL
    ├── parser_test.py                  # (PIC: Lâm) Bộ kiểm thử Đọc thời khóa biểu, PDF/ảnh OCR và cách ly lỗi
    └── ingestion_test.py               # (PIC: Lâm) Bộ kiểm thử Xác thực sơ bộ các hàm xem trước và chuẩn hóa dữ liệu
```

---

## 2. Hệ thống Tài liệu Đặc tả của Team Backend

1. **Phân công Nhân sự Toàn diện (Phase 1 & Phase 2) & Logic Nền tảng (`Parse` + `Conflict Resolution`):**
   * Đọc [`BE_team_task_description.md`](BE_team_task_description.md) để nắm rõ ai là PIC của từng file/phân vùng (`# [pic: khoi]`, `# [pic: lam]`) và những logic nghiệp vụ nào người đó chịu trách nhiệm đọc hiểu, bảo trì và chỉnh sửa.
2. **Đặc tả Tính năng 1 - Tìm kiếm Thông tin (`Information Searching`):**
   * Đọc [`feature_information_searching.md`](feature_information_searching.md) để xem khung tóm tắt thuyết trình, phân luồng Bước 0 trên UI, quy trình Hướng 1 (Hybrid SQL + Vector Search 2 tầng không gọi LLM), Hướng 2 (Academic Knowledge Base RAG 6 bước), điều hướng chéo sang Trợ lý AI và 2 thang chấm điểm 30 điểm kèm ví dụ minh họa.
3. **Đặc tả Tính năng 2 - Xếp lịch Thông minh cùng AI (`Scheduling with AI`):**
   * Đọc [`feature_scheduling_with_ai.md`](feature_scheduling_with_ai.md) để xem khung tóm tắt thuyết trình, ranh giới AI và thuật toán tất định, vai trò của `deadline_hint` trong `NluResult`, cơ chế bộ nhớ từ chối `excluded_slots`, điều hướng chéo sang Tìm kiếm và thang chấm điểm 35 điểm kèm ví dụ minh họa.
4. **Quy chuẩn Kiểm thử trên Docker MySQL 8.0 (`localhost:3307`):**
   * Đọc [`tests/README.md`](tests/README.md) để nắm cách dùng fixture `db_session`, `client` (cô lập giao dịch bằng `create_savepoint`, tự động chuyển sang SQLite trong bộ nhớ nếu máy chưa bật Docker MySQL; đặt `REQUIRE_MYSQL=1` để bắt buộc MySQL thật).

> **NGUYÊN TẮC BẤT BIẾN:** Ba file [`models.py`](models.py), [`database.py`](database.py) và [`AGENTS.md`](AGENTS.md) là hợp đồng chung của cả nhóm. **Không ai được tự ý sửa hoặc định nghĩa lại các class/enum đã có trong `models.py`**. Mọi file code đều phải `from models import ...` và `from database import ...`.
