# Bộ kịch bản prompt kiểm thử: Tính năng Xếp lịch cùng AI (Scheduling with AI)

Tài liệu này cung cấp danh sách **12 kịch bản Prompt kiểm thử phân hoạch tương đương (Equivalence Partitioning & Boundary Testing)** cho tính năng **Xếp lịch cùng AI** (`POST /api/v1/assistant/understand` và chuỗi thao tác `Confirm / Reject / Reschedule`).

Mỗi kịch bản được thiết kế để đánh trúng một nhánh logic hoặc cơ chế kỹ thuật riêng biệt trong hệ thống, đảm bảo không có hai prompt nào trùng lặp tính chất kiểm thử.

---

## Ma trận Bao phủ Kỹ thuật (Coverage Matrix)

| Mã Case | Nhóm tính chất / Góc kỹ thuật kiểm thử | File & Hàm xử lý chính trong Backend |
| :--- | :--- | :--- |
| **TC-01** | Luồng chuẩn (Happy Path) + Ưu tiên buổi (`preferred_time_of_day`) + Ngày tương đối | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py), [`services/proposals.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py) (`_score`, `create_proposal`) |
| **TC-02** | Ràng buộc né buổi (`avoid_time_of_day`) + Giả định cửa sổ 7 ngày (`date_assumed`) | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) (`_time_of_day_flags`), [`services/temporal.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/temporal.py) |
| **TC-03** | Tách biệt Cửa sổ tìm kiếm (`date_hint`) và Chốt chặn Hạn chót (`deadline_hint`) | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) (`_finalize`), [`services/search_engine.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/search_engine.py) |
| **TC-04** | Khung giờ đồng hồ cụ thể (`parse_clock_window` / `requested_start`) | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) (`parse_clock_window`, `_strip_clock_times`), [`services/proposals.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py) (`_pick_slot`) |
| **TC-05** | Tự động chia nhỏ việc dài (`Task Splitting` khi `duration > max_block_minutes`) | [`services/proposals.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py) (`split_task`, `extra_slots_json`) |
| **TC-06** | Chuẩn hóa Teencode, Tiếng Việt không dấu & Khử thông tin nhạy cảm (PII Masking) | [`services/privacy.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/privacy.py) (`sanitize_prompt`), [`services/normalizer.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/normalizer.py) (`normalize_text`) |
| **TC-07** | Chốt chặn Hỏi làm rõ khi khuyết Thời lượng (Chống AI tự bịa `duration_minutes`) | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) (`has_duration_phrase`, `_finalize`) |
| **TC-08** | Chốt chặn Hỏi làm rõ khi từ chỉ ngày quá mơ hồ (`Vague Temporal Guard`) | [`services/temporal.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/temporal.py) (`resolve_date_hint`), [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) |
| **TC-09** | Đổi lịch đa vòng (`Reschedule`) + Bộ nhớ từ chối (`excluded_slots`) | [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py), [`services/proposals.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py) (`_ancestor_slots`, `_subtract`) |
| **TC-10** | Tự động hủy đề xuất treo khi chuyển chủ đề mới (`Abandon Pending Proposals`) | [`database.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/database.py) (`abandon_pending_proposals`), [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py) |
| **TC-11** | Điều hướng chéo khi gõ câu hỏi Tra cứu lịch / Học vụ vào khung Trợ lý AI | [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py) (`redirect_target = "search_home"`) |
| **TC-12** | Chịu lỗi Hạ tầng AI & Chuyển sang Chọn lịch Thủ công (`Graceful AI Fallback`) | [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py) (`rule_based_understand`, `log_ai_error`), [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py) (`available_slots`) |

---

## Chi tiết 12 Kịch bản Prompt & Danh mục Kiểm tra (Checklist)

---

### TC-01: Luồng chuẩn với Ưu tiên Buổi trong ngày và Ngày tương đối

