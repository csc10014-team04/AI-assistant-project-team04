# Kịch bản kiểm thử tích hợp & Hướng dẫn chẩn đoán lỗi

## Phần 1. Phạm vi kiểm thử (theo tiến độ hiện tại của BE)

1. **Trong file này, những gì sẽ được kiểm thử là:**
   * **Cụm Xác thực & Phiên làm việc (`services/security.py`, `routers/auth.py` - PIC: Khôi):** Đăng ký tài khoản mới, chặn trùng tên đăng nhập, đăng nhập đúng/sai mật khẩu, duy trì phiên đăng nhập.
   * **Cụm Thêm sự kiện thủ công & Kiểm tra Trùng lịch (`services/validator.py`, `routers/ingestion.py`, `routers/proposals.py` - PIC: Khôi & Lâm):** Phát hiện xung đột lịch cứng (`is_hard = True`), chặn đè giờ.
   * **Cụm Nhập Thời khóa biểu & Đồng bộ Thông minh `Smart Diff` (`services/validator.py`, `routers/ingestion.py` - PIC: Khôi & Lâm; `services/parser.py` - PIC: Lâm):** Nhập file `.txt` / `.csv` theo **định dạng chuẩn 9 cột** (`course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`), cô lập dòng lỗi sang danh sách vàng, gom xung đột chuỗi tuần, lặp cách tuần (`2 tuần/lần`), nạp cập nhật 2 môn không làm mất các môn còn lại, và nạp ghép lịch học với lịch làm thêm part-time.
   * **Cụm Quét Khung giờ Trống & Chọn lịch Thủ công (`services/search_engine.py`, `find_free_slots`/`find_user_free_slots`, `routers/search.py`, `sourceCode/FE/fallback.py` - PIC: Lâm):** Tính toán khung giờ trống né lịch bận và né giờ ngủ mặc định (`23:30 - 06:30`), căn lưới 15 phút.

2. **Những phần chưa được kiểm thử trong lần này:**
   * **Ảnh chụp / PDF Thời khóa biểu cổng đào tạo (bảng 14 cột có ô gộp nhiều ca):** Lâm đã phát hiện hạn chế về bất đồng cấu trúc cột giữa cổng đào tạo và parser 9 cột hiện tại; ở Đợt 1 Tester chỉ dùng **dữ liệu mẫu `.txt` / `.csv` 9 cột** được cung cấp sẵn trong tài liệu này.
   * **Tính năng Xếp lịch cùng AI (Scheduling with AI):** Sử dụng bộ 12 kịch bản riêng đã soạn tại [`test_prompts_scheduling_with_ai.md`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/BE/test_prompts_scheduling_with_ai.md) khi chuyển sang kiểm thử AI.
   * **Tính năng Tìm kiếm (2 loại: Schedule search & Academic RAG), OAuth2 Google/GitHub, Reminders Sync:** Kiểm thử ở Đợt 2 sau khi BE và FE ghép nối xong các màn hình tương ứng.

---

## Phần 2. Bộ 14 kịch bản kiểm thử

**Nguyên tắc khi Tester gặp lỗi:**
* Nếu bước kiểm tra ở nhóm **Xác thực (`TC-AUTH`)** hoặc **Nạp dữ liệu nền (`TC-IMPORT-01`)** bị lỗi làm app không có dữ liệu hay không vào được lịch -> **Dừng kiểm thử các bước phía sau và báo lỗi ngay cho team BE/FE.**
* Nếu một kịch bản nhánh (`TC-IMPORT-02..05`, `TC-FREESLOT`) bị lỗi tại 1 vài tickbox -> **Ghi nhận đầy đủ theo Mẫu ở Phần 3 và tiếp tục kiểm thử phía sau.**

---

### Nhóm A. Xác thực & Phiên làm việc (`auth_screen.py` <-> `routers/auth.py`)

