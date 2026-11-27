## Mục 2. Tài liệu API (`/openapi.json`) và Quy ước Mã phản hồi

### 1. Các đường dẫn tài liệu & chẩn đoán trực tiếp trên Server BE
- `GET http://<IP_Host>:8080/openapi.json`: Đặc tả OpenAPI 3.x tự động sinh từ schema Pydantic và toàn bộ router FastAPI (`auth`, `oauth`, `assistant`, `proposals`, `tasks`, `reminders`, `ingestion`, `search`, `events`, `user`). Script kiểm thử tự động của Duy dùng trực tiếp file JSON này để đối chiếu hợp đồng request/response.
- `GET http://<IP_Host>:8080/docs`: Giao diện Swagger UI tương tác trên trình duyệt.
- `GET http://<IP_Host>:8080/health` và `GET http://<IP_Host>:8080/health/db`: Kiểm tra trạng thái sống của server BE và kết nối thực tế tới MySQL (`SELECT 1`).
- `GET http://<IP_Host>:8080/api/v1/debug/logs?limit=30`: Tự chẩn đoán mà không cần truy cập terminal máy Host. Trả về `ai_runtime_config` (`vllm_endpoint`, `model`, `nlu_timeout_seconds`, `academic_timeout_seconds`, `endpoint_allowed`, `allowed_hosts_configured`), `ai_call_count`, `recent_ai_calls` (đọc từ `ai_calls.jsonl`, đã ẩn PII, ghi nhận cả lệnh gọi `OK` lẫn `FALLBACK` kèm `http_status`, `latency_ms`, `usage`), cùng `recent_http_errors` và `recent_ai_errors`.

### 2. Header chẩn đoán trả về trên mọi HTTP Response
- `X-Request-ID`: Chuỗi 8 ký tự hex dùng để đối chiếu từng request từ Terminal FE sang `/api/v1/debug/logs`.
- `X-Process-Time-Ms`: Thời gian xử lý thực tế ở phía BE (đơn vị mili-giây, làm tròn 2 chữ số thập phân) trên tất cả các response `2xx`, `4xx` và `500`, phục vụ đo độ trễ tách biệt khỏi độ trễ mạng LAN/VPN.
- `X-Error-Source` (có khi `status >= 400`): Nhãn phân tầng nguyên nhân gồm `FASTAPI_ROUTER_URL_NOT_FOUND`, `PYDANTIC_VALIDATION_ERROR`, `BE_AUTH_GUARD`, `BE_BUSINESS_RULE_REJECTION`, `BE_UNHANDLED_EXCEPTION`.

### 3. Bảng mã phản hồi & mã lỗi

