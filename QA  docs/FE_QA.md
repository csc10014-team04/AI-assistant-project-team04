Bản chạy được trên máy QA:
Python: Cài đặt python phiên bản 3.12 hoặc 3.13 tại trang chính thức python.org.
Môi trường ảo .venv: chạy lệnh trên command prompt: 
	python -m venv .venv
Kích hoạt môi trường ảo: .venv\Scripts\activate
Cài đặt các thư viện cần thiết: Kivy 2.3.1, KivyMD 2.0.0:
Chạy lệnh pip install -r requirements.txt tại thư mục ứng dụng (cụ thể hiện tại là AI-assistant-project-team04)
Đặt địa chỉ:
Cách đặt địa chỉ backend (ASSISTANT_API_URL): Trên máy QA đang chạy backend, mở Command Prompt và gõ lệnh: 
set ASSISTANT_API_URL=http://<Địa_chỉ_IP_mới>:8080 
Bỏ địa chỉ mặc định cứng 26.211.52.63: Tìm file api_client.py trong thư mục sourceCode/FE, mở file trên trình chỉnh sửa và tìm giá trị self.base_url trong hàm __init__, địa chỉ 26.211.52.63 hoặc các địa chỉ cứng bị sai khác sẽ khai báo tại đây, có thể xóa hoặc sửa đổi lại thành địa chỉ local 127.0.0.1:8080.
Danh sách màn hình, cửa sổ, nhãn nút chính xác và hành vi mong đợi:
Màn hình đăng nhập/ đăng ký (Auth screen):
Log in: Hành động thực hiện khi người dùng nhấn nút đăng nhập, hệ thống sẽ gọi phương thức để kiểm tra username và password. Nếu trùng khớp với dữ liệu, chuyển hướng người dùng đến Calendar home screen. Nếu không, thông báo sai thông tin đăng nhập.
Google account (log in): Chuyển hướng đến trang đăng nhập của google, sau khi đăng nhập vào google thành công sẽ tự động chuyển hướng người dùng đến Calendar home screen. (Chưa có)
Github account (log in): Chuyển hướng đến trang đăng nhập của github, sau khi đăng nhập vào github thành công sẽ tự động chuyển hướng người dùng đến Calendar home screen. (Chưa có)
Switch to register: Chuyển hướng người dùng đến trang đăng ký.
Create account: Kiểm tra các thông tin đăng ký gồm username, display name và password. Nếu hợp lệ, lưu thông tin và chuyển hướng người dùng về trang đăng nhập.
Google account (register): Chuyển hướng đến trang đăng nhập của google, sau khi đăng nhập vào google thành công sẽ tự động chuyển hướng người dùng đến trang nhập username.  (Chưa có)
Github account (register): Chuyển hướng đến trang đăng nhập của github, sau khi đăng nhập vào github thành công sẽ tự động chuyển hướng người dùng đến trang nhập username.  (Chưa có)
Username confirm: Người dùng nhập username và được chuyển hướng đến Calendar home screen.

