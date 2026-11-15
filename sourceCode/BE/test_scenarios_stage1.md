# Bộ kịch bản kiểm thử Giai đoạn 1: Sự kiện CRUD, Nhắc nhở & Tùy chọn Xếp lịch

**Nguyên tắc khi Tester gặp lỗi:**

* Nếu bước kiểm tra nền (`TC-EVENT-01` hoặc `TC-PREF-01`) bị lỗi làm app không thao tác được sự kiện hay không lưu được tùy chọn -> **Dừng kiểm thử các bước phụ thuộc phía sau và báo lỗi ngay cho team BE/FE.**
* Nếu một kịch bản nhánh khác bị lỗi tại 1 vài tickbox -> **Ghi nhận đầy đủ bước thao tác, kết quả thực tế kèm log Terminal (`[FE-BE HTTP FAILURE]`) hoặc log từ `/api/v1/debug/logs` và tiếp tục kiểm thử phía sau.**

---

### Nhóm A. Xem Chi tiết, Sửa Giờ, Hạn chót `DEADLINE` và Xóa Sự kiện (`event_modals.py` <-> `routers/events.py`)

#### TC-EVENT-01: Xem chi tiết và Sửa giờ sự kiện mềm (EVENT / TASK) thành công

* **Thao tác của Tester trên App:**
  1. Trên `Lịch chính`, bấm vào khối sự kiện `Họp nhóm đồ án` (`08:00 - 10:00` Thứ Hai) để mở hộp thoại chi tiết (`EventDetailModal`).
  2. Kiểm tra các thông tin hiển thị rồi bấm nút `SỬA GIỜ`.
  3. Trong hộp thoại `Sửa Giờ Sự Kiện`, bấm ô `Giờ bắt đầu mới (bấm để đổi)` chọn `08:30`, bấm ô `Giờ kết thúc mới (bấm để đổi)` chọn `10:30` -> bấm `LƯU`.
  4. Bấm `ĐÓNG` để quay lại `Lịch chính`, quan sát khung giờ mới, sau đó tắt và mở lại ứng dụng.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hộp thoại chi tiết hiển thị đúng tên sự kiện, phân loại `Sự kiện (EVENT)`, địa điểm và khung giờ hiện tại.
  - [ ] Khi mở bộ chọn giờ (`Time30mPickerModal`), các mốc giờ hiển thị dạng lưới 4 cột bước nhảy 15 phút (`:00`, `:15`, `:30`, `:45`).
  - [ ] Sau khi bấm `LƯU`, dòng trạng thái báo `Đã cập nhật thời gian mới vào lịch!` và khối sự kiện trên `Lịch chính` dịch chuyển sang `08:30 - 10:30`.
  - [ ] Khi tắt mở lại ứng dụng, khung giờ `08:30 - 10:30` vẫn được giữ nguyên từ cơ sở dữ liệu.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `EditEventTimeModal` trong `sourceCode/FE/event_modals.py` gọi `PATCH /api/v1/events/{event_id}` trong `routers/events.py`, chuẩn hóa múi giờ qua `_parse_aware_dt` -> `to_db_utc` và đồng bộ lại qua `store.refresh(api)`.

#### TC-EVENT-02: Chặn sửa giờ khi sai thứ tự giờ hoặc trùng lịch hiện có, và kiểm tra nút HỦY BỎ

* **Thao tác của Tester trên App:**
  1. Bấm lại vào sự kiện `Họp nhóm đồ án` (`08:30 - 10:30` Thứ Hai) -> bấm `SỬA GIỜ`.
  2. Chọn `Giờ bắt đầu mới` = `11:00`, `Giờ kết thúc mới` = `10:00` (hoặc `11:00`) -> bấm `LƯU`.
  3. Đổi sang khung giờ đè lên một tiết học đã có trong cùng ngày (ví dụ đè lên giờ môn `Mạng máy tính` nếu đang có trên lịch Thứ Hai, hoặc tạo 1 sự kiện thứ hai từ `14:00 - 15:00` rồi sửa `Họp nhóm đồ án` thành `14:30 - 15:30`) -> bấm `LƯU`.
  4. Bấm `HỦY BỎ`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Ở bước 2, hộp thoại không đóng và hiện chữ đỏ: `Lỗi: Giờ kết thúc phải sau giờ bắt đầu!`.
  - [ ] Ở bước 3, hộp thoại không đóng và hiện chữ đỏ: `Trùng lịch với: '<tên sự kiện>' (<giờ bắt đầu> - <giờ kết thúc>)!`.
  - [ ] Ở bước 4, khi bấm `HỦY BỎ`, hộp thoại sửa giờ đóng lại và khung giờ của sự kiện vẫn giữ nguyên `08:30 - 10:30`, không có thay đổi nào bị lưu nhầm.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `check_event_conflict` tại `sourceCode/FE/event_modals.py` (bỏ qua chính `exclude_event_id` đang sửa nhưng chặn đè lên sự kiện khác) và chốt chặn `event.end_time <= event.start_time` trả về `HTTP 400` tại `PATCH /api/v1/events/{event_id}` trong `routers/events.py`.