| HTTP Status / Cờ JSON | Ý nghĩa nghiệp vụ & điều kiện kích hoạt | Endpoint điển hình |
| :--- | :--- | :--- |
| **`200 OK` + `fallback_mode: true`** | Hệ thống AI gặp sự cố thực tế (`TIMEOUT`, `INFRA_CRASH`, `JSON_PARSE`, `SCHEMA_VALIDATION`, `SEMANTIC_FAILURE`). Các phản hồi LLM khỏe mạnh trả `intent = "unknown"` (tán gẫu, thời lượng trần, khung giờ trần) không kích hoạt `fallback_mode: true`. Khi fallback, BE ghi nhận vào `ai_error_logs` và `ai_calls.jsonl`, chuyển sang xử lý tất định và trả kèm `available_slots` đã cắt khớp đúng `duration_minutes` hoặc `(requested_start, requested_end)` (ở `/understand`), hoặc trích đoạn tài liệu (ở `/academic/ask`); không bao giờ trả `500` vì AI lỗi. | `POST /api/v1/assistant/understand`, `POST /api/v1/search/academic/ask` |
| **`200 OK` + `redirect_target`** | Điều hướng chéo khi người dùng gõ nhầm loại câu: trả `redirect_target = "search_home"` nếu hỏi lịch/học vụ tại khung Chat AI, hoặc `redirect_target = "chat_home"` nếu gõ lệnh xếp lịch tại khung Tìm kiếm / Học vụ. | `POST /api/v1/assistant/understand`, `GET /api/v1/search/events`, `POST /api/v1/search/academic/ask` |
| **`200 OK` + `nlu.needs_clarification: true`** | Yêu cầu xếp lịch thiếu thời lượng bắt buộc, thiếu tên hoạt động, chứa ngày sai lịch (như `31/02`), chứa cụm ngày mơ hồ (`"sớm"`, `"sắp tới"`, `"lúc nào đó"`, ...), thời lượng trần (`"2 tiếng"`), hoặc khung giờ trần (`"7h - 11h"`); chưa tạo `Proposal`, trạng thái chờ làm rõ được lưu vào `pending_clarifications` (TTL 10 phút). | `POST /api/v1/assistant/understand` |
| **`201 Created`** | Tạo mới thành công bản ghi tài khoản, sự kiện thủ công, công việc linh hoạt, hoặc đặt lịch qua bộ chọn thủ công (`ManualFallbackModal`). | `POST /api/v1/auth/register`, `POST /api/v1/events`, `POST /api/v1/tasks`, `POST /api/v1/proposals/manual` |
| **`204 No Content`** | Xóa mềm thành công sự kiện hoặc công việc (không trả body JSON). | `DELETE /api/v1/events/{event_id}`, `DELETE /api/v1/tasks/{task_id}` |
| **`400 Bad Request`** | Vi phạm quy tắc chỉnh sửa trực tiếp: cố sửa `start_time`/`end_time` của sự kiện cứng (`CLASS`/`EXAM`) hoặc cập nhật `end_time <= start_time` trên sự kiện không phải `DEADLINE`. | `PATCH /api/v1/events/{event_id}` |
| **`401 Unauthorized`** | Thiếu header `Authorization: Bearer <jwt_token>`, token sai chữ ký/hết hạn, hoặc sai tên đăng nhập/mật khẩu khi đăng nhập. | Tất cả endpoint bảo vệ và `POST /api/v1/auth/login` |
| **`404 Not Found`** | Hai trường hợp phân biệt rõ:<br>1. **Lỗi nghiệp vụ / Chống IDOR** (`X-Error-Source: BE_BUSINESS_RULE_REJECTION`, detail kiểu `"event not found"`, `"proposal not found"`): Bản ghi không tồn tại hoặc thuộc sở hữu của user khác.<br>2. **Sai route HTTP** (`X-Error-Source: FASTAPI_ROUTER_URL_NOT_FOUND`, detail `"Not Found"`): Client gọi sai đường dẫn URL hoặc sai HTTP method. | `/api/v1/events/{id}`, `/api/v1/proposals/{id}`, `/api/v1/tasks/{id}`, `/api/v1/reminders/{id}` |
| **`409 Conflict`** | Xung đột trạng thái hoặc ràng buộc cứng:<br>- Trùng `username` khi đăng ký.<br>- Xác nhận đề xuất / chọn slot thủ công bị trùng giờ với lịch bận hiện có (`check_hard_conflict`).<br>- Thao tác `confirm`/`reject`/`reschedule` lên `Proposal` không còn ở trạng thái `PROPOSED`. | `POST /api/v1/auth/register`, `POST /api/v1/proposals/{id}/confirm`, `POST /api/v1/proposals/manual`, `POST /api/v1/assistant/understand` |
| **`422 Unprocessable Entity`** | Hai trường hợp:<br>- Lỗi schema Pydantic (thiếu trường, sai kiểu dữ liệu, mật khẩu dưới 6 ký tự, `duration_minutes` ngoài khoảng `15..720`).<br>- Lỗi logic nhập liệu đầu vào: tải lên ảnh/tệp phi thời khóa biểu (`NO_TIMETABLE_DETECTED`), thiếu Tesseract OCR, `end_time <= start_time` ở `POST /api/v1/events`, hoặc `slot_start` không nằm trên lưới 15 phút tại `/proposals/manual`. | `POST /api/v1/ingestion/parse-preview`, `POST /api/v1/events`, `POST /api/v1/proposals/manual` |

---

## Mục 3. Danh sách Biến Môi trường (Environment Variables)

### 1. Kết nối Cơ sở dữ liệu & Bảo mật (Database / Auth / Encryption)

| Biến môi trường | Mặc định trong code | Cách dùng|
| :--- | :--- | :--- |
| `DATABASE_URL` | Tự ghép từ `DB_USER`, `DB_PASSWORD`, `DB_HOST` (`localhost`), `DB_PORT` (`3307`), `DB_NAME` (`university_assistant`) | Trên Host Docker MySQL dùng URL trỏ vào MySQL 8.0 (`mysql+pymysql://...`). |
| `TEST_DATABASE_URL` | Trống (bộ `pytest` dùng SQLite in-memory) | Chỉ thiết lập khi muốn chạy `pytest` trực tiếp trên một schema MySQL nháp; tuyệt đối không trỏ vào DB dữ liệu thật vì suite test sẽ drop/recreate bảng. |
| `JWT_SECRET_KEY` | `"dev-secret-key-change-in-production-32b"` | Chuỗi bí mật ký token JWT HS256. Không ghi giá trị production lên git hoặc báo cáo; giữ trong `.env` nội bộ máy Host. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `"1440"` (24 giờ) | Có thể giảm thấp tạm thời nếu QA viết ca test hết hạn phiên đăng nhập. |
| `DATA_ENCRYPTION_KEY` | `"dev-encryption-key-change-in-production"` | Khóa dùng cho AES-128-CBC Fernet mã hóa chỉ mục RAG trên đĩa. Không chia sẻ khóa production công khai. |

### 2. Hạ tầng Suy luận AI & Kiểm soát Điểm cuối (`llm_config.py`, `nlu.py`, `privacy.py`, `search_engine.py`)