Màn hình lịch chính (Calendar home screen):
Date month and year: Nút tiêu đề hiển thị tháng năm, khi bấm vào sẽ hiển thị một cửa sổ chọn tháng. Chọn một tháng để được chuyển hướng đến khung lịch đó.
Menu button: Nếu đang ở chế độ xem lịch theo tháng, nút này sẽ mở ra một menu ở bên trái màn hình.
Add button: Icon là dấu cộng, bấm vào sẽ hiển thị hai nút Add event và Import scheduling.
Add event: Mở cửa sổ Add event modal.
Import Scheduling: mở cửa sổ Import scheduling modal ở bước 1.
Day node: Là số của ngày trong tháng. Khi bấm vào một ô ngày hợp lệ, màn hình sẽ chuyển sang Chế độ xem lịch theo tuần của tuần chứa ngày đó với hiệu ứng trượt sang trái, đồng thời nút Menu góc trái sẽ đổi thành nút Back. Ô ngày có viền màu đánh dấu hôm nay, các vạch màu hiển thị loại sự kiện bên dưới và có dấu "!" màu đỏ góc trên nếu có sự kiện quan trọng. 
Event Block: Tên sự kiện, có thể kèm theo địa điểm ở dòng trên nếu có. Có dấu "!" góc trên bên phải nếu sự kiện đánh dấu là quan trọng. Khi bấm vào khối sự kiện, sẽ mở cửa sổ Event modal. 
Deadline Banner: Nếu chỉ có 1 hạn chót: hiển thị tên sự kiện (rút gọn nếu quá dài). Nếu có từ 2 hạn chót trở lên: hiển thị "DLS:{số lượng}". Có dấu "!" màu đỏ nếu chứa hạn chót quan trọng. Nếu chỉ có 1 hạn chót, bấm vào sẽ mở trực tiếp Event detail modal. Nếu có nhiều hạn chót, bấm vào sẽ mở cửa sổ danh sách các hạn chót. Chọn một hạn chót để mở Event detail modal của hạn chót đó.
Bottom Navigation: Gồm 3 nút Calendar, Search, AI assistant. Khi bấm sẽ chuyển hướng đến màn hình Calendar home screen, Search screen, AI assistant screen theo thứ tự.
Cửa sổ thêm lịch trình (Import scheduling modal):
Choose file from Device: Chọn file lịch trình để thêm vào ứng dụng. Chỉ hiển thị và hỗ trợ các loại file .csv, .txt, .md, .png, .jpg, .jpeg.
Analyze: Gửi tệp lên hệ thống để phân tích. Khi đang phân tích, nút Analyze không thể bấm. Sau khi hoàn tất sẽ chuyển sang bước 2 và hiển thị các sự kiện mà hệ thống phân tích được
Continue to conflict check: Ở bước 2, sau khi hoàn thành liệt kê các sự kiện, bấm nút này để phân tích các sự kiện hợp lệ để tránh xung đột thời gian. Chuyển qua bước 3 và hiển thị sự kiện hợp lệ và sự kiện bị xung đột.
Save non-conflicting: Thực hiện lưu nhưng sự kiện an toàn vào lịch.
Save all: Lưu toàn bộ danh sách, ghi đè/chấp nhận cả những lịch đang bị xung đột.
Cancel: đóng cửa sổ. 
Cửa sổ chi tiết sự kiện (Event detail modal): 
Edit time: bật một cửa sổ để chỉnh sửa thời gian. Nếu người dùng bấm Save, lưu thời gian hiện tại người dùng nhập. Nếu người bấm Cancel, chỉ đóng cửa sổ.
Important: Bật/tắt đánh dấu quan trọng cho sự kiện. Khi tắt cửa sổ thì thay đổi phải được cập nhật ở Calendar home screen và trong database.
Remind: Chỉnh thời gian nhắc nhở trước thời điểm của sự kiện quan trọng. Các thay đổi phải được lưu lại vào database.
Delete event: Xóa sự kiện được chọn và tắt cửa sổ. Sự kiện phải biến mất khỏi Calendar home screen và database.
Close: tắt cửa sổ.
Cửa sổ thêm sự kiện (Add event modal):
Save: Lưu lại thông tin người dùng nhập vào database và tắt cửa sổ. Sự kiện được thêm vào sẽ xuất hiện trên màn hình Calendar home screen. tại đúng thời điểm mà người dùng đã nhập.
Cancel: tắt cửa sổ.

