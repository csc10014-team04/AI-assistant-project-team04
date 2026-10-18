### Giải thích thuật ngữ

- **Parser (P1-4, P2-2):** đọc file thời khóa biểu thô, xuất ra CSV.
- **Engine (P1-5):** từ các sự kiện đã có và thời lượng cần xếp, tìm ra các khung giờ trống.
- **Validator (P1-6):** kiểm tra lần cuối một khung giờ có trùng ràng buộc cứng hay không.
- **NLU (P1-7):** trích xuất ý định và thông tin (tên hoạt động, thời lượng) từ câu prompt.
- **Bản ghi:** một dòng trong một bảng. **Khóa ngoại:** cột lưu ID của một bản ghi ở bảng khác, dùng để liên kết. Ví dụ: `events.owner_id` lưu ID người sở hữu sự kiện.


## Nhóm A. Quyết định sản phẩm

### A1. Phạm vi và chi tiết về manual exit
Xuất hiện khi AI lỗi, và chỉ dùng để chọn một khung giờ cho yêu cầu vừa gửi, cộng thêm hai thao tác: **xóa** và **sửa giờ** một sự kiện. Lý do: hai thao tác này đơn giản và cần chính xác tuyệt đối. Bắt người dùng prompt "xóa buổi gym thứ Tư" vừa chậm hơn, vừa có xác suất AI hiểu sai.

Hệ thống ghi nhận AI lỗi trong 4 trường hợp: Lỗi quá thời gian phản hồi (Inference Timeout), Lỗi hạ tầng và tiến trình AI bị sập (Infrastructure / Process Crash), Lỗi vỡ cấu trúc dữ liệu đầu ra (Schema Validation Failure), Lỗi ngữ nghĩa không thể xác định (Unresolvable Intent / Semantic Failure).

Khi gặp một trong 4 trường hợp trên, hệ thống không được phép hiện thông báo lỗi hệ thống chung chung (Internal Server Error 500) hay làm sập ứng dụng, mà lập tức kích hoạt luồng **Manual Exit**.

Minh họa một kịch bản cho Manual Exit:

Sinh viên Nguyễn Văn A mở khung chat và gõ câu lệnh:
> *"Xếp cho mình 3 tiếng làm đồ án Cấu trúc dữ liệu vào tuần này, không làm buổi tối nhé."*

---

#### Diễn biến khi xảy ra lỗi:

```
[Người dùng gửi prompt]
         │
         ▼
[Backend nhận request] ──> [Gửi sang Ollama] ──(Sau 3.0s: TIMEOUT!)
                                 │
                                 ▼
                     [Kích hoạt FALLBACK ENGINE]
                                 │
         ┌───────────────────────┴───────────────────────┐
         ▼                                               ▼
[Gọi Thuật toán Python thuần]              [Trả JSON Fallback về Mobile]
- Quét DB tìm slot trống >= 3h             - Trả danh sách slot
- Lọc bỏ khung giờ tối (> 18:00)           - Kèm cờ: fallback_mode = True
```

1. **Bước 1 (Xảy ra lỗi ngầm):**
   * Backend chuyển tiếp câu prompt sang Ollama. Lúc này card đồ họa RTX 4090 đang xử lý một tác vụ nặng khác, bộ đếm thời gian chạm mốc 3.0 giây -> Kích hoạt ngoại lệ `TimeoutException`.
2. **Bước 2 (Chuyển hướng tức thì dưới 1 giây - Theo P1-9):**
   * Backend hủy kết nối với Ollama.
   * Backend chuyển giao xử lý cho **Deterministic Engine (Task 3 - Thuật toán Python thuần)**.
   * Thuật toán Python duyệt bảng `events` trong MySQL, tìm toàn bộ các khoảng trống liên tục >= 3 tiếng vào ban ngày của tuần hiện tại.
   * Backend trả về cho ứng dụng Android một gói JSON đặc biệt:
     ```json
     {
       "fallback_mode": true,
       "message": "Trợ lý AI phản hồi chậm. Chuyển sang chế độ chọn lịch trực tiếp.",
       "available_slots": [
         {"start": "2026-10-20T08:00:00+07:00", "end": "2026-10-20T11:00:00+07:00"},
         {"start": "2026-10-21T13:30:00+07:00", "end": "2026-10-21T16:30:00+07:00"},
         {"start": "2026-10-23T09:00:00+07:00", "end": "2026-10-23T12:00:00+07:00"}
       ]
     }
     ```

