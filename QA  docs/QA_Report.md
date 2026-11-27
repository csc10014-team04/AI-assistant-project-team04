# Báo cáo QA — University Life Assistant

| | |
|---|---|
| Dự án | University Life Assistant (trợ lý lịch học cho sinh viên: backend FastAPI, giao diện Kivy, MySQL, Llama 3.1 8B qua vLLM) |
| Ngày đo | 2026-11-19 |
| Phiên bản kiểm thử | commit `21a680b` (nhánh `main`), cộng các thay đổi chưa commit trong thư mục làm việc (xem mục 2.3) |
| Máy đo | Windows 11, Python 3.12.10, CPU AMD (16 luồng); máy chủ AI và backend trên host `26.211.52.63` (Radmin VPN) |
| Người lập | Nhóm QA |
| Tài liệu đi kèm | `QA_Guide.md` (cách chạy và test), `QA_README.md` (tóm tắt), `BE_QA.md`, `FE_QA.md` |

---

## 1. Tóm tắt điều hành

**Kết luận chung:** phần lõi tính toán xác định của hệ thống (tìm giờ trống, chia việc, kiểm tra xung đột, mã hóa) **hoạt động đúng và nhanh** trên mọi phép thử đã làm. Phần còn yếu nằm ở **độ phủ của kiểm thử, một số lỗi chức năng đã tái hiện được, và những thứ chưa đo được** (chất lượng LLM ngoài đời, hiệu năng API trên host, người dùng thật). Dự án **chưa đủ bằng chứng để kết luận "đạt SLO"**: nhiều mục SLO mới chỉ đo ở chế độ luật hoặc chưa đo.

### Con số chính

| Chỉ số | Kết quả | Đánh giá |
|---|---|---|
| Test tự động | 928 pass, 21 fail, 23 skip, 5 xfail (bộ chính 797/17, giao diện 44/2, backend 87/2) | 21 test fail: 12 do test lỗi thời, 6 cần PIC quyết định, 3 cho thấy lỗi thật (1 chắc chắn, 2 nghi ngờ) |
| Độ phủ mã (dòng + nhánh) | 73% (trước khi bổ sung test parser: 65%) | Còn dưới mục tiêu 80%; `parser.py` đã lên 86% (từ 39%), `search_engine.py` 41%, `routers/events.py` 25% |
| Tìm giờ trống: so với bản tham chiếu vét cạn | 2000/2000 ca khớp, 0 vi phạm bất biến | Đạt |
| Tìm giờ trống: độ trễ p95 (300 sự kiện) | 1,0 ms (giới hạn 200 ms) | Đạt |
| NLU chế độ luật (200 ca) | intent 99,0%, duration 100%, date_hint 97,5% | Chỉ là điểm của nhánh dự phòng |
| NLU với LLM thật (200 ca, 3 lần) | schema adherence 98,0% (3 lần: 98,5 / 97,0 / 98,5%), intent 99,0%, duration 100%, date_hint 97,5%, bịa ngày 0 | Sát ngưỡng 98%: một lần chạy dưới ngưỡng; chưa đủ chắc để kết luận đạt |
| Tìm kiếm / RAG (72 truy vấn) | Hit@1 84,7%, MRR 0,88; chỉ từ chối đúng 25% câu ngoài phạm vi | Cần chỉnh ngưỡng |
| Phân tích tĩnh | ruff 234, mypy 32 lỗi; bandit 0 lỗi mức cao/trung bình | Cần dọn; không có lỗ hổng nghiêm trọng do bandit phát hiện |
| Lỗi và rủi ro đã ghi nhận | 14 mục (mục 4), trong đó 4 mức Cao | Cần sửa trước khi demo |

### Năm rủi ro lớn nhất
1. **Lỗi sập khi nhập thời khóa biểu:** một ô giờ có hậu tố múi giờ (`08:00Z`) làm cả file import bị hủy thay vì chỉ đánh dấu dòng lỗi.
2. **Giao diện không báo lỗi khi gặp lỗi mạng khác thường:** `sourceCode/FE/api_client.py` dòng 337 và 388 dùng biến `e` sau khi khối `except` kết thúc (`NameError`).
3. **Khóa bí mật mặc định công khai:** thiếu `JWT_SECRET_KEY` hoặc `DATA_ENCRYPTION_KEY` thì hệ thống tự dùng khóa có sẵn trong mã nguồn, ai đọc repo cũng biết.
4. **Dữ liệu cá nhân trong git:** `sourceCode/FE/auth_session.json`, `chat_history_db.json` (và bản sao trong `tests/`) vẫn được theo dõi, có chứa token đăng nhập.
5. **Khoảng cách giữa người dùng thật và tính năng hiện có:** các cách dùng thu thập từ bạn bè và thầy chủ yếu là lập kế hoạch cả tuần cho nhiều việc kèm ràng buộc, trong khi trợ lý hiện xếp từng việc một (mục 3.12).

---

## 2. Phạm vi, môi trường, phương pháp

### 2.1 Đã kiểm thử
Tìm giờ trống, chia việc dài, nhập thời khóa biểu (parser) và phát hiện xung đột, mã hóa chỉ mục, tìm kiếm ngoại tuyến (RAG), NLU (bộ luật và LLM), độ trễ các hàm thuần, chất lượng mã (độ phủ, lint, kiểu, bảo mật, độ phức tạp), bộ test sẵn có của dự án, trạng thái host (vLLM, backend), đối chiếu tài liệu FE/BE với mã nguồn, và phân tích các cách dùng thật.

### 2.2 Chưa kiểm thử (và lý do)
| Hạng mục | Lý do |
|---|---|
| Chất lượng dữ liệu tri thức KB (trùng, đủ, nhất quán, độ chính xác lấy mẫu) | Cần MySQL chứa dữ liệu KB; Docker trên máy QA chưa chạy. Mới chạy test chức năng của crawler (43 test pass) |
| `find_user_free_slots` với DB thật, smart diff khi import lại | Cần MySQL |
| Độ trễ và độ sẵn sàng của API trên host, tỉ lệ fallback thực tế | Cần chạy tải lên host dùng chung và tạo tài khoản thử trên DB host (không xóa được bằng API); chưa có cho phép |
| Giao diện thủ công theo kịch bản FE-* (`QA_Guide.md` Phần E) | Cần người thao tác trên màn hình; kịch bản đã sẵn sàng |
| Android APK | Chưa dựng bản `buildozer` |
| Thử nghiệm với người dùng thật (SUS, tỉ lệ hoàn thành) | Chưa tổ chức |
| Độ trễ LLM, sức chứa hàng đợi suy luận | Chưa có script đo riêng (có thể bổ sung) |

