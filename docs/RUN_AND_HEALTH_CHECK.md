# Hướng dẫn kiểm tra môi trường, cài đặt và chạy ứng dụng (BE, DB, AI, FE)

Tài liệu này dùng chung cho tất cả thành viên trong nhóm. Thay vì cài đặt lại từ đầu, mỗi người chạy khối lệnh kiểm tra ở **Mục 1** để biết máy mình đã sẵn sàng tới đâu và chỉ cần làm bổ sung những bước còn thiếu ở **Mục 2**, sau đó chọn chế độ chạy ở **Mục 3**.

---

## Chỉ dẫn dành cho AI Agent (nếu thành viên dùng Agent hỗ trợ trên máy cá nhân)

Nếu bạn là AI Agent đang đọc file này và có quyền chạy lệnh trên máy của thành viên:
1. Chạy khối lệnh kiểm tra ở **Mục 1** trên máy người dùng để xác định: `<REPO_ROOT>`, các bản Python hiện có (`<BE_PYTHON_EXE>` có `uvicorn`/`fastapi`/`pymysql`, `<FE_PYTHON_EXE>` có `kivy`/`kivymd`), trạng thái Docker Desktop, file `sourceCode/Database/assistant_deploy/.env`, container `schedule_db`, và cổng trống khả dụng (nên dùng `18081` nếu `8080` bị Windows giữ gây `[WinError 10013]`).
2. Tự động hoàn thành các bước còn thiếu ở **Mục 2** (chỉ hướng dẫn người dùng thao tác GUI với bước cài Docker Desktop hoặc DBeaver nếu chưa có).
3. Tự động thay toàn bộ placeholder `<...>` bằng đường dẫn và thông số thực tế trên máy đó, rồi tạo một file hướng dẫn riêng cục bộ (ví dụ `docs/LOCAL_RUN_MY_PC.md`, không commit lên git) hoặc in thẳng khối lệnh Terminal 1 và Terminal 2 để người dùng copy chạy ngay.

---

## 1. Kiểm tra nhanh hiện trạng máy cá nhân

Mở PowerShell tại thư mục gốc repo (hoặc chạy trực tiếp, thay `<REPO_ROOT>` bằng đường dẫn repo trên máy bạn) để kiểm tra máy bạn đã có những gì:

```powershell
$repoRoot = "<REPO_ROOT>"   # vi du: C:\Users\TenBan\projects\AI-assistant-project-team04
$hostIp   = "26.211.52.63"  # IP may Host tren Radmin VPN

Write-Host "=== 1. KIEM TRA DOCKER ==="
try { docker --version } catch { Write-Host "CHUA CO DOCKER CLI" }
docker info --format "Docker Engine: {{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "DOCKER ENGINE CHUA CHAY (hay mo Docker Desktop)" }

Write-Host "`n=== 2. KIEM TRA FILE .ENV VA CONTAINER MYSQL ==="
$envPath = Join-Path $repoRoot "sourceCode\Database\assistant_deploy\.env"
Write-Host ".env ton tai: $(Test-Path $envPath)"
docker ps -a --filter "name=schedule_db" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>$null

Write-Host "`n=== 3. KIEM TRA PYTHON & GOI DA CAI ==="
py -0p 2>$null
python -c "import sys; print('python mac dinh:', sys.executable)" 2>$null
foreach ($mod in @("uvicorn", "fastapi", "pymysql", "kivymd")) {
    python -c "import $mod; print('OK:', '$mod')" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "THIEU tren python mac dinh: $mod" }
}

