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

# 3. Cài đặt các thư viện cần thiết (bao gồm đầy đủ phụ thuộc FE/BE)
pip install -r ../../requirements.txt
```

### 1.2. Cấu trúc thư mục `sourceCode/BE/` đầy đủ (Phase 1 & Phase 2)
```text
sourceCode/BE/
├── AGENTS.md                           # [KHÓA CỨNG] Luật kiến trúc chung & Quy tắc bảo toàn nhãn PIC (# [pic: ...])
├── models.py                           # [KHÓA CỨNG] Toàn bộ Enum, Dataclass và 12 bảng SQLAlchemy ORM xếp lịch
├── database.py                         # [KHÓA CỨNG] Kết nối Docker MySQL (3307), đổi múi giờ UTC/+07:00, query an toàn
├── main.py                             # (PIC: Lâm) Điểm khởi chạy FastAPI, CORS, HTTP error diagnostic middleware, /health, /health/db & /api/v1/debug/logs
├── BE_team_task_description.md         # Bản đồ phân công Person-in-Charge (PIC) Phase 1 + Phase 2 & Logic nền tảng
├── feature_information_searching.md    # Đặc tả Tính năng Tìm kiếm Thông tin (Kịch bản thuyết trình + SQL+Vector 2 tầng & Hybrid RAG 6 bước)
├── feature_scheduling_with_ai.md       # Đặc tả Tính năng Xếp lịch cùng AI (Kịch bản thuyết trình + NLU, Rejection Memory & Sort-and-Sweep)
├── feature_techniques_and_rag_guide.md # Cẩm nang Kỹ thuật xử lý cốt lõi (Regex, Vector, RAG) & Sổ tay chẩn đoán RAG 2 bước
├── assets/                             # Sơ đồ kiến trúc dạng nguồn PlantUML (.puml) và ảnh xuất (.svg)
│   ├── scheduling_with_AI.puml         # Nguồn sơ đồ luồng Tính năng Xếp lịch cùng AI
│   ├── scheduling_with_AI.svg          # Ảnh SVG kết xuất từ scheduling_with_AI.puml
│   ├── schedule_query.puml             # Nguồn sơ đồ luồng Tính năng Tìm kiếm Thông tin
│   └── schedule_query.svg              # Ảnh SVG kết xuất từ schedule_query.puml
├── routers/                            # Tầng API nhận HTTP Request từ Frontend và trả JSON
│   ├── auth.py                         # (PIC: Khôi) API Đăng ký (/register), Đăng nhập (/login), Đổi username (/username)
│   ├── oauth.py                        # (PIC: Khôi) API Đăng nhập Google & GitHub OAuth2 (authorization-code + state)
│   ├── ingestion.py                    # (PIC: Lâm Bước 1-2 + Khôi Bước 3-4) Upload, Xem trước, Xung đột, Lưu DB & Đẩy RAG timetable
│   ├── search.py                       # (PIC: Khôi Section 1 + Lâm Section 2) Tìm lịch, Hybrid RAG học vụ & Tìm giờ trống
│   ├── assistant.py                    # (PIC: Khôi) API NLU xếp lịch (/understand), Reset ngữ cảnh (/reset), Điều hướng chéo & Nạp file (/index-file)
│   ├── proposals.py                    # (PIC: Lâm) API Vòng đời đề xuất (/confirm, /reject, /{id}) & Chọn lịch thủ công (/manual)
│   ├── tasks.py                        # (PIC: Lâm) API Công việc linh hoạt CRUD, Hàng đợi ưu tiên & Xếp lịch hàng loạt (/schedule)
│   ├── events.py                       # (PIC: Lâm) API Sự kiện thủ công CRUD, Cập nhật giờ nguyên tử, Preferences & Reminder Audit
│   └── reminders.py                    # (PIC: Lâm) API Cài đặt nhắc hẹn, Đồng bộ báo thức thiết bị (auto-create an toàn /scheduled) & Nhật ký (/audit)
├── services/                           # Tầng xử lý thuật toán và nghiệp vụ (tách biệt với HTTP)
│   ├── security.py                     # (PIC: Khôi) Băm mật khẩu bcrypt, tạo/kiểm tra JWT Token, get_current_user
│   ├── privacy.py                      # (PIC: Khôi) Khử PII (sanitize_prompt), chặn IP ngoại mạng & Mã hóa Fernet
│   ├── validator.py                    # (PIC: Khôi) Kiểm tra trùng lịch cứng, gom nhóm ConflictCard, chu kỳ lặp đa dạng & Lưu xuống MySQL
│   ├── normalizer.py                   # (PIC: Khôi) Chuẩn hóa tiếng Việt không dấu, bung teencode, bảo vệ từ tiếng Anh & lọc từ tục
│   ├── llm_config.py                   # (PIC: Khôi) Nạp cấu hình dotenv thống nhất, URL vLLM, model & timeout tách riêng (3s NLU / 8s Academic RAG)
│   ├── rag.py                          # (PIC: Khôi) Cắt đoạn bảo toàn dòng, nhúng vector 512 chiều, index thời khóa biểu & Kho VectorIndex mã hóa (MIN_SCORE=0.22)
│   ├── kb_models.py                    # (PIC: Khôi) 8 bảng SQLAlchemy ORM (kb_*) cho Cơ sở tri thức học vụ có cấu trúc
│   ├── nlu.py                          # (PIC: Khôi) Trích xuất ý định/thực thể/deadline_hint qua vLLM (có kiểm soát ngữ cảnh & đối chiếu chữ gốc) kèm Fallback quy tắc
│   ├── search_engine.py                # (PIC: Khôi Section 1-2 + Lâm Section 3) Search SQL+Vector, Hybrid RAG 6 bước (kb_* + vector) & Slot trống <200ms
│   ├── parser.py                       # (PIC: Lâm) Đọc file thời khóa biểu (.csv/.md/.txt/.pdf/ảnh OCR), lọc edge cases & cách ly lỗi
│   ├── temporal.py                     # (PIC: Lâm) Quy đổi ngày tương đối song ngữ + ISO sang cửa sổ [start, end] (+07:00) & hỏi làm rõ
│   ├── proposals.py                    # (PIC: Lâm) Chọn slot (kể cả trong khung giờ rộng), chia nhỏ việc dài (split_task), Proposal & Priority Queue
│   ├── inference_queue.py              # (PIC: Lâm) Hàng đợi tuần tự FIFO (InferenceBroker) chống quá tải GPU/VRAM
│   ├── ai_logging.py                   # (PIC: Lâm) Phân loại mã lỗi AI & ghi nhật ký gỡ lỗi ra logs/ai_errors.jsonl và logs/ai_calls.jsonl
│   └── telemetry.py                    # (PIC: Lâm) Luồng thu thập định kỳ độ trễ p50/p95, RAM, GPU VRAM vào MySQL
├── tools/                              # Công cụ đánh giá offline
│   └── eval_nlu.py                     # Chấm điểm độ chính xác trích xuất NLU trên tập dữ liệu kiểm thử
└── tests/                              # Kiểm thử cấp module/API chạy trực tiếp trên Docker MySQL 8.0 (port 3307)
    ├── README.md                       # Hướng dẫn kiến trúc kiểm thử Savepoint Isolation & tiêu chuẩn viết test
    ├── data/nlu_eval.jsonl             # Tập câu mẫu kiểm thử độ chính xác NLU
    ├── conftest.py                     # (PIC: Khôi) Fixture dùng chung nối MySQL 3307 (hoặc SQLite fallback) và tự động rollback
    ├── test_auth.py                    # (PIC: Khôi) Bộ kiểm thử Đăng ký, Đăng nhập, JWT, UTC/+07:00 và ràng buộc MySQL
    ├── test_validator.py               # (PIC: Khôi) Bộ kiểm thử Kiểm tra xung đột cứng, gom ConflictCard và lưu MySQL
    ├── test_ai_endpoints_audit.py      # Bộ kiểm thử rà soát API Trợ lý AI, tìm kiếm, học vụ & hợp đồng đầu cuối
    ├── test_assistant_reminders_api.py # Bộ kiểm thử API Nhắc hẹn, Trợ lý AI & đồng bộ thiết bị
    ├── test_events_and_search_coverage.py # Bộ kiểm thử hồi quy patch nguyên tử, reminder race, reset ngữ cảnh & ranh giới tìm kiếm
    ├── test_p2_ai.py                   # Bộ kiểm thử Phase 2 cho NLU, RAG, Telemetry, Inference Queue & Priority Queue
    ├── test_privacy_nlu.py             # Bộ kiểm thử riêng tư, khử PII, chuẩn hóa và rào chắn NLU
    ├── parser_test.py                  # (PIC: Lâm) Bộ kiểm thử Đọc thời khóa biểu, PDF/ảnh OCR và cách ly lỗi
    └── ingestion_test.py               # (PIC: Lâm) Bộ kiểm thử Xác thực sơ bộ các hàm xem trước và chuẩn hóa dữ liệu