---

#### Trên màn hình điện thoại (Giao diện Manual Exit):

Khung chat không bị biến mất, ứng dụng lập tức trượt lên một bảng điều khiển chọn nhanh dạng danh sách (Bottom Sheet / Modal Dialog) thay vì tiếp tục bắt người dùng chờ AI trả lời:

```
+-------------------------------------------------------------+
|  (!) Trợ lý AI đang bận. Bạn hãy chọn nhanh khung giờ dưới: |
+-------------------------------------------------------------+
|  Tên hoạt động: [ Làm đồ án CTDL                    ]       |
|  Thời lượng:    [ 3 giờ                             ]       |
|                                                             |
|  CÁC KHUNG GIỜ CÒN TRỐNG TRONG TUẦN:                        |
|  ( ) Thứ Ba  (20/10): 08:00 - 11:00 (Sáng rảnh)             |
|  (*) Thứ Tư  (21/10): 13:30 - 16:30 (Sau giờ Triết)         |
|  ( ) Thứ Sáu (23/10): 09:00 - 12:00 (Trước ca Mạng)         |
|                                                             |
|  [ + Chọn giờ khác trên lịch ]                              |
|                                                             |
|  [     XÁC NHẬN THÊM VÀO LỊCH      ]    [   HỦY BỎ   ]      |
+-------------------------------------------------------------+
```

* **Thao tác của sinh viên:**
  * Sinh viên thấy ngay 3 phương án khả thi do thuật toán tính sẵn.
  * Sinh viên chỉ cần chạm chọn vào ô tròn: `(*) Thứ Tư (21/10): 13:30 - 16:30`.
  * Nhấn nút **[Xác nhận thêm vào lịch]**.
* **Kết quả:**
  * Ứng dụng gửi lệnh `POST /api/v1/events` lên Backend.
  * Sự kiện được ghi chính thức vào cơ sở dữ liệu. Lịch trên màn hình tự động cập nhật thêm khối màu của môn Đồ án CTDL.

Người dùng vẫn được điều hướng rõ ràng đến các nút action cụ thể ngay cả khi AI lỗi.

### A2. Hệ thống có những loại thực thể/đối tượng nào? 
- `Event`: có giờ bắt đầu và giờ kết thúc.
- `Deadline`: chỉ có một thời điểm.
- `Task`: có thời lượng và ưu tiên, chưa xếp giờ. (vd: "Hoạt động A, 3 tiếng")

**Cách biểu diễn trong Database:**
Thay vì tách bảng `deadlines` riêng, `Deadline` được lưu chung vào bảng `events` với cột phân loại `kind = 'DEADLINE'` và quy ước **`start_time = end_time`** (thời lượng bằng 0 phút). Cách thiết kế này mang lại 3 lợi ích trực tiếp:
1. **Không làm sai lệch Engine:** Vì `start_time == end_time` (thời lượng = 0), thuật toán tìm giờ trống tự động đi qua mà không coi Deadline là khối bận chiếm chỗ.
2. **Thống nhất bảng `reminders` (A5):** Bảng `reminders` chỉ cần liên kết với duy nhất khóa ngoại `event_id` là có thể đặt nhắc nhở cho cả buổi học, lịch thi lẫn hạn nộp bài.
3. **Đơn giản hóa truy vấn cho team DB:** Khi lấy dữ liệu hiển thị lên lịch tuần/tháng, chỉ cần `SELECT` từ một bảng `events` duy nhất.
Quan hệ giữa `Task` và `Event` là một `Task` sinh ra nhiều `Event`, vì P2-4 cho phép chia nhỏ task. Ví dụ: "Hoạt động A, 3 tiếng" có thể được xếp thành hai khối 1,5 tiếng. Nếu Phase 1 thiết kế quan hệ một-một, Phase 2 sẽ phải đổi lược đồ.

### A3. Vòng đời của một đề xuất (Proposal)

Duties đã nhắc đến state machine (P1-8) và cơ chế hủy đề xuất bị bỏ ngang (P2-7). Các trạng thái:

```
PROPOSED ──> CONFIRMED     (Accept: sinh Event chính thức)
         ├─> REJECTED      (Reject)
         ├─> RESCHEDULED  (Reschedule: sinh đề xuất mới, đề xuất cũ đóng lại)
         └─> ABANDONED     (người dùng chuyển sang yêu cầu khác, theo P2-7)
```