Từ PR #29, `services/llm_config.py` tự động nạp cấu hình từ `sourceCode/Database/assistant_deploy/.env` rồi đến `sourceCode/BE/.env` lúc khởi động (`main.py`, `privacy.py`), đồng thời vẫn ưu tiên biến môi trường đặt trực tiếp trong shell.

| Biến môi trường | Mặc định trong code | Cách dùng|
| :--- | :--- | :--- |
| `VLLM_ENDPOINT` | Nếu trống sẽ kiểm tra `LLAMA_API_URL`, sau đó tự dò cổng `8000` rồi `11434` trên `127.0.0.1` -> `http://127.0.0.1:8000/v1/chat/completions` | **Test AI thật (Duy đo JGA/Latency):** trỏ tới máy Host chạy vLLM (ví dụ `http://26.211.52.63:8000/v1/chat/completions`).<br>**Test Fallback khi AI sập (Nguyên/Duy):** đặt `http://127.0.0.1:1/v1/chat/completions` để từ chối kết nối tức thì. |
| `LLAMA_API_URL` | `""` (trong Docker Compose đặt `http://llama_engine:8000`) | Biến dự phòng khi `VLLM_ENDPOINT` chưa đặt; BE tự chuẩn hóa hậu tố `/v1/chat/completions`. |
| `LLM_MODEL` | `"hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"` | Phải khớp với tên model đang phục vụ trên container `llama_engine` của vLLM. |
| `LLM_TIMEOUT_SECONDS` | `"3.0"` (giây) | Thời hạn chờ tối đa cho NLU ở Feature 2 (và làm ngưỡng dự phòng cho Academic RAG nếu chưa đặt `ACADEMIC_LLM_TIMEOUT_SECONDS`) trước khi chuyển sang `fallback_mode = True` dưới 1 giây. Khi chạy đo độ chính xác NLU qua `tools/eval_nlu.py` (không gắn `--rules`), script tự nâng lên `"20.0"` nếu biến này chưa được đặt. |
| `ACADEMIC_LLM_TIMEOUT_SECONDS` | `"8.0"` (giây) | Thời hạn chờ riêng cho bước sinh câu trả lời RAG ở Feature 1 Mode B (`POST /api/v1/search/academic/ask`). |
| `LLM_ALLOWED_HOSTS` | `""` (chỉ cho phép localhost, mạng LAN nội bộ, Tailscale `100.64.0.0/10`) | Nếu QA gọi từ máy khác qua Radmin VPN / Hamachi (ví dụ `26.211.52.63`), thêm IP/CIDR của máy Host vào biến này (cách nhau bằng dấu phẩy) để không bị chốt chặn riêng tư `assert_private_endpoint` từ chối. QA kiểm tra nhanh qua `GET /api/v1/debug/logs` -> `ai_runtime_config.endpoint_allowed == true`. |

### 3. Giám sát hiệu năng, hàng đợi & nhật ký lỗi

| Biến môi trường | Mặc định trong code | Cách dùng|
| :--- | :--- | :--- |
| `INFERENCE_QUEUE_LOGGING` | `"0"` (tắt) | Đặt `"1"` trên máy Host trong đợt Duy chạy benchmark để ghi thời gian chờ/xử lý từng request vào bảng `inference_queue_logs`. |
| `TELEMETRY_INTERVAL_SECONDS` | `"0"` (tắt) | Đặt `"15"` (hoặc `"5"`) khi Duy chạy đo tải để ghi liên tục RAM, VRAM và độ sâu hàng đợi vào bảng `telemetry_metric_logs`. |
| `AI_CALL_LOG_PATH` | `sourceCode/BE/logs/ai_calls.jsonl` | File log JSONL ghi nhật ký kiểm toán ẩn PII cho mọi lượt gọi AI (`OK` lẫn `FALLBACK`) kèm `feature`, `source`, `http_status`, `latency_ms` và `usage` token; đọc trực tiếp qua `/api/v1/debug/logs`. |
| `AI_ERROR_LOG_PATH` | `sourceCode/BE/logs/ai_errors.jsonl` | File log JSONL phục vụ tính `JSON Schema Validity Rate` và phân loại lỗi AI. |
| `BE_HTTP_ERROR_LOG_PATH` | `sourceCode/BE/logs/be_http_errors.jsonl` | File log JSONL ghi mọi lỗi HTTP 4xx/500 phục vụ `/api/v1/debug/logs`. |
| `REMINDER_AUDIT_LOG_PATH` | `sourceCode/BE/logs/reminder_audit.jsonl` | File log JSONL đối chiếu vòng đời nhắc hẹn (`created`, `updated`, `scheduled`, `delivered`). |

### 4. Tìm kiếm, OCR, dữ liệu & tích hợp ngoài