### 2.3 Điều kiện cần biết
- Thư mục làm việc có thay đổi chưa commit: `sourceCode/FE/api_client.py` đã được đổi địa chỉ mặc định về `http://26.211.52.63:8080` (trước đó là `127.0.0.1:8080`).
- Host `26.211.52.63`: ban đầu chạy backend **bản cũ** (thiếu 5 đường dẫn, không gửi header chẩn đoán). Sau đó đã cập nhật: hiện có đủ 33 đường dẫn khớp mã nguồn, có `X-Request-ID`, `X-Process-Time-Ms`, `/api/v1/debug/logs` hoạt động, `endpoint_allowed = true`.
- Công cụ: pytest 9.2, pytest-cov, ruff 0.17, mypy 2.4, bandit 1.9, radon 6.0. Mã đo nằm trong `tests/` và `QA  docs/` (có thể chạy lại bằng `run_qa.ps1 -All`).

### 2.4 Phương pháp
- **Hàm xác định** (tìm giờ trống, chia việc, mã hóa, parser): ca viết tay có đáp án biết trước, so sánh với bản tham chiếu vét cạn trên dữ liệu ngẫu nhiên có seed, kiểm tra bất biến, kiểm tra tính chất (metamorphic), fuzz. Ngưỡng đạt: 100%.
- **Hàm xếp hạng hoặc heuristic** (RAG, NLU): bộ ca có nhãn, độ chính xác kèm khoảng tin cậy Wilson 95%, tách theo nhóm ca.
- **Hiệu năng**: warm-up, nhiều lần đo, báo p50/p95/p99 và độ dốc log-log theo kích thước đầu vào.
- Khung tham chiếu: ISO/IEC 25010 (và tinh thần ISO/IEC 25059, TS 4213), ISO/IEC/IEEE 29119-4. Đây là tham chiếu phương pháp, không phải chứng nhận.
- Số lượng ca và số lần đo đều vượt mức tối thiểu trong kế hoạch hơn 10%.

### 2.5 Tiêu chuẩn đánh giá
Các tiêu chuẩn dưới đây là **căn cứ phương pháp và ngưỡng**, không phải chứng nhận. Ngưỡng ghi "đề xuất" do nhóm (Data/Lead) chốt.

**a) Khung chất lượng và kiểm thử**

| Tiêu chuẩn | Dùng để làm gì trong báo cáo |
|---|---|
| ISO/IEC 25010 (mô hình chất lượng sản phẩm) | Phân nhóm đặc tính: đúng chức năng, hiệu năng, độ tin cậy, bảo mật, khả năng bảo trì |
| ISO/IEC 25059 và ISO/IEC TS 4213 | Mở rộng cho hệ thống AI: đo độ chính xác phân loại (intent, duration, date_hint) |
| ISO/IEC/IEEE 29119-4 (kỹ thuật kiểm thử) | Phân vùng tương đương, giá trị biên, kiểm tra bất biến, so với bản tham chiếu |
| ISO/IEC TR 24029-1 | Đánh giá độ bền của mạng nơ-ron: câu sai chính tả, thiếu dấu, tiếng Anh lẫn Việt |
| NIST AI RMF 1.0 | Đo đạc rủi ro AI: bịa ngày, từ chối đúng, fallback khi AI lỗi |
| ISO/IEC 25012, 25024 | Chất lượng dữ liệu KB: đầy đủ, nhất quán, không trùng, đúng định dạng (chưa đo, cần MySQL) |
| OWASP ASVS / Top 10 | Chính sách mật khẩu, khóa mặc định, token trong git |

**b) Chỉ số và ngưỡng đã dùng**

| Nhóm | Chỉ số | Ngưỡng | Nguồn |
|---|---|---|---|
| NLU | Schema adherence | ≥ 98% | SLO nhóm |
| NLU | Bịa ngày | 0 | SLO nhóm |
| NLU | Intent / duration / date_hint | ≥ 95% / 95% / 90% | Đề xuất (25059, TS 4213) |
| Hàm xác định | Vi phạm bất biến; khớp bản tham chiếu | 0; 100% | 29119-4 |
| Tìm kiếm | Hit@k, MRR, nDCG; tỉ lệ từ chối câu ngoài phạm vi | Mốc hồi quy `FLOORS` | Cranfield/TREC |
| Hiệu năng | p50, p95, p99 (không dùng trung bình); độ dốc log-log | `find_free_slots` p95 < 200 ms (300 sự kiện); API đầu-cuối ≤ 4 s | `tests/README.md` 2.4 |
| Mã nguồn | Độ phủ dòng và nhánh | ≥ 80%; module lõi ≥ 90% | Thực hành phổ biến |
| Mã nguồn | Độ phức tạp cyclomatic (radon) | ≤ 10 mỗi hàm | McCabe |
| Bảo mật tĩnh | bandit mức cao | 0 | OWASP |
| Gán nhãn | Cohen's kappa giữa hai người gán nhãn | ≥ 0,6 (chưa đo, cần người thứ hai) | Landis & Koch |

**c) Quy tắc thống kê**
- Mọi tỉ lệ kèm n và khoảng tin cậy Wilson 95%.
- Khi không có lỗi nào: dùng "quy tắc ba" (cận trên 95% của tỉ lệ lỗi ≈ 3/n). Muốn chứng minh ≥ 98% với 95% tin cậy cần khoảng 150 ca không lỗi; bộ 200 ca đủ cho mức này nhưng chỉ khi có đúng 0 lỗi.
- Số liệu của bộ luật (`--rules`) **không** thay cho số liệu của LLM; mục NLU báo riêng hai chế độ.
- Lần đo LLM lặp 3 lần (600 lượt) vì đầu ra LLM không hoàn toàn xác định.

---

## 3. Kết quả chi tiết

### 3.1 Test tự động tổng hợp (`run_qa.ps1`)

| Bộ | Đạt | Fail | Skip | xfail |
|---|---|---|---|---|
| Bộ chính `tests/` (không gồm Kivy) | 797 | 17 | 23 | 5 |
| Giao diện Kivy | 44 | 2 | 0 | 0 |
| Backend `sourceCode/BE/tests` | 87 | 2 | 0 | 0 |
| **Tổng** | **928** | **21** | **23** | **5** |

Nguyên nhân 21 test fail (xem log `QA  docs\last_run`):

| Nhóm | Số test | Phán đoán |
|---|---|---|
| API trả `201` thay vì `200`; schema có bảng mới `pending_clarifications` (14 câu lệnh); `PRI18` (giá trị mặc định chỉ có sau khi lưu); `ENG18` (trái README); `BE42` (phụ thuộc ngày); `PH06` (file requirements đã gộp); 2 test backend (`_FakeResp` thiếu `status_code`); `SEC25` (chính sách mật khẩu 6 so với 8 ký tự) | 12 | Test lỗi thời hoặc phụ thuộc thời gian |
| Phản hồi thiếu `courses_created`, `source`, `task_id` (`E2E01/03/27`, `PSM15`) | 4 | Cần PIC API quyết định |
| Truy hồi trả rỗng sau khi commit thời khóa biểu (`RG01`, `RG02`) | 2 | Cần PIC |
| `PH05`: `NameError` thật ở `api_client.py` | 1 | **Lỗi code thật** |
| Thông báo nhắc hẹn: `NT02`, `NT06` ("…: At ") | 2 | Nghi lỗi hiển thị thật |