#### TC-EVENT-03: Khóa chỉnh sửa giờ đối với Lịch cố định (CLASS / EXAM)

* **Thao tác của Tester trên App:**
  1. Trên `Lịch chính`, bấm vào một tiết học loại `CLASS` đã nạp từ thời khóa biểu (ví dụ `Vi tích phân 2` hoặc `Tư duy tính toán`) để mở hộp thoại chi tiết.
  2. Quan sát và thử bấm vào nút đầu tiên trong danh sách nút chức năng.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Nút sửa giờ chuyển sang màu xám, hiển thị nhãn `SỬA GIỜ (LỊCH CỐ ĐỊNH - KHÓA)` và ở trạng thái vô hiệu hóa (`disabled`).
  - [ ] Bấm vào nút này không mở hộp thoại chọn giờ mới.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra thuộc tính `is_hard = True` của `CLASS`/`EXAM` trên `EventDetailModal` (`sourceCode/FE/event_modals.py`) và chốt chặn `if event.is_hard: raise HTTPException(400, "cannot edit time of hard events (CLASS/EXAM)")` trong `PATCH /api/v1/events/{event_id}` (`routers/events.py`).

#### TC-EVENT-04: Tạo mới và Sửa mốc Hạn chót (DEADLINE zero-duration)

* **Thao tác của Tester trên App:**
  1. Tại `Lịch chính`, bấm nút `+` để mở `Thêm Sự Kiện Mới`.
  2. Nhập `Tên sự kiện` = `Nộp bài tập lớn`, bấm ô `Loại sự kiện` chọn `Hạn chót (DEADLINE)`, chọn `Ngày` là Thứ Tư tuần hiện tại, bấm ô giờ chọn `09:00` (ngay cả khi trong ngày Thứ Tư đang có tiết học từ `07:30 - 09:30`) -> bấm `LƯU`.
  3. Trên đỉnh cột Thứ Tư của `Lịch chính`, bấm vào thẻ hạn chót `Nộp bài tập lớn` -> bấm `SỬA HẠN CHÓT` -> đổi thành `17:00` -> bấm `LƯU`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Khi chọn loại `Hạn chót (DEADLINE)` lúc thêm mới, ô `Giờ kết thúc` tự động đồng bộ bằng `Giờ bắt đầu` và bị làm mờ (`disabled`).
  - [ ] Việc lưu `DEADLINE` lúc `09:00` thành công, không bị chặn bởi lỗi trùng giờ với tiết học `07:30 - 09:30`.
  - [ ] Khi mở chi tiết `DEADLINE`, thời gian chỉ hiển thị 1 mốc duy nhất `Hạn chót: 09:00 (<ngày>)` và nút đầu tiên có tên `SỬA HẠN CHÓT` (không bị khóa).
  - [ ] Sau khi sửa thành `17:00` và bấm `LƯU`, thời gian hiển thị cập nhật thành `Hạn chót: 17:00` và giữ nguyên sau khi tải lại lịch.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra quy tắc `end_time == start_time` (zero-duration point event) trong `POST /api/v1/events`, `PATCH /api/v1/events/{event_id}` (`routers/events.py`), và `is_deadline=True` bỏ qua kiểm tra chiếm dụng giờ trong `check_event_conflict` (`sourceCode/FE/event_modals.py`).

#### TC-EVENT-05: Xóa mềm sự kiện khỏi lịch

* **Thao tác của Tester trên App:**
  1. Bấm vào sự kiện `Nộp bài tập lớn` (hoặc một sự kiện thủ công bất kỳ) trên `Lịch chính` để mở hộp thoại chi tiết.
  2. Bấm nút màu đỏ `XÓA SỰ KIỆN`.
  3. Tắt ứng dụng và mở lại để kiểm tra.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Ngay sau khi bấm `XÓA SỰ KIỆN`, hộp thoại tự đóng và sự kiện biến mất khỏi `Lịch chính` cũng như màn hình `Tìm kiếm`.
  - [ ] Sau khi tắt và mở lại ứng dụng, sự kiện đã xóa không xuất hiện lại.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `DELETE /api/v1/events/{event_id}` trong `routers/events.py` gán `event.deleted_at = datetime.now(UTC_TZ).replace(tzinfo=None)` (trả về `HTTP 204`) và `reminder_scheduler.cancel(event_id)` hủy báo thức cục bộ trong `sourceCode/FE/event_modals.py`.