| Biến môi trường | Mặc định trong code | Cách dùng|
| :--- | :--- | :--- |
| `ENABLE_NEURAL_SEARCH_FALLBACK` | `"0"` (tắt) | Đặt `"1"` nếu muốn bật tầng sentence-transformer (`SEARCH_NEURAL_EMBED_MODEL`, mặc định `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`). |
| `RAG_DATA_DIR` | `sourceCode/BE/data/rag` | Thư mục lưu chỉ mục vector mã hóa cho tài liệu và học vụ. |
| `TESSERACT_CMD` | `None` (dò theo `PATH` hệ thống) | Chỉ định đường dẫn file `tesseract.exe` trên Windows nếu OCR ảnh thời khóa biểu không tìm thấy trong `PATH`. |
| `CORS_ORIGINS` | `""` | Để trống với app Kivy; chỉ điền danh sách origin cách nhau bằng dấu phẩy nếu thử nghiệm bằng client trình duyệt. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | `""` | Chỉ cần điền khi chạy test OAuth2 thật ở giai đoạn sau. |

---

## Mục 5. Cách chạy bộ test có sẵn và kết quả pass/fail gần nhất

### 1. Lệnh chạy các bộ kiểm thử có sẵn

- **Bộ test nội bộ của Backend (nhanh, dùng SQLite in-memory):**
  ```powershell
  python -m pytest sourceCode/BE/tests -q
  ```
- **Bộ đánh giá NLU tất định (`tools/eval_nlu.py` trên 30 mẫu `nlu_eval.jsonl`):**
  ```powershell
  python sourceCode/BE/tools/eval_nlu.py --rules
  ```
  (Bỏ cờ `--rules` nếu muốn đo trực tiếp với server vLLM đang bật; script tự đặt `LLM_TIMEOUT_SECONDS = 20.0` nếu biến môi trường này chưa được gán).
- **Bộ test tổng hợp ở thư mục gốc (`tests/`):**
  ```powershell
  python -m pytest tests -q
  ```
  Lưu ý: Tệp `tests/test_fe_notifier.py` import module giao diện Kivy từ `sourceCode/FE/notifier.py`. Nếu chạy trên môi trường Python chỉ cài thư viện BE (chưa cài `kivy`), dùng cờ `--ignore=tests/test_fe_notifier.py`.

### 2. Kết quả kiểm thử gần nhất (trên bản PR #29, commit `4f2cd38`)

- `python -m pytest sourceCode/BE/tests -q`: **89 passed** (`0 failed`), bao gồm bộ kiểm toán đầu-cuối `sourceCode/BE/tests/test_ai_endpoints_audit.py` và các ca hồi quy của PR #29.
- `python sourceCode/BE/tools/eval_nlu.py --rules`: **30 mẫu**, `intent_acc_pct = 100.0%`, `duration_acc_pct = 100.0%`, `hint_acc_pct = 93.3%`, `bad_dates = 0`.
- **Kiểm chứng gọi AI trực tiếp với máy chủ vLLM** (`http://26.211.52.63:8000/v1/chat/completions`, `Meta-Llama-3.1-8B-Instruct-AWQ-INT4`): **26/26** lệnh gọi live HTTP `200 OK` (21 lệnh Feature 2 NLU + 5 lệnh Feature 1 Mode B Academic KB RAG) và **2/2** lệnh ép ngoại tuyến ghi nhận đầy đủ `FALLBACK` trong `ai_calls.jsonl`, `0` lỗi.
- **Nhóm kiểm thử trọng tâm AI / NLU / Proposal / Fallback / KB trong `tests/`** (`test_ai_layer.py`, `test_nlu_and_normalizer.py`, `test_be_proposals.py`, `test_fe_fallback.py`, `test_kb_structured.py`): **124 passed, 1 skipped**.
- **Toàn bộ `python -m pytest tests -q`:** Trên môi trường chạy đầy đủ `tests/test_fe_notifier.py` (như ảnh QA ghi nhận), kết quả trước các cập nhật mới ghi nhận **531 passed, 17 failed, 26 skipped**. Trên môi trường BE thuần (chạy kèm `--ignore=tests/test_fe_notifier.py`), kết quả là **523 passed, 17 failed, 26 skipped**.


## Mục 6. Danh sách lỗi đã biết và hạn chế thiết kế hiện tại

1. **`PATCH /api/v1/events/{event_id}` trả `EventOut`, không trả object `reminders`:** Khi bật hoặc tắt `is_important`, BE cập nhật/tạo/xóa bản ghi nhắc hẹn chưa giao (`delivered_at IS NULL`) trong DB (`routers/events.py` dòng 150-164), nhưng response JSON chỉ trả schema `EventOut` (`id`, `title`, `room`, `kind`, `start_time`, `end_time`, `is_hard`, `is_important`).
2. **Kiểm tra lưới 15 phút khi tạo thủ công:** `POST /api/v1/proposals/manual` (`services/proposals.py` dòng 437-438) kiểm tra `start.minute % 15 == 0`, trong khi `end = start + timedelta(minutes=duration_minutes)` cho phép mọi `duration_minutes` trong khoảng `15..720` (nên giờ kết thúc có thể không chia hết cho 15 nếu `duration_minutes` không là bội số của 15); còn `POST /api/v1/events` không ép bước nhảy 15 phút.
3. **Truy vấn học vụ có cấu trúc (`kb_*`) giữ cả bản ghi chưa bị từ chối:** Hàm `_retrieve_structured_kb_hits` trong `services/search_engine.py` (dòng 741; kiểm tra `review_status` tại các dòng 795, 801, 845, 865, 888) lọc loại `REJECTED`, tức cả dữ liệu `APPROVED` và `PENDING` (chờ duyệt) vẫn được dùng để trả lời ở tab Tìm kiếm học vụ.
4. **Phân biệt `is_hard` và `blocks_availability`:** `EventKind.CLASS` và `EventKind.EXAM` có `is_hard = True` (không cho kéo giờ trực tiếp); `EventKind.TASK` và `EventKind.EVENT` có `is_hard = False`, nhưng trong bộ tìm ô trống (`find_free_slots`) mọi sự kiện có thời lượng dương vẫn chặn khung giờ bận để tránh xếp chồng hai task lên cùng một khoảng thời gian.
[AI đọc để giải đáp thắc mắc], hạn chế:

5. **Neo mốc giờ bắt đầu đơn lẻ (thiếu giờ kết thúc):** Câu lệnh chỉ nêu mốc giờ bắt đầu (ví dụ `"xếp lịch họp nhóm lúc 9h ngày mai"`) không bị hiểu nhầm thành thời lượng 9 tiếng mà hỏi lại thời lượng; tuy nhiên `NluResult` và `_pick_slot()` (`services/proposals.py` dòng 94-96) chỉ neo cứng khung giờ khi có đủ cặp `(requested_start, requested_end)` (như `"từ 9h đến 11h"`), nên mốc `"lúc 9h"` không được giữ lại sau khi bổ sung thời lượng.
6. **Phạm vi máy trạng thái làm rõ đa lượt (`PendingClarification`):** Chưa có giới hạn số lượt hỏi lặp (`max_turns`, chỉ có TTL 10 phút hoặc lệnh hủy / từ khóa chuyển chủ đề); `context_json` không lưu các khe phụ (`preferred_time_of_day`, `avoid_time_of_day`, `priority`, `deadline`) qua chuỗi từ 3 lượt trở lên; và khi câu gốc có thứ trùng ngày hôm nay (`date_assumed = True`) đồng thời thiếu thời lượng, cụm ngày có thể bị xóa ở lượt lưu trung gian (`routers/assistant.py` dòng 289-290).
7. **Điều kiện dữ liệu cho Academic KB (`POST /api/v1/search/academic/ask`):** Truy vấn cấu trúc yêu cầu các bảng `kb_*` trên MySQL đã nạp dữ liệu từ `database/UniInfo/`; truy vấn tài liệu văn bản yêu cầu đã nạp tệp vào `RAG_DATA_DIR` qua `POST /api/v1/search/academic/documents`. Khi không có đoạn trích đạt ngưỡng Step 3, hệ thống dừng sớm và không gọi LLM để chống ảo giác.

---

## Mục 7. Quy tắc nghiệp vụ cần kiểm (Tiêu chí Đạt / Không đạt)