Nhận xét: test của dự án được viết cẩn thận (hơn 800 ca) nhưng **chưa được bảo trì theo code**: 12 test fail vì code đã đổi chứ không phải vì code sai. Nên cập nhật để bộ test lại là cảnh báo đáng tin.

**Định nghĩa và lý do dùng**
- *Test hồi quy (regression test)*: test chạy lại sau mỗi thay đổi để biết chức năng cũ còn đúng không. Dùng vì đây là cách rẻ nhất để phát hiện code mới làm hỏng code cũ.
- *Pass / fail / skip / xfail*: đạt / không đạt / bỏ qua (thiếu điều kiện chạy, ví dụ thiếu thư viện) / lỗi đã biết, được đánh dấu để tự báo khi được sửa. Báo cả bốn số vì "0 fail" nhưng nhiều skip có thể che mất test không chạy.
- *Test lỗi thời (stale test)*: test fail do code đã đổi có chủ đích. Phân loại riêng để không đếm nhầm thành lỗi sản phẩm, và để bộ test không bị mất uy tín (báo động giả làm người ta bỏ qua cảnh báo thật).
- *Chạy từng bộ trong tiến trình riêng*: hai file `conftest.py` xung đột và test Kivy có thể làm sập tiến trình, nên không gộp chung một lần chạy.

### 3.2 NLU (trích ý định, thời lượng, mốc ngày)

Bộ 200 ca (`sourceCode/BE/tests/data/nlu_eval.jsonl`): gồm 106 ca xếp lịch, 23 xóa, 23 dời, 25 hỏi lịch, 23 ngoài phạm vi; có dấu/không dấu, teencode, emoji, tiếng Anh, ca biên (14/15/720/721 phút), ca có deadline.

**Chế độ luật (nhánh dự phòng):**

| Chỉ số | Kết quả | Khoảng tin cậy 95% |
|---|---|---|
| Intent | 198/200 = 99,0% | 96,4 đến 99,7% |
| Duration | 200/200 = 100% | 98,1 đến 100% |
| Date-hint | 195/200 = 97,5% | 94,3 đến 99,0% |
| `bad_dates` (bịa ngày) | 0 | |

Các ca còn lệch: ca 116 (`xoá` viết khác dấu không nhận là xóa), ca 165 (câu hỏi lịch bằng tiếng Anh có chữ `schedule` bị hiểu thành lệnh xếp lịch), ca 27/28/68/149 (nhãn chưa khớp hành vi mới).

**Chế độ LLM thật** (Llama 3.1 8B AWQ, 3 lần chạy, `temperature = 0`):

| Lần | Lượt dùng kết quả của LLM | Lượt rơi về fallback | Schema adherence | Intent | Duration | Date-hint | Bịa ngày | Thời gian (200 câu) |
|---|---|---|---|---|---|---|---|---|
| 1 | 197 | 3 | 98,5% | 99,0% | 100% | 97,5% | 0 | 210 s |
| 2 | 194 | 6 | 97,0% | 99,0% | 100% | 97,5% | 0 | 272 s |
| 3 | 197 | 3 | 98,5% | 99,0% | 100% | 97,5% | 0 | 213 s |
| **Tổng / trung bình** | **588/600** | **12/600 (2,0%)** | **98,0%** (khoảng tin cậy 96,5 đến 98,9%) | 99,0% | 100% | 97,5% | 0 | trung bình 1,2 s mỗi câu |

Cách đọc:
- **Schema adherence sát ngưỡng 98%.** Nhật ký lỗi cho thấy hai câu (`thank you`, `dịch giúp mình câu này sang tiếng Anh`) khiến mô hình trả lời bình thường thay vì JSON (`JSON_PARSE`) ở mọi lần chạy; nguyên nhân các lượt fallback còn lại xem `sourceCode/BE/logs/ai_errors.jsonl` (nhật ký có cả `TIMEOUT` và `INFRA_CRASH`; chưa quy từng lượt về từng lần chạy). Lần 2 có nhiều fallback hơn (6 so với 3).
- **Intent, duration, date_hint giống hệt chế độ luật.** Mã có các chốt chặn "chữ gốc của người dùng thắng mô hình" (thời lượng và mốc ngày lấy từ văn bản, không từ LLM), nên ba chỉ số này **không đo được khả năng hiểu của riêng LLM**. Chúng cho thấy hệ thống kết hợp luật và LLM an toàn (0 bịa ngày), không cho thấy LLM giỏi hơn luật. Muốn đo LLM, cần bộ ca mà luật làm sai (câu diễn đạt tự do) và người gán nhãn độc lập.
- Mọi lỗi AI đều rơi về kết quả của bộ luật (fallback) và không lần nào làm sập bộ đánh giá. Việc API không bao giờ trả `500` vì AI lỗi vẫn phải thử ở mức API (ca API-19 trong `QA_Guide.md`).

**Lưu ý khi diễn giải:** 170/200 ca do người trong nhóm QA viết sau khi đọc mã nguồn, nên con số có phần lạc quan. Nó đo "xử lý đúng các câu nhóm đã dự tính", không phải "đúng với câu người dùng gõ ngoài đời" (xem 3.12).

**Định nghĩa và lý do dùng**
- *Intent accuracy*: tỉ lệ câu được phân đúng loại yêu cầu (xếp lịch, xóa, dời, hỏi lịch, ngoài phạm vi). Dùng vì phân sai loại dẫn tới hành động sai (xóa nhầm thay vì hỏi), đây là lỗi người dùng thấy rõ nhất.
- *Duration accuracy*: thời lượng trích ra khớp nhãn. Sai thời lượng làm lịch đề xuất sai ngay từ đầu.
- *Date-hint accuracy*: mốc ngày tương đối ("mai", "thứ 6 tuần sau") được trích đúng.
- *Schema adherence*: tỉ lệ lượt LLM trả JSON đúng cấu trúc mà không phải rơi về fallback. Dùng vì mô hình 8B hay trả lời tự do thay vì JSON; chỉ tiêu 98% là SLO của nhóm. Chỉ có nghĩa ở chế độ LLM.
- *Bịa ngày (hallucinated date)*: hệ thống đưa ra ngày mà câu của người dùng không hề có. Ngưỡng 0 vì lịch sai ngày có hậu quả thật (lỡ hạn nộp, lỡ thi).
- *Khoảng tin cậy Wilson 95%*: khoảng giá trị thật có thể nằm trong, cho tỉ lệ đo trên mẫu nhỏ. Dùng Wilson (không dùng công thức chuẩn) vì ổn định khi tỉ lệ gần 0% hoặc 100%.
- *Chạy LLM 3 lần, `temperature = 0`*: đầu ra LLM không hoàn toàn lặp lại ngay cả khi `temperature = 0`; lặp lại để thấy độ dao động (97,0 đến 98,5%).
- *Tách chế độ luật và chế độ LLM*: vì hai chế độ cho số khác nhau và chốt chặn trong mã làm kết quả giống nhau; gộp chung sẽ khiến báo cáo đánh giá sai khả năng của LLM.

