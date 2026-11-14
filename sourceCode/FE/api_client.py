import os   # at the top of the file
import json
from datetime import datetime, timezone
from pathlib import Path
from kivy.network.urlrequest import UrlRequest
from kivy.storage.jsonstore import JsonStore

from fallback import AI_TIMEOUT_SECONDS

FE_DEBUG_LOG_PATH = Path(__file__).resolve().parent / "fe_http_debug.log"  # local diagnostic log on user/tester machine


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
        self.store = JsonStore("auth_session.json")
        # order: environment variable (desktop) > address saved in the app (phones have no env vars) > localhost
        saved = self.store.get("settings").get("base_url") if self.store.exists("settings") else None
        self.base_url = (os.getenv("ASSISTANT_API_URL") or saved or "http://26.211.52.63:8080").rstrip("/")

        # Phục hồi token từ bộ nhớ cục bộ nếu có
        self.access_token = None
        self.user_id = None
        self.display_name = None
        self.debug_http = os.getenv("FE_DEBUG_HTTP", "1") != "0"  # print detailed http failures to console by default
        self._load_session()
    
    def set_base_url(self, url):
        """remember the backend address on the device (settings screen / first-run prompt)."""
        self.base_url = url.strip().rstrip("/")
        self.store.put("settings", base_url=self.base_url)

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

    @staticmethod
    def _header_ci(headers, target_name):
        """case-insensitive lookup on UrlRequest response headers."""
        if not isinstance(headers, dict):
            return None
        target_lower = target_name.lower()
        for key, value in headers.items():
            if str(key).lower() == target_lower:
                return value
        return None

    @staticmethod
    def _infer_http_error_source(status_code, result, header_source):
        """use server X-Error-Source header when present, else classify locally."""
        if header_source:
            return header_source
        if status_code == 404 and isinstance(result, dict) and result.get("detail") == "Not Found":
            return "FASTAPI_ROUTER_URL_NOT_FOUND: FE goi sai duong dan URL"
        if status_code == 422:
            return "PYDANTIC_VALIDATION_ERROR: Du lieu FE gui len chua khop schema BE"
        if status_code in (401, 403):
            return "BE_AUTH_GUARD: Loi xac thuc hoac token het han"
        if status_code is not None and status_code >= 500:
            return "BE_UNHANDLED_EXCEPTION: Loi ben trong code BE hoac ket noi DB"
        return "BE_BUSINESS_RULE_REJECTION: BE tu choi theo quy tac nghiep vu"

    @staticmethod
    def _safe_payload_preview(payload):
        """serialize payload for debug printing while redacting password fields."""
        if payload is None:
            return "None"
        if isinstance(payload, dict) and "password" in payload:
            redacted = dict(payload)
            redacted["password"] = "***"
            return json.dumps(redacted, ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)

    def _emit_diagnostic_block(self, block):
        """print diagnostic block to console and append it to the local log file."""
        print(block, flush=True)
        try:
            with open(FE_DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
                log_file.write(block + "\n")
        except Exception:
            pass

    def _print_http_failure(
        self,
        method,
        url,
        payload=None,
        req=None,
        result=None,
        status_code=None,
        resp_headers=None,
        raw_body=None,
    ):
        """print and persist diagnostic box when backend returns 4xx or 5xx."""
        if not self.debug_http:
            return
        if resp_headers is None and req is not None:
            resp_headers = getattr(req, "resp_headers", None)
        if status_code is None and req is not None:
            status_code = getattr(req, "resp_status", None)
        response_data = result if result is not None else raw_body
        req_id = self._header_ci(resp_headers, "X-Request-ID") or "N/A"
        elapsed_ms = self._header_ci(resp_headers, "X-Process-Time-Ms") or "N/A"
        hdr_src = self._header_ci(resp_headers, "X-Error-Source")
        source_label = self._infer_http_error_source(status_code, response_data, hdr_src)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        block = (
            "\n" + "=" * 70 + "\n"
            f"[FE-BE HTTP FAILURE] {method} {url} -> HTTP {status_code}\n"
            f"- Timestamp (UTC) : {timestamp}\n"
            f"- Request         : {method} {url}\n"
            f"- HTTP Status     : {status_code}\n"
            f"- Request ID (BE) : {req_id}\n"
            f"- Elapsed (BE ms) : {elapsed_ms}\n"
            f"- Error Origin    : {source_label}\n"
            f"- Sent Payload    : {self._safe_payload_preview(payload)}\n"
            f"- BE Response Body: {response_data}\n"
            f"- Local Log File  : {FE_DEBUG_LOG_PATH}\n"
            f"- Debug Endpoint  : {self.base_url}/api/v1/debug/logs\n"
            + "=" * 70
        )
        self._emit_diagnostic_block(block)

    def _print_network_error(self, method, url, payload=None, error=None, exc=None):
        """print and persist diagnostic box when client cannot reach backend or times out."""
        if not self.debug_http:
            return
        err_obj = exc if exc is not None else error
        exc_type = type(err_obj).__name__ if err_obj is not None else "UnknownError"
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        block = (
            "\n" + "=" * 70 + "\n"
            f"[FE-BE NETWORK ERROR] {method} {url}\n"
            f"- Timestamp (UTC) : {timestamp}\n"
            f"- Request         : {method} {url}\n"
            f"- Exception Type  : {exc_type}\n"
            "- Error Origin    : NETWORK / CONNECTION (request did not reach BE server or timed out)\n"
            f"- Error Details   : {err_obj}\n"
            f"- Sent Payload    : {self._safe_payload_preview(payload)}\n"
            f"- Local Log File  : {FE_DEBUG_LOG_PATH}\n"
            f"- Debug Endpoint  : {self.base_url}/api/v1/debug/logs\n"
            + "=" * 70
        )
        self._emit_diagnostic_block(block)

    def _request(self, endpoint, method="GET", payload=None, on_success=None, on_failure=None, on_error=None, timeout=None):
        """Hàm cốt lõi xử lý gửi HTTP Request"""
        url = f"{self.base_url}{endpoint}"
        req_body = json.dumps(payload) if payload is not None else None

        def default_cb(req, result):
            pass

        def wrapped_failure(req, result):
            self._print_http_failure(method, url, payload, req, result)
            if on_failure:
                on_failure(req, result)

        def wrapped_error(req, error):
            self._print_network_error(method, url, payload, error)
            if on_error:
                on_error(req, error)

        return UrlRequest(
            url,
            req_body=req_body,
            req_headers=self.get_headers(),
            method=method,
            on_success=on_success or default_cb,
            on_failure=wrapped_failure,
            on_error=wrapped_error,
            timeout=timeout,
        )

    def get_debug_logs(self, on_success, on_failure=None, on_error=None, limit=30):
        """fetch recent BE HTTP errors and AI errors for self-service debugging."""
        self._request(
            f"/api/v1/debug/logs?limit={int(limit)}",
            method="GET",
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
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
    def upload_timetable_file(self, file_path, on_success=None, on_failure=None, on_error=None):
        """Upload a timetable file (.csv, .txt, .md, .png, .jpg, .jpeg, .pdf) asynchronously via multipart/form-data."""
        import os
        import threading
        import requests
        from kivy.clock import Clock

        def _worker():
            url = f"{self.base_url}/api/v1/ingestion/parse-preview"
            filename = os.path.basename(file_path)
            payload_info = {"filename": filename}
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"

                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                ext = os.path.splitext(filename)[1].lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".csv": "text/csv",
                    ".txt": "text/plain",
                    ".md": "text/markdown",
                    ".pdf": "application/pdf",
                }
                mime_type = mime_map.get(ext, "application/octet-stream")

                files = {"file": (filename, file_bytes, mime_type)}
                resp = requests.post(url, headers=headers, files=files, timeout=(10, 30))
                try:
                    data = resp.json()
                except Exception:
                    data = {"detail": resp.text}

                if 200 <= resp.status_code < 300:
                    if on_success:
                        Clock.schedule_once(lambda dt: on_success(None, data), 0)
                else:
                    self._print_http_failure(
                        method="POST",
                        url=url,
                        payload=payload_info,
                        result=data,
                        status_code=resp.status_code,
                        resp_headers=dict(resp.headers),
                        raw_body=resp.text,
                    )
                    if on_failure:
                        Clock.schedule_once(lambda dt: on_failure(None, data), 0)
            except requests.exceptions.Timeout as e:
                self._print_network_error(method="POST", url=url, payload=payload_info, exc=e)
                if on_error:
                    Clock.schedule_once(lambda dt: on_error(None, "Quá thời gian kết nối tới máy chủ (Timeout 30s)"), 0)
            except requests.exceptions.ConnectionError as e:
                self._print_network_error(method="POST", url=url, payload=payload_info, exc=e)
                if on_error:
                    Clock.schedule_once(lambda dt: on_error(None, "Không thể kết nối tới máy chủ (kiểm tra mạng hoặc VPN)"), 0)
            except Exception as e:
                self._print_network_error(method="POST", url=url, payload=payload_info, exc=e)
                if on_error:
                    Clock.schedule_once(lambda dt: on_error(None, str(e)), 0)

        threading.Thread(target=_worker, daemon=True).start()

    def parse_preview(self, text_data=None, file_path=None, on_success=None, on_failure=None, on_error=None):
        """Preview parsed timetable rows. Accepts either file_path or raw text_data."""
        if file_path:
            return self.upload_timetable_file(file_path, on_success, on_failure, on_error)

        import threading
        import requests
        from kivy.clock import Clock

        def _worker():
            url = f"{self.base_url}/api/v1/ingestion/parse-preview"
            raw_content = text_data or ""
            payload_info = {"raw_content": raw_content[:300]}
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"

                resp = requests.post(
                    url,
                    headers=headers,
                    data={"raw_content": raw_content},
                    timeout=30,
                )
                try:
                    data = resp.json()
                except Exception:
                    data = {"detail": resp.text}

                if 200 <= resp.status_code < 300:
                    if on_success:
                        Clock.schedule_once(lambda dt: on_success(None, data), 0)
                else:
                    self._print_http_failure(
                        method="POST",
                        url=url,
                        payload=payload_info,
                        result=data,
                        status_code=resp.status_code,
                        resp_headers=dict(resp.headers),
                        raw_body=resp.text,
                    )
                    if on_failure:
                        Clock.schedule_once(lambda dt: on_failure(None, data), 0)
            except Exception as e:
                self._print_network_error(method="POST", url=url, payload=payload_info, exc=e)
                if on_error:
                    Clock.schedule_once(lambda dt: on_error(None, str(e)), 0)

        threading.Thread(target=_worker, daemon=True).start()

    def resolve_preview(self, import_batch_id, valid_rows, corrected_rows, skipped_line_numbers, on_success=None, on_failure=None, on_error=None):
        """Send corrected rows and skipped lines to resolve preview into all_valid_rows."""
        payload = {
            "import_batch_id": import_batch_id,
            "valid_rows": valid_rows,
            "corrected_rows": corrected_rows,
            "skipped_line_numbers": skipped_line_numbers,
        }
        self._request(
            "/api/v1/ingestion/resolve-preview",
            method="POST",
            payload=payload,
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )

    def check_conflicts(self, incoming_rows, on_success=None, on_failure=None, on_error=None, replace_previous_imports=False):
        """Check conflicts for parsed timetable rows."""
        payload = {
            "incoming_rows": incoming_rows,
            "replace_previous_imports": replace_previous_imports,
        }
        self._request(
            "/api/v1/ingestion/check-conflicts",
            method="POST",
            payload=payload,
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )

    def commit_import(self, import_batch_id, resolved_rows, on_success=None, on_failure=None, on_error=None, replace_previous_imports=False):
        """Commit resolved timetable rows into MySQL."""
        payload = {
            "import_batch_id": import_batch_id,
            "resolved_rows": resolved_rows,
            "replace_previous_imports": replace_previous_imports,
        }
        self._request(
            "/api/v1/ingestion/commit",
            method="POST",
            payload=payload,
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )

    def commit_events(self, events=None, on_success=None, on_failure=None, on_error=None, import_batch_id=None):
        """Backward-compatibility wrapper."""
        batch_id = import_batch_id or ""
        resolved = events or []
        self.commit_import(
            import_batch_id=batch_id,
            resolved_rows=resolved,
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )

    # =========================================================================
    # 3. SEARCH & PROPOSALS
    # =========================================================================
    def list_events(self, start_from, end_until, on_success, on_failure, on_error, top_k=200):
        """all of the logged-in user's events between two ISO datetimes (empty query = no text filter)."""
        from urllib.parse import quote
        endpoint = (f"/api/v1/search/events?q=&top_k={int(top_k)}"
                    f"&start_from={quote(start_from, safe='')}&end_until={quote(end_until, safe='')}")
        self._request(endpoint, method="GET", on_success=on_success, on_failure=on_failure, on_error=on_error)

    def search_events(self, query, start_date, end_date, on_success, on_failure, on_error):
        from urllib.parse import quote
        endpoint = f"/api/v1/search/events?q={quote(query)}&start_from={start_date}&end_until={end_date}"
        self._request(endpoint, method="GET", on_success=on_success, on_failure=on_failure, on_error=on_error)

    def search_events_query(self, query_text, on_success, on_failure=None, on_error=None, top_k=50):
        """Schedule Search: Hybrid SQL + Vector search over user's events."""
        from urllib.parse import urlencode
        params = urlencode({"q": query_text, "top_k": top_k})
        self._request(
            f"/api/v1/search/events?{params}",
            method="GET",
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )

    def ask_academic_kb(self, query_text, on_success, on_failure=None, on_error=None, top_k=3):
        """Academic Knowledge Base RAG: Ask questions about courses, lecturers, requirements."""
        payload = {"query": query_text, "top_k": top_k}
        self._request(
            "/api/v1/search/academic/ask",
            method="POST",
            payload=payload,
            on_success=on_success,
            on_failure=on_failure,
            on_error=on_error,
        )


    # new method, next to the other calls:
    def understand(self, prompt, on_success, on_failure, on_error, reschedule_proposal_id=None):
        payload = {"prompt": prompt, "reschedule_proposal_id": reschedule_proposal_id}
        # strict client-side timeout (P1-9): on expiry on_error is called and the chat opens the manual picker
        self._request("/api/v1/assistant/understand", method="POST", payload=payload,
                on_success=on_success, on_failure=on_failure, on_error=on_error, timeout=AI_TIMEOUT_SECONDS)
    def get_free_slots(self, window_start, window_end, duration_minutes, on_success, on_failure, on_error,
                   respect_preferences=True):
        payload = {"window_start": window_start, "window_end": window_end,
               "duration_minutes": duration_minutes, "respect_preferences": respect_preferences}
        self._request("/api/v1/search/free-slots", method="POST", payload=payload,
                  on_success=on_success, on_failure=on_failure, on_error=on_error)

    def patch_event(self, event_id, payload, on_success=None, on_failure=None, on_error=None):
        """Update event details (start_time, end_time, is_important, title, room)."""
        self._request(f"/api/v1/events/{event_id}", method="PATCH", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def delete_event(self, event_id, on_success=None, on_failure=None, on_error=None):
        """Soft delete event."""
        self._request(f"/api/v1/events/{event_id}", method="DELETE",
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    def audit_reminder(self, event_id, offset_minutes=30, scheduled_on_device_at=None, on_success=None, on_failure=None, on_error=None):
        """Post reminder audit log to backend."""
        payload = {
            "offset_minutes": offset_minutes,
            "scheduled_on_device_at": scheduled_on_device_at,
        }
        self._request(f"/api/v1/events/{event_id}/reminder-audit", method="POST", payload=payload,
                      on_success=on_success, on_failure=on_failure, on_error=on_error)

    # =========================================================================
    # 3b. REMINDER AUDIT (used by notifier.ReminderScheduler)
    # =========================================================================
    @staticmethod
    def _device_time():
        """aware ISO timestamp from the phone's clock (the body of these two calls is required by the server)."""
        from datetime import datetime
        return {"at": datetime.now().astimezone().isoformat()}

    def report_reminder_scheduled(self, event_id):
        self._request(f"/api/v1/reminders/{event_id}/scheduled", method="POST", payload=self._device_time())

    def report_reminder_delivered(self, event_id):
        self._request(f"/api/v1/reminders/{event_id}/delivered", method="POST", payload=self._device_time())

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