* **Prompt tự nhiên (dùng để nhập vào ô chat):**
  ```text
  Xếp giúp mình 2 tiếng ôn tập Giải tích vào chiều ngày mai
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Kiểm tra đường đi chuẩn (Happy Path) của ý định `schedule_task` từ bước trích xuất thực thể qua vLLM, quy đổi ngày tương đối `"ngày mai"`, chấm điểm ưu tiên buổi chiều (`preferred_time_of_day = "afternoon"`, khung `12:00-18:00` nhận điểm tối ưu `0.0` trong hàm [`_score`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py#L68-L80)), và nguyên tắc an toàn **Human-in-the-Loop** (chỉ tạo bản ghi `Proposal` trạng thái `PROPOSED`, chưa tạo bản ghi trong bảng `events`).
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` trả về đúng `"schedule_task"`.
  - [ ] Trường `nlu.title` trích xuất sạch tên hoạt động (ví dụ: `"ôn tập Giải tích"`, không dính các từ rác `"xếp giúp mình"`, `"2 tiếng"`, `"chiều ngày mai"`).
  - [ ] Trường `nlu.duration_minutes` bằng `120`.
  - [ ] Trường `nlu.preferred_time_of_day` bằng `"afternoon"`, `nlu.avoid_time_of_day` bằng `null`.
  - [ ] Trường `nlu.date_hint` bằng `"ngày mai"`, và cả `window_start` lẫn `window_end` đều trỏ đúng vào ngày dương lịch của ngày mai (`date_assumed = false`).
  - [ ] Hệ thống trả về đối tượng `proposal` khác `null` với `status = "PROPOSED"`, khung giờ đề xuất nằm trong khoảng `12:00` đến `18:00` ngày mai (múi giờ `+07:00`), căn chẵn lưới 15 phút (`:00`, `:15`, `:30`, `:45`) và không đè lên bất kỳ lớp học cứng (`is_hard = true`) hay giờ ngủ nào.
  - [ ] Kiểm tra trong MySQL: Bảng `proposals` có thêm 1 dòng `PROPOSED`, bảng `tasks` có thêm 1 dòng `PENDING`, nhưng bảng `events` **chưa** sinh ra sự kiện này cho tới khi người dùng bấm nút **Confirm**.

---

### TC-02: Ràng buộc Phủ định Buổi (`avoid_time_of_day`) và Tự mở rộng Cửa sổ 7 ngày (`date_assumed`)

* **Prompt tự nhiên:**
  ```text
  Xếp 90 phút làm bài tập Hệ điều hành, đừng xếp vào buổi tối nhé
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào hai cơ chế: (1) Bộ nhận diện phủ định ngữ cảnh trước từ chỉ buổi (`"đừng"`, `"không"`, `"tránh"` đứng trong phạm vi 3 từ trước `"buổi tối"` tại hàm [`_time_of_day_flags`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L238-L251)) để điền vào `avoid_time_of_day` thay vì `preferred_time_of_day`; (2) Cơ chế tự giả định cửa sổ tìm kiếm 7 ngày tới (`DEFAULT_WINDOW_DAYS = 7`, `date_assumed = true`) khi người dùng không nêu ngày cụ thể.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` bằng `"schedule_task"` và `nlu.duration_minutes` bằng `90`.
  - [ ] Trường `nlu.avoid_time_of_day` bằng `"evening"` và `nlu.preferred_time_of_day` bằng `null` (không bị nhận nhầm thành muốn học buổi tối).
  - [ ] Trường `nlu.date_hint` bằng `null`, cờ `nlu.date_assumed` bằng `true`, cửa sổ `[window_start, window_end]` mở rộng từ ngày hiện tại đến 6 ngày kế tiếp.
  - [ ] Khung giờ trong `proposal` trả về nằm vào ban ngày (trước `18:00`), tránh hoàn toàn khung giờ tối `18:00-23:00`.

---

### TC-03: Câu ghép có cả Cửa sổ Tìm kiếm (`date_hint`) và Chốt chặn Hạn chót (`deadline_hint`)

* **Prompt tự nhiên:**
  ```text
  Hạn nộp báo cáo Mạng máy tính là thứ sáu, xếp cho mình 2 tiếng làm báo cáo trong tuần này
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào cơ chế tách biệt `date_hint` và `deadline_hint` trong [`NluResult`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L87-L98) và bước khóa cận trên tại [`_finalize`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L392-L399). Cụm `"tuần này"` mở rộng cửa sổ tìm kiếm đến hết Chủ Nhật, nhưng cụm `"Hạn nộp ... là thứ sáu"` phải kích hoạt `deadline_hint = "thứ sáu"` để ép `window_end <= deadline` (tức tối Thứ Sáu), đảm bảo thuật toán quét giờ trống không bao giờ gợi ý làm bài vào Thứ Bảy hoặc Chủ Nhật (sau hạn nộp). Đồng thời kiểm tra khả năng tự gán mức ưu tiên cao nhất (`priority = 1`) khi có từ khóa `"hạn nộp"`.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.date_hint` bằng `"tuần này"` và trường `nlu.deadline_hint` bằng `"thứ sáu"`.
  - [ ] Trường `nlu.deadline` được quy đổi thành ngày dương lịch của Thứ Sáu tuần hiện tại.
  - [ ] Trường `nlu.window_end` bị khóa chặn trên bằng đúng ngày Thứ Sáu (`window_end == deadline`), không bị tràn sang Thứ Bảy hay Chủ Nhật.
  - [ ] Trường `nlu.priority` tự động nhận giá trị `1` (mức ưu tiên cao nhất).
  - [ ] Khung giờ đề xuất trong `proposal` kết thúc trước `23:59` ngày Thứ Sáu (đạt tiêu chí cứng `No Missed Deadline`).