### 3.3 Tìm giờ trống (`find_free_slots`)

| Phép thử | Kết quả |
|---|---|
| 35 ca viết tay (biên, múi giờ, giờ ngủ, khoảng nghỉ, deadline, gộp sự kiện) | đúng 100% |
| 2000 lịch ngẫu nhiên so với bản tham chiếu vét cạn | 2000/2000 giống hệt |
| Bất biến: thẳng lưới, không chạm sự kiện, đủ độ dài, nằm trong cửa sổ | 0 vi phạm |
| 6 quan hệ metamorphic (đổi thứ tự, thêm deadline, thêm sự kiện, trùng lặp, tăng độ dài, tăng khoảng nghỉ) | đúng 100% |
| Độ trễ p95 (300 sự kiện) | 1,0 ms; 5000 sự kiện: 23,6 ms; độ dốc 1,06 (gần tuyến tính) |

Kết luận: **đạt**, cận trên tỉ lệ lỗi khoảng 0,15% (quy tắc ba, n = 2000). `find_user_free_slots` (phần đọc cấu hình từ database) chưa kiểm vì cần MySQL.

**Định nghĩa và lý do dùng**
- *Khoảng trống (free slot)*: đoạn thời gian liên tục không có sự kiện chặn, nằm ngoài giờ ngủ, thẳng lưới 15 phút, đủ độ dài yêu cầu (cộng khoảng nghỉ). Đây là lõi của việc xếp lịch; sai ở đây là xếp việc đè lên giờ học.
- *Bản tham chiếu vét cạn (oracle)*: cài đặt chậm nhưng hiển nhiên đúng (thử từng ô 15 phút), so với thuật toán thật trên 2000 lịch ngẫu nhiên có seed. Dùng khi không có đáp án nhãn sẵn; khớp 100% nghĩa là hai cách tính độc lập cho cùng kết quả (kiểm thử vi sai, differential testing).
- *Bất biến (invariant)*: tính chất phải luôn đúng với mọi đầu vào (thẳng lưới, không chạm sự kiện, đủ độ dài, trong cửa sổ). Kiểm tra được cả khi không biết đáp án.
- *Metamorphic*: đổi đầu vào theo cách đã biết trước ảnh hưởng đến đầu ra (đổi thứ tự sự kiện không được đổi kết quả; tăng khoảng nghỉ không được thêm khoảng trống). Dùng bổ sung cho oracle để bắt lỗi mà oracle cũng mắc.
- *Quy tắc ba*: khi có 0 lỗi trên n phép thử, cận trên 95% của tỉ lệ lỗi xấp xỉ 3/n (2000 phép thử cho khoảng 0,15%). Dùng để không kết luận "không lỗi" quá mạnh.
- *p95 và độ dốc log-log*: 95% lượt chạy nhanh hơn giá trị này; độ dốc 1 là tuyến tính, 2 là bình phương. Dùng p95 vì trung bình che mất các lượt chậm.

### 3.4 Chia việc dài (`split_task`)

25 test đều đạt. 3000 ca ngẫu nhiên: 0 vi phạm các bất biến (tổng thời lượng bằng thời lượng việc, không khối nào vượt `max_block`, khối nằm trong khoảng trống, không chồng nhau, tối đa 6 khối). Với các ca có nghiệm, thuật toán tham lam tìm được lịch ở **1907/1910 ca (99,8%, khoảng tin cậy 99,5 đến 99,9%)**.
Một điểm khác với mô tả: ca `remaining = 45`, `cap = 30` trả khối 30 và khối 15, tức khối nhỏ hơn `min_block` vẫn có thể xuất hiện. Cần PIC xác nhận đây là hành vi chấp nhận được.

**Định nghĩa và lý do dùng**
- *`split_task`*: chia một việc dài (ví dụ 6 giờ) thành tối đa 6 khối vào các khoảng trống rời nhau, mỗi khối không vượt `max_block` và không nhỏ hơn `min_block` (30 phút).
- *Bất biến của phép chia*: tổng khối bằng thời lượng việc, không khối nào vượt `max_block`, khối nằm trong khoảng trống, không chồng nhau, tối đa 6 khối. Dùng vì thuật toán tham lam có thể cho kết quả "trông hợp lý" nhưng sai tổng; bất biến bắt được lỗi đó với 3000 ca ngẫu nhiên.
- *Tỉ lệ tìm được lịch trên ca có nghiệm (completeness)*: kết quả tham lam có thể bỏ lỡ nghiệm tồn tại. Đo riêng để biết người dùng bị báo "không xếp được" oan bao nhiêu (3/1910).

### 3.5 Nhập thời khóa biểu (parser) và xung đột

| Phép thử | Kết quả |
|---|---|
| 48 dòng có nhãn (32 lỗi, 16 hợp lệ) | precision 100%, recall 100% (cận dưới recall 89,3%, n = 32) |
| Không bỏ sót dòng nào (`valid + invalid = số dòng`), `line_number` đúng | đạt |
| Fuzz 3000 file biến dạng | 1 file làm sập parser, đều do cùng một lỗi (B-02) |
| 6 ca phát hiện xung đột (không chồng, trùng trong file, trùng sự kiện có sẵn, khác ngày, sát nhau, rỗng) | đạt; 15 buổi hàng tuần gộp thành một thẻ |
| 5 xfail (lỗi đã biết) | B-02, B-03, B-04 |

Bổ sung (`tests/test_parser_formats.py`, 80 test): bảng Markdown và bảng đồng nghĩa tiêu đề tiếng Việt/Anh (dấu phẩy, chấm phẩy, tab), ô lịch nhiều buổi (`T4 07:30-09:10 (C.45) T6 ...`) tách đúng từng buổi, ô gộp kế thừa môn trước, giải mã UTF-8 và latin-1, PDF (lớp chữ, bảng kẻ ô, trang trống, file hỏng), ảnh qua OCR Tesseract (bảng kẻ ô, ảnh trắng, file hỏng), gộp kết quả nhiều trang. Tất cả đạt, không có lỗi mới. Ba quan sát về thiết kế:
- Bảng không có cột ngày bắt đầu/kết thúc (kiểu xuất từ portal) bị đánh dấu `EMPTY_FIRST_DATE` ở **mọi dòng**; người dùng phải nhập ngày từng dòng. Đây là thiết kế có chủ đích nhưng làm nhập liệu từ portal rất tốn công; nên có ô nhập ngày học kỳ một lần.
- PDF chỉ chứa văn bản tự do (không phải bảng) không được nhận dạng; mọi dòng bị đánh dấu lỗi (không sập).
- File cũ mã hóa không phải UTF-8 được giải mã bằng latin-1, nên tiếng Việt cũ (Windows-1258) có thể hiện sai dấu.

