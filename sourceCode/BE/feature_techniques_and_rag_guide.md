# Cẩm nang Kỹ thuật Xử lý Cốt lõi và Chẩn đoán RAG trong Hệ thống Backend

Tài liệu này hệ thống hóa toàn bộ các kỹ thuật xử lý, thuật toán và công nghệ được áp dụng **trực tiếp trong mã nguồn Backend** của đồ án. Mục tiêu của tài liệu là giải thích bản chất vấn đề, lý do chọn kỹ thuật và cơ chế vận hành tới đúng mức cần thiết để người đọc hiểu rõ cách hệ thống xử lý trước khi đi sâu vào từng dòng code.

---

## Phần 1: Biểu thức Chính quy (Regex) và Tiền xử lý Văn bản

### 1.1. Biểu thức Chính quy (Regular Expressions) vừa đủ dùng để đọc hiểu mã nguồn

Trong hệ thống này ([services/nlu.py](services/nlu.py), [services/normalizer.py](services/normalizer.py), [services/search_engine.py](services/search_engine.py), [services/temporal.py](services/temporal.py)), Regex được dùng ở 3 việc chính: lọc thông tin nhạy cảm, bóc tách thời lượng/ngày/giờ từ câu tự nhiên và chuẩn hóa teencode. Cần nắm 5 thành phần sau:

1. **Lớp ký tự cơ bản:**
   * `\d`: khớp một chữ số (`0` đến `9`). Ví dụ `\d{1,2}` khớp `8` hoặc `14`.
   * `\w`: khớp ký tự chữ cái, chữ số hoặc gạch dưới (`_`).
   * `\s`: khớp khoảng trắng, tab hoặc xuống dòng.
2. **Định lượng số lần lặp (Quantifiers):**
   * `?`: lặp 0 hoặc 1 lần (tùy chọn).
   * `+`: lặp 1 lần trở lên.
   * `*`: lặp 0 lần trở lên.
   * `{m,n}`: lặp từ `m` đến `n` lần (ví dụ `\d{4}-\d{1,2}-\d{1,2}` khớp ngày chuẩn ISO `2026-11-26`).
3. **Nhóm giữ lại và Nhóm không giữ lại (`(...)` so với `(?:...)`):**
   * `(...)` vừa gom cụm vừa lưu giá trị bắt được để code lấy qua `.group(1)`, `.group(2)`.
   * `(?:...)` chỉ gom cụm để áp dụng phép OR `|` hoặc `?` mà không làm rối chỉ số nhóm. Ví dụ `(?:thứ|thu)\s*(hai|ba|[2-7])` khớp cụm nhưng chỉ lưu phần số/tên thứ ở `.group(1)`.