**FE**: có 3 nút mặc định hiện lên khi một proposal được đưa ra: `Confirm`, `Reject`, `Reschedule`.
* **`Confirm` và `Reject`**: Gọi trực tiếp 2 API tương ứng ở Backend (`POST /proposals/{id}/confirm` và `POST /proposals/{id}/reject`), chuyển trạng thái tức thì mà không cần qua mô hình AI, loại bỏ hoàn toàn rủi ro AI hiểu sai câu chữ khi người dùng nhắn văn bản xác nhận hoặc từ chối.
* **`Reschedule`**: Đóng vai trò ghim ngữ cảnh (Context Anchor). Khi người dùng bấm nút này trước khi nhập lệnh điều chỉnh (ví dụ: "dời xuống tối đi"), hệ thống khóa cứng phiên xử lý vào đúng sự kiện của đề xuất đó. Cơ chế này đảm bảo Backend luôn biết chính xác đối tượng cần dời giờ mà không yêu cầu người dùng phải gõ lại tên hoạt động, loại bỏ triệt để lỗi thiếu thực thể.
Ví dụ: sau khi bấm nút `Reschedule` của proposal: "chơi bóng rổ lúc 8h sáng" rồi nhập prompt "dời xuống tối đi", user không cần nhắc lại tên hoạt động mà hệ thống vẫn hiểu vì nút `Reschedule` được bấm từ proposal 'chơi bóng rổ'.
* **`Abandoned`**: Kích hoạt tự động ở tầng logic khi người dùng nhắn sang một chủ đề mới mà không bấm bất kỳ nút nào, hệ thống tự động đánh dấu đề xuất hiện tại là bị bỏ dở (theo đúng yêu cầu P2-7).

`Reschedule` hoạt động như sau:
```
[Proposal 1: 14:00 - 17:00] ──(User: "Trễ hơn đi")──> [Đóng Proposal 1: status = 'RESCHEDULED']
                                                                  │
                                                                  ▼
                                                       [Sinh Proposal 2: 18:00 - 21:00]
                                                       (Lưu kèm: parent_id = 1)
```
#### Quy trình 4 bước cụ thể trong code:

* **Bước 1: Khóa đề xuất cũ (Close the current proposal)**
  * BE tìm bản ghi đề xuất hiện tại (vd: `Proposal ID = 1`, khung giờ `14:00 - 17:00`).
  * Cập nhật trạng thái: `status = 'RESCHEDULED'`. 
  * Điều này đảm bảo trên giao diện, các nút bấm [Confirm/Reject/Reschedule] của Proposal 1 sẽ bị vô hiệu hóa (disabled), tránh việc người dùng bấm nhầm vào đề xuất đã hết hạn.

* **Bước 2: Bổ sung ràng buộc mới vào thuật toán (Add Constraint)**
  * BE (hoặc AI NLU) nhận diện ràng buộc mới: *"Không lấy khung 14:00 - 17:00 nữa, cần tìm khung muộn hơn sau 17:00"*.
  * Đưa danh sách các khung giờ đã bị từ chối vào danh sách cấm (Blacklisted slots) để thuật toán không gợi ý lại đúng cái giờ người dùng vừa từ chối.

* **Bước 3: Engine chạy lại để tìm khung giờ mới**
  * Engine quét lại cơ sở dữ liệu và tìm ra một khoảng trống tiếp theo thỏa mãn điều kiện mới (ví dụ: `18:00 - 21:00`).

* **Bước 4: Tạo đề xuất mới trong Database (Create new linked proposal)**
  * BE tạo một dòng mới trong bảng `proposals` (ví dụ: `Proposal ID = 2`):
    * `task_name`: "Học bài" (kế thừa từ Proposal 1).
    * `start_time`: `18:00`, `end_time`: `21:00`.
    * `status`: `'PROPOSED'` (Đang chờ người dùng phản hồi).
    * `parent_id`: `1` (Khóa ngoại trỏ ngược về Proposal 1 để lưu vết lịch sử).
  * Trả Proposal 2 về cho Android hiển thị thành một thẻ mới kèm câu giải thích: *"Mình đã đổi sang khung 18:00 - 21:00 tối nay cho bạn nhé."*

Câu hỏi đặt ra: Tại sao không sửa luôn proposal 1 mà phải tạo thêm proposal mới làm gì? Tại sao không để hai bên chat qua lại, chừng nào user chốt rồi tạo thẳng một `Event` luôn, sao phải sinh ra các bản `proposal` ở giữa làm gì?

