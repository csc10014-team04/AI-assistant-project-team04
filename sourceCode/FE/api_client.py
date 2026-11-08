import os   # at the top of the file
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
    # Hằng số mặc định
    BASE_URL = "http://26.211.52.63:8080" 

    def __init__(self):
        # Thuộc tính instance giúp truy cập qua self.base_url
        # in APIClient.__init__ replace the hard-coded address (8000 is the AI engine, the backend is 8080):
        self.base_url = os.getenv("ASSISTANT_API_URL", "http://127.0.0.1:8080").rstrip("/")
        # self.base_url = self.BASE_URL
        self.store = JsonStore("auth_session.json")

        # Phục hồi token từ bộ nhớ cục bộ nếu có
        self.access_token = None
        self.user_id = None
        self.display_name = None
        self._load_session()
    
    def _load_session(self):
        """Khôi phục token từ lần đăng nhập trước"""
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
        """Tự động gắn thẻ Authorization Bearer Token"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _request(self, endpoint, method="GET", payload=None, on_success=None, on_failure=None, on_error=None):
        """Hàm cốt lõi xử lý gửi HTTP Request"""
        url = f"{self.base_url}{endpoint}"
        req_body = json.dumps(payload) if payload else None
        
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
    # 1. AUTHENTICATION
    # =========================================================================
    def register(self, username, display_name, password, email, on_success, on_failure, on_error):
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

    def oauth_start(self, provider, redirect_uri, on_success, on_failure, on_error):
        """provider = "google" | "github". Success body: {"authorize_url", "state"}; open the URL in a browser."""
        from urllib.parse import quote
        self._request(f"/api/v1/auth/oauth/{provider}/start?redirect_uri={quote(redirect_uri, safe='')}",
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def oauth_exchange(self, provider, code, redirect_uri, state, on_success, on_failure, on_error):
        """Send the code the provider gave back; success body has access_token / user_id / display_name."""
        payload = {"code": code, "redirect_uri": redirect_uri, "state": state}
        self._request(f"/api/v1/auth/oauth/{provider}/exchange", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    # =========================================================================
    # 2. INGESTION
    # =========================================================================
    def parse_preview(self, text_data, on_success, on_failure, on_error):
        payload = {"text": text_data}
        self._request("/api/v1/ingestion/parse-preview", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def commit_events(self, events, on_success, on_failure, on_error):
        payload = {"events": events}
        self._request("/api/v1/ingestion/commit", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    # =========================================================================
    # 3. SEARCH & PROPOSALS
    # =========================================================================
    def search_events(self, query, start_date, end_date, on_success, on_failure, on_error):
        from urllib.parse import quote
        endpoint = f"/api/v1/search/events?q={quote(query)}&start_from={start_date}&end_until={end_date}"
        self._request(endpoint, method="GET", on_success=on_success, on_failure=on_failure, on_error=on_error)


    # new method, next to the other calls:
    def understand(self, prompt, on_success, on_failure, on_error, reschedule_proposal_id=None):
        payload = {"prompt": prompt, "reschedule_proposal_id": reschedule_proposal_id}
        self._request("/api/v1/assistant/understand", method="POST", payload=payload,
                on_success=on_success, on_failure=on_failure, on_error=on_error)
    def get_free_slots(self, window_start, window_end, duration_minutes, on_success, on_failure, on_error,
                   respect_preferences=True):
        payload = {"window_start": window_start, "window_end": window_end,
               "duration_minutes": duration_minutes, "respect_preferences": respect_preferences}
        self._request("/api/v1/search/free-slots", method="POST", payload=payload,
                  on_success=on_success, on_failure=on_failure, on_error=on_error)

    # =========================================================================
    # 4. PROPOSAL LIFECYCLE (Accept / Reject buttons) AND MANUAL PICKER
    # =========================================================================
    def confirm_proposal(self, proposal_id, on_success, on_failure, on_error):
        self._request(f"/api/v1/proposals/{proposal_id}/confirm", method="POST",
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def reject_proposal(self, proposal_id, on_success, on_failure, on_error):
        self._request(f"/api/v1/proposals/{proposal_id}/reject", method="POST",
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def create_manual_event(self, title, duration_minutes, slot_start, slot_end, on_success, on_failure, on_error):
        payload = {"title": title, "duration_minutes": duration_minutes,
                   "slot_start": slot_start, "slot_end": slot_end}
        self._request("/api/v1/proposals/manual", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)


# Khởi tạo instance duy nhất
api = APIClient()