```

---

## 2. Hệ thống Tài liệu Đặc tả của Team Backend

1. **Phân công Nhân sự Toàn diện (Phase 1 & Phase 2) & Logic Nền tảng (`Parse` + `Conflict Resolution`):**
   * Đọc [`BE_team_task_description.md`](BE_team_task_description.md) để nắm rõ ai là PIC của từng file/phân vùng (`# [pic: khoi]`, `# [pic: lam]`) và những logic nghiệp vụ nào người đó chịu trách nhiệm đọc hiểu, bảo trì và chỉnh sửa.
2. **Đặc tả Tính năng 1 - Tìm kiếm Thông tin (`Information Searching`):**
   * Đọc [`feature_information_searching.md`](feature_information_searching.md) (Kịch bản thuyết trình không đi sâu code ở Mục 0, kèm sơ đồ [`.puml`](assets/schedule_query.puml)/[`.svg`](assets/schedule_query.svg), quy trình Hybrid SQL + Vector 2 tầng, Hybrid RAG 6 bước `kb_*` + Vector `MIN_SCORE = 0.22` + timeout `8s`, và 2 thang chấm 30 điểm).
3. **Đặc tả Tính năng 2 - Xếp lịch Thông minh cùng AI (`Scheduling with AI`):**
   * Đọc [`feature_scheduling_with_ai.md`](feature_scheduling_with_ai.md) (Kịch bản thuyết trình liền mạch ở Mục 0, kèm sơ đồ [`.puml`](assets/scheduling_with_AI.puml)/[`.svg`](assets/scheduling_with_AI.svg), cơ chế rào chắn `NluResult` + `deadline_hint`, bộ nhớ từ chối `excluded_slots`, `PendingClarification` + `/reset`, xử lý khung giờ rộng, và rubric chấm điểm 35 điểm).