**Định nghĩa và lý do dùng**
- *Parser*: đọc file thời khóa biểu (CSV, bảng Markdown, PDF, ảnh qua OCR) thành các dòng sự kiện, trả `valid_rows` và `invalid_rows` thay vì dừng khi gặp lỗi (quy tắc "không sập, không bỏ dòng im lặng" của dự án).
- *Precision và recall trên dòng lỗi*: precision là trong số dòng bị báo lỗi, bao nhiêu thật sự lỗi; recall là trong số dòng lỗi thật, bao nhiêu bị bắt. Dùng recall cao vì để lọt một dòng lỗi vào lịch thật nguy hiểm hơn báo nhầm (người dùng chỉ phải xác nhận lại).
- *Bất biến "valid + invalid = số dòng"*: bảo đảm không dòng nào bị bỏ im lặng.
- *Fuzz*: sinh file biến dạng ngẫu nhiên (3000 file) để tìm tổ hợp đầu vào không ai nghĩ tới. Dùng vì parser nhận dữ liệu do người dùng tải lên, không kiểm soát được.
- *xfail*: test cho lỗi đã biết; test sẽ báo XPASS khi lỗi được sửa, nên không phải nhớ bỏ đánh dấu.
- *Test định dạng bằng dữ liệu tự sinh*: repo không có file PDF hoặc ảnh mẫu, nên test tự tạo lúc chạy; làm vậy để test lặp lại được và không phải đưa file nhị phân vào git.
- *Độ phủ nhánh*: do `parser.py` có nhiều nhánh theo định dạng, độ phủ nhánh cho biết định dạng nào chưa từng được chạy (từ 39% lên 86%).
- *Phát hiện xung đột import*: so các dòng mới với lịch có sẵn để cảnh báo chồng giờ trước khi ghi; dùng test có đáp án biết trước (không chồng, trùng, sát nhau).

### 3.6 Mã hóa (Fernet)
31 test đạt: giải mã đúng với tiếng Việt, emoji, chuỗi rỗng, 100.000 ký tự và 500 chuỗi ngẫu nhiên; đổi 1 byte bất kỳ đều bị phát hiện; sai khóa trả `None`; hai lần mã hóa cùng văn bản cho hai token khác nhau; file chỉ mục không chứa văn bản gốc. Tốc độ: khoảng 75 MB/s (mã hóa + giải mã, 1 MB).
Hai rủi ro đã được đưa vào test (B-08, B-09).

**Định nghĩa và lý do dùng**
- *Fernet*: mã hóa đối xứng có xác thực (AES-128-CBC cộng HMAC-SHA256) của thư viện `cryptography`. Dự án dùng để mã hóa chỉ mục tìm kiếm lưu trên đĩa.
- *Khứ hồi (round-trip)*: mã hóa rồi giải mã phải ra đúng văn bản gốc, thử với tiếng Việt, emoji, chuỗi rỗng, 100.000 ký tự, 500 chuỗi ngẫu nhiên. Đây là điều kiện tối thiểu; sai ở đây là mất dữ liệu.
- *Phát hiện sửa đổi (tamper detection)*: đổi 1 byte bất kỳ phải bị từ chối. Dùng vì mã hóa có xác thực chỉ có giá trị nếu thật sự từ chối dữ liệu bị đổi.
- *Sai khóa trả `None`*: để lỗi khóa không gây sập và không lộ dữ liệu.
- *Hai lần mã hóa cho hai token khác nhau*: có IV ngẫu nhiên, nên kẻ quan sát không biết hai bản ghi có cùng nội dung.
- *Kiểm tra file không chứa văn bản gốc*: xác nhận dữ liệu thật sự được mã hóa trên đĩa, không chỉ "có hàm mã hóa".
- *Chỉ kiểm hành vi, không chứng minh an toàn mật mã*: thư viện được tin cậy; rủi ro nằm ở cách quản lý khóa (B-08, B-09).

### 3.7 Tìm kiếm / RAG (kho chỉ mục ngoại tuyến)
72 truy vấn có nhãn (kho A: 24 dòng thời khóa biểu; kho B: 20 đoạn quy chế mô phỏng) + 12 truy vấn ngoài phạm vi.

| Nhóm | Số câu | Hit@3 |
|---|---|---|
| Khớp từ khóa (exact, mã môn, phòng) | 44 | 100% |
| Không dấu, viết tắt | 13 | 77% |
| Diễn đạt khác | 9 | 89% |
| Theo thứ trong tuần | 6 | 50% |
| **Tổng** | 72 | Hit@1 84,7% (khoảng tin cậy 74,7 đến 91,2%), Hit@3 90%, MRR 0,88, nDCG@3 0,87 |

Từ chối câu ngoài phạm vi: với ngưỡng hiện tại `MIN_SCORE = 0.12` chỉ **6/24 (25%)** được từ chối đúng. Quét ngưỡng: 0,20 → 79% (nhầm 11% câu hợp lệ); 0,25 → 92% (nhầm 14%); 0,30 → 100% (nhầm 28%).
Hạn chế: nhãn do một người gán; văn bản quy chế là văn bản mô phỏng.

**Định nghĩa và lý do dùng**
- *RAG / truy hồi*: tìm các đoạn dữ liệu liên quan nhất để đưa cho LLM trả lời. Bộ này dùng vector băm 512 chiều, không dùng mô hình embedding, nên cần đo chất lượng thật thay vì giả định.
- *Hit@k*: tỉ lệ câu hỏi có đáp án đúng nằm trong k kết quả đầu. Hit@1 cho biết kết quả đầu có đúng không, Hit@3 cho phép sai thứ hạng nhẹ.
- *MRR (mean reciprocal rank)*: trung bình của 1/thứ hạng của đáp án đúng đầu tiên; thưởng cho đáp án xếp cao.
- *nDCG@k*: như MRR nhưng tính nhiều đáp án và giảm dần theo thứ hạng. Báo cả ba vì mỗi chỉ số bắt một khía cạnh; đây là bộ chỉ số chuẩn của đánh giá truy hồi thông tin (Cranfield, TREC).
- *Tách nhóm ca (từ khóa, không dấu, diễn đạt khác, theo thứ)*: để biết điểm yếu nằm ở đâu thay vì chỉ một con số trung bình (nhóm "theo thứ" chỉ 50%).
- *Câu ngoài phạm vi và quét ngưỡng `MIN_SCORE`*: một hệ thống tốt phải biết từ chối khi không có thông tin. Quét ngưỡng cho thấy đánh đổi giữa từ chối đúng và từ chối nhầm câu hợp lệ.
- *`FLOORS`*: mốc chặn dưới đặt sát kết quả hiện tại, nên test trở thành cảnh báo hồi quy khi chất lượng tụt.

### 3.8 Độ trễ các hàm thuần (300 lần mỗi mức)