Write-Host "`n=== 4. KIEM TRA KET NOI MAY HOST QUA RADMIN VPN ==="
try { Invoke-RestMethod "http://${hostIp}:8080/health" -TimeoutSec 3 | ConvertTo-Json -Compress } catch { Write-Host "CHUA NOI DUOC BE HOST (8080): $($_.Exception.Message)" }
try { Invoke-RestMethod "http://${hostIp}:8000/v1/models" -TimeoutSec 3 | Out-Null; Write-Host "AI HOST (8000): OK" } catch { Write-Host "CHUA NOI DUOC AI HOST (8000): $($_.Exception.Message)" }
```

**Cách đọc nhanh để biết mình cần làm gì tiếp:**
- **Nếu Docker Engine đang chạy + `.env` là `True` + `schedule_db` đang `Up` + đủ gói Python:** Bỏ qua Mục 2, đi thẳng tới **Mục 3**.
- **Nếu thiếu bất kỳ mục nào:** Chỉ làm đúng bước con tương ứng trong **Mục 2**.

---

## 2. Cài đặt bổ sung các phần còn thiếu (bỏ qua bước đã đạt)

### Bước 2.1 - Cài và bật Docker Desktop (chỉ làm khi chưa có Docker)
- Tải và cài **Docker Desktop** cho Windows.
- Mở Docker Desktop, chờ tới khi góc dưới bên trái hiện **`Engine running`**.

### Bước 2.2 - Tạo file `.env` cho MySQL Docker (chỉ làm khi `.env` báo `False`)
Tạo file `sourceCode\Database\assistant_deploy\.env` (tham khảo `sourceCode\Database\assistant_deploy\.env.example`) với nội dung:

```env
DB_ROOT_PASSWORD=<MAT_KHAU_ROOT_TUY_CHON>
DB_USER=schedule_admin
DB_PASSWORD=<MAT_KHAU_DB_TUY_CHON>
```

### Bước 2.3 - Khởi động MySQL container `schedule_db` (chỉ làm khi `schedule_db` chưa `Up`)
```powershell
Set-Location "<REPO_ROOT>\sourceCode\Database\assistant_deploy"
docker compose up -d db
docker ps --filter "name=schedule_db"
```
- Khi cột `NAMES` hiện `schedule_db` và cột `PORTS` hiện `0.0.0.0:3307->3306/tcp` là thành công. Ở lần chạy đầu tiên, MySQL mất khoảng 10 đến 15 giây để chạy xong `init.sql`.
- **Bảng `pending_clarifications`:** Server BE hiện tự động khởi tạo bảng này trong giai đoạn khởi động `lifespan()` tại `sourceCode/BE/main.py` trước khi nhận request, nên không cần tạo thủ công trước khi chạy.

### Bước 2.4 - Cài đặt thư viện Python (chỉ làm khi thiếu gói)
- **Nếu chỉ chạy FE kết nối máy Host (Hướng A):**
  ```powershell
  Set-Location "<REPO_ROOT>"
  <FE_PYTHON_EXE> -m pip install -r requirements-endUser.txt
  ```
- **Nếu chạy cả BE local và FE (Hướng B):**
  ```powershell
  Set-Location "<REPO_ROOT>"
  <BE_PYTHON_EXE> -m pip install -r requirements-fullStack.txt
  ```
  - *Lưu ý:* Nếu máy có 2 bản Python riêng (ví dụ `kivy`/`kivymd` cài sẵn trên Python 3.12 còn `uvicorn`/`fastapi`/`pymysql` cài trên Python 3.15), không cần cài Kivy sang bản 3.15; chỉ cần gọi đúng `<BE_PYTHON_EXE>` ở Terminal 1 và `<FE_PYTHON_EXE>` ở Terminal 2.

### Bước 2.5 (Tùy chọn) - Kết nối DBeaver để xem dữ liệu DB trực quan
Chỉ cần cài nếu muốn mở bảng SQL xem dữ liệu bằng giao diện:
1. Mở DBeaver -> nhấn **New Database Connection** (biểu tượng phích cắm góc trên bên trái) -> chọn **MySQL 8** -> **Next**.
2. Tại thẻ **Main**, điền khớp với `docker-compose.yml` và `.env`:
   - Server Host: `localhost`
   - Port: `3307`
   - Database: `university_assistant`
   - Username: `<DB_USER>` (mặc định `schedule_admin`)
   - Password: `<DB_PASSWORD>`
3. Chuyển sang thẻ **Driver properties**:
   - Đổi `allowPublicKeyRetrieval` thành `true`.
   - Đổi `useSSL` thành `false`.
4. Nhấn **Test Connection...** (nếu hỏi tải Driver files thì nhấn **Download**), hiện `Connected` thì nhấn **Finish**. Mở rộng `university_assistant` -> `Tables` sẽ thấy các bảng đã được tạo từ `init.sql`.

---

## 3. Hai hướng chạy ứng dụng

### Hướng A - Chạy FE trên máy cá nhân, dùng chung BE/DB/AI trên máy Host (Mặc định)

- **Nguyên lý hoạt động:** Theo mặc định trong `sourceCode/FE/api_client.py`, `APIClient` trỏ tới `http://26.211.52.63:8080`. Khi chạy theo hướng này, **code BE vừa `git pull` về máy cá nhân hoàn toàn không được thực thi**; mọi xử lý phía BE phụ thuộc vào phiên bản BE đang chạy trên máy Host.
- **Điều kiện:** Máy Host đã pull code mới nhất + khởi động lại BE + bật DB và AI; máy cá nhân bật Radmin VPN.
- **Lệnh chạy (Windows PowerShell):**
  ```powershell
  Set-Location "<REPO_ROOT>\sourceCode\FE"
  <FE_PYTHON_EXE> main.py
  ```
  - Nếu cần trỏ sang IP Host khác mặc định, thêm `$env:ASSISTANT_API_URL = "http://<HOST_IP>:8080"` trước lệnh chạy `main.py`.