4. **Cẩm nang Kỹ thuật Xử lý & Chẩn đoán RAG (`Techniques & RAG Guide`):**
   * Đọc [`feature_techniques_and_rag_guide.md`](feature_techniques_and_rag_guide.md) để nắm trước toàn bộ kỹ thuật áp dụng cụ thể trong hệ thống (Regex vừa đủ dùng, Feature Hashing 512 chiều, Sort-and-Sweep, Hybrid RAG) cùng sổ tay chẩn đoán 2 bước khi RAG trả lời kém (kiểm tra `top-2`, đồng bộ embed DB-Query, xử lý lỗi tách chunk kiểu *Luật 264/263*, và kiểm tra context đẩy vào LLM).
5. **Quy chuẩn Kiểm thử trên Docker MySQL 8.0 (`localhost:3307`):**
   * Đọc [`tests/README.md`](tests/README.md) để nắm cách dùng fixture `db_session`, `client` (cô lập giao dịch bằng `create_savepoint`, tự động chuyển sang SQLite trong bộ nhớ nếu máy chưa bật Docker MySQL; đặt `REQUIRE_MYSQL=1` để bắt buộc MySQL thật).

> **NGUYÊN TẮC BẤT BIẾN:** Ba file [`models.py`](models.py), [`database.py`](database.py) và [`AGENTS.md`](AGENTS.md) là hợp đồng chung của cả nhóm. **Không ai được tự ý sửa hoặc định nghĩa lại các class/enum đã có trong `models.py`**. Mọi file code đều phải `from models import ...` và `from database import ...`.