Hai hướng trên đều chỉ có chung một đầu ra là: trạng thái cuối cùng mà không lưu được lịch sử các đề xuất. Chỉ khi ta có chuỗi: Proposal 1 -> Proposal 2 -> Proposal 3, ta mới thống kê được chỉ số: "Trung bình AI phải gợi ý bao nhiêu lần (mấy vòng Reschedule) thì sinh viên mới chịu bấm `Confirm`?"

Ngoài ra lưu thành các proposal còn giúp hệ thống backtracking dễ dàng hơn. VD: sau khi xem Proposal 2 ("18:00"), người dùng thấy tối nay bận và bảo "Thôi quay lại giờ ban đầu lúc 14:00 đi", hệ thống chỉ cần đọc lại Proposal 1 trong Database là có sẵn dữ liệu để phục hồi ngay lập tức.

**Hơn nữa về mặt thống kê, lưu lại proposal có tác dụng:**
1. **Bằng chứng cho Zero Overlap.** Chạy lại Validator trên toàn bộ đề xuất đã từng tạo, để chứng minh bằng số liệu rằng 100% đề xuất không trùng ràng buộc cứng.
2. **Tái hiện lỗi.** Khi có phản ánh "app gợi ý trùng giờ", tra lại: prompt gốc, kết quả NLU trích xuất, các khung Engine trả về. Từ đó biết lỗi nằm ở AI, ở Engine hay ở dữ liệu.
3. **Nguyên liệu cho P2-12** (log phân loại lỗi AI): các đề xuất bị từ chối, kèm prompt tương ứng, cho thấy kiểu câu nào AI hay hiểu sai.
4. **Đo độ trễ từng khâu**, phục vụ mục tiêu dưới 4 giây của P2-10.

#### Liên kết dữ liệu từ Task -> Proposal -> Event (chuẩn bị cho P2-4)

Ở A2 đã xác định một `Task` ("Làm đồ án, 3 tiếng") có thể được chia nhỏ thành nhiều `Event` (ví dụ hai khối 1,5 tiếng vào Thứ Ba và Thứ Năm) khi tuần đó không có khung giờ trống liên tục đủ 3 tiếng (theo P2-4). Để bảng `proposals` hỗ trợ được cả Phase 1 (1 khung giờ) và Phase 2 (chia nhiều khung giờ) mà không phải sửa lại cấu trúc bảng:
```
tasks                         proposals                              events
-----------------             ------------------------------         -------------------------
id = 10                       id = 1                                 id = 101
title = "Đồ án"               task_id = 10 (khóa ngoại -> tasks.id)  task_id = 10
duration_minutes = 180        start_time, end_time (khung giờ chính) proposal_id = 1
priority = 2                  extra_slots_json = NULL (ở Phase 1)    start_time, end_time (khối 1)
                                                                     -------------------------
                                                                     id = 102 (nếu có chia nhỏ)
                                                                     task_id = 10
                                                                     proposal_id = 1
                                                                     start_time, end_time (khối 2)
```
- **Ở Phase 1 (không chia nhỏ task):** Bảng `proposals` sử dụng 2 cột `start_time` và `end_time` để lưu khung giờ đề xuất, cột `extra_slots_json` để `NULL`. Khi người dùng bấm `Confirm`, BE tạo 1 dòng trong bảng `events`.
- **Ở Phase 2 (khi làm P2-4 chia nhỏ task):** Khung giờ đầu tiên vẫn lưu ở `start_time`, `end_time`; các khung giờ chia nhỏ còn lại được lưu dạng chuỗi JSON vào cột `extra_slots_json`. Khi người dùng bấm `Confirm`, BE đọc cả khung chính lẫn `extra_slots_json` để sinh ra các dòng tương ứng trong bảng `events` có cùng `task_id` và `proposal_id`.

### A4. Luồng nhập thời khóa biểu và nhập lại

- Có bước xem trước và xác nhận sau khi parse để tránh sai sót từ OCR.
- Khi trường đổi lịch và sinh viên tải file mới lên:
  - Chỉ thay các sự kiện parse từ file (img/pdf), giữ nguyên các sự kiện tạo qua prompt AI hoặc qua giao diện thủ công.

Nên sẽ cần trường `source` trên mỗi sự kiện, với các giá trị `IMPORTED`, `AI_CREATED`, `MANUAL` (`MANUAL` dành cho lối thoát thủ công của P1-9), kèm `import_batch_id` để biết sự kiện thuộc lần nhập nào.

