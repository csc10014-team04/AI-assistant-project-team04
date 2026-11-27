# Hướng dẫn chạy và kiểm thử cho QA — University Life Assistant

Tài liệu này là bản hướng dẫn từng bước. Đọc cùng với:
- `BE_QA.md`: API, mã phản hồi, biến môi trường, quy tắc nghiệp vụ, checklist kết nối AI (do nhóm BE viết).
- `FE_QA.md`: màn hình, nhãn nút, luồng người dùng, log của app (do nhóm FE viết).
- `QA_README.md`: tóm tắt nhanh và danh sách lỗi đã biết.
- `QA_Report.md`: báo cáo QA với số liệu đã đo.

Quy ước: lệnh PowerShell chạy tại thư mục gốc repo `AI-assistant-project-team04` (nơi có thư mục `sourceCode`), trừ khi ghi khác.

---

## Phần A. Chuẩn bị máy QA (làm một lần)

| Bước | Việc | Lệnh / kiểm tra | Kết quả mong đợi |
|---|---|---|---|
| A1 | Cài Python 3.12 hoặc 3.13 (không dùng 3.14 vì Kivy không cài được) | `py -3.12 --version` | `Python 3.12.x` |
| A2 | Tạo môi trường ảo | `py -3.12 -m venv .venv` | Có thư mục `.venv` |
| A3 | Kích hoạt (gõ đúng `Activate.ps1`) | `.\.venv\Scripts\Activate.ps1` | Dấu nhắc có `(.venv)`. Nếu bị chặn: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| A4 | Cài thư viện đầy đủ (backend, FE, test) | `python -m pip install -r requirements-fullStack.txt` | Không báo lỗi |
| A5 | Cài công cụ QA | `python -m pip install -r "QA  docs\requirements-qa.txt"` | Không báo lỗi |
| A6 | (Tùy chọn) Tesseract OCR để thử import bằng ảnh | Cài chương trình Tesseract kèm dữ liệu ngôn ngữ `vie`; nếu không có trong `PATH`, đặt `TESSERACT_CMD` | Không có thì import ảnh báo lỗi 422 "thiếu Tesseract", không phải lỗi app |
| A7 | Kiểm tra nhanh toàn bộ | `.\"QA  docs"\run_qa.ps1` | Bảng tóm tắt (xem Phần C) |

Hai điều hay nhầm:
- Gõ đường dẫn file `.py` mà không có `python -m pytest` thì Windows chỉ mở VS Code.
- Đứng sai thư mục thì báo `file or directory not found`. Luôn `cd` vào thư mục gốc repo.

---

## Phần B. Dựng môi trường để kiểm thử

Có hai cách. Chọn **B1 nếu chỉ chạy test tự động**, **B2 để thử API/giao diện với dữ liệu thật**.

### B1. Chỉ chạy test tự động (không cần dịch vụ nào)
Bộ test dùng SQLite trong bộ nhớ và mô phỏng LLM. Không cần MySQL, vLLM hay mạng. Chuyển sang Phần C.

### B2. Chạy backend và giao diện thật

Theo `BE_QA.md` mục 9, gồm 6 bước. Tóm tắt:

1. **Kiểm tra máy chủ AI (vLLM)** từ máy QA:
   ```powershell
   Invoke-RestMethod http://26.211.52.63:8000/v1/models
   ```
   Phải thấy `hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4`. Nếu lỗi: kiểm tra Radmin VPN, tường lửa cổng 8000, hoặc bật vLLM trên máy host.
2. **Cấu hình `sourceCode/BE/.env`** (mẫu có trong `BE_QA.md` mục 9, bước 3). Bắt buộc có `VLLM_ENDPOINT`, `LLM_ALLOWED_HOSTS=26.211.52.63`, `DATABASE_URL`, `JWT_SECRET_KEY`, `DATA_ENCRYPTION_KEY`. Không đưa giá trị thật lên git hoặc báo cáo.
3. **Bật MySQL**: `docs/Guide_2_Connect_to_Database.md`, thường là `docker compose up -d db` trong `sourceCode/Database/assistant_deploy`. Kiểm tra: `(Test-NetConnection 127.0.0.1 -Port 3307).TcpTestSucceeded` phải là `True`.
4. **Chạy backend** (từ `sourceCode\BE`, mỗi lần đổi `.env` hoặc `git pull` phải chạy lại):
   ```powershell
   cd sourceCode\BE
   uvicorn main:app --host 127.0.0.1 --port 8080
   ```