4. **Ranh giới từ `\b` (Word Boundary):**
   * Khớp vị trí ranh giới giữa một ký tự từ (`\w`) và một ký tự không phải từ (khoảng trắng, dấu câu, đầu/cuối chuỗi).
   * **Ví dụ thực tế trong đồ án:** Trước đây biểu thức `_SEARCH_DATE_RE` thiếu `\b`, khiến một mẫu ngắn khớp nhầm vào bên trong chuỗi dài khác. Khi đặt `\b(...)\b` bao ngoài danh sách mẫu ngày và thứ (ví dụ trong [services/search_engine.py](services/search_engine.py#L259-L269)), hệ thống bảo đảm từ khóa mã môn như `"ctdl"` không bao giờ bị nhận nhầm thành một phần của từ chỉ ngày hay thứ.
5. **Kiểm tra điều kiện xung quanh không tiêu thụ ký tự (Lookaround):**
   * **Negative Lookbehind `(?<!pattern)` (nhìn lùi phủ định):** Khẳng định chuỗi ngay phía trước KHÔNG được khớp `pattern`. Ví dụ trong [services/temporal.py](services/temporal.py#L118), mẫu `(?:^|(?<!\d))(\d{1,2})\s*[/-]\s*(\d{1,2})` giúp sau khi đã xử lý ngày ISO `YYYY-MM-DD`, bộ bắt ngày kiểu `dd/mm` hoặc `dd-mm` không cắt nhầm 2 chữ số cuối năm trong `"2026-12-18"`.
   * **Negative Lookahead `(?!pattern)` (nhìn tới phủ định):** Khẳng định chuỗi ngay phía sau KHÔNG được khớp `pattern`. Ví dụ trong [services/nlu.py](services/nlu.py#L406), mẫu `lịch(?!\s+sự\b(?!\s+kiện))` và `có gì(?!\s+đâu\b)` ngăn bộ phân loại ý định nhận nhầm câu xã giao *"lịch sự"* hoặc *"không có gì đâu"* thành yêu cầu xem lịch trình `query_schedule`.

### 1.2. Chuẩn hóa Unicode (`NFC`, `NFD`) và Gấp dấu tiếng Việt (`fold`)

* **Vấn đề:** Cùng một chữ tiếng Việt có dấu (như chữ `á`) có thể được biểu diễn theo kiểu dựng sẵn (1 mã Unicode - `NFC`) hoặc kiểu tổ hợp (chữ `a` cộng thêm dấu sắc - `NFD`). Nếu không thống nhất, hai chuỗi nhìn giống hệt nhau trên màn hình vẫn so sánh sai khi so khớp.
* **Cách xử lý trong hệ thống:**
  * Tiền xử lý chuẩn hóa đầu vào về `NFC` ([services/normalizer.py](services/normalizer.py#L95)).
  * Khi lập chỉ mục vector và so khớp từ khóa không phân biệt dấu ([services/rag.py](services/rag.py#L84-L87)), hàm `fold()` chuyển chữ thường, đổi `đ` thành `d`, phân rã sang `NFD` rồi lọc bỏ mọi ký tự dấu phụ (`unicodedata.category(c) != "Mn"`). Nhờ vậy `"đồ án"` và `"do an"` sinh ra vector hoàn toàn giống nhau.

### 1.3. Khử thông tin nhạy cảm (PII Redaction) & Bảo vệ Ngữ cảnh Tiếng Anh

* **Khử PII (`sanitize_prompt` trong [services/privacy.py](services/privacy.py#L35-L48)):** Trước khi văn bản đi vào LLM hay ghi vào log lỗi, Regex tự động thay địa chỉ email bằng `[email]`, URL web bằng `[url]` và số điện thoại Việt Nam bằng `[phone]`, đồng thời giới hạn độ dài để vừa cửa sổ ngữ cảnh mô hình.
* **Bảo vệ từ tiếng Anh đa nghĩa (`_has_vietnamese_context` trong [services/normalizer.py](services/normalizer.py#L51-L66)):** Một số từ viết tắt teencode tiếng Việt trùng mặt chữ với từ tiếng Anh thông dụng (`gap` - gấp, `vs` - với, `hop` - họp, `lam` - làm, `bai` - bài, `hoc` - học). Hệ thống kiểm tra xem câu có dấu tiếng Việt hoặc từ khóa bối cảnh tiếng Việt hay không; nếu là câu tiếng Anh thuần như *"Mind the gap vs other"*, hệ thống bỏ qua không đổi chữ `"gap"` thành `"gấp"`.

---

## Phần 2: Kỹ thuật Xử lý trong Tính năng Xếp lịch cùng AI (`Scheduling with AI`)

### 2.1. Giới hạn vai trò AI, Few-Shot Prompting và Structured Output

* **Bản chất LLM:** Mô hình ngôn ngữ lớn (`Meta-Llama-3.1-8B-Instruct-AWQ-INT4` chạy trên `vLLM`) là mô hình dự đoán token tiếp theo. Nó rất mạnh ở khả năng hiểu ngữ nghĩa linh hoạt nhiều cách diễn đạt nhưng có nhược điểm cố hữu là tính toán số học/lịch dương không chính xác và có thể **ảo giác (hallucination)**, tức tự bịa ra dữ liệu nghe hợp lý nhưng sai sự thật.
* **Cách hệ thống kiểm soát ([services/nlu.py](services/nlu.py#L40-L123)):**
  1. **Bounded Role:** AI chỉ làm nhiệm vụ **trích xuất thực thể NLU**, tuyệt đối không tự tìm giờ trống và không được phép ghi vào cơ sở dữ liệu lịch chính thức.
  2. **Few-Shot Prompting + `temperature = 0.0`:** Gắn kèm các cặp câu hỏi - JSON mẫu trong `FEW_SHOT` để định hướng phân biệt giữa xếp lịch (`schedule_task`), hỏi lịch (`query_schedule`), đổi lịch (`reschedule`), xóa (`delete_event`) và câu xã giao (`unknown`), cùng `temperature = 0.0` để đầu ra ổn định tối đa.
  3. **Structured Output & Retry:** Yêu cầu `response_format = {"type": "json_object"}` và kiểm tra bằng `Pydantic` (`NluResult`). Nếu JSON vỡ cấu trúc hoặc lệch kiểu dữ liệu, hệ thống từ chối kết quả và tự động thử lại tối đa 1 lần trước khi rơi về bộ quy tắc dự phòng.

### 2.2. Chốt chặn Chống Ảo giác bằng Đối chiếu Chữ gốc (Literal-Text Guards)

* AI không được phép điền bừa những trường người dùng chưa nói. Trong [`_finalize`](services/nlu.py#L469-L571):
  * **Thời lượng (`duration_minutes`):** Chỉ nhận khi được chặn biên trong `15..720` phút và câu gốc thực sự chứa cụm chỉ thời lượng; nếu người dùng không nêu thời lượng, hệ thống đặt lại thành `None` để hỏi làm rõ.
  * **Ngày tháng & Hạn chót (`date_hint`, `deadline_hint`):** Giá trị AI trích ra chỉ được giữ lại nếu cụm từ đó xuất hiện nguyên văn trong câu gốc của người dùng (và không nhầm các từ chỉ buổi như `sáng`, `chiều`, `tối`).

### 2.3. Quy đổi Ngày Tương đối Tất định & Chặn Cận trên Hạn chót

* Hàm [`resolve_date_hint`](services/temporal.py#L37-L209) biến các chuỗi tự nhiên tiếng Việt và tiếng Anh (*"hôm nay"*, *"ngày mai"*, *"thứ sáu"*, *"tuần sau"*, *"Friday"*, *"2026-12-18"*) thành khoảng ngày `[start, end]` cố định dựa duy nhất vào đồng hồ `reference_now` theo múi giờ `+07:00`.
* Nếu câu vừa có phạm vi tìm lịch (`date_hint = "tuần này"`) vừa có hạn chót (`deadline_hint = "thứ sáu"`), hệ thống áp dụng phép chặn cận trên `window_end = min(window_end, deadline)` để thuật toán tìm slot không bao giờ gợi ý khung giờ trễ hạn.
* Nếu người dùng nhập cụm mơ hồ (*"lúc nào rảnh"*, *"sắp tới"*), hàm gắn `clarification_question` để hỏi lại.

### 2.4. Thuật toán Tìm Khung giờ Trống Sort-and-Sweep ($O(N \log N)$)

* Thay vì kiểm tra từng ô thời gian (lãng phí khi khoảng tìm kiếm dài nhiều tuần), hàm [`find_free_slots`](services/search_engine.py#L1246-L1320) dùng kỹ thuật quét đoạn (Sort-and-Sweep / Merge Intervals):
  1. Thu thập mọi sự kiện chiếm thời gian (`blocks_availability = True`, bỏ qua `DEADLINE` vì deadline là điểm thời gian có độ dài 0), mở rộng hai đầu thêm khoảng nghỉ đệm `min_break_minutes`, và sinh các đoạn giờ ngủ hằng đêm (`_build_sleep_intervals`).
  2. Sắp xếp toàn bộ khoảng bận tăng dần theo thời điểm bắt đầu ($O(N \log N)$) rồi gộp các đoạn giao nhau hoặc liền kề thành danh sách khoảng bận không chồng lấn.
  3. Quét tuyến tính phần bù giữa `[window_start, window_end]` và danh sách đã gộp, làm tròn đầu khoảng trống lên và cuối khoảng trống xuống theo lưới bước `15` phút (`slot_step_minutes = 15`). Chỉ giữ lại các khoảng trống có độ dài lớn hơn hoặc bằng `duration_minutes`.

### 2.5. Chấm điểm Slot, Bộ nhớ Từ chối (`excluded_slots`), Chia nhỏ Việc và Hàng đợi FIFO

* **Chọn khung giờ tối ưu & Khung giờ rộng ([services/proposals.py](services/proposals.py#L89-L160)):** Hàm `_pick_slot` trượt bước `15` phút trong các khoảng trống khả dụng, chọn khung giờ theo thứ tự ưu tiên: khớp buổi mong muốn (`preferred_time_of_day`), tránh buổi không muốn (`avoid_time_of_day`), ưu tiên giờ sinh hoạt bình thường và chọn thời điểm sớm nhất. Khi người dùng chỉ định khung giờ cụ thể (kể cả khoảng rộng như *"từ 2pm đến 5pm trong 1 tiếng"*), `_pick_slot` tìm khối phù hợp nằm gọn trong `[want_start, want_end]` thay vì ép độ dài phải bằng đúng cả khoảng.
* **Bộ nhớ Từ chối (`excluded_slots`):** Khi người dùng bấm `Reschedule`, hệ thống truy ngược chuỗi `parent_id` của đề xuất để thu thập mọi khung giờ đã từng gợi ý trước đó và cắt bỏ ra khỏi các khoảng trống, tránh đề xuất lặp lại đúng giờ người dùng vừa từ chối.
* **Chia nhỏ Việc dài (`split_task`):** Nếu thời lượng vượt quá giới hạn làm việc liên tục (`max_block_minutes`, mặc định `180` phút) hoặc không có một khoảng trống đơn lẻ đủ dài, hàm đệ quy `split_task` chia công việc thành nhiều khối (mỗi khối tối thiểu `30` phút, tối đa `6` mảnh), chừa khoảng nghỉ `min_break_minutes` giữa các khối và lưu phần phụ vào `extra_slots_json`.
* **Hàng đợi FIFO `InferenceBroker` ([services/inference_queue.py](services/inference_queue.py)):** Dùng hàng đợi vé `deque` kết hợp biến điều kiện `threading.Condition` để bảo đảm mỗi thời điểm chỉ có 1 yêu cầu suy luận chạy tới mô hình cục bộ, tránh quá tải GPU/VRAM; nếu đợi hàng quá `1.0s` sẽ ngắt ngay để không treo trải nghiệm người dùng.
* **Human-in-the-Loop (`Proposal` -> `Event`):** Đề xuất nháp chỉ lưu vào bảng `proposals` (`PROPOSED`). Chỉ khi người dùng bấm `Confirm`, hệ thống mới chạy kiểm tra trùng lịch cứng lần cuối (`check_hard_conflict`) rồi mới đổi trạng thái sang `CONFIRMED` và ghi vào bảng `events`.

---

## Phần 3: Kỹ thuật Xử lý trong Tính năng Tìm kiếm Thông tin (`Information Searching`)

### 3.1. Tìm kiếm Lai (Hybrid SQL + Vector Search) và Tư duy Không dùng LLM

* **Vì sao Tra cứu Lịch cá nhân không gọi LLM?** Câu trả lời cho *"tuần sau mình thi môn gì"* phải chính xác tuyệt đối 100% theo dữ liệu thực trong DB. Nếu đưa cho LLM tự tóm tắt danh sách lịch, LLM có thể bỏ sót hoặc nhìn nhầm giờ/phòng. Vì vậy luồng Schedule Search dừng hẳn ở bước xếp hạng Vector rồi trả thẻ sự kiện có cấu trúc từ MySQL.
* **Thứ tự 2 pha ([services/search_engine.py](services/search_engine.py#L533-L615)):**
  1. **Pha SQL (Lọc cứng trước):** Truy vấn ngay những sự kiện thuộc đúng `owner_id`, chưa xóa mềm (`deleted_at IS NULL`), nằm trong khung thời gian, đúng `kind` và `room`. Mục tiêu là vừa bảo mật chống xem chéo dữ liệu người khác (anti-IDOR), vừa thu hẹp tập ứng viên về đúng phạm vi cấu trúc.
  2. **Pha Vector & Từ vựng (Xếp hạng ngữ nghĩa sau):** Nếu người dùng có từ khóa chủ đề (`keywords`), hệ thống tính điểm tương đồng giữa truy vấn và từng sự kiện ứng viên rồi sắp xếp giảm dần theo điểm và tăng dần theo thời gian.

### 3.2. Độ tương đồng Cosine & Cơ chế Vector 2 Tầng

* **Vector Embedding & Cosine Similarity:** Thay vì so khớp đúng từng chữ cái, văn bản được ánh xạ thành một vector số thực nhiều chiều. Khi hai vector đã được chuẩn hóa độ dài đơn vị (L2 normalization, tức $\lVert \vec{v} \rVert_2 = 1$), độ tương đồng Cosine chính là tích vô hướng:

  $$\cos(\theta) = \vec{q} \cdot \vec{d} = \sum_{i=1}^{D} q_i d_i$$

* **Tầng 1 - Signed Feature Hashing 512 chiều + Cụm Khái niệm (`rag.embed` + `SEMANTIC_CONCEPT_CLUSTERS`):**
  * Vì dữ liệu lịch cá nhân không được gửi ra dịch vụ đám mây bên ngoài (quy tắc cô lập riêng tư P1-2) và cần tốc độ dưới 2ms mà không phụ thuộc GPU, hệ thống dùng kỹ thuật băm đặc trưng (Feature Hashing, Weinberger et al., 2009) trên hàm băm xác định `zlib.crc32`:
    1. Tách từ đơn (word unigrams), cặp từ liên tiếp (word bigrams) và bộ 3 ký tự (character trigrams, ví dụ `"^to"`, `"toa"`, `"oan"`, `"an$"`). Trigrams ký tự giúp bắt tốt cả lỗi chính tả nhẹ hoặc biến thể ngắn.
    2. Ánh xạ mỗi đặc trưng sang chỉ số `h % 512` và cộng `+1.0` hoặc `-1.0` tùy bit dấu `(h >> 16) & 1` (kỹ thuật băm có dấu giúp giảm nhiễu va chạm so với cộng một chiều), sau đó chuẩn hóa L2.
    3. Kết hợp từ điển **9 cụm khái niệm môn học** (`SEMANTIC_CONCEPT_CLUSTERS`) gắn các token neo trực giao (ví dụ mọi môn Toán `MTH`, *Xác suất thống kê*, *Vi tích phân 2* đều được chèn thêm tag cụm Toán), nhờ đó gõ `"toán"` vẫn kéo được đúng các môn Toán với ngưỡng vector `0.25`.
    4. Điểm cuối tầng 1 kết hợp độ khớp từ vựng (`_compute_lexical_score`) và điểm vector (`VECTOR_SIMILARITY_THRESHOLD = 0.25`).
* **Tầng 2 - Neural Embedding Fallback (Tùy chọn qua CPU):**
  * Chỉ kích hoạt khi Tầng 1 trả về ít hơn `MIN_TIER1_RESULTS` (`1`) kết quả và biến môi trường `ENABLE_NEURAL_SEARCH_FALLBACK=1` được bật.
  * Mô hình nhẹ đa ngữ `paraphrase-multilingual-MiniLM-L12-v2` được nạp lười (lazy-load) trên CPU để mã hóa ngữ nghĩa sâu cho các từ đồng nghĩa hoàn toàn mới chưa có trong từ điển, với ngưỡng lọc `NEURAL_FALLBACK_THRESHOLD = 0.42`.

---

## Phần 4: Chuyên sâu về RAG - Tham chiếu Học liệu và Sổ tay Chẩn đoán

### 4.1. Bản chất của RAG ("Bài thi mở sách" - Lab 6 CSC10014)

Theo tài liệu thực hành *Lab 6 - Adding AI to the Assistant, Safely* của giảng viên TS. Lê Thanh Tùng:
* Hỏi trực tiếp LLM giống như bắt sinh viên **thi đóng sách**: AI trả lời từ trí nhớ huấn luyện tổng quát nên không hề biết quy chế riêng của khoa/trường và có xu hướng **bịa thông tin mạch lạc** (hallucination).
* **RAG (Retrieval-Augmented Generation)** biến bài toán thành **thi mở sách**: tìm đúng đoạn văn bản quy định liên quan trước, rồi đưa đoạn đó cho AI và buộc AI chỉ được tổng hợp câu trả lời từ nguồn vừa tìm thấy (hoặc nói *"không biết / tài liệu không đề cập"* nếu không có căn cứ).
* Trong quy trình 4 khâu của RAG, **3 khâu là lập trình tất định** (tìm kiếm/truy xuất đoạn liên quan, kiểm tra ngưỡng để dừng sớm khi không có kết quả, và hậu kiểm trích dẫn/fallback) và **chỉ duy nhất khâu diễn đạt lại văn bản** là giao cho LLM.

### 4.2. Chia đoạn (Chunking) & Tìm kiếm Lai Học vụ trong Hệ thống

* **Chiến lược `chunk_text` hiện tại ([services/rag.py](services/rag.py#L121-L137)):**
  * Đọc văn bản theo từng dòng không rỗng để **không bao giờ cắt ngang một dòng thời khóa biểu hoặc một dòng quy định**.
  * Gom các dòng thành từng đoạn (chunk) dài tối đa `CHUNK_CHARS = 400` ký tự, có phần gối đầu `CHUNK_OVERLAP = 80` ký tự để tránh đứt mạch thông tin nằm ngay ranh giới hai đoạn liên tiếp.
  * Mỗi chunk được lưu kèm tên nguồn (`source`) và vector 512 chiều trong tệp chỉ mục mã hóa đối xứng Fernet (`VectorIndex`, tệp `owner_0.idx` hoặc thư mục `data/rag/academic_kb`).
* **So sánh với chiến lược gắn siêu dữ liệu theo mục (`H26#5.3` trong Lab 6):** Trong Lab 6, tài liệu Markdown học vụ được chia **mỗi mục là một chunk** kèm metadata (`doc_id`, `title`, `version`, `owner`) để khi truy xuất có thể chỉ đích danh số hiệu văn bản, phiên bản và điều khoản gốc.
* **Cách Hệ thống thực thi Hybrid RAG 6 bước ([services/search_engine.py](services/search_engine.py#L968-L1169)):**
  1. **Bước 1 (Chuẩn hóa & Mở rộng câu hỏi):** Khử PII, chuẩn hóa teencode, bung viết tắt môn học và từ khóa học vụ song ngữ (`_expand_kb_abbreviations`, ví dụ `graduation -> tốt nghiệp`, `credits -> tín chỉ`, `cntt -> công nghệ thông tin`).
  2. **Bước 2-3 (Truy xuất Lai có cấu trúc + Vector):** Quét đồng thời 8 bảng SQL `kb_*` (`_retrieve_structured_kb_hits`) và kho chỉ mục vector mã hóa (`rag.retrieve` với ngưỡng tối thiểu `MIN_SCORE = 0.22`). Kết quả hai nguồn được **đan xen (interleave)** và khử trùng lặp để lấy đúng `top_k` trích dẫn. Nếu danh sách rỗng, hệ thống **dừng trước khi gọi LLM** (Abstain Gate).
  3. **Bước 4 (Đóng gói Ngữ cảnh giới hạn):** Hàm `_pack_rag_context` đánh số `[1], [2]...` và cắt trong giới hạn `MAX_RAG_CONTEXT_CHARS = 2400` ký tự để toàn bộ prompt hệ thống + ngữ cảnh + câu hỏi nằm gọn trong cửa sổ `2048` token của `vLLM`.
  4. **Bước 5-6 (Sinh câu trả lời qua vLLM & Hậu kiểm/Fallback):** Gửi qua hàng đợi FIFO với `temperature = 0.1`, timeout `8.0s`. Nếu AI trả lời kiểu từ chối thiếu thông tin (`_is_academic_rag_refusal`), hệ thống xóa các `citations` đính kèm để tránh gây hiểu nhầm. Nếu `vLLM` quá hạn hoặc sập, hệ thống trả nguyên văn các trích đoạn tìm được ở Bước 3 (`fallback_mode = True`).

### 4.3. Sổ tay Chẩn đoán 2 Bước khi RAG Trả lời Dở (Theo Ghi chú Giảng viên)

Khi kiểm thử thấy hệ thống RAG trả lời sai, thiếu ý hoặc lạc đề, ta tuyệt đối không đoán mò mà kiểm tra tuần tự đúng **2 tầng** sau:

#### Bước 1: Kiểm tra Tầng Truy xuất (Retrieval Quality)

Trước hết, thử truy xuất với `top_k` nhỏ (ví dụ **`top_k = 2`**) và kiểm tra danh sách trích dẫn trả về (qua `citations` trong response, trường `retrieved_context` trong `logs/ai_errors.jsonl`, hoặc in log kiểm thử trong terminal):

1. **Tình huống 1A - Top-2 hoàn toàn KHÔNG liên quan đến câu hỏi ban đầu:**
   * **Kiểm tra đồng nhất không gian Vector DB và Query:** Vector lưu trong DB (`.idx`) lúc nạp tài liệu và vector của câu hỏi lúc truy vấn bắt buộc phải được tạo bởi **cùng một hàm `embed`**, cùng chuẩn hóa `fold()`, cùng từ điển viết tắt `_EMBED_ABBREVIATIONS` và cùng số chiều (`512`).
   * **Lỗi hay gặp trong dự án:** Nếu lập trình viên bổ sung từ viết tắt mới vào `_EMBED_ABBREVIATIONS` hoặc chỉnh `_WEEKDAY_CANONICAL_PATTERNS` trong [services/rag.py](services/rag.py#L29-L100) nhưng lại **quên nạp lại (re-index)** các tệp `.idx` cũ, vector câu hỏi lúc search sẽ lệch hệ quy chiếu so với vector đã lưu trong DB, dẫn đến điểm Cosine thấp hoặc trượt kết quả.
   * **Kiểm tra ngưỡng lọc:** Nếu `best score < MIN_SCORE (0.22)`, `rag.retrieve` ghi nhận mã `RAG_LOW_SCORE` vào `logs/ai_errors.jsonl` kèm nội dung đoạn có điểm cao nhất để người phát triển soi lại xem tại sao điểm lại thấp.

2. **Tình huống 1B - Top-2 có chữ liên quan thật, nhưng nội dung lấy ra lại SAI hoặc LỖI THỜI so với bản chất câu hỏi:**
   * **Ví dụ kinh điển:** Trong bộ quy chế có *Luật 264 nội dung "sửa đổi, bổ sung Luật 263"*, nên văn bản Luật 264 vẫn nhắc tên cụm từ của Luật 263, còn Luật 263 gốc lại chứa toàn bộ đoạn mô tả chi tiết khớp rất nhiều từ khóa của câu hỏi. Khi người dùng hỏi về quy định đó, bộ tìm kiếm có thể kéo nhầm **chunk của Luật 263 cũ** lên Top 1 vì mật độ từ khớp bề mặt cao hơn.
   * **Nguyên nhân gốc nằm ở Kỹ thuật Tách Chunk và Siêu dữ liệu (Chunking & Metadata):**
     * Nếu chỉ cắt đều `400` ký tự thuần túy theo số ký tự (`CHUNK_CHARS = 400`), tiêu đề điều khoản cha hoặc ghi chú *"được sửa đổi bởi Luật 264"* có thể bị rớt ở chunk trước đó, làm chunk chứa điều khoản mất ngữ cảnh hiệu lực.
     * Kho vector hiện tại xếp hạng thuần túy theo điểm tương đồng văn bản, chưa có trường trạng thái hiệu lực (`superseded_by`) hay trọng số ưu tiên phiên bản mới.
   * **Hướng xử lý triệt để khi gặp lỗi này:**
     1. **Section-aware Chunking (như gợi ý trong Lab 6):** Chia chunk theo ranh giới Điều/Khoản/Mục và **gắn kèm tiêu đề cha + metadata phiên bản/ngày hiệu lực** vào đầu mỗi chunk trước khi `embed`.
     2. **Hợp nhất văn bản trước khi nạp (Consolidation):** Với văn bản sửa đổi bổ sung, hợp nhất phần sửa đổi vào văn bản gốc (hoặc gắn cờ loại bỏ chunk cũ đã hết hiệu lực khỏi chỉ mục) ngay ở khâu chuẩn bị dữ liệu DB/Admin.
     3. **Tăng cường Metadata Filtering / Re-ranking:** Lọc hoặc cộng điểm ưu tiên cho tài liệu có phiên bản/năm ban hành mới hơn khi hai đoạn có cùng chủ đề.

#### Bước 2: Kiểm tra Tầng Đẩy Ngữ cảnh vào LLM (Context Injection & Generation)

Nếu Bước 1 đã xác nhận Top-2 chứa đúng đoạn tài liệu trả lời hoàn hảo cho câu hỏi nhưng câu trả lời cuối cùng của AI vẫn dở, ta kiểm tra ngay xem **context có thực sự được đẩy đủ vào LLM hay không**:

1. **Kiểm tra quá trình đóng gói `_pack_rag_context`:**
   * Tổng dung lượng ngữ cảnh bị giới hạn bởi `MAX_RAG_CONTEXT_CHARS = 2400` ([services/search_engine.py](services/search_engine.py#L736-L791)). Nếu đoạn đứng đầu hoặc các dòng `kb_*` quá dài, đoạn chứa đáp án nằm ở vị trí sau có thể bị cắt bớt dấu `...` hoặc bị loại khỏi `context_block` trước khi gửi tới LLM.
   * Ngược lại, trong cửa sổ tối đa `2048` token của `vLLM`, nếu câu hỏi cộng ngữ cảnh cộng `300` token đầu ra vượt ngân sách token, `vLLM` sẽ từ chối hoặc cắt bớt phần đầu ngữ cảnh.
2. **Cách tự kiểm tra trực tiếp trên máy chủ BE:**
   * Gọi `GET /api/v1/debug/logs` (xem [`routers` / `main.py`](main.py#L250-L275)) hoặc mở `logs/ai_calls.jsonl` để kiểm tra bản ghi cuộc gọi `academic_rag`: xem `status` (`OK` hay `FALLBACK`), `raw_output`, `latency_ms` và `usage` (số prompt tokens thực sự đã đi qua LLM).
   * Kiểm tra `logs/ai_errors.jsonl` nếu `fallback_mode = True`: xem AI bị ngắt vì `TIMEOUT` (vượt `8.0s`) hay `INFRA_CRASH` (sai endpoint/vLLM chưa bật/bị chặn allowlist `LLM_ALLOWED_HOSTS`).

---

## Phần 5: Kỹ thuật Bảo mật, Cô lập Dữ liệu và Toàn vẹn Giao dịch trong BE

1. **Xác thực & Chống truy cập chéo (Anti-IDOR):**
   * Mật khẩu băm bằng `bcrypt`; phiên làm việc dùng `JWT` (`HS256`, hết hạn cấu hình qua `JWT_EXPIRE_MINUTES`).
   * Mọi câu truy vấn dữ liệu cá nhân đều đi qua `active_events_stmt(owner_id)` / `active_courses_stmt(owner_id)` / `get_proposal(db, owner_id, id)` để chắc chắn một sinh viên không bao giờ đọc hoặc sửa được lịch, tác vụ, đề xuất hay nhắc hẹn của người khác.
2. **Cô lập Quyền riêng tư & Mã hóa Kho Vector Cục bộ (`services/privacy.py`):**
   * Chặn gửi prompt chứa lịch cá nhân ra ngoài mạng riêng (`assert_private_endpoint` chỉ cho phép loopback, mạng nội bộ Docker/RFC1918/Tailscale hoặc IP trong `LLM_ALLOWED_HOSTS`).
   * Dữ liệu kho vector (`owner_*.idx`) được mã hóa đối xứng bằng **Fernet** (kết hợp **AES-128-CBC** mã hóa nội dung và **HMAC-SHA256** xác thực toàn vẹn chống sửa đổi trái phép), khóa dẫn xuất từ `DATA_ENCRYPTION_KEY` qua **PBKDF2-HMAC-SHA256** (`310,000` vòng lặp). Nếu giải mã thất bại, hệ thống ném `IndexDecryptionError` thay vì âm thầm ghi đè làm mất chỉ mục cũ.
3. **Toàn vẹn Giao dịch & Chống Race Condition (`Savepoint`):**
   * Khi cập nhật thời gian sự kiện ([routers/events.py](routers/events.py)), kiểm tra ràng buộc hợp lệ trên cặp biến tạm trước khi gán vào đối tượng ORM để lỗi nghiệp vụ không làm bẩn trạng thái session.
   * Khi tạo hoặc cập nhật bản ghi `Reminder` đồng thời từ nhiều luồng API, hệ thống dùng savepoint lồng nhau (`with db.begin_nested():`) để bắt `IntegrityError` an toàn mà không làm hỏng giao dịch chính.

---

## Phần 6: Nguồn Tham chiếu Có thể Kiểm chứng (Verifiable Sources)

1. **Học liệu môn học CSC10014 - Thực hành Tuần 6:** Dr. Lê Thanh Tùng, *Lab 6: Adding AI to the Assistant, Safely (LLM, Inverted Index, BM25, Open-book RAG, Structured Output & Grounding Check)*, Khoa Công nghệ Thông tin, Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM (FIT-HCMUS, 2026).
2. **Retrieval-Augmented Generation (RAG):** Patrick Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, Advances in Neural Information Processing Systems (NeurIPS 2020), arXiv:2005.11401.
3. **Feature Hashing (Signed Vector Projection dùng trong `rag.embed`):** Kilian Q. Weinberger, Anirban Dasgupta, John Langford, Alex Smola, Josh Attenberg, *Feature Hashing for Large Scale Multitask Learning*, ICML 2009.
4. **BM25 Ranking Function (đối chiếu tìm kiếm văn bản học liệu Lab 6):** Stephen Robertson và Hugo Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*, Foundations and Trends in Information Retrieval, 2009.
5. **JSON Web Token (JWT) & Dẫn xuất khóa PBKDF2:**
   * M. Jones, J. Bradley, N. Sakimura, *JSON Web Token (JWT)*, IETF RFC 7519 (2015).
   * M. S. Turan et al., *Recommendation for Password-Based Key Derivation (PBKDF2)*, NIST Special Publication 800-132 (2010).