---

### Nhóm B. Đánh dấu Quan trọng, Báo trước & Chu trình Nhắc nhở (`event_modals.py`, `notifier.py` <-> `routers/events.py`, `routers/reminders.py`)

#### TC-REM-01: Bật đánh dấu Quan trọng (!) và Thay đổi mốc thời gian Báo trước

* **Thao tác của Tester trên App:**
  1. Bấm vào một sự kiện trên `Lịch chính` (ví dụ `Họp nhóm đồ án`) để mở hộp thoại chi tiết.
  2. Quan sát dòng `Sự kiện Quan trọng: TẮT`, sau đó bấm nút `QUAN TRỌNG`.
  3. Bấm vào nút bên cạnh chữ `Báo trước:` (mặc định đang là `00:30`), chọn mốc `00:15` (hoặc `00:45`) trong bảng `Chọn Thời Gian Báo Trước`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Khi bấm `QUAN TRỌNG`, nhãn trạng thái đổi sang màu cam `Sự kiện Quan trọng: ĐÃ BẬT (!)`, nút đổi thành `QUAN TRỌNG (!)` và hiện dòng thông báo đã bật báo thức.
  - [ ] Khi đổi mốc `Báo trước:` sang `00:15`, nút cập nhật nhãn `00:15` và dòng trạng thái báo `Đã bật báo thức trước 00:15!`.
  - [ ] Trên lưới `Lịch chính`, khối sự kiện có hiển thị dấu chấm than đỏ `!` báo hiệu sự kiện quan trọng.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `toggle_important` và `_arm_alarm` trong `sourceCode/FE/event_modals.py` gọi `PUT /api/v1/reminders/{event_id}` (`routers/reminders.py`) và `POST /api/v1/events/{event_id}/reminder-audit` (`routers/events.py`), ghi dòng `"scheduled"` vào `logs/reminder_audit.jsonl` kèm `fire_at`.

#### TC-REM-02: Tắt đánh dấu Quan trọng và Tự động hủy nhắc nhở chưa gửi

* **Thao tác của Tester trên App:**
  1. Mở lại hộp thoại chi tiết của sự kiện đang ở trạng thái `QUAN TRỌNG (!)` từ `TC-REM-01`.
  2. Bấm lại vào nút `QUAN TRỌNG (!)` để tắt.
  3. Đóng hộp thoại, sau đó tắt và mở lại ứng dụng rồi bấm xem lại sự kiện đó.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Nhãn trạng thái chuyển về `Sự kiện Quan trọng: TẮT`, nút chuyển về màu xám `QUAN TRỌNG`, dòng trạng thái hiện `Đã tắt quan trọng.`.
  - [ ] Dấu `!` trên khối sự kiện ngoài `Lịch chính` biến mất và không tự bật lại sau khi khởi động lại ứng dụng.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `PATCH /api/v1/events/{event_id}` với payload `{"is_important": False}` trong `routers/events.py` thực thi câu lệnh xóa các bản ghi `Reminder` chưa gửi (`Reminder.delivered_at.is_(None)`) của sự kiện đó trong DB và gọi `reminder_scheduler.cancel` ở FE.

#### TC-REM-03: Kích hoạt Hộp thoại Thông báo Sự kiện, Báo lại (Snooze) và Xác nhận

* **Thao tác của Tester trên App:**
  1. Mở menu thanh bên (`Sidebar`), tại mục `Thời gian báo lại`, nhập `Giờ` = `0`, `Phút` = `1` (để rút ngắn chu kỳ báo lại xuống 1 phút khi test), sau đó đóng thanh bên.
  2. Tạo mới hoặc sửa giờ một sự kiện sao cho thời điểm báo trước rơi vào đúng thời điểm hiện tại (ví dụ: chỉnh giờ sự kiện có mốc báo trước khớp với giờ hiện tại hoặc trong vòng 1 phút tới, bật `QUAN TRỌNG (!)`).
  3. Khi hộp thoại `THÔNG BÁO SỰ KIỆN` bật lên trên màn hình, kiểm tra nội dung và bấm nút `Báo lại`.
  4. Đợi 1 phút để hộp thoại `THÔNG BÁO SỰ KIỆN` hiện lại lần thứ hai, lần này bấm nút `Xác nhận`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Hộp thoại `THÔNG BÁO SỰ KIỆN` tự động bật lên kèm nội dung `(<Địa điểm>) - <Tên sự kiện>: Lúc <Giờ bắt đầu>` và dòng đếm ngược `Tự động báo lại sau: 60s`.
  - [ ] Khi bấm `Báo lại` (hoặc để hết 60 giây không bấm), hộp thoại đóng lại và tự động bật lại sau đúng số phút đã cấu hình ở mục `Thời gian báo lại` (1 phút).
  - [ ] Khi bấm `Xác nhận` ở lần hiện lại, hộp thoại đóng hẳn và không báo lặp lại nữa.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm / FE):** Kiểm tra `DeviceNotificationModal`, `set_snooze_interval`, `schedule_snooze` trong `sourceCode/FE/notifier.py` và các endpoint `POST /api/v1/reminders/{event_id}/scheduled`, `POST /api/v1/reminders/{event_id}/delivered`, `GET /api/v1/reminders/audit` trong `routers/reminders.py`.