### A5. Đánh dấu `quan trọng` (Mark as `important`) & nhắc nhở

Dùng local notification (P2-9).
- Người dùng đánh dấu quan trọng bằng **nút** trên thẻ sự kiện.
- Một sự kiện có thể có nhiều mốc nhắc không? Ví dụ trước 1 ngày và trước 1 giờ. **KHÔNG**
- **Đồng bộ:** khi lịch thay đổi (dời, xóa sự kiện), điện thoại phải hủy và hẹn lại các nhắc nhở cũ. Cơ chế nào báo cho điện thoại biết lịch đã thay đổi trên database?
-> Đồng bộ ngay trong phản hồi của API (Response-based Sync)
Cách hoạt động: Khi người dùng gửi yêu cầu qua chatbot để thay đổi/xóa lịch, BE sau khi cập nhật DB xong sẽ không chỉ trả về câu nói của AI, mà trả về kèm danh sách trạng thái mới của sự kiện đó:
  ```json
  {
    "reply": "Đã dời môn CTDL sang 08:00 Thứ Bảy.",
    "action": "RESCHEDULE",
    "event_id": 101,
    "canceled_reminder_time": "2026-10-23T07:30:00+07:00",
    "new_reminder_time": "2026-10-24T07:30:00+07:00"
  }
  ```
* **Phía điện thoại (app):** Nhận được phản hồi này, app thực hiện 2 lệnh:
  1. Hủy lịch hẹn cũ của `event_id: 101`.
  2. Tạo lịch hẹn mới vào `07:30 Thứ Bảy`.

- **Audit (P2-13):** nhắc nhở được hiển thị trên điện thoại, không phải trên server. Nên để có audit trail thì app phải gửi ngược về server các mốc "đã hẹn giờ" và "đã hiển thị" -> làm thêm API cho phần này. Trên server sẽ lưu một bảng `reminders`. Mỗi dòng gồm `event_id`, `offset_minutes` (nhắc trước bao nhiêu phút), và các mốc thời gian `scheduled_on_device_at`, `delivered_at` do app báo về.

### A6. Thông tin người dùng và tùy chọn sinh hoạt

**P2-8 (đăng nhập bằng Google/GitHub):** Người dùng đăng nhập bằng Google thì không có mật khẩu. Nếu Phase 1 thiết kế `hashed_password` là cột bắt buộc, Phase 2 sẽ phải sửa lược đồ. Nên tách ngay từ Phase 1:

```
users                    auth_identities                       user_preferences
-------------            -----------------------------         -------------------------
id                       id                                    user_id (khóa ngoại)
display_name             user_id (khóa ngoại -> users.id)      sleep_start      = 23:30
created_at               provider = "password" | "google"      sleep_end        = 06:30
                                    | "github"                 min_break_minutes = 15
                         provider_user_id (username, hoặc      max_block_minutes = 180
                                    ID từ Google/GitHub)
                         hashed_password (chỉ có giá trị
                                    khi provider="password")
```

Với cách này, Phase 1 chỉ dùng `provider = "password"`. Phase 2 thêm Google và GitHub bằng cách **thêm dòng mới**, không đổi lược đồ. Một người dùng còn có thể liên kết nhiều cách đăng nhập vào cùng một tài khoản.

**Tác dụng của việc tách `user_preferences` khỏi `users`:**
1. **Task P1-3 không phải chờ.** Bảng `users` và `auth_identities` chốt được ngay. Các tùy chọn bàn tiếp sau.
2. **Thêm tùy chọn không đụng tới phần đăng nhập.** Ví dụ tuần 7 muốn thêm "không xếp lịch vào Chủ Nhật": chỉ thêm cột vào `user_preferences`. Phần liên quan đến bảo mật không bị chạm tới.
3. **Thu hẹp phạm vi truy cập.** Engine chỉ đọc `user_preferences`, không bao giờ thấy mật khẩu băm. Điều này cũng đáp ứng được P1-2 (cách ly dữ liệu cá nhân).
4. **Giá trị mặc định.** Người dùng mới vẫn có một dòng tùy chọn mặc định hợp lý, và có thể chỉnh qua prompt, ví dụ "tôi thường ngủ lúc 11 giờ khuya".

## Nhóm B. Biểu diễn dữ liệu

### B1. Lưu thời gian theo định dạng nào?