1. **Chống chồng lịch & tái kiểm tra khi xác nhận:** `POST /api/v1/proposals/{id}/confirm` và `POST /api/v1/proposals/manual` chạy lại kiểm tra xung đột tại thời điểm lưu (`services/proposals.py` dòng 365-370); nếu khung giờ vừa bị sự kiện khác chiếm chỗ phải trả `409 Conflict` và giữ nguyên `Proposal` ở trạng thái `PROPOSED` (không tạo `Event`).
2. **Sự kiện `DEADLINE` không chiếm chỗ:** `EventKind.DEADLINE` được chuẩn hóa về sự kiện điểm (`end_time == start_time`), `blocks_availability = False`, và không chặn thuật toán tìm ô trống (`find_free_slots`).
3. **Vòng đời `Proposal`:** `Proposal` mới sinh có trạng thái `PROPOSED` (không có timeout tự hủy theo thời gian); chuyển sang `CONFIRMED` (confirm), `REJECTED` (reject), `RESCHEDULED` (khi tạo được đề xuất mới thay thế qua `reschedule_proposal_id`) hoặc `ABANDONED` (khi người dùng mở một yêu cầu gốc mới). Gọi lại `confirm`/`reject`/`reschedule` lên proposal không còn ở `PROPOSED` phải trả `409 Conflict`.
4. **Quy tắc Import & `replace_previous_imports`:** Cờ `replace_previous_imports=true` chỉ đối chiếu, phát hiện xung đột và thay thế các sự kiện có `source = IMPORTED`, tuyệt đối không xóa các sự kiện do người dùng tạo tay (`MANUAL`) hoặc AI xếp (`AI_CREATED`).
5. **Tôn trọng `UserPreference` (`sleep_start`, `sleep_end`, `min_break_minutes`, `max_block_minutes`):** Khung giờ AI đề xuất hoặc `/search/free-slots` không được lấn vào giờ ngủ và phải chừa tối thiểu `min_break_minutes` quanh các sự kiện đã có. Khi task dài hơn `max_block_minutes` hoặc phải tách nhiều khối (`split_task` và `schedule_pending_tasks`), mỗi khối liên tục không vượt `max_block_minutes` và giữa các khối phải chừa ít nhất `min_break_minutes` (làm tròn lên theo `slot_step_minutes`, mặc định 15 phút).
6. **Khóa sửa giờ sự kiện cứng (`CLASS`/`EXAM`):** `PATCH /api/v1/events/{event_id}` nếu gửi `start_time` hoặc `end_time` trên sự kiện có `is_hard = True` phải trả `400 Bad Request`; sửa `title`, `room` hoặc `is_important` vẫn được phép.
7. **Cô lập dữ liệu theo `owner_id` (Chống IDOR):** Mọi thao tác đọc/sửa/xóa trên `events`, `tasks`, `proposals`, `reminders` của user khác phải trả `404 Not Found` với header `X-Error-Source: BE_BUSINESS_RULE_REJECTION`, không rò rỉ dữ liệu hay để lộ mã `403`.
8. **Làm rõ đa lượt và dời lịch (`PendingClarification`):** Hỏi tuần tự 1 khe bắt buộc mỗi lượt (ưu tiên ngày -> thời lượng -> tên hoạt động), hỗ trợ trả lời gộp nhiều khe trong 1 lượt, hủy lệnh (`hủy`/`cancel`) và chuyển chủ đề có từ khóa, bảo toàn `reschedule_proposal_id` qua các lượt làm rõ, hết hạn sau 10 phút.
9. **Chế độ Fallback và đồng bộ khung giờ thủ công:** Phản hồi LLM khỏe mạnh trả `intent = "unknown"` không kích hoạt `fallback_mode = True`; khi AI lỗi thực sự, `available_slots` trả về phải khớp `duration_minutes` hoặc `(requested_start, requested_end)`, xác nhận từ `ManualFallbackModal` giữ đúng biên khung giờ đã chọn, và `ProposalCard` không bị khóa vĩnh viễn khi gặp lỗi tạm thời (`on_error`, `401`, `409` xung đột lịch).
10. **Truy vấn học vụ RAG 6 bước (`POST /api/v1/search/academic/ask`):** Giới hạn ngữ cảnh trong cửa sổ `max_model_len = 2048`, dùng timeout riêng 8 giây (`ACADEMIC_LLM_TIMEOUT_SECONDS`), dừng sớm không gọi LLM ở Step 3 khi điểm truy xuất thấp, từ chối có căn cứ khi câu hỏi ngoài phạm vi học vụ, và tự động fallback sang trích đoạn tài liệu khi vLLM ngoại tuyến.

---

## Mục 8. Cách tạo dữ liệu thử và dọn dẹp (Tài khoản test, xóa user thử)

Mỗi lần gọi `/api/v1/assistant/understand` đều tạo bản ghi mới trong `pending_clarifications`, `tasks` hoặc `proposals` (khi tạo được đề xuất). Khuyến nghị quy trình chuẩn bị, cấp phát và dọn dữ liệu thử cho QA:

0. **Chuẩn bị trước phiên đo QA trên máy của Nguyên (máy chạy BE cục bộ):**
   - Merge PR #29 vào `main`, sau đó trên máy của Nguyên chạy `git pull`, cập nhật thư viện (`pip install -r sourceCode/BE/requirements.txt`), và khởi động lại `uvicorn` (xem checklist chi tiết tại **Mục 9** bên dưới).
   - Bảo đảm kết nối Radmin VPN tới máy chủ AI của Duy (`26.211.52.63:8000`) và cấu hình đúng `VLLM_ENDPOINT`, `LLM_ALLOWED_HOSTS` trong `sourceCode/BE/.env`.
   - Gọi `GET http://127.0.0.1:8080/api/v1/debug/logs?limit=5` kiểm tra `ai_runtime_config.endpoint_allowed == true` và `vllm_endpoint` trỏ đúng máy chủ vLLM của Duy (`http://26.211.52.63:8000/v1/chat/completions`).
   - Nếu đo Feature 1 Mode B, xác nhận các bảng `kb_*` trên MySQL đã có dữ liệu và tài liệu cần thiết đã được nạp qua `POST http://127.0.0.1:8080/api/v1/search/academic/documents` vào `RAG_DATA_DIR` cục bộ.
   - Gửi 1 câu xếp lịch làm nóng vLLM trước khi bắt đầu bấm giờ đo hàng loạt.

1. **Tạo tài khoản test mới qua API công khai:**
   - Gọi `POST /api/v1/auth/register` với `username` riêng theo ca/ngày (ví dụ `qa_nguyen_01`, `qa_duy_load_01`), `password` tối thiểu 6 ký tự và `display_name`. BE tự tạo đồng thời các bản ghi ở `users`, `auth_identities` và `user_preferences` mặc định (`23:30 - 06:30`, `min_break_minutes = 15`, `max_block_minutes = 180`), trả kèm `access_token` và `user_id`.