| Hàm | Quy mô | p50 | p95 | Độ dốc |
|---|---|---|---|---|
| Tìm giờ trống | 300 sự kiện / 5000 | 0,73 ms / 15,8 ms | 1,0 ms / 23,6 ms | 1,06 |
| Chuẩn hóa văn bản | 500 ký tự | 0,82 ms | 1,6 ms | 0,68 |
| Quy đổi mốc ngày | 500 lệnh gọi | 2,8 ms | 3,8 ms | 1,02 |
| Đọc file thời khóa biểu | 5000 dòng | 26,7 ms | 56,3 ms | 0,79 |
| Phát hiện xung đột import | **200 dòng** | **438 ms** | **469 ms** | **1,79 (gần bình phương)** |
| Mã hóa + giải mã | 1 MB | 26,6 ms | 28,8 ms | 0,93 |

Điểm chậm duy nhất là phát hiện xung đột khi import file lớn (B-07).

**Định nghĩa và lý do dùng**
- *Latency (độ trễ)*: thời gian một lần gọi hàm. Chỉ đo hàm thuần (không mạng, không database) để tách riêng chi phí tính toán; độ trễ API đầu-cuối cần backend thật nên chưa có.
- *p50 / p95 / p99*: phân vị của độ trễ; p95 là mức mà 95% lượt chạy nhanh hơn. Dùng phân vị thay cho trung bình vì người dùng cảm nhận các lượt chậm, và trung bình che mất chúng.
- *Warm-up và 300 lần mỗi mức*: bỏ vài lần đầu (nạp cache, import) và lặp đủ nhiều để p95 ổn định.
- *Độ dốc log-log*: đo nhiều kích thước đầu vào, vẽ log(thời gian) theo log(kích thước); độ dốc cho biết bậc tăng trưởng (1 tuyến tính, 2 bình phương). Dùng vì một điểm đo không cho biết hàm có chịu nổi dữ liệu lớn hơn không; phát hiện B-07 nhờ độ dốc 1,79.
- *Ngưỡng 200 ms cho 300 sự kiện*: lấy từ `tests/README.md` mục 2.4 của nhóm, vì vòng xếp lịch còn có LLM (khoảng 1,2 s mỗi lượt), phần tính toán phải nhỏ so với đó.

### 3.9 Chất lượng mã nguồn

| Công cụ | Kết quả |
|---|---|
| Độ phủ (dòng + nhánh) | **73% tổng** (65% trước khi bổ sung 80 test định dạng cho parser). Tốt: `parser` 86%, `proposals` 91%, `privacy` 85%, `validator` 82%, `auth` 81%, `rag` 81%. Yếu: `routers/events.py` 25%, `telemetry` 39%, `search_engine` 41%, `temporal` 63%, `eval_nlu` 0% |
| ruff | 234 phát hiện (141 tự sửa được); nhiều nhất: kiểu `Optional` (72), mặc định gọi hàm trong tham số (65, thường là mẫu `Depends` của FastAPI), import chưa sắp xếp (38), import thừa (18) |
| mypy | 32 lỗi trong 12 file (nhiều nhất `validator.py`) |
| bandit | 0 mức cao, 0 mức trung bình, 9 mức thấp (phần lớn báo nhầm: chuỗi `'password'`, `'bearer'`, URL OAuth); đáng xem `subprocess` trong `telemetry.py` và `try/except/pass` trong `nlu.py` |
| radon | Độ phức tạp trung bình hạng B (5,7) trên 294 hàm; 36 hàm từ hạng C trở lên (14 hàm hạng D đến F). Nặng nhất: `_retrieve_structured_kb_hits` (113), `understand` ở router trợ lý (102), `resolve_date_hint` (52), `_parse_timetable_table_rows` (46). `search_engine.py` có chỉ số bảo trì hạng C (điểm 0) |

`parser.py` ban đầu chỉ 39% vì các nhánh PDF, ảnh/OCR và bảng có tiêu đề không có test nào (repo không có file mẫu PDF hoặc ảnh; `parser_test.py`, `ingestion_test.py` là script tự kiểm không nằm trong pytest). Sau khi bổ sung `tests/test_parser_formats.py` (80 test, tự sinh PDF và ảnh lúc chạy) độ phủ lên **86%**.

Hàm càng phức tạp càng khó kiểm thử; các hàm hạng F trùng với các module có độ phủ thấp, nên đây là nơi dễ có lỗi chưa phát hiện.

**Định nghĩa và lý do dùng**
- *Độ phủ (coverage)*: tỉ lệ dòng (và nhánh) mã được test chạy qua. Dùng để tìm vùng không test nào chạm tới; không chứng minh test đúng. Ngưỡng 80% (lõi 90%) là thực hành phổ biến.
- *Độ phủ nhánh*: đếm cả hai hướng của mỗi `if`, nên chặt hơn độ phủ dòng.
- *ruff*: kiểm tra phong cách và lỗi cú pháp thường gặp (import thừa, mặc định gọi hàm trong tham số). Dùng vì nhanh và bắt lỗi nhỏ sớm.
- *mypy*: kiểm tra kiểu tĩnh. Dùng vì dự án dùng chú thích kiểu của Python 3.12 và Pydantic, sai kiểu thường lộ ở lúc chạy.
- *bandit*: quét lỗ hổng bảo mật tĩnh (mật khẩu viết cứng, `subprocess`, `try/except/pass`). Ngưỡng "không có mức cao"; nhiều cảnh báo mức thấp là báo nhầm nên cần đọc tay.
- *radon (độ phức tạp cyclomatic, MI)*: số đường đi độc lập qua hàm (McCabe); trên 10 là khó hiểu và khó test. Chỉ số bảo trì (MI) tổng hợp thêm độ dài và độ khó. Dùng để chỉ ra nơi dễ có lỗi ẩn, đặc biệt khi trùng với độ phủ thấp.

### 3.10 Hạ tầng host (đọc, không ghi)

| Kiểm tra | Kết quả |
|---|---|
| vLLM `/v1/models` | `200`, đúng model `Meta-Llama-3.1-8B-Instruct-AWQ-INT4`; p50 11 ms |
| Backend `/health`, `/health/db` | `200`, `ok`; từ máy QA qua VPN: 120 lần, 0 lỗi, p50 78,6 ms, p95 92,5 ms |
| `/openapi.json` | 33 đường dẫn, khớp mã nguồn hiện tại (ban đầu chỉ có 28, đã cập nhật) |
| Header chẩn đoán | `X-Request-ID`, `X-Process-Time-Ms`, `X-Error-Source` có mặt |
| `/api/v1/debug/logs` | hoạt động, `endpoint_allowed = true` |
| Truy cập không token | `401` đúng |

Độ trễ 78 ms của `/health` gồm cả đường truyền VPN, không phải thời gian xử lý của backend (header `X-Process-Time-Ms` ghi 0,5 ms).