#### TC-AUTH-01: Đăng ký tài khoản mới thành công
* **Thao tác của Tester trên App:**
  1. Mở app, tại màn hình Đăng nhập bấm nút `CHUYỂN QUA ĐĂNG KÝ`.
  2. Nhập `Tên đăng nhập`: `sv_test_01` (nếu từng tạo rồi thì đổi thành `sv_test_02`), `Họ tên hiển thị`: `Nguyen Van Test`, `Mật khẩu`: `TestPass123`.
  3. Bấm `TẠO TÀI KHOẢN`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Ứng dụng không bị đứng, tự động chuyển về tab `Đăng nhập`.
  - [ ] Không có thông báo lỗi màu đỏ hiện trên màn hình.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Kiểm tra endpoint `POST /api/v1/auth/register` trong `routers/auth.py` ghi đồng bộ 3 bảng `users`, `auth_identities` (hash `bcrypt`), `user_preferences` (mặc định ngủ `23:30 - 06:30`) vào MySQL và trả về `HTTP 201`.

#### TC-AUTH-02: Chặn đăng ký trùng tên đăng nhập và sai độ dài hợp lệ
* **Thao tác của Tester trên App:**
  1. Quay lại tab `Đăng ký`, nhập lại đúng tên `sv_test_01` vừa tạo ở `TC-AUTH-01`, điền họ tên và mật khẩu hợp lệ rồi bấm `TẠO TÀI KHOẢN`.
  2. Thử nhập một tên đăng nhập mới bất kỳ nhưng cố tình nhập `Mật khẩu` chỉ có 3 ký tự (`123`) rồi bấm `TẠO TÀI KHOẢN`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Ở bước 1, màn hình hiển thị thông báo rõ ràng: `Tên đăng nhập đã tồn tại` (không cho tạo đè tài khoản cũ).
  - [ ] Ở bước 2, màn hình hiển thị thông báo lỗi (không cho đăng ký mật khẩu dưới 6 ký tự) và không bị văng app.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Xác nhận `HTTP 409 Conflict` cho trường hợp trùng `provider_user_id` và `HTTP 422 Unprocessable Entity` từ `RegisterRequest` (`min_length=6` cho `password`) trong `routers/auth.py`.

#### TC-AUTH-03: Đăng nhập sai mật khẩu và đăng nhập thành công
* **Thao tác của Tester trên App:**
  1. Tại tab `Đăng nhập`, nhập `Tên đăng nhập`: `sv_test_01`, `Mật khẩu`: `SaiMatKhau999` -> bấm `ĐĂNG NHẬP`.
  2. Xóa mật khẩu sai, nhập lại đúng `TestPass123` -> bấm `ĐĂNG NHẬP`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Khi nhập sai mật khẩu: Màn hình hiện dòng lỗi `Sai tên đăng nhập hoặc mật khẩu!` và vẫn đứng ở màn hình Đăng nhập.
  - [ ] Khi nhập đúng mật khẩu: App chuyển sang màn hình `Lịch chính`.
  - [ ] Lưới lịch của tài khoản mới tạo phải **trống** (hoặc chỉ có lịch thật vừa nạp, không còn các môn học mẫu kiểu giả lập ban đầu).
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Kiểm tra `verify_password` trong `services/security.py`, `POST /api/v1/auth/login` trả `401` khi sai mật khẩu và `200` kèm JWT token khi đúng; FE chuyển `event_store.store.is_demo = False`.

#### TC-AUTH-04: Lưu phiên làm việc khi tắt app và Đăng xuất về đúng màn hình
* **Thao tác của Tester trên App:**
  1. Đang ở `Lịch chính` sau `TC-AUTH-03`, bấm dấu `X` tắt hẳn cửa sổ ứng dụng rồi mở lại app.
  2. Mở menu cạnh trái (nút 3 gạch ở góc trên trái), bấm vào ô thông tin tài khoản dưới cùng -> bấm `Đăng xuất`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Khi mở lại app ở bước 1: App tự động khôi phục phiên và vào thẳng màn hình `Lịch chính`, không bắt đăng nhập lại.
  - [ ] Khi bấm `Đăng xuất` ở bước 2: App quay lại màn hình Đăng nhập mượt mà, không bị đứng hay lỗi.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi / FE):** Kiểm tra lưu/xóa `auth_session.json` trong `api_client.py` và tên screen điều hướng `"auth_screen"` trong `side_bar_menu.py`.

---

### Nhóm B. Thêm Sự kiện Thủ công & Chốt chặn Xung đột Lịch (`event_modals.py` <-> `validator.py` & `proposals.py`)

*(Thực hiện trên tài khoản `sv_test_01` đang trống lịch)*