2. **Dọn dữ liệu trung gian trong quá trình test lặp qua API:**
   - Xóa mềm sự kiện hoặc công việc: `DELETE /api/v1/events/{event_id}` và `DELETE /api/v1/tasks/{task_id}` (đều trả `204 No Content`).
   - Dọn lịch import cũ: gọi `POST /api/v1/ingestion/commit` kèm `replace_previous_imports: true` để thay thế tập sự kiện `IMPORTED` trước đó.
   - Đóng `Proposal` nháp đang treo: gọi `POST /api/v1/proposals/{id}/reject`, hoặc gửi một câu lệnh xếp lịch gốc mới (không truyền `reschedule_proposal_id`) để tự động đóng toàn bộ `PROPOSED` cũ sang `ABANDONED`.
3. **Xóa hoàn toàn tài khoản thử trong MySQL khi kết thúc đợt test (nhờ `ON DELETE CASCADE`):**
   - Toàn bộ bảng dữ liệu người dùng (`auth_identities`, `pending_clarifications`, `user_preferences`, `courses`, `tasks`, `proposals`, `events`, `reminders`) đều gắn khóa ngoại `ON DELETE CASCADE` tới `users.id` (còn 3 bảng log đặt `user_id` là `ON DELETE SET NULL`).
   - Do đó, để xóa sạch toàn bộ dữ liệu lịch, task, đề xuất của user thử trên MySQL Docker (`schedule_db`), chỉ cần chạy truy vấn xóa dòng trong `users`:
     ```sql
     SELECT id, display_name FROM users WHERE display_name LIKE 'QA_%';
     DELETE FROM users WHERE id IN (<danh_sach_id_can_xoa>);
     ```
   - Lưu ý tách biệt với `TEST_DATABASE_URL`: không bao giờ gán `TEST_DATABASE_URL` vào DB MySQL đang chứa dữ liệu QA chung vì khi `pytest` chạy có thể drop/recreate bảng trên `TEST_DATABASE_URL`.

---

## Mục 9. Checklist chuẩn bị kết nối AI trên máy chạy BE (máy của Nguyên)

Khi máy của Nguyên vừa chạy app/bot kiểm thử (FE) vừa chạy trực tiếp Backend (BE cục bộ) để kết nối tới máy chủ AI (vLLM trên máy Duy tại `26.211.52.63:8000`) và MySQL, cần thực hiện đủ 6 bước sau trước khi chốt phiên bản đo:

### Bước 1 - Đồng bộ mã nguồn PR #29
- Sau khi pull code mới, cập nhật lại thư viện môi trường Python của BE:
  ```powershell
  pip install -r sourceCode/BE/requirements.txt
  ```

### Bước 2 - Kiểm tra mạng Radmin VPN và thông luồng tới máy chủ AI của Duy (`26.211.52.63:8000`)
- Bật Radmin VPN trên máy của Nguyên và bảo đảm đang nối chung mạng ảo với máy của Duy.
- Kiểm tra kết nối trực tiếp tới vLLM từ PowerShell trên máy của Nguyên:
  ```powershell
  Invoke-RestMethod http://26.211.52.63:8000/v1/models
  ```
- Yêu cầu kết quả phải trả HTTP `200` kèm tên model `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`. Nếu lệnh này thất bại, cần xử lý kết nối Radmin VPN, tường lửa cổng `8000`, hoặc bật container vLLM trên máy Duy trước khi khởi động BE.

### Bước 3 - Tạo hoặc cập nhật tệp `sourceCode/BE/.env` trên máy của Nguyên
- Cơ chế nạp biến môi trường của `sourceCode/BE/services/llm_config.py`: đọc `sourceCode/Database/assistant_deploy/.env` trước, ghi đè bằng `sourceCode/BE/.env`, và ưu tiên cao nhất cho biến môi trường đã thiết lập trực tiếp trong shell hiện tại. Cần bảo đảm terminal chạy BE không giữ sẵn biến `VLLM_ENDPOINT` cũ trỏ về `127.0.0.1`.
- Cấu hình mẫu cho tệp `sourceCode/BE/.env` trên máy của Nguyên:
  ```env
  VLLM_ENDPOINT=http://26.211.52.63:8000/v1/chat/completions
  LLM_ALLOWED_HOSTS=26.211.52.63
  LLM_MODEL=hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4
  LLM_TIMEOUT_SECONDS=3.0
  ACADEMIC_LLM_TIMEOUT_SECONDS=8.0
  DATABASE_URL=mysql+pymysql://<DB_USER>:<DB_PASSWORD>@<DB_HOST>:3307/university_assistant?charset=utf8mb4
  JWT_SECRET_KEY=<chuoi_bi_mat_toi_thieu_32_ky_tu>
  DATA_ENCRYPTION_KEY=<khoa_ma_hoa_rag>
  RAG_DATA_DIR=sourceCode/BE/data/rag
  ```
