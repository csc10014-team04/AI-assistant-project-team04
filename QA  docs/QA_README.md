# QA — hướng dẫn nhanh

Bộ tài liệu QA: `QA_Guide.md` (hướng dẫn từng bước), `QA_Report.md` (báo cáo), `BE_QA.md` và `FE_QA.md` (tài liệu của nhóm BE và FE), file này (tóm tắt nhanh).

Tài liệu này dành cho người làm QA của dự án (University Life Assistant). Cập nhật lần cuối: 2026-11-19.

## 1. Chạy tất cả bằng một lệnh

Từ thư mục gốc repo, với môi trường ảo đã kích hoạt (Python 3.12 hoặc 3.13):

```powershell
python -m pip install -r "QA  docs\requirements-qa.txt"      # cài công cụ QA, chỉ cần làm một lần
.\"QA  docs"\run_qa.ps1                                        # nhanh: bộ test chính + FE + backend + NLU (khoảng 4 phút)
.\"QA  docs"\run_qa.ps1 -Coverage -Lint                        # thêm độ phủ + ruff/mypy/bandit/radon
.\"QA  docs"\run_qa.ps1 -All                                   # thêm cả benchmark độ trễ
```

Script in một bảng tóm tắt và lưu log đầy đủ của từng bộ test vào `QA  docs\last_run\` (đính kèm vào báo cáo lỗi).
Muốn biết test nào fail: `Select-String -Path "QA  docs\last_run\*.log" -Pattern "^FAILED"`.

### Vì sao không chạy `pytest` trần?
- Repo có **hai** file `conftest.py` (`tests/` và `sourceCode/BE/tests/`). Chạy chung một phiên pytest sẽ báo `cannot import name 'class_row' from 'conftest'`. Script chạy mỗi nhóm trong một tiến trình riêng.
- Các test Kivy (FE) mở cửa sổ thật và **có thể làm sập cả tiến trình Python** (lúc đó pytest dừng giữa chừng, không có dòng tổng kết). Script tách chúng ra và báo "ended without a summary" nếu bị sập.

## 2. Các file QA nằm ở đâu

| Việc đo | File | Cách chạy riêng |
|---|---|---|
| Độ chính xác NLU (200 ca) | `sourceCode/BE/tests/data/nlu_eval.jsonl`, `sourceCode/BE/tools/eval_nlu.py` | `cd sourceCode\BE; python tools/eval_nlu.py --rules` (chế độ LLM cần vLLM) |
| Free-slot (35 ca tay + 2000 ca ngẫu nhiên so với bản vét cạn) | `tests/test_free_slots_accuracy.py` | `python -m pytest tests\test_free_slots_accuracy.py -s` |
| Parser/import (48 dòng có nhãn + fuzz 3000) | `tests/test_parser_import.py` | `python -m pytest tests\test_parser_import.py -s` |
| Parser: bảng, PDF, ảnh/OCR, mã hóa file (80 test, tự sinh dữ liệu lúc chạy) | `tests/test_parser_formats.py` | `python -m pytest tests	est_parser_formats.py -q` |
| Tìm kiếm / RAG (72 truy vấn có nhãn + 12 ngoài phạm vi) | `tests/test_rag_quality.py`, `tests/search_eval.jsonl`, `tests/search_eval_corpus.jsonl` | `python -m pytest tests\test_rag_quality.py -s` |
| `split_task` | `test_split_task.py` | `python -m pytest test_split_task.py` |
| Mã hóa Fernet | `test_crypto.py` | `python -m pytest test_crypto.py` |
| Độ trễ hàm thuần | `bench_pure.py` | `cd sourceCode\BE; python ..\..\bench_pure.py --runs 300 --json ..\..\"QA  docs"\bench_results.json` |
| Câu thật từ bạn bè và thầy | `QA  docs/real_user_prompts.jsonl` | (dữ liệu, không phải test) |

Vị trí file có thể đổi khi nhóm sắp xếp lại; các file test tự tìm thư mục `sourceCode/BE`.

## 3. Known issues (chạy ngày 2026-11-19)

Kết quả hiện tại: bộ chính 797 pass / 17 fail / 23 skip / 5 xfail; FE 44 pass / 2 fail; backend 87 pass / 2 fail (21 test fail, trong đó 1 là lỗi code thật ở mục `PH05`).
"Test cũ" nghĩa là nhiều khả năng test lỗi thời so với code; "Hỏi PIC" nghĩa là cần người phụ trách quyết định test hay code sai.

| Test | Hiện tượng | Phán đoán |
|---|---|---|
| `E2E11`, `PSM27`, 2 test khác | API trả `201` thay vì `200` | Test cũ |
| `E2E01/03/27`, `PSM15` | Phản hồi thiếu `courses_created`, `source`, `task_id` | Hỏi PIC (FE có dùng không?) |
| `SEC25[1234567]` | Mật khẩu 7 ký tự được chấp nhận. `BE_QA.md` ghi quy tắc hiện tại là **tối thiểu 6 ký tự**, test lại kỳ vọng 8 | Test cũ, hoặc nhóm đổi chính sách (OWASP khuyên ≥ 8) |
| `PRI18` | `Task(...)` chưa lưu thì `priority` là `None` | Test cũ |
| `UD01`, `UD09`, `UD11` | Schema có thêm bảng `pending_clarifications` (14 câu lệnh) | Test cũ |
| `ENG18` | Test cho rằng TASK mềm không chặn giờ trống, trái với README | Test cũ (xác nhận với Lâm) |
| `BE42` | Truy vấn "ngày 9/11" phụ thuộc ngày hiện tại | Test phụ thuộc thời gian |
| `RG01`, `RG02` | Truy hồi trả rỗng sau khi commit thời khóa biểu | Hỏi PIC |
| `PH05` | `sourceCode/FE/api_client.py` dòng 337 và 388: `lambda dt: on_error(None, str(e))` dùng biến `e` sau khi khối `except` đã kết thúc → `NameError`, người dùng không thấy thông báo lỗi. Sửa: gán `msg = str(e)` trước lambda | **Lỗi code thật (FE)**; cần `pyflakes` để test này chạy |
| `PH06` | Test tìm `sourceCode/BE/requirements.txt`; file này đã bị gộp vào `requirements-fullStack.txt` và `requirements-endUser.txt` ở thư mục gốc | Test cũ (và hướng dẫn cài đặt cũ cần cập nhật) |
| `test_assistant_reminders_api` (2 test) | `_FakeResp` thiếu `status_code` | Test cũ |
| `NT02`, `NT06` (FE) | Nội dung thông báo là "Upcoming Event" / "Làm đồ án: At " (còn dư chữ "At" không có địa điểm/giờ) | Hỏi PIC FE: có thể là lỗi hiển thị thật |
| NLU ca 116 | `xoá` (viết khác dấu) không nhận là xóa | Lỗi thật (`services/nlu.py`) |
| NLU ca 165 | `what is on my schedule today` bị đoán là `schedule_task` | Lỗi thật |
| NLU ca 27, 28, 68, 149 | Nhãn chưa khớp hành vi mới ("sớm", "dạo này", "sáng mai") | Nhóm chốt nhãn đúng |

Lỗi đã biết, mỗi lỗi có test `xfail` (tự báo XPASS khi được sửa):
- Parser sập cả file khi một ô giờ có hậu tố múi giờ ở một bên (`08:00Z`, `08:00+07:00`).
- Giờ có hậu tố múi giờ ở cả hai bên được chấp nhận thay vì từ chối.
- File CSV xuất từ Excel (có BOM) làm dòng tiêu đề thành dòng lỗi `INVALID_KIND`.

Các điểm yếu chưa có test fail nhưng nên nêu trong báo cáo:
- RAG: `MIN_SCORE = 0.12` chỉ từ chối đúng 25% câu ngoài phạm vi (bảng quét ngưỡng in khi chạy `test_rag_quality.py -s`).
- Mã hóa: khi thiếu `DATA_ENCRYPTION_KEY` hệ thống dùng khóa mặc định công khai; đổi khóa rồi ghi tiếp làm mất chỉ mục RAG cũ.
- `detect_import_conflicts` có độ phức tạp gần bình phương (200 dòng CSV mất khoảng 0,4 đến 0,7 giây).
- `auth_session.json` và `chat_history_db.json` (cả ở thư mục gốc và `sourceCode/FE`) đang được git theo dõi và có chứa token đăng nhập.

## 4. Chuẩn và ngưỡng (đề xuất, Data/Lead chốt)

| Chỉ số | Căn cứ | Ngưỡng gợi ý |
|---|---|---|
| Schema adherence NLU, hallucination | `eval_nlu.py` | ≥ 98%, 0 (đo ở chế độ LLM) |
| Intent / duration / date_hint | ISO/IEC 25010, 25059, TS 4213 | ≥ 95% / ≥ 95% / ≥ 90% |
| Free-slot, split_task, mã hóa | ISO/IEC/IEEE 29119-4 | Bất biến 0 vi phạm; khớp bản tham chiếu 100% |
| `find_free_slots` độ trễ | `tests/README.md` mục 2.4 | p95 < 200 ms trên 300 sự kiện |
| Tìm kiếm | Cranfield/TREC (Hit@k, MRR, nDCG) | Mốc hồi quy trong `test_rag_quality.py` (FLOORS) |

Mọi tỉ lệ cần kèm khoảng tin cậy Wilson 95% và ghi rõ n. Số liệu của bộ luật NLU **không** phải số liệu của LLM.

## 5. Việc cần máy hoặc người khác

- vLLM (host AI): NLU chế độ LLM, độ trễ và tỉ lệ JSON hợp lệ của LLM.
- MySQL: chất lượng dữ liệu KB (`kb_*`), `find_user_free_slots`, smart diff khi import lại.
- Backend + FE chạy thật: độ trễ API p95, độ sẵn sàng, tỉ lệ fallback thực tế, giao diện theo tài liệu `Frontend_QA`.
- Người ngoài nhóm: câu thật, người gán nhãn thứ hai, thử với 5 đến 10 sinh viên (SUS).

## 6. Gỡ lỗi nhanh

| Triệu chứng | Nguyên nhân và cách xử lý |
|---|---|
| Gõ đường dẫn file `.py` chỉ mở VS Code | Phải gõ `python -m pytest ...` |
| `2 skipped` ở test KB | Thiếu `beautifulsoup4`: `python -m pip install beautifulsoup4` |
| `file or directory not found: tests\...` | Đang đứng sai thư mục; `cd` vào thư mục gốc repo |
| `Activate.ps1` không chạy | Gõ đúng tên `Activate.ps1`; nếu bị chặn: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Kivy không cài được | Dùng Python 3.12 hoặc 3.13, không dùng 3.14; cài bằng `pip install -r requirements-fullStack.txt` (người chỉ dùng app: `requirements-endUser.txt`) |
| `cannot import name 'class_row' from 'conftest'` | Đừng gộp hai thư mục `tests` vào một lần chạy; dùng `run_qa.ps1` |
| Pytest dừng giữa chừng, không có dòng tổng kết | Một test Kivy làm sập tiến trình; chạy test FE riêng |