#### TC-MANUAL-01: Thêm sự kiện thủ công mới thành công
* **Thao tác của Tester trên App:**
  1. Tại màn hình `Lịch chính`, bấm nút dấu `+` (hoặc nút `Thêm sự kiện`).
  2. Nhập: Tên sự kiện = `Họp nhóm đồ án`, Loại = `EVENT`, Ngày = ngày Thứ Hai tuần hiện tại (định dạng `YYYY-MM-DD`), Giờ bắt đầu = `08:00`, Giờ kết thúc = `10:00`.
  3. Bấm `LƯU`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hộp thoại thêm sự kiện tự đóng sau khi lưu.
  - [ ] Trên lưới lịch cột Thứ Hai xuất hiện khối `Họp nhóm đồ án` đúng khoảng `08:00 - 10:00`.
  - [ ] Bấm nút `Tìm kiếm` hoặc tắt mở lại app -> sự kiện `Họp nhóm đồ án` vẫn tồn tại (đã lưu thật xuống DB).
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Khôi & Lâm):** Kiểm tra `POST /api/v1/ingestion/check-conflicts` không phát hiện trùng, `POST /api/v1/proposals/manual` tạo bản ghi `Event` UTC (+07:00 khi trả về) và `store.refresh(api)` cập nhật UI.

#### TC-MANUAL-02: Chặn thêm sự kiện đè giờ lên lịch đã có
* **Thao tác của Tester trên App:**
  1. Mở lại hộp thoại `Thêm sự kiện mới`.
  2. Nhập một sự kiện mới vào **cùng ngày Thứ Hai** vừa tạo ở `TC-MANUAL-01`, khung giờ gối đầu `09:00` đến `11:00`, loại `CLASS`, tên `Học bù`.
  3. Bấm `LƯU`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hệ thống phát hiện trùng giờ (khoảng `09:00 - 10:00` bị đè lên `Họp nhóm đồ án`).
  - [ ] Trên giao diện báo lỗi trùng lịch và **không** tạo thêm khối `Học bù` đè lên lịch cũ.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Kiểm tra `check_hard_conflict` / `detect_import_conflicts` trong `services/validator.py`.

#### TC-MANUAL-03: Kiểm tra validation khi nhập giờ kết thúc nhỏ hơn hoặc bằng giờ bắt đầu
* **Thao tác của Tester trên App:**
  1. Mở `Thêm sự kiện mới`, nhập Giờ bắt đầu = `14:00`, Giờ kết thúc = `13:00` (hoặc `14:00`), bấm `LƯU`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] App từ chối lưu và thông báo lỗi hợp lệ trên form, không bị văng app.
* **Đặc tả kỹ thuật (BE Reference - PIC: Lâm / Khôi):** Kiểm tra validation khoảng thời gian dương (`duration >= 15`) ở cả form FE và `ManualEventRequest` trong `routers/proposals.py`.

---

### Nhóm C. Nhập Thời khóa biểu 9 Cột, Cô lập Lỗi & Đồng bộ Thông minh (`ingestion.py`, `parser.py`, `validator.py`)

**Chuẩn bị 4 tệp `.txt` mẫu trên máy Tester trước khi chạy Nhóm C** (Tester tạo bằng Notepad và lưu với định dạng UTF-8; thay khoảng ngày `2026-11-16` -> `2026-12-27` bằng 6 tuần tính từ tuần hiện tại đang test nếu cần dễ quan sát trên lịch tuần):

* **File 1 (`tkb_dot1.txt` - 5 dòng đúng + 1 dòng sai giờ `25:00` + 1 dòng trùng Thứ Hai `08:00` với `TC-MANUAL-01`):**
  ```csv
  course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
  CSC10008,Mạng máy tính,T2,07:30,09:30,C.45,2026-11-16,2026-12-21,CLASS
  MTH00006,Vi tích phân 2,T3,07:30,11:10,C.33,2026-11-17,2026-12-22,CLASS
  BAA00021,Thể dục 1,T4,07:30,09:30,Sân A,2026-11-18,2026-12-23,CLASS
  CSC10014,Tư duy tính toán,T5,07:30,11:10,I.11E,2026-11-19,2026-12-24,CLASS
  BAA00005,Kinh tế đại cương,T6,25:00,11:10,C.24,2026-11-20,2026-12-25,CLASS
  ```
