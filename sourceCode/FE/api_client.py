import json
from kivy.network.urlrequest import UrlRequest
from kivy.storage.jsonstore import JsonStore

"""
FILE: api_client.py
CHỨC NĂNG: 
- Là cầu nối duy nhất giữa Frontend (Kivy) và Backend (FastAPI/Django/...).
- Quản lý phiên đăng nhập (Session) bằng cách lưu trữ Access Token (JWT) vào bộ nhớ thiết bị.
- Cung cấp các hàm gọi API chuẩn hóa, tự động gắn Header xác thực.

CÁCH HOẠT ĐỘNG:
- Dùng Kivy `UrlRequest` để gọi HTTP bất đồng bộ (không làm đơ giao diện).
- Lưu token vào file `auth_session.json` qua Kivy `JsonStore`.
- Lớp APIClient được khởi tạo thành một instance duy nhất (Singleton) ở cuối file tên là `api` để các file giao diện có thể import và dùng chung.
"""




class APIClient:
    def __init__(self):
        # [CẦN BACKEND XỬ LÝ] 
        # Đổi URL này thành IP hoặc Domain thực tế của máy chủ khi đưa vào chạy mạng LAN hoặc Internet.
        self.base_url = "http://127.0.0.1:8000"
        self.store = JsonStore("auth_session.json")

        # Phục hồi token từ bộ nhớ cục bộ nếu có
        self.access_token = None
        self.user_id = None
        self.display_name = None
        self._load_session()
    
    def _load_session(self):
        """Khôi phục token từ lần đăng nhập trước (nếu người dùng chưa đăng xuất)"""
        if self.store.exists("auth"):
            data = self.store.get("auth")
            self.access_token = data.get("access_token")
            self.user_id = data.get("user_id")
            self.display_name = data.get("display_name")

    def save_session(self, token, user_id, display_name):
        """Lưu token sau khi đăng nhập thành công"""
        self.access_token = token
        self.user_id = user_id
        self.display_name = display_name
        self.store.put("auth", access_token=token, user_id=user_id, display_name=display_name)

    def clear_session(self):
        """Xóa token khi người dùng đăng xuất"""
        self.access_token = None
        self.user_id = None
        self.display_name = None
        if self.store.exists("auth"):
            self.store.delete("auth")

    def get_headers(self):
        """Tự động gắn thẻ Authorization Bearer Token vào mọi Request cần xác thực"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _request(self, endpoint, method="GET", payload=None, on_success=None, on_failure=None, on_error=None):
        """Hàm dùng chung để gửi UrlRequest"""
        """Hàm cốt lõi xử lý gửi HTTP Request"""
        url = f"{self.base_url}{endpoint}"
        req_body = json.dumps(payload) if payload else None
        
        # Chặn callback mặc định nếu không truyền vào để tránh lỗi NoneType
        def default_cb(req, result): pass
        
        return UrlRequest(
            url,
            req_body=req_body,
            req_headers=self.get_headers(),
            method=method,
            on_success=on_success or default_cb,
            on_failure=on_failure or default_cb,
            on_error=on_error or default_cb
        )

    # =========================================================================
    # 1. AUTHENTICATION (Đăng nhập / Đăng ký)
    # =========================================================================
    def register(self, username, display_name, password, email, on_success, on_failure, on_error):
        # [CẦN BACKEND XỬ LÝ]
        # Hiện tại biến email được truyền vào là một chuỗi rỗng "" từ giao diện do đã bị xóa ô nhập.
        # Backend cần chấp nhận email rỗng (Nullable) hoặc Database không bắt buộc trường Email.
        payload = {
            "username": username,
            "password": password,
            "display_name": display_name,
            "email": email
        }
        self._request("/api/v1/auth/register", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def login(self, username, password, on_success, on_failure, on_error):
        payload = {"username": username, "password": password}
        self._request("/api/v1/auth/login", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)
        
        # [CẦN BACKEND XỬ LÝ] - THIẾU HÀM GỌI OAUTH
        # Backend cần cung cấp API để:
        # 1. Nhận Access Token từ Google/Github sau khi xác thực thành công.
        # 2. API liên kết Username cho tài khoản OAuth mới tạo.
        # Cần định nghĩa thêm: def oauth_login(...) và def confirm_oauth_username(...) tại đây.



    # =========================================================================
    # 2. INGESTION (Xử lý ảnh/văn bản sang lịch)
    # =========================================================================
    def parse_preview(self, text_data, on_success, on_failure, on_error):
        payload = {"text": text_data}
        self._request("/api/v1/ingestion/parse-preview", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def resolve_preview(self, preview_id, modifications, on_success, on_failure, on_error):
        payload = {"modifications": modifications}
        self._request(f"/api/v1/ingestion/{preview_id}/resolve-preview", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def check_conflicts(self, events, on_success, on_failure, on_error):
        payload = {"events": events}
        self._request("/api/v1/ingestion/check-conflicts", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def commit_events(self, events, on_success, on_failure, on_error):
        payload = {"events": events}
        self._request("/api/v1/ingestion/commit", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    # =========================================================================
    # 3. SEARCH & PROPOSALS (Tìm kiếm & Xử lý đề xuất)
    # =========================================================================
    def search_events(self, query, start_date, end_date, on_success, on_failure, on_error):
        # GET request với query params
        endpoint = f"/api/v1/search/events?q={query}&start={start_date}&end={end_date}"
        self._request(endpoint, method="GET", on_success=on_success, on_failure=on_failure, on_error=on_error)

    def get_free_slots(self, date_str, duration_minutes, on_success, on_failure, on_error):
        endpoint = f"/api/v1/search/free-slots?date={date_str}&duration={duration_minutes}"
        self._request(endpoint, method="GET", on_success=on_success, on_failure=on_failure, on_error=on_error)

# Khởi tạo instance duy nhất để dùng chung cho toàn bộ app
api = APIClient()