---

### Hướng B - Tự chạy BE local trên máy cá nhân + MySQL Docker local + gọi ké AI máy Host

- **Khi nào dùng:** Khi bạn vừa `git pull` hoặc tự sửa code trong `sourceCode/BE/` và muốn chạy/kiểm thử trực tiếp code BE mới trên máy mình mà không phụ thuộc máy Host đã cập nhật BE chưa.
- **Lưu ý về DB và cổng:**
  - Nên nối vào MySQL Docker cục bộ trên chính máy bạn (`127.0.0.1:3307`) với `<DB_USER>` và `<DB_PASSWORD>` trong file `.env` của bạn (không nối vào DB chung `26.211.52.63:3307` vì `.env` máy Host không đẩy lên git nên thường khác mật khẩu).
  - Dùng cổng `<BE_PORT>` là `18081` (hoặc `8081`) để tránh lỗi `[WinError 10013]` khi Windows/Hyper-V giữ cổng `8080`.
  - Đặt `LLM_TIMEOUT_SECONDS = "10"` (BE) và `ASSISTANT_AI_TIMEOUT = "15"` (FE) để tránh timeout sớm khi gọi AI qua Radmin VPN.

**Mở 2 cửa sổ PowerShell song song:**

**Terminal 1 - Bật server BE local (`127.0.0.1:<BE_PORT>`):**
```powershell
Set-Location "<REPO_ROOT>\sourceCode\BE"

# 1. Ket noi MySQL Docker cuc bo tren may ban
$env:DATABASE_URL = "mysql+pymysql://<DB_USER>:<DB_PASSWORD>@127.0.0.1:3307/university_assistant?charset=utf8mb4"

# 2. Goi ke vLLM AI server tren may Host qua Radmin VPN (neu chay AI local thi bo 3 dong nay)
$env:VLLM_ENDPOINT = "http://<HOST_IP>:8000/v1/chat/completions"
$env:LLM_ALLOWED_HOSTS = "<HOST_IP>"
$env:LLM_TIMEOUT_SECONDS = "10"

# 3. Khoi dong server BE local
<BE_PYTHON_EXE> -m uvicorn main:app --host 127.0.0.1 --port <BE_PORT> --reload
```