---

### TC-04: Chỉ định Khung giờ Đồng hồ Cụ thể (`parse_clock_window` / `requested_start`)

* **Prompt tự nhiên:**
  ```text
  Ngày mai xếp lịch họp nhóm đồ án từ 14h đến 15h30
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào bộ lọc [`_strip_clock_times`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L175-L177) và [`parse_clock_window`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L189-L204). Trước đây, các con số chỉ mốc đồng hồ như `"14h"` rất dễ bị đọc nhầm thành thời lượng `"14 tiếng"`. Prompt này kiểm tra việc hệ thống nhận diện đúng khoảng giờ đồng hồ `14:00 -> 15:30`, tự suy ra thời lượng bằng hiệu số `15h30 - 14h00 = 90` phút, điền `requested_start = "14:00"`, `requested_end = "15:30"`, và ép hàm [`_pick_slot`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py#L94-L95) chọn chính xác mốc `14:00` (với điểm ưu tiên tuyệt đối `-1.0`) nếu khung đó đang trống.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.duration_minutes` được tính đúng bằng `90` (tuyệt đối không bị đọc nhầm `"14h"` thành `840` phút hoặc lỗi vượt ngưỡng).
  - [ ] Trường `nlu.requested_start` bằng `"14:00"` và `nlu.requested_end` bằng `"15:30"`.
  - [ ] Trường `nlu.title` không còn sót các chữ `"từ 14h đến 15h30"`.
  - [ ] Nếu chiều mai từ `14:00` đến `15:30` của user đang trống, `proposal.start_time` bắt đầu đúng lúc `14:00:00+07:00` và `proposal.end_time` kết thúc đúng lúc `15:30:00+07:00` (không bị đẩy tự động về `08:00` sáng).

---

### TC-05: Tự động Chia nhỏ Công việc Dài (`Task Splitting` qua hàm đệ quy `split_task`)

* **Prompt tự nhiên:**
  ```text
  Thứ bảy tuần này xếp cho mình 5 tiếng làm đồ án Trí tuệ nhân tạo
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào thuật toán đệ quy chia nhỏ công việc [`split_task`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py#L119-L151) (yêu cầu kiến trúc `P2-4`). Vì cấu hình `UserPreference.max_block_minutes` mặc định giới hạn mỗi phiên làm việc liên tục tối đa `180` phút (3 tiếng), một yêu cầu kéo dài `300` phút (5 tiếng) vượt quá `cap = 180` nên không được phép xếp thành 1 khối 5 tiếng liên tục. Hệ thống phải tự động cắt thành nhiều khối nhỏ (mỗi khối `<= 180` phút và `>= 30` phút, tối đa `MAX_PIECES = 6` khối), lưu khối đầu vào `start_time/end_time` và các khối còn lại vào cột JSON `extra_slots_json`.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.duration_minutes` bằng `300`.
  - [ ] Hệ thống trả về `proposal` khác `null`, trong đó độ dài của khối chính (`end_time - start_time`) không vượt quá `180` phút.
  - [ ] Trường `proposal.extra_slots` (hoặc `extra_slots_json` trong DB) chứa các khối thời gian bổ sung, và tổng thời lượng của tất cả các khối cộng lại bằng đúng `300` phút.
  - [ ] Không có bất kỳ khối lẻ nào ngắn hơn `30` phút (`MIN_BLOCK_MIN = 30`), và giữa các khối đảm bảo khoảng nghỉ đệm (`min_break_minutes = 15`).
  - [ ] Trường `proposal.rationale` có câu thông báo rõ: `"Công việc 300 phút được chia thành ... khối vì không có khoảng trống liên tục đủ dài."`

---

### TC-06: Chuẩn hóa Teencode, Tiếng Việt Không dấu & Khử Thông tin Nhạy cảm (PII Sanitization)