* **File 2 (`tkb_update_2mon.txt` - Chỉ sửa khung giờ của `Vi tích phân 2` và `Thể dục 1`, đồng thời có 1 dòng giữ nguyên):**
  ```csv
  course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
  MTH00006,Vi tích phân 2,T3,13:30,15:30,C.33,2026-11-17,2026-12-22,CLASS
  BAA00021,Thể dục 1,T4,15:00,17:00,Sân B,2026-11-18,2026-12-23,CLASS
  ```
* **File 3 (`lich_lam_them.txt` - Lịch làm thêm part-time không có `course_code`):**
  ```csv
  course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
  ,Làm thêm quán cà phê,T7,14:00,17:30,Quận 5,2026-11-21,2026-12-26,CLASS
  ```
* **File 4 (`lich_cach_tuan.txt` - Kiểm tra chu kỳ `2 tuần/lần` và `DEADLINE`):**
  ```csv
  course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
  PSY001,Lớp Tâm lý học (2 tuần/lần),CN,09:00,11:00,Online,2026-11-22,2026-12-27,CLASS
  ,Nộp báo cáo giữa kỳ,T6,23:59,23:59,,2026-11-20,2026-11-20,DEADLINE
  ```

#### TC-IMPORT-01: Đọc file hỗn hợp (dòng đúng + dòng lỗi giờ) và Cô lập lỗi (Bước 1 -> Bước 2)
* **Thao tác của Tester trên App:**
  1. Tại màn hình `Lịch chính`, mở chức năng `Import lịch` (Bước 1/3).
  2. Chọn tệp `tkb_dot1.txt` -> bấm `PHÂN TÍCH`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] App chuyển sang màn hình `Xem trước & Xử lý (Bước 2/3)`, không bị đứng hay sập khi trong file có dòng `25:00`.
  - [ ] Có **4 thẻ màu xanh** (`Mạng máy tính`, `Vi tích phân 2`, `Thể dục 1`, `Tư duy tính toán`) hiển thị đúng tên môn và khung giờ.
  - [ ] Có **1 thẻ màu vàng** cho dòng 6 (`Kinh tế đại cương`), ghi rõ lỗi sai định dạng giờ `25:00` và vẫn hiển thị nguyên dòng gốc.
* **Đặc tả kỹ thuật (BE Reference - PIC: Lâm):** Kiểm tra `parse_timetable_content` trong `services/parser.py` và `POST /api/v1/ingestion/parse-preview` trong `routers/ingestion.py`: tách `valid_rows` (4) và cô lập lỗi vào `invalid_rows` (1) với mã `INVALID_START_TIME`.

#### TC-IMPORT-02: Gom nhóm Xung đột chuỗi tuần (Bước 3) và Lưu lịch hàng tuần (Bước 4)
* **Thao tác của Tester trên App:**
  1. Tiếp nối từ `TC-IMPORT-01` trên màn hình Bước 2/3, sửa lại dòng vàng `Kinh tế đại cương` thành giờ đúng `07:30` (hoặc chọn Bỏ qua dòng vàng đó) -> bấm `TIẾP TỤC KIỂM TRA TRÙNG LỊCH`.
  2. Ở màn hình Bước 3/3 (nếu có thẻ đỏ), chọn phương án giải quyết xung đột (ví dụ: Giữ sự kiện mới `Mạng máy tính`, hoặc Giữ cả hai) rồi bấm `LƯU CHÍNH THỨC VÀO LỊCH`.
  3. Trên màn hình `Lịch chính`, bấm mũi tên chuyển qua tuần kế tiếp để xem lịch các tuần sau.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Dòng `Mạng máy tính` (Thứ Hai `07:30 - 09:30`, 6 tuần) bị phát hiện trùng với `Họp nhóm đồ án` (`08:00 - 10:00` đã tạo ở `TC-MANUAL-01`), và được gom thành **1 Thẻ Xung Đột màu đỏ duy nhất** (không bị nhân lên 6 thẻ).
  - [ ] Sau khi bấm Lưu chính thức, cả tuần hiện tại lẫn các tuần kế tiếp (từ `2026-11-16` đến `2026-12-25`) đều tự động hiện đầy đủ các buổi học của 4 môn trên lưới lịch.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Kiểm tra `detect_import_conflicts` và `commit_resolved_import` trong `services/validator.py`, `POST /api/v1/ingestion/check-conflicts` và `POST /api/v1/ingestion/commit` trong `routers/ingestion.py`.