---

### Nhóm C. Tùy chọn Xếp lịch của Người dùng trên Sidebar (`side_bar_menu.py` <-> `routers/events.py` & `services/search_engine.py`)

#### TC-PREF-01: Thay đổi và Lưu Tùy chọn Xếp lịch trên Thanh bên (Sidebar)

* **Thao tác của Tester trên App:**
  1. Tại màn hình `Lịch chính`, bấm nút 3 gạch ở góc trên bên trái để mở `Menu` thanh bên (`SideBarMenu`).
  2. Tại mục `Khung giờ ngủ:`, bấm nút `Ngủ: 23:30` -> chọn `22:30` -> bấm `Lưu`; bấm nút `Dậy: 06:30` -> chọn `07:00` -> bấm `Lưu`.
  3. Tại ô `Thời gian nghỉ giữa ca (phút):`, xóa `30` và nhập `45`.
  4. Tại ô `Thời lượng liên tục tối đa (phút):`, xóa `180` và nhập `120`.
  5. Bấm nút `LƯU TÙY CHỌN`, đóng thanh bên rồi mở lại thanh bên.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Khi bấm `LƯU TÙY CHỌN`, phía trên nút lưu hiện dòng chữ màu xanh lá: `Đã lưu tùy chọn thành công!`.
  - [ ] Dưới cửa sổ Terminal không xuất hiện khung lỗi `[FE-BE HTTP FAILURE]`.
  - [ ] Khi đóng và mở lại thanh bên, các thông số vẫn hiển thị đúng `Ngủ: 22:30`, `Dậy: 07:00`, nghỉ giữa ca `45`, thời lượng tối đa `120`.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `save_preferences` trong `sourceCode/FE/side_bar_menu.py` gọi `POST /api/v1/user/preferences` trong `routers/events.py` (`user_router`), tách chuỗi `sleep_schedule` qua `_parse_time_str`, giới hạn `min_break_minutes` trong `[0, 360]` và `max_block_minutes` trong `[15, 720]`, lưu vào bảng `user_preferences`.

#### TC-PREF-02: Kiểm chứng Khung giờ ngủ và Thời gian nghỉ giữa ca mới lưu áp dụng vào Quét Giờ Trống

* **Thao tác của Tester trên App:**
  1. Giữ nguyên cấu hình vừa lưu ở `TC-PREF-01` (`Ngủ: 22:30`, `Dậy: 07:00`, `Thời gian nghỉ giữa ca`: `45` phút).
  2. Mở tính năng tìm khung giờ trống (hoặc kích hoạt bảng chọn lịch thủ công `ManualFallbackModal` cho một công việc `60 phút` vào ngày có tiết học buổi sáng kết thúc lúc `11:10`).
  3. Sau khi kiểm tra xong, mở lại thanh bên đổi trả về mặc định (`Ngủ: 23:30`, `Dậy: 06:30`, nghỉ `30`, tối đa `180`) rồi bấm `LƯU TÙY CHỌN`.
* **Checklist kết quả kỳ vọng (Tickbox dành cho Tester):**
  - [ ] Không có khung giờ trống nào bắt đầu trước `07:00` sáng hoặc kết thúc sau `22:30` tối (đã áp dụng khung giờ ngủ mới `22:30 - 07:00` thay vì `23:30 - 06:30`).
  - [ ] Ngay sau tiết học kết thúc lúc `11:10`, khung giờ trống kế tiếp phải cách ra ít nhất `45 phút` (tức bắt đầu từ `12:00` sau khi cộng 45 phút thành `11:55` và làm tròn lên lưới 15 phút), thay vì `11:30` như khi để đệm 15 phút.
* **Đặc tả kỹ thuật (BE & FE Reference - PIC: Lâm):** Kiểm tra `find_user_free_slots` trong `services/search_engine.py` đọc bản ghi `UserPreference` từ DB (`sleep_start`, `sleep_end`, `min_break_minutes`) và truyền vào `find_free_slots` khi xử lý `POST /api/v1/search/free-slots` (`routers/search.py`).