**Có 2 dạng:**
- **Naive datetime:** chỉ có ngày và giờ, không có múi giờ: `2026-10-14 07:30`. Không biết đây là 7:30 ở Việt Nam hay ở London.
- **Aware datetime:** có độ lệch múi giờ: `2026-10-14 07:30+07:00`. Giá trị này xác định một thời điểm duy nhất trên thực tế.

**Thống nhất sử dụng AWARE**. Vì dùng naive sẽ gây sai lệch khi máy local gọi hàm lấy giờ hiện tại dùng khác múi giờ mà server sử dụng.
Database lưu UTC. JSON dùng chuẩn ISO 8601 có offset, ví dụ `"2026-10-14T07:30:00+07:00"`.

### B2. Độ chi tiết của thời gian

- Lưu thời gian đến phút.
- Làm tròn các đề xuất về bội số 15 phút. (ví dụ "14:15 đến 17:15" thay vì "14:09 đến 17:09"). Lưới chọn giờ thủ công của P1-9 sẽ dùng dạng 15 phút để thống nhất.

### B3. Lịch học lặp hằng tuần thì lưu thế nào?

Giả định: mọi môn học đều diễn ra tất cả các tuần. Ví dụ: môn "Cấu trúc dữ liệu", thứ Hai 07:30 đến 09:30, phòng E201, 15 tuần, bắt đầu từ thứ Hai 07/09/2026. Ngoại lệ: buổi 16/11 nghỉ, học bù vào thứ Bảy 21/11.

Cách lưu: một bảng `courses` lưu thông tin chung, và bảng `events` lưu từng buổi đã expand, có khóa ngoại `course_id`:

```
courses                          events
---------------------            -------------------------------------------
id = 1                           id=1  course_id=1  2026-09-07 07:30-09:30
title = "CTDL"                   id=2  course_id=1  2026-09-14 07:30-09:30
room = "E201"                    ...   (không có buổi 16/11; có buổi 21/11)
import_batch_id = 3
```

Những thông tin chung (common) thì lưu ở course, để vd có đổi phòng thì chỉ cần sửa 1 dòng trong `courses`. 
Xóa một buổi thì xóa 1 dòng trong `events`.

Các buổi học định kỳ (kind = CLASS) thì thuộc về một môn học (course_id có giá trị).
Nhưng các sự kiện do người dùng tạo qua AI (VD: "Chơi bóng rổ"), hoặc sự kiện đầu khóa (kind = EVENT ở C2), hoặc lịch thi độc lập không gắn với môn học cố định sẽ có course_id = NULL. Nếu bảng events không có cột title và room riêng, các sự kiện này sẽ không có nơi lưu tên và địa điểm.

Vậy **CHỐT** như sau:

Bảng `courses`: lưu `id`, `course_code` (VD: `"CSC10004"`), `title`, `default_room`, `owner_id`, `import_batch_id`.

Bảng `events`: **vẫn có cột `title` và `room` riêng**, kèm `course_id` (cho phép `NULL`).
* Khi tạo buổi học từ `Course`, Importer chép `title` và `room` xuống `events`.
* Nếu đổi phòng cả môn học: chạy 1 lệnh `UPDATE events SET room = ... WHERE course_id = 1`.

Như vậy khi hiển thị lịch lên màn hình hoặc chạy Engine, chỉ cần đọc duy nhất bảng events là có đủ tên và phòng, không cần phải JOIN sang bảng courses ở mọi câu truy vấn.

### B4. Mức độ ràng buộc và ưu tiên

Duties nhắc đến hai khái niệm: ràng buộc cứng (P1-6) và trọng số ưu tiên (P2-5). Ta cài đặt như sau:
- Thang ưu tiên: 1 đến 3, số bé là ưu tiên cao.

- Ai gán trọng số ưu tiên khi người dùng không nói? P2-5 ghi "user assigned or AI inferred", nghĩa là AI có thể tự suy ra.
Cách xử lý là AI sẽ trả về 1 nhắc nhở: "Hãy gán độ ưu tiên, else thì gán mặc định là 3." Nếu sau đó user có gán giá trị thì set tương ứng, else thì gán là 3 như đã thông báo.
Team AI về sau có thể improve chỗ này: khi user không gán trọng số thì không gán mặc định là 3 mà cho **AI tự suy ra dựa trên rules được team AI viết sẵn.** VD: những activity liên quan đến hcmus thì ưu tiên mặc định là 2, hay event có keyword "Thi CK" thì ưu tiên mặc định là 1.