#### TC-IMPORT-03: Nạp file cập nhật chỉ 2 môn (`Smart Diff` không xóa mất các môn khác)
* **Thao tác của Tester trên App:**
  1. Mở lại `Import lịch`, chọn tệp `tkb_update_2mon.txt` (chỉ có 2 môn `Vi tích phân 2` và `Thể dục 1` với giờ mới vào buổi chiều), để tùy chọn `replace_previous_imports` ở trạng thái mặc định (tắt/False) -> phân tích và lưu vào lịch.
  2. Quan sát lại tuần học trên `Lịch chính`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] 2 môn `Vi tích phân 2` và `Thể dục 1` đã chuyển sang khung giờ chiều mới (`13:30 - 15:30` Thứ Ba và `15:00 - 17:00` Thứ Tư). Khung giờ sáng cũ của 2 môn này không còn nữa.
  - [ ] Các môn **không có trong file mới** (`Mạng máy tính`, `Tư duy tính toán`) và sự kiện thủ công (`Họp nhóm đồ án`) **vẫn còn nguyên vẹn**, tuyệt đối không bị mất.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi):** Kiểm tra cơ chế **Smart Diff & Subject-Scoped Upsert** (`_subject_keys_for_row`, `_build_incoming_subject_windows`, `_event_occurrence_sig`) trong `services/validator.py` (`commit_resolved_import`).

#### TC-IMPORT-04: Nạp ghép Lịch làm thêm part-time sau khi đã có Lịch học chính khóa
* **Thao tác của Tester trên App:**
  1. Mở `Import lịch`, chọn tệp `lich_lam_them.txt` (không có mã môn học `course_code`, là ca làm thêm Thứ Bảy `14:00 - 17:30`) -> phân tích và lưu vào lịch.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hệ thống chấp nhận dòng không có `course_code` (không báo lỗi thiếu mã môn).
  - [ ] Toàn bộ lịch học của 4 môn đã nạp ở các bước trước vẫn còn nguyên.
  - [ ] Trên cột Thứ Bảy các tuần xuất hiện thêm ca `Làm thêm quán cà phê` (`14:00 - 17:30`).
* **Đặc tả kỹ thuật (BE Reference - PIC: Lâm & Khôi):** Kiểm tra trường `course_code` tùy chọn (`""`) trong `parser.py` và khả năng lưu nối tiếp nhiều đợt `IMPORTED` cùng tồn tại trong `validator.py`.

#### TC-IMPORT-05: Lịch lặp cách tuần (`2 tuần/lần`) và Mốc hạn chót `DEADLINE`
* **Thao tác của Tester trên App:**
  1. Mở `Import lịch`, chọn tệp `lich_cach_tuan.txt` -> phân tích và lưu vào lịch.
  2. Lần lượt chuyển lịch trên `Lịch chính` qua Chủ Nhật tuần 1 (`2026-11-22`), tuần 2 (`2026-11-29`), và tuần 3 (`2026-12-06`). Kiểm tra thêm ngày Thứ Sáu `2026-11-20`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] `Lớp Tâm lý học (2 tuần/lần)` xuất hiện vào Chủ Nhật tuần 1 (`22/11`), **trống** vào Chủ Nhật tuần 2 (`29/11`), và xuất hiện lại đúng vào Chủ Nhật tuần 3 (`06/12`).
  - [ ] Mốc `Nộp báo cáo giữa kỳ` (loại `DEADLINE`) không bị vẽ thành ô dẹp dính trên lưới giờ, mà hiển thị ở vùng tiêu đề/dải hạn chót trên đỉnh cột Thứ Sáu `20/11`.
* **Đặc tả kỹ thuật (BE Reference - PIC: Khôi & FE):** Kiểm tra `_parse_recurrence_spec` + `_iter_row_dates` (`timedelta(days=7 * k)`) trong `services/validator.py`, và nhánh `e["kind"] == "DEADLINE"` tại `calendar_screen.py` (`deadline_banner_box`).

---

### Nhóm D. Thuật toán Quét Giờ trống & Chọn Lịch Thủ công (`search_engine.py` Section 3 & `fallback.py`)

*(Để test trực tiếp đường dẫn tìm giờ trống khi AI bận hoặc tắt tạm dịch vụ AI/đặt timeout nhỏ, hoặc mở bảng chọn lịch thủ công trên màn hình Trợ lý AI)*