Màn hình tìm kiếm (Search screen): 
Search button: Tìm kiếm sự kiện theo yêu cầu của người dùng. Khi bấm vào sẽ hiện ra một list sự kiện khớp với yêu cầu (không quá 30 yêu cầu trong một list).
Filter Button: Mở cửa sổ Filter modal.
My Scheduling: Chuyển qua chế độ tìm kiếm event.
Academic Q&A: Chuyển qua chế độ tìm kiếm Q&A.
Event Block: Tên sự kiện, có thể kèm theo địa điểm ở dòng trên nếu có. Có dấu "!" ở đầu bên trái nếu sự kiện đánh dấu là quan trọng. Khi bấm vào khối sự kiện, sẽ mở cửa sổ Event modal. 
Bottom Navigation: Gồm 3 nút Calendar, Search, AI assistant. Khi bấm sẽ chuyển hướng đến màn hình Calendar home screen, Search screen, AI assistant screen theo thứ tự.
Cửa sổ chức năng lọc loại sự kiện (Filter modal):
Apply and Search: Áp dụng các mục loại sự kiện và đánh dấu quan trọng và tắt cửa sổ. Khi kích hoạt, Search screen sẽ hiển thị các loại sự kiện được tích vào, nếu tích vào đánh dấu quan trọng thì sẽ chỉ hiển sự kiện được đánh dấu quan trọng.