**Định nghĩa và lý do dùng**
- *Kiểm tra chỉ đọc (read-only probe)*: chỉ gửi yêu cầu `GET`, không tạo tài khoản hay dữ liệu trên host dùng chung. Dùng vì host là môi trường của cả nhóm và tạo dữ liệu cần được cho phép.
- */health, /health/db*: xác nhận backend và database sống; là nền cho chỉ số độ sẵn sàng (availability).
- *Kiểm tra openapi*: so số đường dẫn của host với mã hiện tại để biết host chạy đúng phiên bản; tránh báo lỗi cho phiên bản đã cũ.
- *Header chẩn đoán*: `X-Request-ID` để lần theo một yêu cầu, `X-Process-Time-Ms` để tách thời gian xử lý khỏi thời gian mạng, `X-Error-Source` để biết lỗi do AI hay backend.
- *Truy cập không token trả `401`*: kiểm tra tối thiểu của kiểm soát truy cập (OWASP ASVS).

### 3.11 Dữ liệu tri thức (KB)
Chỉ có test chức năng: 43 test của crawler và dữ liệu cấu trúc đều đạt. Các chiều chất lượng dữ liệu chưa đo (cần MySQL). Truy vấn SQL mẫu có trong lịch sử trao đổi QA và `QA_Guide.md`.

**Định nghĩa và lý do dùng**
- *KB (knowledge base)*: dữ liệu quy chế, thông báo trường được thu thập và dùng để trả lời câu hỏi. Câu trả lời sai vì dữ liệu sai hay thiếu, nên chất lượng dữ liệu quyết định chất lượng trả lời.
- *Chiều chất lượng dữ liệu (ISO/IEC 25012, 25024)*: đầy đủ (không thiếu trường bắt buộc), nhất quán (không mâu thuẫn), không trùng lặp, đúng định dạng, cập nhật (ngày hết hạn), có nguồn. Chưa đo vì cần truy vấn MySQL; test chức năng chỉ cho biết crawler chạy đúng, không cho biết dữ liệu tốt.
- *Mẫu duyệt tay (`kb_sample_for_review.csv`)*: độ đúng của nội dung cần người đọc; lấy mẫu ngẫu nhiên để ước lượng tỉ lệ sai với khoảng tin cậy.

### 3.12 Các cách dùng thật (bạn bè và thầy)
Thu thập 17 mô tả từ 6 người, lưu ở `QA  docs/real_user_prompts.jsonl`.

| Nhóm yêu cầu | Hỗ trợ hiện nay |
|---|---|
| Chia thời gian giữa 2 việc (hạn nộp và thi); lập thời khóa biểu cả tuần; lộ trình ôn thi nhiều ngày | Không |
| Tìm khoảng trống từ 45 phút trong tuần | Một phần |
| Dán danh sách môn từ portal rồi bảo xếp | Một phần (có nhập, không tự xếp) |
| Ràng buộc nhiều lớp (ngủ, thể dục theo hạn mức, khung cấm, thời gian đi lại) | Một phần (có giờ ngủ, khoảng nghỉ) |
| Liên kết Google Calendar; việc lặp hằng ngày | Không |
| Trợ lý hỏi lại khi cần xác nhận | Có |

Bộ luật hiểu sai nhiều câu này (đọc "học tiếng Đức 30 phút mỗi ngày" thành việc 30 phút; "khoảng trống từ 45 phút" thành việc 45 phút). 3 trong 11 prompt dài bị cắt vì giới hạn 500 ký tự; một câu mất đoạn "để trống tối thứ 7". Mẫu nhỏ, chọn thuận tiện, nên chỉ để minh họa.

**Định nghĩa và lý do dùng**
- *Câu thật (real-user prompts)*: mô tả do người ngoài nhóm viết, không biết mã nguồn. Dùng để đo khoảng cách giữa "đúng với câu nhóm dự tính" (3.2) và "đúng với cách người ta thật sự nói", điều mà bộ 200 ca tự viết không cho thấy.
- *Mức hỗ trợ (Có / Một phần / Không)*: so từng yêu cầu với tính năng hiện có. Đây là đo độ phủ nhu cầu (functional suitability trong ISO/IEC 25010), không phải đo độ chính xác.
- *Giới hạn 500 ký tự*: kiểm tra riêng vì `sanitize_prompt` cắt đầu vào, câu dài của người dùng có thể mất phần quan trọng mà không báo.
- *Mẫu nhỏ, chọn thuận tiện*: nên không dùng để tính tỉ lệ; chỉ dùng để phát hiện loại nhu cầu bị bỏ sót. Cần thử với 5 đến 10 sinh viên (SUS) để có số liệu thật.

---

## 4. Danh sách lỗi

| ID | Mức | Khu vực | Mô tả | Bằng chứng |
|---|---|---|---|---|
| B-01 | Cao | FE | `api_client.py:337,388`: `lambda dt: on_error(None, str(e))` dùng `e` sau khối `except` → `NameError`, người dùng không thấy thông báo lỗi. Sửa: gán `msg = str(e)` trước lambda | test `PH05` (pyflakes) |
| B-02 | Cao | BE (parser) | Ô giờ có hậu tố múi giờ ở một bên (`08:00Z`, `08:00+07:00`) làm `TypeError` ở `parser.py:467`, cả file import bị hủy; vi phạm quy tắc "không sập khi gặp dòng lỗi" | `test_parser_import.py` (xfail), fuzz |
| B-03 | Trung bình | BE (parser) | File CSV xuất từ Excel (UTF-8 có BOM): dòng tiêu đề thành dòng lỗi `INVALID_KIND` (decode `utf-8` thay vì `utf-8-sig`) | xfail |
| B-04 | Thấp | BE (parser) | Giờ có hậu tố múi giờ ở cả hai bên được chấp nhận thay vì từ chối | xfail |
| B-05 | Trung bình | NLU | `xoá` (đặt dấu khác `xóa`) không nhận là lệnh xóa; ca 116 | `eval_nlu --rules` |
| B-06 | Trung bình | NLU | Câu hỏi lịch tiếng Anh có `schedule` bị hiểu thành xếp lịch; đoạn bảo vệ còn ép cả kết quả đúng của LLM sang `schedule_task`; ca 165 | `eval_nlu` |
| B-07 | Trung bình | BE (hiệu năng) | `detect_import_conflicts` gần bình phương: 200 dòng CSV mất 0,44 đến 0,47 giây | `bench_pure.py` |
| B-08 | Cao | Bảo mật | Thiếu `JWT_SECRET_KEY` hoặc `DATA_ENCRYPTION_KEY` thì dùng khóa mặc định công khai (`dev-secret-key-...`, `dev-encryption-key-...`); khóa mã hóa lại là SHA-256 của chuỗi, không có salt hay vòng lặp | test mã hóa, `BE_QA.md` mục 3 |
| B-09 | Trung bình | BE (RAG) | Đổi khóa mã hóa rồi ghi tiếp làm mất vĩnh viễn chỉ mục cũ (đọc ra rỗng, lần ghi sau ghi đè) | `test_crypto.py` |
| B-10 | Cao | Quy trình | `auth_session.json`, `chat_history_db.json` (ở `sourceCode/FE/` và `tests/`) vẫn nằm trong git, có chứa token; file lạ `tests/tatus -sb` cũng bị theo dõi | `git ls-files` |
| B-11 | Trung bình | FE | Thông báo nhắc hẹn hiện "Tên sự kiện: At " (thừa chữ `At`, thiếu địa điểm hoặc giờ); tiêu đề là "Upcoming Event" thay vì nội dung test chờ | `NT02`, `NT06` |
| B-12 | Trung bình | RAG | `MIN_SCORE = 0.12` chỉ từ chối đúng 25% câu ngoài phạm vi; viết tắt không dấu và câu hỏi theo thứ trong tuần truy hồi kém | `test_rag_quality.py` |
| B-13 | Thấp | Quy trình | Test cũ (xem 3.1) làm báo động giả; tài liệu hướng dẫn cài đặt nhắc `requirements.txt` đã bị gộp | `run_qa.ps1` |
| B-14 | Thấp | BE (thiết kế) | Chính sách mật khẩu tối thiểu 6 ký tự (test kỳ vọng 8) | `SEC25` |