#### TC-FREESLOT-01: Quét khung giờ trống né Lịch bận, né Giờ ngủ và có Nghỉ đệm 15 phút
* **Thao tác của Tester trên App:**
  1. Đảm bảo tài khoản đang test đã có các tiết học buổi sáng đã nạp ở Nhóm C (ví dụ Thứ Ba có lớp `13:30 - 15:30` hoặc sáng Thứ Năm có lớp `07:30 - 11:10`).
  2. Kích hoạt chế độ Chọn lịch thủ công (gửi một yêu cầu xếp lịch thời lượng `60 phút` vào ngày có tiết học đó khi server AI đang bận/tắt để mở `ManualFallbackModal`, hoặc gọi qua màn hình chọn khung giờ trống).
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Danh sách các khung giờ trống gợi ý (`available_slots`) tuyệt đối **không** nằm trong giờ đang có lớp học (`07:30 - 11:10`).
  - [ ] Các khung giờ trống đều **cách mép đầu/mép cuối lớp học ít nhất 15 phút** (ví dụ lớp kết thúc `11:10` thì giờ trống sớm nhất bắt đầu từ `11:30`, làm tròn lên lưới 15 phút).
  - [ ] Không có bất kỳ khung giờ trống nào rơi vào khung giờ ngủ mặc định (`23:30 - 06:30`).
  - [ ] Bấm chọn 1 khung giờ trống trong danh sách -> sự kiện mới được thêm vào `Lịch chính`.
* **Đặc tả kỹ thuật (BE Reference - PIC: Lâm):** Kiểm tra `find_user_free_slots` và `find_free_slots` (thuật toán `sort-and-sweep` $O(N \log N)$, căn lưới 15 phút, đệm 15 phút, `_build_sleep_busy_intervals`) trong `services/search_engine.py` Section 3 và `POST /api/v1/search/free-slots` trong `routers/search.py` Section 2.

#### TC-FREESLOT-02: Yêu cầu thời lượng lớn hơn mọi khoảng trống hiện có trong ngày
* **Thao tác của Tester trên App:**
  1. Trên một ngày đã kín gần hết lịch (mỗi khoảng trống giữa các ca học chỉ dài 60 - 90 phút), yêu cầu tìm khung giờ trống cho một việc kéo dài `300 phút` (5 tiếng) chỉ trong đúng ngày hôm đó.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hệ thống không trả về các khoảng trống ngắn hơn 300 phút.
  - [ ] Hiển thị thông báo không có khung giờ trống phù hợp (thay vì đứng app hay trả lỗi hệ thống 500).
* **Đặc tả kỹ thuật (BE Reference - PIC: Lâm):** Kiểm tra điều kiện lọc `slot.duration_minutes() >= duration_minutes` trong `services/search_engine.py` và xử lý danh sách rỗng an toàn trong `ManualFallbackModal` (`sourceCode/FE/fallback.py`).

---

## Phần 3. Hướng dẫn tester xem chi tiết lỗi & ghi nhận

### 3.1. Tại sao cần xem Log thay vì chỉ chụp câu thông báo trên màn hình App?
Thông báo hiện trên màn hình App (như *"Lỗi hệ thống (422)"*, *"Không thể kết nối"*, hay *"Lỗi thêm sự kiện"*) được viết ngắn gọn để hướng dẫn sinh viên sử dụng, **không chứa thông tin kỹ thuật để lập trình viên biết dòng code nào hay đội nào (FE hay BE) đang bị lệch**.

Team BE & FE đã tích hợp sẵn **2 công cụ tự xem log lỗi**. Khi chạy app gặp bất kỳ lỗi nào, Tester có thể tự xem ngay nguyên nhân chi tiết mà **không cần đợi người giữ máy Host AI/DB trích xuất log giúp**:

---

### 3.2. Hai cách tự xem nguyên nhân lỗi