Màn hình trợ lý AI (AI assistant screen):
Send Message: Biểu tượng gửi tin nhắn, người dùng bấm vào sẽ gửi yêu cầu xếp lịch của người dùng đến AI. AI sẽ phân tích yêu cầu và phản hồi lại bằng một đề xuất sắp xếp lịch trình cùng với 3 nút: Confirm, Reject, Rescheduling. Nếu AI gặp trục trặc, ngay lập tức hiển thị Manual fallback modal. 
Confirm: Chấp nhận đề xuất của AI, thêm sự kiện vào lịch trình. Calendar home screen cập nhật lịch trình mới. Kết thúc phiên đề xuất đó.
Reject: Từ chối yêu cầu của AI, kết thúc phiên đề xuất đó.
Rescheduling: Tạo một banner nhắc nhở trên khung chat, yêu cầu tiếp theo của người dùng sẽ thay đổi đề xuất này của AI.
Bottom Navigation: Gồm 3 nút Calendar, Search, AI assistant. Khi bấm sẽ chuyển hướng đến màn hình Calendar home screen, Search screen, AI assistant screen theo thứ tự.
Chọn giờ thủ công (Manual Fallback modal):
Confirm: Xác nhận chọn một lịch trình được hệ thống đề xuất và thêm và lịch trình. Calendar home screen cập nhật lịch trình mới.
Cancel: Đóng cửa sổ.
Thông báo nhắc nhở (Notification): 
Khi thời gian thông báo đến, hiển thị trong cửa sổ: Địa điểm, tên sự kiện và thời gian.
Có hai nút bấm bên dưới: 
Xác nhận (Confirm): Đóng thông báo. Hệ thống sẽ báo về máy chủ là thông báo đã được gửi.
Báo lại (Snooze): Thông báo sẽ tạm ẩn đi và hẹn giờ để nhắc lại sau.
Tự động: Hộp thoại sẽ đếm ngược 60 giây. Nếu không bấm gì sau 60 giây, hệ thống sẽ tự động chọn "Báo lại". 
Báo lại (Snooze): Mặc định, thời gian báo lại là sau 5 phút, nhưng có thể thay đổi thiết lập này không dưới 1 phút. 
Luồng người dùng:
Luồng Đăng nhập / Đăng ký (Auth Flow):
Người dùng mở app vào Auth screen.
Đăng nhập:
Nhập tài khoản/mật khẩu -> Nhấn Log in -> Hợp lệ chuyển sang Calendar home, sai báo lỗi.
Chọn Google/Github (Tương lai) -> Đăng nhập thành công -> Calendar home.
Đăng ký:
Từ Auth screen bấm Switch to register -> Màn hình đăng ký.
Nhập form -> Bấm Create account -> Hợp lệ lưu DB -> Quay về form Log in.
Chọn Google/Github -> Đăng nhập bên thứ 3 thành công -> Chuyển đến màn Username confirm -> Nhập Username -> Calendar home.
Luồng Lịch chính (Calendar Home Flow): Người dùng đang ở Calendar home screen, có thể thao tác:
Điều hướng thời gian: Bấm "Date month and year" -> Chọn tháng -> Chuyển lịch sang tháng đó. Bấm "Day node" -> Chuyển sang màn hình xem Tuần (có hiệu ứng trượt, menu trái thành nút Back).
Mở Menu: Bấm "Menu button" (ở chế độ tháng) -> Mở menu trái.
Chuyển Tab (Bottom Navigation): Nhấn Search hoặc AI Assistant để đổi màn hình.
Xem sự kiện:
Bấm vào khối "Event Block" hoặc "Deadline Banner" (nếu có 1 deadline) -> Mở Event Detail Modal.
Bấm "Deadline Banner" (nếu >=2) -> Mở cửa sổ danh sách -> Chọn 1 sự kiện -> Mở Event Detail Modal.
Thêm lịch trình (Add Button +):
Nhánh 1 (Add event): Mở Add Event Modal -> Nhập thông tin -> Bấm Save (Lưu DB/UI) hoặc Cancel.
Nhánh 2 (Import Scheduling):
Bước 1: Mở Import Modal, chọn file (.csv, txt...) -> Bấm "Analyze" (Nút bị khóa khi đang chạy).
Bước 2: Hiển thị sự kiện phân tích được -> Bấm "Continue to conflict check".
Bước 3: Hiện sự kiện hợp lệ & xung đột. Nhấn "Save non-conflicting" hoặc "Save all" để lưu, nhấn Cancel để đóng.
Luồng Chi tiết Sự kiện (Event Detail Flow):
Khi Event detail modal đang mở:
Sửa giờ (Edit time): Mở cửa sổ sửa -> Bấm Save để lưu thay đổi giờ, Cancel để đóng cửa sổ sửa.
Đánh dấu (Important) & Nhắc nhở (Remind): Thao tác Bật/Tắt quan trọng hoặc chỉnh thời gian Remind -> Hệ thống tự động cập nhật UI và lưu Database.
Xóa (Delete event): Bấm xóa -> Sự kiện biến mất khỏi DB và giao diện -> Đóng cửa sổ.
Bấm Close -> Đóng cửa sổ.
Luồng Tìm kiếm (Search Flow):
Người dùng bấm Tab Search -> Vào Search screen.
Chọn chế độ: My Scheduling hoặc Academic Q&A.
(Tùy chọn) Bấm Filter Button -> Mở Filter modal -> Chọn loại sự kiện/Đánh dấu quan trọng -> Bấm "Apply and Search" -> Quay lại Search screen.
Nhập từ khóa -> Bấm Search button -> Hiển thị danh sách kết quả (tối đa 30).
Bấm vào một Event Block trong danh sách -> Mở Event detail modal.
Luồng Trợ lý AI (AI Assistant Flow):
Người dùng bấm Tab AI -> Vào AI assistant screen.
Nhập text -> Bấm Send Message.
Nhánh AI phản hồi thành công:
Hiển thị đề xuất lịch trình.
Bấm Confirm: Chấp nhận -> Lưu vào lịch trình (UI/DB).
Bấm Reject: Bỏ qua -> Đóng phiên.
Bấm Rescheduling: Hiện banner nhắc nhở. Tin nhắn chat tiếp theo người dùng gõ sẽ được hiểu là yêu cầu sửa lại đề xuất này.
Nhánh AI bị trục trặc:
Hiển thị Manual fallback modal.
Bấm Confirm: Chọn 1 lịch hệ thống đề xuất -> Thêm vào lịch.
Bấm Cancel: Đóng modal, quay lại khung chat.
Luồng Thông báo (Notification Flow - Chạy ngầm):
Tới giờ hẹn -> Hiện popup thông báo (Địa điểm, Tên, Thời gian).
Hành động 1: Nhấn Confirm -> Đóng thông báo, gửi phản hồi xác nhận cho Server.
Hành động 2: Nhấn Snooze -> Ẩn thông báo, set lịch nhắc lại (mặc định sau 5 phút).
Không làm gì: Đếm ngược 60 giây hết hạn -> Hệ thống tự động kích hoạt lệnh Snooze.