* **Prompt tự nhiên:**
  ```text
  xep giup m 1h30p lam bt ctdl vao sang mai, gui qua mail sv24120001@student.hcmus.edu.vn sdt 0912345678
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào tầng tiền xử lý bảo mật và ngôn ngữ trước khi chạm tới LLM: (1) Hàm [`sanitize_prompt`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/privacy.py) phải quét và che giấu toàn bộ địa chỉ email thành `[EMAIL]` và số điện thoại Việt Nam thành `[PHONE]` để không bao giờ gửi PII thô sang tiến trình AI hoặc ghi xuống nhật ký lỗi; (2) Hàm [`normalize_text`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/normalizer.py) phải khôi phục dấu tiếng Việt và bung từ viết tắt teencode (`"xep giup m"` -> `"xếp giúp mình"`, `"bt"` -> `"bài tập"`, `"sang mai"` -> `"sáng mai"`); (3) Biểu thức [`_HOURS_MINUTES_RE`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L172) phải đọc đúng định dạng ghép `"1h30p"` thành `90` phút.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` bằng `"schedule_task"`, `nlu.duration_minutes` bằng `90`.
  - [ ] Trường `nlu.preferred_time_of_day` bằng `"morning"`, `nlu.date_hint` bằng `"ngày mai"` (sau khi chuẩn hóa `"sang mai"` -> `"sáng ngày mai"`).
  - [ ] Trong tiêu đề `nlu.title` hoặc trong bảng nhật ký lỗi `ai_error_logs` (nếu có), địa chỉ email `sv24120001@student.hcmus.edu.vn` và số điện thoại `0912345678` đã bị thay thế bằng nhãn ẩn danh (`[EMAIL]`, `[PHONE]`), không lộ dữ liệu cá nhân thô.
  - [ ] Hệ thống tạo đề xuất thành công vào buổi sáng ngày mai (`06:00-12:00`).

---

### TC-07: Chốt chặn Hỏi làm rõ khi Thiếu Thời lượng (`Missing Duration Guard`)

* **Prompt tự nhiên:**
  ```text
  Chiều thứ năm tuần này xếp lịch cho mình đi tập thể thao nhé
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào chốt chặn chống ảo giác thời lượng tại [`_finalize`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L365-L366) và dòng 400-402. Ngay cả khi mô hình LLM tự đoán một con số mặc định (như `60` phút), hàm [`has_duration_phrase(prompt)`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L213-L215) kiểm tra văn bản gốc của người dùng, phát hiện không có bất kỳ cụm từ chỉ thời lượng nào nên ép `result.duration_minutes = None`, bật cờ `needs_clarification = true` và dừng lại hỏi người dùng thay vì tự ý xếp lịch.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` bằng `"schedule_task"`, `nlu.preferred_time_of_day` bằng `"afternoon"`, `nlu.date_hint` nhận diện đúng `"thứ năm"`.
  - [ ] Trường `nlu.duration_minutes` bắt buộc bằng `null` (không bị AI tự bịa ra `60` hay `90`).
  - [ ] Trường `nlu.needs_clarification` bằng `true`.
  - [ ] Trường `nlu.clarification_question` trả về câu hỏi: `"Bạn muốn dành bao lâu cho hoạt động này?"`.
  - [ ] Trường `proposal` trong JSON phản hồi bằng `null` (không sinh bản ghi rác trong bảng `proposals`).

---

### TC-08: Chốt chặn Hỏi làm rõ khi Cụm từ Thời gian Mơ hồ (`Vague Temporal Guard`)