#### Cách 1: Nhìn ngay vào cửa sổ dòng lệnh (Terminal/Console) nơi đang chạy App Kivy
Mỗi khi ứng dụng FE gửi yêu cầu sang BE bị lỗi (`4xx`, `5xx`) hoặc rớt mạng, tệp [`api_client.py`](file:///C:/Users/heyto/projects/AI-assistant-project-team04/sourceCode/FE/api_client.py) tự động in ra một khung thông báo có dạng:

```text
======================================================================
[FE-BE HTTP FAILURE] POST http://26.211.52.63:8080/api/v1/ingestion/check-conflicts -> HTTP 422
- Request ID   : 7f3a12c9
- Nguon loi    : PYDANTIC_VALIDATION_ERROR: Du lieu FE gui len thieu truong hoac sai kieu du lieu so voi schema BE
- Payload gui  : {"valid_rows": [...]}
- Phan hoi BE  : {"detail": [{"loc": ["body", "incoming_rows"], "msg": "Field required"}]}
======================================================================
```

Tester chỉ cần **bôi đen và copy nguyên khung `[FE-BE HTTP FAILURE]` hoặc `[FE-BE NETWORK ERROR]` này**. Chỉ nhìn vào dòng `Nguon loi` và `Phan hoi BE`, team BE và FE biết ngay vấn đề thuộc về ai:
* `MANG / KET NOI`: Server BE chưa bật, sai địa chỉ IP, hoặc đứt mạng giữa máy Tester và máy Host.
* `FASTAPI_ROUTER_URL_NOT_FOUND` (404 kèm detail `"Not Found"`): FE gọi sai đường dẫn URL (giao FE sửa).
* `PYDANTIC_VALIDATION_ERROR` (422): Dữ liệu FE gửi lên thiếu tên trường hoặc sai định dạng so với BE yêu cầu (FE hoặc BE đối chiếu schema).
* `BE_BUSINESS_RULE_REJECTION` (400, 404 detail chữ thường, 409,...): BE nhận được đúng dữ liệu nhưng từ chối theo logic nghiệp vụ (ví dụ: trùng tên đăng nhập, trùng lịch, không tìm thấy bản ghi).
* `BE_UNHANDLED_EXCEPTION` (500): Lỗi sập bên trong code BE hoặc kết nối MySQL (giao thẳng cho Khôi hoặc Lâm dựa theo vị trí file trong `debug_origin`).

#### Cách 2: Mở Trình duyệt Web xem trực tiếp Lịch sử Lỗi của Server BE (`GET /api/v1/debug/logs`)
Bất cứ lúc nào (ngay cả khi test trên điện thoại không nhìn thấy cửa sổ Terminal, hoặc muốn xem thêm lỗi của tầng AI trong `ai_errors.jsonl`), Tester mở trình duyệt web (Chrome/Edge) ngay trên máy của mình và truy cập địa chỉ:

```text
http://<Dia_chi_IP_may_Host>:8080/api/v1/debug/logs
```
*(Ví dụ: `http://127.0.0.1:8080/api/v1/debug/logs` nếu chạy cùng máy, hoặc `http://26.211.52.63:8080/api/v1/debug/logs` theo địa chỉ server hiện tại của nhóm).*

Trang web sẽ trả về JSON liệt kê 30 lỗi mới nhất theo thứ tự mới nhất ở trên cùng:
* `recent_http_errors`: Danh sách các lần gọi API bị lỗi (`request_id`, `method`, `path`, `status_code`, `error_source`, `origin`, `detail`, `traceback`).
* `recent_ai_errors`: Danh sách các lỗi bên trong mô hình AI (timeout, sai JSON, ảo giác ngày giờ, prompt gốc đã che thông tin cá nhân, và kết quả thô `raw_output` của AI).

Tester có thể đối chiếu mã **`Request ID`** in ở Cách 1 với trường **`request_id`** ở Cách 2 để lấy đầy đủ `origin` (tên file và số dòng gây lỗi của BE) và `traceback`.

---

### 3.3. Mẫu thẻ báo lỗi

Mỗi khi gặp một tickbox bị **Fail** trong Phần 2 (hoặc trong file test AI), Tester chỉ cần gửi tin nhắn theo đúng 4 mục dưới đây:

```text
1. Mã kịch bản & Tickbox lỗi: (Ví dụ: TC-IMPORT-02 - Tickbox số 1 Fail)
2. Thao tác vừa làm & Kết quả thấy trên màn hình: (Ví dụ: Bấm nút Lưu lịch ở Bước 2 thì app đứng ở Bước 2, hiện chữ "Lỗi")
3. Khung Log trên Terminal FE (copy nguyên đoạn [FE-BE HTTP FAILURE] nếu có):
   - Request ID: ...
   - Nguon loi: ...
   - Phan hoi BE: ...
4. Đường dẫn / File dữ liệu đã dùng (nếu có): (Ví dụ: file tkb_dot1.txt)
```