- Trường `is_hard` là phải có ở phase 1, còn trường `priority` cũng nên được thêm vào ngay từ Phase 1, dù P2-5 thuộc Phase 2. Nhưng thêm cột ngay từ đầu rẻ hơn nhiều so với đổi lược đồ khi đã có dữ liệu.

### B5. Định danh (ID) cho các bản ghi (record)

**Làm rõ:** mỗi người dùng có đúng một user_id. Nhưng mọi sự kiện, task, đề xuất, nhắc nhở đều cần ID riêng. Khi người dùng xóa "buổi gym thứ Tư", BE phải biết chính xác bản ghi nào cần xóa, tức là `DELETE /events/{event_id}`.

**`owner_id` khác với `user_id`:** `owner_id` là một cột trong bảng `events`, lưu ID của người sở hữu sự kiện đó.

**Tại sao bắt buộc kiểm tra `owner_id`:** Token của sinh viên A cho biết `user_id = 7`. A gửi `DELETE /events/124`. Nếu BE chỉ kiểm tra "đã đăng nhập chưa" rồi xóa, trong khi sự kiện với id 124 thuộc sinh viên B, thì A đã xóa được lịch của B. Đây là lỗ hổng IDOR. Và như thế là đã vi phạm nội dung "cách ly dữ liệu cá nhân" của P1-2.
Vậy `owner_id` chỉ đơn giản là để lưu người sở hữu của một sự kiện giữa vô số sự kiện trên DB, chỉ có người sở hữu sự kiện mới có quyền xóa/thay đổi.

Phương án định dạng ID:
- Số nguyên tự tăng: dễ đoán, nhưng bảo mật đến từ việc **luôn kiểm tra `owner_id`**, không đến từ việc ID khó đoán.

## Nhóm C. Triển khai

### C1. Xóa thật hay đánh dấu đã xóa?

- **Hard delete:** xóa hẳn dòng khỏi bảng.
- **Soft delete:** thêm cột `deleted_at`, chỉ ghi thời điểm xóa và giữ nguyên dòng. Hỗ trợ hoàn tác và audit.

**Lưu ý cho team DB:** nếu chọn soft delete, **mọi câu truy vấn** phải có điều kiện `deleted_at IS NULL`, để:
- Sự kiện đã xóa không hiện lại trên lịch.
- Engine không coi khung giờ của sự kiện đã xóa là bận. Nếu quên lọc, khung đó không bao giờ được gợi ý dù thực tế đang trống.
- Validator không từ chối nhầm một đề xuất hợp lệ vì trùng với sự kiện đã xóa.
- App không hẹn nhắc nhở cho sự kiện đã xóa.

**CHỐT:** 
* **`events`, `courses`, `tasks`**: Dùng **Soft Delete (`deleted_at`)** vì người dùng có thao tác xóa các mục này khỏi lịch (bao gồm cả buổi học, lịch thi, sự kiện và deadline nằm trong bảng `events`), và cần `deleted_at IS NULL` để lọc khi truy vấn.
* **`proposals`**: **Không dùng cột `deleted_at`**. Toàn bộ vòng đời được quản lý bằng cột `status` (`PROPOSED`, `CONFIRMED`, `REJECTED`, `RESCHEDULED`, `ABANDONED`). Không có dòng proposal nào bị xóa, 100% bản ghi luôn nằm lại DB để phục vụ thống kê P2-12.

### C2. Lược đồ cột của file CSV trung gian
**[Chốt bởi: BE (P1-4) + AIS (P2-2) + DB]** | Liên quan: P1-4, P2-2

CSV là hợp đồng chung giữa Parser của Phase 1 và OCR của Phase 2, nên các cột phải cố định từ Phase 1. Phác thảo:

```
course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind
CSC10004,Cau truc du lieu,MON,07:30,09:30,E201,2026-09-07,2026-12-14,CLASS
CSC10004,Thi giua ky CTDL,,13:00,14:30,E301,2026-10-26,2026-10-26,EXAM
CSC10004,Nop bai tap CTDL,,23:59,23:59,,2026-11-20,2026-11-20,DEADLINE
HCMUS001,Sinh hoat dau khoa,,08:00,11:30,Hoi truong 1,2026-09-05,2026-09-05,EVENT
```