* **Prompt tự nhiên:**
  ```text
  Xếp cho mình 1 tiếng đọc tài liệu nghiên cứu vào lúc nào đó sắp tới
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào nhánh kiểm tra độ mơ hồ thời gian (`P2-3`) trong [`services/temporal.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/temporal.py) và biểu thức `_DATE_HINT_RE` trong [`services/nlu.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L142-L143). Khác với TC-02 (người dùng bỏ trống hoàn toàn ngày nên hệ thống áp dụng mặc định 7 ngày), ở đây người dùng cố tình dùng các từ bất định (`"lúc nào đó"`, `"sắp tới"`, `"khi nào rảnh"`, `"vài hôm nữa"`). Hệ thống phải bắt được cụm từ mơ hồ này và yêu cầu sinh viên xác nhận lại ngày cụ thể.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` bằng `"schedule_task"` và `nlu.duration_minutes` bằng `60`.
  - [ ] Trường `nlu.date_hint` bắt được cụm từ mơ hồ (`"lúc nào đó"` hoặc `"sắp tới"`).
  - [ ] Trường `nlu.needs_clarification` bằng `true` và `nlu.clarification_question` khác `null` (yêu cầu người dùng làm rõ ngày/tuần muốn xếp).
  - [ ] Trường `proposal` trong JSON phản hồi bằng `null`.

---

### TC-09: Đổi lịch Đa vòng (`Reschedule`) và Bộ nhớ Từ chối (`excluded_slots`)

* **Điều kiện tiên quyết:** Thực hiện ngay sau khi nhận được thẻ đề xuất ở **TC-01** (lấy `proposal.id` vừa tạo làm `reschedule_proposal_id`, hoặc bấm nút **Reschedule** trên giao diện chat).
* **Prompt tự nhiên (kèm `reschedule_proposal_id = <id_của_TC_01>`):**
  ```text
  Dời sang buổi sáng giúp mình, khung giờ đó mình bận rồi
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào luồng `reschedule` có trạng thái trong [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py#L52-L76) và hàm [`_ancestor_slots`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/proposals.py#L154-L167) trong `services/proposals.py`. Khi truyền `reschedule_proposal_id`, hệ thống phải: (1) không hủy đề xuất cha ở bước đầu (`abandoned_proposals = 0`); (2) kế thừa nguyên vẹn `task_id`, `title` (`"ôn tập Giải tích"`) và `duration_minutes` (`120`) từ đề xuất cha dù câu prompt mới không hề nhắc lại tên môn hay số giờ; (3) gom toàn bộ các khung giờ của chuỗi đề xuất cha vào danh sách loại trừ `excluded_slots` để không bao giờ đề xuất lặp lại khung giờ cũ; (4) chuyển trạng thái đề xuất cha sang `RESCHEDULED` và tạo đề xuất con mới (`parent_id` trỏ về đề xuất cha).
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `abandoned_proposals` trong JSON phản hồi bằng `0`.
  - [ ] Đề xuất mới (`proposal`) giữ nguyên `task_id`, `title` (`"ôn tập Giải tích"`) và thời lượng `120` phút của TC-01.
  - [ ] Trường `proposal.parent_id` bằng đúng `id` của đề xuất ở TC-01.
  - [ ] Khung giờ mới nằm vào buổi sáng (`06:00-12:00`) và hoàn toàn khác với khung giờ đã bị từ chối ở TC-01.
  - [ ] Kiểm tra trong MySQL: Bản ghi `Proposal` cũ của TC-01 đã chuyển trạng thái từ `PROPOSED` sang `RESCHEDULED`.

---

### TC-10: Tự động Đóng Đề xuất Treo khi Chuyển sang Chủ đề Mới (`Abandon Pending Proposals`)

* **Điều kiện tiên quyết:** Đang có ít nhất 1 thẻ đề xuất ở trạng thái `PROPOSED` trên màn hình (ví dụ thẻ vừa sinh ra ở TC-09), nhưng người dùng **không** bấm Confirm/Reject/Reschedule mà gõ luôn một câu lệnh gốc mới (`reschedule_proposal_id = null`).
* **Prompt tự nhiên (với `reschedule_proposal_id = null`):**
  ```text
  Sáng thứ tư tuần sau xếp cho mình 45 phút chuẩn bị slide thuyết trình
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào quy tắc vòng đời đề xuất tại `AGENTS.md` Mục 4 và hàm [`abandon_pending_proposals`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/database.py) được gọi ở đầu [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py#L50-L51). Khi người dùng bắt đầu một yêu cầu xếp lịch gốc mới mà bỏ lửng đề xuất cũ đang chờ xác nhận, hệ thống phải tự động chuyển toàn bộ các đề xuất `PROPOSED` cũ của user đó sang `ABANDONED` để dọn sạch trạng thái treo trước khi tạo đề xuất mới.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `abandoned_proposals` trong JSON phản hồi lớn hơn hoặc bằng `1`.
  - [ ] Kiểm tra trong MySQL: Đề xuất đang chờ ở lượt trước đã tự động chuyển sang `status = "ABANDONED"`.
  - [ ] Hệ thống tạo một `Task` mới và một `Proposal` mới (`status = "PROPOSED"`, `parent_id = null`) với thời lượng `45` phút vào sáng Thứ Tư tuần sau.

---

### TC-11: Điều hướng Chéo khi Gõ nhầm Câu hỏi Tra cứu vào Khung Trợ lý AI (`Cross-Tab Redirect`)

* **Prompt tự nhiên:**
  ```text
  Sáng thứ sáu tuần này mình có lịch học hay lịch thi môn gì không?
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào cơ chế phân tách rạch ròi giữa hai không gian chức năng (`Trợ lý AI` dùng để xếp lịch mới so với `Tìm kiếm` dùng để tra cứu lịch trình và hỏi đáp học vụ) tại [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py#L80-L86). Khi NLU phân loại `intent = "query_schedule"`, hệ thống không thực hiện tìm giờ trống hay tạo `Proposal` mà trả về thông điệp điều hướng kèm siêu dữ liệu nút bấm để giao diện Kivy (`ChatBubble`) hiển thị nút chuyển thẳng sang màn hình `search_home`.
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] Trường `nlu.intent` bằng `"query_schedule"`.
  - [ ] Trường `proposal` bằng `null` (không tạo công việc hay đề xuất xếp lịch).
  - [ ] Trường `message` chứa thông báo điều hướng: `"It seems bạn đang muốn tra cứu lịch trình hoặc hỏi đáp học vụ. Khung 'Trợ lý AI' chỉ dùng để xếp lịch công việc mới; bạn hãy bấm nút 'Tìm kiếm' để chuyển sang trang Tra cứu nhé."`
  - [ ] Trường `redirect_target` bằng `"search_home"` và `redirect_button_label` bằng `"Tìm kiếm"`.

---

### TC-12: Chịu lỗi Hạ tầng AI & Chuyển sang Chế độ Chọn lịch Thủ công (`Graceful AI Fallback`)

* **Điều kiện tiên quyết (Giả lập sự cố AI):** Tắt tiến trình `vLLM` (hoặc đặt biến môi trường `VLLM_ENDPOINT=http://127.0.0.1:1/v1/chat/completions` để kết nối bị từ chối ngay lập tức).
* **Prompt tự nhiên:**
  ```text
  Xếp 2 tiếng ôn thi Cấu trúc dữ liệu vào ngày mai
  ```
* **Bản đặc tả kỹ thuật (Technical Abstract):**
  * **Mục tiêu kiểm thử:** Đánh vào cơ chế chịu lỗi 4 điều kiện suy giảm AI (`AGENTS.md` Mục 8) tại [`understand_prompt`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/services/nlu.py#L483-L497) và nhánh `result.fallback_mode` trong [`routers/assistant.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/routers/assistant.py#L74-L101). Khi mô hình AI không phản hồi hoặc sập, API tuyệt đối không được trả lỗi HTTP 500 làm đơ ứng dụng, mà phải: (1) ghi nhật ký lỗi vào bảng `ai_error_logs` và tệp `logs/ai_errors.jsonl`; (2) chuyển sang kết quả của bộ trích xuất quy tắc tất định (`rule_based_understand`); (3) gọi thuật toán `find_user_free_slots` tính sẵn danh sách các khoảng trống trong cửa sổ ngày mai và trả về trong mảng `available_slots` để giao diện mở ngay bảng chọn lịch thủ công (`ManualFallbackModal`).
* **Checklist kết quả kỳ vọng (Tickbox):**
  - [ ] API vẫn trả về mã trạng thái `HTTP 200 OK` (không văng lỗi 500 hay timeout treo giao diện).
  - [ ] Trường `nlu.fallback_mode` bằng `true`, `nlu.source` bằng `"rules"`, và `nlu.fallback_reason` ghi rõ mã lỗi (`INFRA_CRASH` hoặc `TIMEOUT`).
  - [ ] Bộ trích xuất quy tắc dự phòng vẫn lấy đúng `nlu.intent = "schedule_task"`, `nlu.duration_minutes = 120`, và cửa sổ ngày mai.
  - [ ] Trường `message` trả về: `"Trợ lý AI đang bận. Chuyển sang chế độ chọn lịch trực tiếp."`
  - [ ] Mảng `available_slots` trong JSON phản hồi khác rỗng, mỗi phần tử chứa `start_time`, `end_time` (định dạng ISO 8601 có đuôi `+07:00`) và `duration_minutes >= 120`.
  - [ ] Kiểm tra trong MySQL và File Log: Bảng `ai_error_logs` tăng thêm 1 bản ghi với `triggered_fallback = true`, và tệp `logs/ai_errors.jsonl` ghi nhận thêm 1 dòng JSON lỗi tương ứng.