Ma trận thiết bị:
Window: Đã chạy thử
Android APK: Chưa chạy thử. Sử dụng buildozer để đóng gói thành APK để kiểm tra trên điện thoại.
Cấu hình Buildozer: Di chuyển vào thư mục sourceCode/FE và chạy lệnh: buildozer init Mở file buildozer.spec vừa được tạo, tìm dòng requirements = python3, kivy và thêm các thư viện FE vào (ví dụ: requirements = python3, kivy==2.3.1, kivymd==2.0.0, requests, plyer). Đảm bảo cấp các quyền cần thiết (Internet, Camera...) trong phần android.permissions. 
Log của app: 
Vị trí: Path(__file__).resolve().parent / "fe_http_debug.log".
Trong đó: Path(__file__).resolve().parent là thư mục chứa file thực thi (cụ thể: file thực thi là main.py, thư mục chứa file thực thi là FE)
Cách đọc Request ID và Error Origin: Khi có lỗi HTTP (4xx, 5xx) hoặc lỗi kết nối mạng, ứng dụng sẽ ghi một khối chẩn đoán (diagnostic block) vào file log:
Request ID: Nằm ở dòng - Request ID (BE): Giá trị này được trích xuất trực tiếp từ header X-Request-ID do Backend trả về. Nếu Backend không gửi header này, hệ thống sẽ hiển thị là "N/A". 
Error Origin: Nằm ở dòng - Error Origin :. Ứng dụng sẽ ưu tiên lấy giá trị từ header X-Error-Source của Backend, nếu không có, nó sẽ tự suy luận nguyên nhân gốc rễ dựa trên mã lỗi HTTP:
FASTAPI_ROUTER_URL_NOT_FOUND (404): Frontend gọi sai đường dẫn URL.
PYDANTIC_VALIDATION_ERROR (422): Dữ liệu Frontend gửi lên không khớp với schema của Backend.
BE_AUTH_GUARD (401, 403): Lỗi xác thực hoặc token đã hết hạn.
BE_UNHANDLED_EXCEPTION (5xx): Lỗi nội bộ trong code Backend hoặc lỗi kết nối Database.
BE_BUSINESS_RULE_REJECTION: Backend từ chối request dựa trên quy tắc nghiệp vụ.
NETWORK / CONNECTION: Request bị timeout hoặc hoàn toàn không chạm tới được máy chủ Backend.
Danh sách hạn chế đã biết:
Nhắc nhở chỉ chạy khi app mở.
Chưa có chức năng đặt lại mật khẩu.











Xong
Chuẩn bị
Vì sao QA cần
[]
Bản chạy được trên máy QA:
Hướng dẫn cài đặt (Python 3.12/3.13; .venv, pip install -r requirements.txt)
Python 3.14 không cài được Kivy
[]
Cách đặt địa chỉ backend (ASSISTANT_API_URL) và bỏ địa chỉ mặc định cứng 26.211.52.63
Đã gây nhầm: app gọi sang host cũ
[]
Danh sách màn hình và luồng người dùng: Đăng ký/đăng nhập; import 3 bước; thêm/sửa xóa sự kiện; chat AI (Xác nhận/Từ chối/Suy nghĩ thêm); chọn giờ thủ công;  tìm kiếm; nhắc nhở
Dùng làm kịch bản test giao diện
[]
Ma trận thiết bị: Window (đã chạy), Android APK (Chưa kiểm thử, có buildozer.spec)
Báo cáo cần nói rõ đã/chưa test trên thiết bị nào
[]
Log của app: vị trí fe_https_debug_log, cách đọc request ID và error Origin
QA đính kèm vào báo cáo lỗi
[]
Nhãn nút chính xác và hành vi mong đợi (Lấy từ giao diện)
QA viết bước test khớp với giao diện thật
[]
Danh sách hạn chế đã biết: nhắc nhở chỉ chạy khi app mở, chưa có đặt lại mật khẩu
Tránh báo trùng