5. **Kiểm tra sức khỏe backend** (mở cửa sổ PowerShell khác):
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8080/health          # {"status":"ok"}
   Invoke-RestMethod http://127.0.0.1:8080/health/db       # {"status":"ok","database":"ok"}
   (Invoke-RestMethod http://127.0.0.1:8080/api/v1/debug/logs?limit=5).ai_runtime_config
   ```
   Trong `ai_runtime_config` phải có `endpoint_allowed: true` và `vllm_endpoint` đúng máy chủ AI.
6. **Làm nóng vLLM** bằng một yêu cầu thử, rồi xem `recent_ai_calls[0]` có `status == "OK"`, `source == "llm"`, `http_status == 200`.
7. **Chạy ứng dụng giao diện** (cửa sổ khác, cùng `.venv`):
   ```powershell
   $env:ASSISTANT_API_URL="http://127.0.0.1:8080"
   python sourceCode\FE\main.py
   ```
   Nếu app gọi nhầm địa chỉ cũ, xóa cài đặt đã lưu (`settings.base_url` trong `auth_session.json`) rồi chạy lại, và đăng xuất/đăng nhập lại.

**Bước bắt buộc trước mọi đợt test trên máy host:** xác nhận host đang chạy bản backend mới nhất.
```powershell
(Invoke-RestMethod http://<IP_host>:8080/openapi.json).paths.PSObject.Properties.Name | Sort-Object
```
Phải thấy `/api/v1/debug/logs`, `/api/v1/events`, `/api/v1/user/preferences`. Nếu thiếu, host đang chạy bản cũ: yêu cầu người giữ host `git pull` và chạy lại `uvicorn`. Mọi kết quả đo trên bản cũ không có giá trị.

---

## Phần C. Chạy toàn bộ test tự động

```powershell
.\.venv\Scripts\Activate.ps1
.\"QA  docs"\run_qa.ps1                  # nhanh, khoảng 4 phút
.\"QA  docs"\run_qa.ps1 -All             # thêm độ phủ, phân tích tĩnh, đo độ trễ (khoảng 10 phút)
```

Script chạy mỗi nhóm trong tiến trình riêng (vì repo có hai `conftest.py`, và test Kivy có thể làm sập tiến trình) và lưu log từng nhóm vào `QA  docs\last_run\`.

Xem test nào fail và lý do:
```powershell
Select-String -Path "QA  docs\last_run\*.log" -Pattern "^FAILED"
```

### C1. Các bộ test và cách chạy riêng

| # | Nhóm | Lệnh | Ghi chú |
|---|---|---|---|
| 1 | Bộ chính | `python -m pytest tests -q --ignore=tests/test_fe_notifier.py --ignore=tests/test_fe_event_store.py --ignore=tests/test_fe_fallback.py --ignore=tests/test_frontend.py` | Gồm cả các test QA (free-slot, parser, RAG) |
| 2 | Giao diện Kivy | `$env:KIVY_NO_ARGS="1"; python -m pytest tests/test_fe_notifier.py tests/test_fe_event_store.py tests/test_fe_fallback.py tests/test_frontend.py -q` | Cần Kivy; chạy riêng vì có thể sập tiến trình |
| 3 | Backend | `python -m pytest sourceCode/BE/tests -q` | Chạy riêng, không gộp với nhóm 1 |
| 4 | NLU (luật) | `cd sourceCode\BE; python tools/eval_nlu.py --rules` | 200 ca |
| 5 | Free-slot | `python -m pytest tests/test_free_slots_accuracy.py -s` | In số ca khớp bản tham chiếu và p95 |
| 6 | Parser/import | `python -m pytest tests/test_parser_import.py -s` | 5 xfail là lỗi đã biết, bình thường |
| 7 | RAG | `python -m pytest tests/test_rag_quality.py -s` | In bảng chất lượng và bảng quét ngưỡng |
| 8 | split_task, mã hóa | `python -m pytest test_split_task.py test_crypto.py -q` | Vị trí file có thể đổi; script tự tìm |
| 9 | Độ trễ | `cd sourceCode\BE; python ..\..\bench_pure.py --runs 300 --json ..\..\"QA  docs"\bench_results.json` | Cắm sạc, đóng chương trình khác |
| 10 | Độ phủ | `python -m pytest tests --cov=sourceCode/BE --cov-branch --cov-report=term-missing:skip-covered -q` (kèm các `--ignore` của nhóm 1) | |
| 11 | Phân tích tĩnh | `ruff check sourceCode\BE --exclude sourceCode/BE/.venv` · `mypy sourceCode\BE --ignore-missing-imports` · `bandit -r sourceCode\BE -x sourceCode/BE/.venv,sourceCode/BE/tests` · `radon cc -s -a sourceCode\BE\services sourceCode\BE\routers` | |
| 12 | Dữ liệu tri thức (KB) | `python -m pytest tests/test_kb_crawler.py tests/test_kb_structured.py -q -rs` | Phải có `beautifulsoup4`; nếu thấy `skipped` là thiếu thư viện |

### C2. Đo NLU với LLM thật (cần vLLM)
```powershell
cd sourceCode\BE
$env:VLLM_ENDPOINT="http://26.211.52.63:8000/v1/chat/completions"
$env:LLM_ALLOWED_HOSTS="26.211.52.63"
1..3 | ForEach-Object { python tools/eval_nlu.py }
```
Ghi từng lần: `schema_adherence_pct`, `fallback`, `intent_acc_pct`, `duration_acc_pct`, `hint_acc_pct`, `bad_dates`. Báo trung bình và khoảng tin cậy Wilson 95%.
Cách đọc: `schema_adherence_pct` chỉ có ý nghĩa ở chế độ LLM (SLO ≥ 98%, `bad_dates` = 0).

### C3. Cách đọc kết quả
- `N passed` là tốt. `skipped` phải xem lý do (`-rs`), thường là thiếu thư viện.
- `xfailed` là lỗi đã biết, có test tái hiện. `XPASS` nghĩa là lỗi đã được sửa: gỡ đánh dấu xfail.
- `ended without a summary` (do script báo): tiến trình pytest bị sập, chạy nhóm đó riêng.
- Mọi tỉ lệ khi đưa vào báo cáo phải kèm số mẫu `n` và khoảng tin cậy.

---

## Phần D. Kiểm thử API thủ công (backend)

Biến dùng chung (đổi địa chỉ nếu thử trên host):
```powershell
$BASE = "http://127.0.0.1:8080"
function Api($method, $path, $body = $null, $token = $null) {
    $h = @{}; if ($token) { $h["Authorization"] = "Bearer $token" }
    $args = @{ Method = $method; Uri = "$BASE$path"; Headers = $h; UseBasicParsing = $true; ErrorAction = "Stop" }
    if ($body) { $args["Body"] = ($body | ConvertTo-Json -Depth 6); $args["ContentType"] = "application/json" }
    try { $r = Invoke-WebRequest @args } catch { $r = $_.Exception.Response }
    [pscustomobject]@{ Status = [int]$r.StatusCode; Source = $r.Headers["X-Error-Source"]; RequestId = $r.Headers["X-Request-ID"]; Ms = $r.Headers["X-Process-Time-Ms"] }
}
```
Tạo tài khoản thử (đặt tên có tiền tố `QA_` để dọn dễ, xem Phần F):
```powershell
$u = "qa_$(Get-Random -Maximum 99999)"
$reg = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/register" -ContentType "application/json" `
        -Body (@{ username = $u; password = "Passw0rd!"; display_name = "QA_$u" } | ConvertTo-Json)
$T = $reg.access_token
```

Mỗi dòng dưới đây là một ca test: gửi yêu cầu, so với kết quả mong đợi (lấy từ `BE_QA.md` mục 2 và 7).

| ID | Ca test | Lệnh (rút gọn) | Mong đợi |
|---|---|---|---|
| API-01 | Đăng ký trùng tên | gọi `register` lần hai với cùng `username` | `409` |
| API-02 | Mật khẩu ngắn | `register` với password 5 ký tự | `422` (quy tắc hiện tại: tối thiểu 6 ký tự) |
| API-03 | Đăng nhập sai | `login` sai mật khẩu | `401` |
| API-04 | Không token | `Api GET /api/v1/tasks` không token | `401` |
| API-05 | Tạo sự kiện hợp lệ | `Api POST /api/v1/events` với `title`, `kind="EVENT"`, `start_time`, `end_time` (ISO `+07:00`) | `201` |
| API-06 | Giờ kết thúc ≤ giờ bắt đầu | như API-05 nhưng `end_time = start_time` (kind khác DEADLINE) | `422` |
| API-07 | Chống IDOR | tài khoản B gọi `PATCH`/`DELETE` lên `event_id` của A | `404`, header `X-Error-Source: BE_BUSINESS_RULE_REJECTION` |
| API-08 | Xóa mềm | `DELETE /api/v1/events/{id}` | `204`; gọi lại → `404` |
| API-09 | Sửa giờ sự kiện cứng | tạo lịch bằng import (CLASS) rồi `PATCH` `start_time` | `400` |
| API-10 | Sai đường dẫn | `GET /api/v1/khong-ton-tai` | `404`, `X-Error-Source: FASTAPI_ROUTER_URL_NOT_FOUND` |
| API-11 | Header chẩn đoán | mọi phản hồi | có `X-Request-ID`, `X-Process-Time-Ms` |
| API-12 | Xếp lịch bằng AI | `POST /api/v1/assistant/understand` với `{"prompt": "xếp 2 tiếng học bài ngày mai"}` | `200`, có `proposal` hoặc `available_slots` |
| API-13 | Thiếu thời lượng | prompt `"xếp lịch học bài"` | `200`, `nlu.needs_clarification = true`, chưa tạo `proposal` |
| API-14 | Xác nhận đề xuất | `POST /api/v1/proposals/{id}/confirm` | `200`, có `events` và `reminders` |
| API-15 | Xác nhận lại | gọi `confirm` lần hai | `409` |
| API-16 | Từ chối | `POST /api/v1/proposals/{id}/reject` | `200`; sau đó `confirm` → `409` |
| API-17 | Chọn giờ thủ công trùng lịch | `POST /api/v1/proposals/manual` vào khung đã bận | `409` |
| API-18 | Slot lệch lưới 15 phút | `slot_start` phút lẻ (ví dụ `09:07`) | `422` |
| API-19 | Fallback khi AI sập | đặt `VLLM_ENDPOINT=http://127.0.0.1:1/v1/chat/completions`, chạy lại backend, gọi `understand` | `200`, `fallback_mode = true`, có `available_slots`, không bao giờ `500` |
| API-20 | Lệnh tìm kiếm ở khung chat | prompt `"ngày mai có lịch gì"` vào `understand` | `redirect_target = "search_home"` |
| API-21 | Lệnh xếp lịch ở khung tìm kiếm | `GET /api/v1/search/events?q=xếp 2 tiếng học bài` | `redirect_target = "chat_home"` |
| API-22 | Ngoài phạm vi học vụ | `POST /api/v1/search/academic/ask` hỏi chuyện không liên quan | từ chối có căn cứ, không gọi LLM |
| API-23 | Sinh viên thử file không phải thời khóa biểu | `POST /api/v1/ingestion/parse-preview` với ảnh/tệp lạ | `422` (`NO_TIMETABLE_DETECTED`) |
| API-24 | Import thay thế | `POST /api/v1/ingestion/commit` với `replace_previous_imports=true` | chỉ thay `IMPORTED`, giữ nguyên `MANUAL` và `AI_CREATED` |

Mẹo: Swagger UI tại `$BASE/docs` cho phép thử mọi endpoint và xem đúng định dạng body. Dùng `X-Request-ID` của phản hồi để tra `GET /api/v1/debug/logs`.

---

## Phần E. Kiểm thử giao diện thủ công (FE)

Môi trường: backend đang chạy (Phần B2), app chạy bằng `python sourceCode\FE\main.py`. Nhãn nút trên giao diện viết **in hoa**; ghi đúng như thấy. Với mỗi ca ghi: Đạt / Không đạt, ảnh chụp màn hình, và đính kèm khối chẩn đoán trong `sourceCode\FE\fe_http_debug.log` nếu có lỗi HTTP.

### E1. Đăng nhập / đăng ký
| ID | Bước | Mong đợi |
|---|---|---|
| FE-AU-01 | Mở app | Hiện màn hình đăng nhập |
| FE-AU-02 | Nhập đúng tài khoản, nhấn `LOG IN` | Vào màn hình Calendar |
| FE-AU-03 | Nhập sai mật khẩu, nhấn `LOG IN` | Hiện thông báo sai thông tin, vẫn ở màn hình đăng nhập |
| FE-AU-04 | Nhấn `SWITCH TO REGISTER` | Sang màn hình đăng ký |
| FE-AU-05 | Điền hợp lệ, nhấn `CREATE ACCOUNT` | Lưu tài khoản, quay về form đăng nhập |
| FE-AU-06 | Đăng ký trùng tên | Báo trùng tên đăng nhập |
| FE-AU-07 | Đăng ký mật khẩu 5 ký tự | Báo lỗi dữ liệu |
| FE-AU-08 | Nút Google / GitHub | Chưa có (hạn chế đã biết): ghi nhận, không báo lỗi trùng |

### E2. Màn hình lịch chính
| ID | Bước | Mong đợi |
|---|---|---|
| FE-CA-01 | Nhấn tiêu đề tháng/năm, chọn tháng khác | Lịch chuyển sang tháng đó |
| FE-CA-02 | Nhấn một ô ngày | Chuyển sang xem tuần, có hiệu ứng trượt, nút Menu thành Back |
| FE-CA-03 | Ở chế độ tháng nhấn nút Menu | Mở menu bên trái |
| FE-CA-04 | Nhấn nút `+` | Hiện hai nút Add event và Import scheduling |
| FE-CA-05 | Ô ngày hôm nay | Có viền màu; ngày có sự kiện quan trọng có dấu `!` đỏ |
| FE-CA-06 | Ngày có đúng 1 hạn chót | Banner hiện tên hạn chót; nhấn mở chi tiết |
| FE-CA-07 | Ngày có ≥ 2 hạn chót | Banner `DLS:{số lượng}`; nhấn mở danh sách, chọn một mở chi tiết |
| FE-CA-08 | Thanh dưới | Ba nút Calendar, Search, AI Assistant chuyển đúng màn hình |

### E3. Thêm sự kiện, chi tiết sự kiện
| ID | Bước | Mong đợi |
|---|---|---|
| FE-EV-01 | `+` → Add event, nhập đủ, nhấn Save | Sự kiện xuất hiện đúng ngày giờ trên lịch; có trong database |
| FE-EV-02 | Add event rồi nhấn `CANCEL` | Đóng cửa sổ, không thêm gì |
| FE-EV-03 | Nhấn một Event Block | Mở cửa sổ chi tiết |
| FE-EV-04 | Edit time → Save | Giờ mới được lưu và hiển thị |
| FE-EV-05 | Edit time → Cancel | Chỉ đóng cửa sổ sửa |
| FE-EV-06 | Bật/tắt Important | Dấu `!` cập nhật trên lịch và lưu database |
| FE-EV-07 | Đổi thời gian Remind | Lưu lại; sau khi mở lại vẫn đúng |
| FE-EV-08 | `DELETE EVENT` | Sự kiện biến mất khỏi lịch và database; cửa sổ đóng |
| FE-EV-09 | `CLOSE` | Đóng cửa sổ |
| FE-EV-10 | Sửa giờ sự kiện CLASS/EXAM (cứng) | Bị từ chối (backend `400`) với thông báo dễ hiểu |

### E4. Import thời khóa biểu (3 bước)
| ID | Bước | Mong đợi |
|---|---|---|
| FE-IM-01 | `+` → Import scheduling → `CHOOSE FILE FROM DEVICE` | Chỉ hiện `.csv .txt .md .png .jpg .jpeg` |
| FE-IM-02 | Chọn file mẫu `sourceCode/Database/user_data/samples/timetable_sample.csv`, nhấn `ANALYZE` | Nút khóa khi đang chạy; sau đó sang bước 2 với danh sách sự kiện |
| FE-IM-03 | File có dòng lỗi (giờ 25:00, ngày sai) | Dòng lỗi hiển thị riêng, dòng hợp lệ vẫn dùng được, app không sập |
| FE-IM-04 | Bước 2, nhấn `CONTINUE TO CONFLICT CHECK` | Bước 3 hiện sự kiện hợp lệ và sự kiện xung đột |
| FE-IM-05 | `SAVE NON-CONFLICTING` | Chỉ lưu sự kiện an toàn |
| FE-IM-06 | `SAVE ALL` | Lưu toàn bộ, kể cả xung đột |
| FE-IM-07 | `CANCEL` ở mỗi bước | Đóng cửa sổ, không lưu |
| FE-IM-08 | Import lại file mới (thay thế) | Chỉ thay sự kiện đã import, giữ sự kiện tạo tay và do AI xếp |
| FE-IM-09 | File ảnh không phải thời khóa biểu / máy chủ thiếu Tesseract | Thông báo lỗi rõ ràng |
| FE-IM-10 | File CSV xuất từ Excel (UTF-8 có BOM) | **Lỗi đã biết**: dòng tiêu đề hiện như dòng lỗi |

### E5. Tìm kiếm
| ID | Bước | Mong đợi |
|---|---|---|
| FE-SE-01 | Tab Search, chọn `My Scheduling`, nhập từ khóa, nhấn Search | Danh sách sự kiện khớp, tối đa 30 |
| FE-SE-02 | Mở Filter, chọn loại sự kiện và Important, `Apply and Search` | Chỉ hiện loại đã chọn; chọn Important chỉ hiện sự kiện quan trọng |
| FE-SE-03 | Chọn `Academic Q&A`, hỏi một câu học vụ | Có câu trả lời kèm trích dẫn; khi AI sập, trả trực tiếp đoạn trích gốc |
| FE-SE-04 | Nhập lệnh xếp lịch vào ô tìm kiếm | Có nút điều hướng sang trợ lý AI |
| FE-SE-05 | Nhấn một kết quả sự kiện | Mở chi tiết sự kiện |

### E6. Trợ lý AI
| ID | Bước | Mong đợi |
|---|---|---|
| FE-AI-01 | Gửi `xếp 2 tiếng học bài ngày mai` | Hiện đề xuất kèm ba nút `Confirm`, `Reject`, `Reschedule` |
| FE-AI-02 | `Confirm` | Sự kiện vào lịch, Calendar cập nhật, kết thúc phiên đề xuất |
| FE-AI-03 | `Reject` | Kết thúc phiên đề xuất, không thêm sự kiện |
| FE-AI-04 | `Reschedule` rồi gõ `dời sang buổi tối` | Hiện banner nhắc; tin nhắn kế tiếp tạo đề xuất mới thay thế |
| FE-AI-05 | Gửi `xếp lịch học bài` (thiếu thời lượng) | Trợ lý hỏi lại thời lượng, chưa tạo đề xuất |
| FE-AI-06 | Gửi câu ngoài phạm vi (`hôm nay trời đẹp quá`) | Trả lời hợp lý, không tạo đề xuất, không báo lỗi |
| FE-AI-07 | Tắt vLLM hoặc đặt endpoint sai rồi gửi lệnh xếp lịch | Hiện cửa sổ chọn giờ thủ công ngay |
| FE-AI-08 | Cửa sổ thủ công: chọn khung, `CONFIRM` | Sự kiện được thêm đúng khung đã chọn |
| FE-AI-09 | Cửa sổ thủ công: `CANCEL` | Quay lại khung chat, chat không bị khóa |
| FE-AI-10 | Gửi lệnh xem lịch vào khung chat | Có nút điều hướng sang màn hình Search |
| FE-AI-11 | Gửi liên tiếp nhiều câu | Không bị mất tin; trả lời đúng thứ tự |

### E7. Nhắc hẹn (chạy ngầm)
| ID | Bước | Mong đợi |
|---|---|---|
| FE-NO-01 | Tạo sự kiện quan trọng có Remind ngắn, chờ đến giờ | Cửa sổ thông báo hiện địa điểm, tên sự kiện, thời gian |
| FE-NO-02 | Nhấn `Confirm` | Đóng thông báo, báo về máy chủ đã gửi |
| FE-NO-03 | Nhấn `Snooze` | Ẩn thông báo, nhắc lại sau 5 phút (mặc định) |
| FE-NO-04 | Không bấm gì 60 giây | Tự động báo lại |
| FE-NO-05 | Đổi thời gian báo lại xuống 1 phút | Nhắc lại sau 1 phút |
| FE-NO-06 | Đóng app trước giờ nhắc | **Hạn chế đã biết:** không có thông báo (nhắc hẹn chỉ chạy khi app đang mở) |
| FE-NO-07 | Nội dung thông báo | **Nghi lỗi:** có thể hiện "Tên sự kiện: At " (thừa chữ `At`, thiếu thông tin) |

### E8. Lỗi kết nối và thiết bị
| ID | Bước | Mong đợi |
|---|---|---|
| FE-NW-01 | Tắt backend rồi thao tác | Thông báo "Cannot connect to server (check network or VPN)"; app không sập |
| FE-NW-02 | Token hết hạn (hoặc đổi `JWT_SECRET_KEY`) | Bị đưa về đăng nhập |
| FE-NW-03 | Mở `fe_http_debug.log` sau lỗi HTTP | Có khối chẩn đoán với `Request ID (BE)` và `Error Origin` |
| FE-DV-01 | Windows | Chạy thử (đã chạy) |
| FE-DV-02 | Android APK (`buildozer`) | Chưa thử; ghi rõ trong báo cáo là chưa kiểm thử |

---

## Phần F. Dữ liệu thử và dọn dẹp

1. Mỗi ca/ngày dùng tài khoản riêng: `username` dạng `qa_<tên>_<số>`, `display_name` bắt đầu bằng `QA_`.
2. Dọn qua API: `DELETE /api/v1/events/{id}`, `DELETE /api/v1/tasks/{id}`; đóng đề xuất treo bằng `POST /api/v1/proposals/{id}/reject`; dọn lịch import bằng `commit` với `replace_previous_imports=true`.
3. Dọn hẳn khi kết thúc đợt test (người có quyền vào MySQL): xóa dòng trong `users`, các bảng dữ liệu người dùng tự xóa theo (`ON DELETE CASCADE`):
   ```sql
   SELECT id, display_name FROM users WHERE display_name LIKE 'QA_%';
   DELETE FROM users WHERE id IN (<danh_sach_id>);
   ```
4. **Không bao giờ** đặt `TEST_DATABASE_URL` vào MySQL đang chứa dữ liệu thật: bộ test có thể xóa và tạo lại bảng.
5. Không commit các file chứa token hoặc lịch sử chat (`auth_session.json`, `chat_history_db.json`).

---

## Phần G. Báo lỗi

Mỗi lỗi một mục, theo mẫu:

```
ID: BUG-xxx            Mức độ: Nghiêm trọng | Cao | Trung bình | Thấp
Khu vực: BE | FE | AI/NLU | Dữ liệu | Hạ tầng
Tiêu đề: (một câu)
Môi trường: Windows 11, Python 3.12.x, commit <git rev-parse --short HEAD>, backend (local/host), có/không vLLM
Các bước tái hiện: 1) ... 2) ... 3) ...
Kết quả mong đợi:
Kết quả thực tế:
Bằng chứng: ảnh chụp; khối chẩn đoán từ fe_http_debug.log; Request ID (X-Request-ID); đoạn log trong QA  docs\last_run
Ghi chú: (có xuất hiện mọi lần không, có đã biết trong QA_README không)
```

Mức độ: **Nghiêm trọng** (mất dữ liệu, lộ bí mật, app sập), **Cao** (chức năng chính sai), **Trung bình** (sai nhưng có cách khác), **Thấp** (hiển thị, chữ).
Kiểm tra `QA_README.md` mục "Known issues" trước khi báo để tránh trùng.

---

## Phần H. Danh sách đánh dấu cuối đợt test

- [ ] Host chạy bản backend mới (có `/api/v1/debug/logs`).
- [ ] `run_qa.ps1 -All` đã chạy, log lưu trong `QA  docs\last_run`.
- [ ] NLU chế độ LLM đã chạy 3 lần, ghi trung bình và khoảng tin cậy.
- [ ] Các ca API-01 đến API-24 đã chạy trên backend mới.
- [ ] Các ca giao diện FE-* đã chạy, có ảnh chụp cho ca fail.
- [ ] Tài khoản thử đã dọn.
- [ ] Không có token hoặc bí mật trong báo cáo.
- [ ] Báo cáo ghi rõ đã và chưa kiểm thử: Windows (đã), Android (chưa), người dùng thật (chưa).