Từ tài liệu `BE_QA.md` mục 6 (chưa tự tái hiện): `PATCH /events` không trả thông tin nhắc hẹn khi đổi `is_important`; kiểm tra lưới 15 phút chỉ áp cho giờ bắt đầu ở `/proposals/manual`; dữ liệu KB chờ duyệt (`PENDING`) vẫn dùng để trả lời; trạng thái làm rõ đa lượt chưa có giới hạn số lượt.

---

## 5. Đối chiếu với tiêu chí (SLO)

| Tiêu chí | Mục tiêu | Kết quả | Trạng thái |
|---|---|---|---|
| Free-slot đúng | Bất biến 0 vi phạm; khớp bản tham chiếu 100% | 2000/2000 | **Đạt** |
| Free-slot độ trễ | p95 < 200 ms (300 sự kiện) | 1,0 ms | **Đạt** |
| Schema adherence (NLU, LLM) | ≥ 98% | 98,0% trung bình (588/600 lượt; 97,0 đến 98,5% theo lần chạy; khoảng tin cậy 96,5 đến 98,9%) | **Sát ngưỡng, chưa chắc đạt** |
| Bịa ngày (NLU) | 0 | 0 ca bịa ngày trên 600 lượt | **Đạt** |
| Intent / duration / date_hint (NLU, LLM) | ≥ 95% / 95% / 90% (đề xuất) | intent 99,0%, duration 100%, date_hint 97,5% (cả 3 lần giống nhau) | **Đạt trên bộ 200 ca** (cận dưới khoảng tin cậy: intent 96,4%, date_hint 94,3%); xem lưu ý ở 3.2 |
| Fallback khi AI sập, không bao giờ `500` | 100% | Có test đạt; chưa đo trên host | **Chưa đủ bằng chứng** |
| Độ trễ API đầu-cuối (≤ 4 s), độ sẵn sàng | theo SLO nhóm | Chưa đo | **Chưa đo** |
| Test tự động | 0 fail | 21 fail (xem 3.1) | **Chưa đạt** |
| Độ phủ | ≥ 80% (module lõi ≥ 90%) | 73%; `proposals` 91%, `parser` 86%, `search_engine` 41% | **Chưa đạt** (đã cải thiện) |
| Độ phức tạp hàm | ≤ 10 | 36 hàm vượt (14 hàm hạng D đến F) | **Chưa đạt** |
| Bảo mật tĩnh (bandit) | không có mức cao | 0 mức cao | **Đạt** |

---

## 6. Khuyến nghị (theo thứ tự ưu tiên)

1. **Ngay:** sửa B-01 (gán `msg = str(e)`); bắt `TypeError` trong parser và đánh dấu dòng lỗi thay vì hủy file (B-02); gỡ file token khỏi git và đổi `JWT_SECRET_KEY` trên host (B-10, B-08); đặt `DATA_ENCRYPTION_KEY` một lần trước khi nạp dữ liệu và **không đổi** sau đó (B-09).
2. **Trước khi chốt số liệu:** chốt SLO với Data/Lead; chạy NLU với LLM thật (đã làm trong báo cáo này) và lặp lại sau mỗi lần sửa NLU; sửa B-05, B-06 rồi chạy lại 200 ca.
3. **Làm sạch bộ test:** cập nhật 12 test lỗi thời, quyết định 6 test cần PIC, xử lý 3 test cho thấy lỗi thật; mục tiêu cuối: `run_qa.ps1` không còn fail.
4. **Nâng độ phủ** cho `search_engine`, `routers/events.py`, `telemetry`, `temporal` (parser đã lên 86%); tách các hàm hạng F (`understand`, `_retrieve_structured_kb_hits`, `resolve_date_hint`).
5. **Chỉnh RAG:** thử `MIN_SCORE` khoảng 0,25 kèm mở rộng viết tắt (`ctdl`, `xstk`, `gdtc`) và xử lý câu hỏi theo thứ.
6. **Phạm vi sản phẩm:** quyết định tính năng nào trong nhóm "lập kế hoạch cả tuần" nằm trong phạm vi; ghi khoảng cách chức năng vào báo cáo đồ án như một hạn chế đã biết.
7. **Đo còn thiếu:** KB (cần MySQL), API trên host (cần cho phép tạo tài khoản thử và người có quyền dọn), giao diện thủ công theo `QA_Guide.md` Phần E, Android, người dùng thật (5 đến 10 sinh viên, SUS), và người thứ hai gán nhãn để tính kappa.

---

## 7. Hạn chế của báo cáo
- Số liệu NLU và RAG dựa trên bộ ca do một người viết sau khi đọc mã nguồn; kho quy chế là văn bản mô phỏng. Dùng làm mốc hồi quy, không phải độ chính xác ngoài đời.
- Mỗi số đo đã ghi rõ n. Khoảng tin cậy là Wilson 95%.
- Các số về host đo từ một máy qua VPN tại một thời điểm; không đại diện cho tải thực tế.
- Phân tích tĩnh chỉ đếm lỗi, không đánh giá mức nghiêm trọng của từng lỗi.
- Báo cáo này không thay thế kiểm thử giao diện thủ công và thử nghiệm với người dùng thật.

---

## Phụ lục. Tái hiện số liệu

```powershell
cd "<repo>"
.\.venv\Scripts\Activate.ps1
python -m pip install -r "QA  docs\requirements-qa.txt"
.\"QA  docs"\run_qa.ps1 -All
```

NLU với LLM thật:

```powershell
cd sourceCode\BE
$env:VLLM_ENDPOINT="http://26.211.52.63:8000/v1/chat/completions"; $env:LLM_ALLOWED_HOSTS="26.211.52.63"
1..3 | ForEach-Object { python tools/eval_nlu.py }
```

Dữ liệu kèm theo: `tests/search_eval.jsonl`, `tests/search_eval_corpus.jsonl`, `QA  docs/real_user_prompts.jsonl`, `QA  docs/bench_results.json`, `QA  docs/last_run/*.log`.