Các điểm đã chốt:
- Định dạng giờ `HH:MM` (24 giờ), ngày `YYYY-MM-DD`, mã hóa UTF-8 để lưu tiếng Việt có dấu.
- Danh sách giá trị hợp lệ của cột `kind` khi parse từ file: `CLASS`, `EXAM`, `DEADLINE`, `EVENT` (file thời khóa biểu cố định không có `TASK`; còn trong bảng `events` dưới DB thì cột `kind` có thêm giá trị thứ 5 là `TASK` dành cho các công việc do AI xếp lịch).
- Cột `kind` dùng để phân loại đầu vào để Importer xử lý phù hợp với từng loại:
  + `kind = CLASS`: Tạo 1 dòng ở bảng `courses` và chạy thuật toán lặp mỗi tuần tạo N dòng trong bảng `events` (kéo dài từ `first_date` đến `last_date`, `is_hard = True`).
  + `kind = EXAM` hoặc `EVENT`: `first_date == last_date`, tạo đúng 1 dòng duy nhất trong bảng `events` (`course_id = NULL`).
  + `kind = DEADLINE`: `first_date == last_date`, tạo 1 dòng trong bảng `events` với `kind = 'DEADLINE'` và `start_time = end_time` (thời lượng bằng 0 phút để không chặn khung giờ của Engine).

Dòng không parse được thì xử lý như sau (P1-4): cơ chế "Cách ly dòng lỗi và xác nhận có điều kiện" (Flagging with Human-in-the-Loop Fallback)

#### Bước 1: Phân tách luồng xử lý tại tầng Parser
Khi đọc file, Parser trả về một cấu trúc dữ liệu gồm hai tập hợp riêng biệt thay vì ném lỗi làm sập chương trình:
```json
{
  "valid_rows": [
    {
      "line_number": 1,
      "course_code": "CSC10004",
      "title": "Cau truc du lieu",
      "weekday": "MON",
      "start_time": "07:30",
      "end_time": "09:30",
      "kind": "CLASS"
    }
  ],
  "invalid_rows": [
    {
      "line_number": 4,
      "raw_text": "Thuc hanh Mang may tinh - T7 Tiet 7-9",
      "error_code": "MISSING_TIME_FORMAT",
      "error_message": "Khong the trich xuat gio bat dau va gio ket thuc"
    }
  ]
}
```

#### Bước 2: Hiển thị trạng thái phân cấp tại màn hình Xem trước (Preview Screen)
* Trên ứng dụng di động:
  * Hiển thị bảng danh sách các môn đã bóc tách thành công (`valid_rows`) với trạng thái sẵn sàng nhập (màu xanh).
  * Hiển thị danh sách các dòng bị lỗi (`invalid_rows`) ở một khu vực riêng biệt (màu vàng cảnh báo), hiển thị rõ số dòng và câu văn bản gốc bị lỗi.

#### Bước 3: Cung cấp 2 lựa chọn xử lý cho người dùng
Người dùng được trao quyền quyết định thông qua 2 nút hành động:
1. **Sửa trực tiếp (Inline Correction):** Người dùng có thể nhấn vào dòng lỗi để nhập bổ sung giờ bắt đầu/kết thúc bị thiếu ngay trên form giao diện.
2. **Bỏ qua dòng lỗi có kiểm soát (Explicit Skip):** Nếu dòng bị lỗi thực chất chỉ là dòng chữ ghi chú không quan trọng của trường, người dùng chủ động bấm nút *"Bỏ qua dòng này và tiếp tục nhập các môn còn lại"*.

### C3. Các bảng log vận hành
**[Cho team DB]**

Duties có 4 loại log. Cần chốt mỗi loại lưu ở đâu (MySQL, file, hay cơ sở dữ liệu chuỗi thời gian) và gồm những trường nào:

| Duty | Nội dung | Trường tối thiểu đề xuất |
|:---|:---|:---|
| P2-11 | Telemetry: độ trễ, VRAM, RAM, độ dài hàng đợi | thời điểm, tên chỉ số, giá trị |
| P2-12 | Phân loại lỗi AI | thời điểm, prompt, đầu ra thô, loại lỗi, số lần thử lại |
| P2-13 | Audit nhắc nhở | `reminder_id`, đã hẹn giờ lúc, đã hiển thị lúc |
| P2-10 | Hàng đợi suy luận | thời điểm vào hàng đợi, bắt đầu xử lý, kết thúc |

**[Đề xuất]** Phase 1 chỉ cần **thống nhất lược đồ** các bảng log, chưa cần hiện thực. Lý do: bảng `proposals` (A3) và `reminders` (A5) cần có sẵn các cột mà log ở Phase 2 sẽ dùng tới.