- Lưu ý bắt buộc: `LLM_ALLOWED_HOSTS=26.211.52.63` là tham số không thể thiếu vì `sourceCode/BE/services/privacy.py` chặn toàn bộ địa chỉ IP nằm ngoài dải RFC1918 và Tailscale nếu không được khai báo trong danh sách cho phép này.

### Bước 4 - Khởi chạy server BE cục bộ và kiểm tra cấu hình FE trên máy của Nguyên
- Mở terminal tại thư mục `sourceCode/BE` và khởi chạy máy chủ FastAPI:
  ```powershell
  uvicorn main:app --host 127.0.0.1 --port 8080
  ```
  Mỗi lần thay đổi tệp `.env` hoặc kéo commit mới đều phải khởi động lại tiến trình `uvicorn` để nạp cấu hình và mã nguồn mới.
- Kiểm tra cấu hình kết nối phía FE (`sourceCode/FE/api_client.py`): bảo đảm biến môi trường `ASSISTANT_API_URL` (nếu có) và khóa `settings.base_url` lưu trong `auth_session.json` trỏ đúng về `http://127.0.0.1:8080` (cổng `8080` của server BE, tuyệt đối không trỏ nhầm sang cổng `8000` của vLLM hoặc IP của máy khác).

### Bước 5 - Điều kiện dữ liệu DB và kho tài liệu Academic KB trên máy BE
- Gọi `GET http://127.0.0.1:8080/health/db` để xác nhận kết nối MySQL thông suốt (`{"status": "ok", "database": "ok"}`).
- Bảng `pending_clarifications` được tự động tạo khi chạy nhờ hàm `_ensure_clarification_table` trong `sourceCode/BE/routers/assistant.py`; tài khoản MySQL cấu hình trong `DATABASE_URL` cần có quyền `CREATE TABLE` trên schema `university_assistant` (hoặc chạy sẵn câu lệnh tạo bảng từ `sourceCode/Database/assistant_deploy/init.sql`).
- Nếu bot kiểm thử có chạy Feature 1 Mode B (`POST /api/v1/search/academic/ask`):
  - Các bảng `kb_*` (`kb_faculties`, `kb_departments`, `kb_lecturers`, `kb_programs`, `kb_courses`, `kb_sources`) trên MySQL phải đã được nạp dữ liệu từ `database/UniInfo/`.
  - Các tệp tài liệu văn bản (sổ tay sinh viên, quy chế, chương trình đào tạo) phải được nạp vào `RAG_DATA_DIR` cục bộ trên máy của Nguyên thông qua `POST http://127.0.0.1:8080/api/v1/search/academic/documents` (vì chỉ mục vector lưu trực tiếp trên ổ đĩa của máy chạy BE, không đồng bộ qua MySQL).

### Bước 6 - Tiền kiểm qua `/api/v1/debug/logs`, làm nóng vLLM và bảng chẩn đoán nhanh
- Gọi `GET http://127.0.0.1:8080/api/v1/debug/logs?limit=10` và kiểm tra đối tượng `ai_runtime_config`:
  - `vllm_endpoint`: `"http://26.211.52.63:8000/v1/chat/completions"`
  - `model`: `"hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"`
  - `endpoint_allowed`: `true`
  - `allowed_hosts_configured`: `true`
- Trước khi cho bot bấm giờ đo hàng loạt, gửi trước 1 yêu cầu làm nóng (warm-up, ví dụ `"Xếp 1 tiếng đọc sách ngày mai"`), rồi kiểm tra lại `GET http://127.0.0.1:8080/api/v1/debug/logs?limit=5`. Nếu bản ghi `recent_ai_calls[0]` hiển thị `status == "OK"`, `source == "llm"`, `http_status == 200` và có đối tượng `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`), kết nối BE -> AI đã sẵn sàng.

| Dấu hiệu `FALLBACK` trên `/api/v1/debug/logs` | Nguyên nhân và cách xử lý trên máy Nguyên / máy Duy |
| :--- | :--- |
| `endpoint_allowed: false` hoặc lỗi `refusing to send schedule data to non-private endpoint` | Thiếu `LLM_ALLOWED_HOSTS=26.211.52.63` trong `sourceCode/BE/.env`, sai tên biến môi trường, hoặc chưa khởi động lại `uvicorn`. |
| `INFRA_CRASH: ConnectError` hoặc `ConnectTimeout` | Mất kết nối Radmin VPN tới `26.211.52.63`, tường lửa chặn cổng `8000`, hoặc container `local_llama_inference` (vLLM) trên máy Duy chưa chạy. |
| `TIMEOUT: ReadTimeout` | vLLM đang khởi tạo lần đầu (cold start) hoặc GPU trên máy Duy quá tải vượt ngưỡng `3.0s` (NLU) / `8.0s` (Academic RAG). |
| `INFRA_CRASH: HTTPStatusError` với mã `404` | Giá trị `LLM_MODEL` trong `.env` không khớp đúng tên model đang phục vụ trên máy chủ vLLM của Duy (`hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`). |