**Terminal 2 - Chạy app FE trỏ vào BE local (`127.0.0.1:<BE_PORT>`):**
```powershell
Set-Location "<REPO_ROOT>\sourceCode\FE"
$env:ASSISTANT_API_URL = "http://127.0.0.1:<BE_PORT>"
$env:ASSISTANT_AI_TIMEOUT = "15"
<FE_PYTHON_EXE> main.py
```

---

## 4. Kiểm tra dịch vụ BE, DB và AI đang chạy

Thay `<TARGET_IP>` và `<TARGET_PORT>` tương ứng (`26.211.52.63` và `8080` khi kiểm tra máy Host; `127.0.0.1` và `<BE_PORT>` khi kiểm tra BE local theo Hướng B):

```powershell
$targetIp   = "<TARGET_IP>"    # vi du: "26.211.52.63" hoac "127.0.0.1"
$targetPort = "<TARGET_PORT>"  # vi du: "8080" (Host) hoac "18081" (Local)
$aiIp       = "<HOST_IP>"      # vi du: "26.211.52.63"

Write-Host "1. Kiem tra BE:"
try { Invoke-RestMethod "http://${targetIp}:${targetPort}/health" | ConvertTo-Json -Compress } catch { Write-Host "LOI BE: $($_.Exception.Message)" }

Write-Host "`n2. Kiem tra MySQL DB qua BE:"
try { Invoke-RestMethod "http://${targetIp}:${targetPort}/health/db" | ConvertTo-Json -Compress } catch { Write-Host "LOI DB: $($_.Exception.Message)" }

Write-Host "`n3. Kiem tra cau hinh AI & luot goi AI gan nhat tren BE:"
try {
    $dbg = Invoke-RestMethod "http://${targetIp}:${targetPort}/api/v1/debug/logs?limit=5"
    $dbg.ai_runtime_config | ConvertTo-Json -Compress
    Write-Host "So luot goi AI gan day: $($dbg.ai_call_count)"
    $dbg.recent_ai_calls | Select-Object -First 3 feature, status, source, http_status, latency_ms, fallback_reason | Format-Table -AutoSize
} catch { Write-Host "LOI DEBUG LOGS: $($_.Exception.Message)" }

Write-Host "`n4. Kiem tra truc tiep vLLM AI server (port 8000):"
try { Invoke-RestMethod "http://${aiIp}:8000/v1/models" | ConvertTo-Json -Depth 3 -Compress } catch { Write-Host "KHONG TRUY CAP DUOC PORT 8000: $($_.Exception.Message)" }
```

**Cách đọc kết quả:**
- **Bước 1 (`{"status":"ok"}`):** Server BE đang chạy và thông mạng.
- **Bước 2 (`{"status":"ok","database":"ok"}`):** BE đã nối được MySQL và chạy thành công `SELECT 1`. Nếu HTTP `503` là DB chưa bật hoặc sai `DATABASE_URL`.
- **Bước 3 (`/api/v1/debug/logs`):**
  - Trả về JSON: `ai_runtime_config.endpoint_allowed` phải là `true`, `vllm_endpoint` trỏ đúng về vLLM; trong `recent_ai_calls`, `status: "OK"` và `source: "llm"` là AI chạy thật, `FALLBACK`/`rules` là đang rơi về dự phòng (xem `fallback_reason`).
  - Trả về `(404) Not Found`: Server BE đang chạy phiên bản cũ trước khi có endpoint `/api/v1/debug/logs`; cần kiểm chứng AI bằng Bước 4 và gửi thử 1 câu xếp lịch trên app.
- **Bước 4 (cổng `8000`):** Trả về JSON có `"owned_by":"vllm"`, `"id":"hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"` là vLLM đã bật và mở cổng `8000` qua Radmin VPN.
