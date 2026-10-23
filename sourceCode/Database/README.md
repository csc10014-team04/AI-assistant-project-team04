# Infrastructure & Backend Integration Guide — Database & AI Services

> **Course:** CSC10014 — Virtual Assistant Project  
> **Target Database:** MySQL 8.0 (`utf8mb4_unicode_ci`, UTC timestamps)  
> **AI Engine:** Meta-Llama-3.1-8B-Instruct (AWQ-INT4) via vLLM  
> **Central Host IP:** `192.168.100.112` *(or `127.0.0.1` when developing on the host laptop)*

---

## 1. Network Topology & Port Mapping

Services run inside a private Docker bridge network (`internal_bridge`). When connecting from outside Docker (GUI clients, or Backend running locally in virtual environment), use the **Host Ports**:

| Service | Container Internal Address | Host External Access | Purpose |
| :--- | :--- | :--- | :--- |
| **MySQL 8.0** | `db:3306` | `Host_IP:3307` | Central Database (Port 3307 avoids conflicts with local MySQL) |
| **vLLM AI Engine** | `llama_engine:8000` | `Host_IP:8000` | Llama 3.1 8B Inference API |
| **Backend Gateway** | `backend:8080` | `Host_IP:8080` | Central FastAPI Service |
| **Frontend Web** | `frontend:80` | `Host_IP:80` | Status & Web Preview UI |

> [!IMPORTANT]
> **Why Port 3307 on Host?**  
> Port 3306 on developer laptops is frequently occupied by a local MySQL, MariaDB, or XAMPP service. Therefore, Docker exposes MySQL on host port **`3307`** (`"3307:3306"`).

---

## 2. Database Connection Guide

### A. External GUI Client Access (DBeaver, MySQL Workbench, DataGrip)

Use these credentials to connect your database manager to the central host:

* **Host:** `192.168.100.112` *(or `127.0.0.1` / `localhost` if running Docker locally)*
* **Port:** `3307`
* **Database / Default Schema:** `assistant_uni`
* **Username:** `schedule_main` 
* **Password:** *(Defined in `assistant_deploy/.env` — ask Host Lead via Discord/Zalo)*

---

### B. Python / SQLAlchemy Connection Strings

Choose the connection string based on **where your code is executing**:

#### 1. Backend Running Locally on Developer PC (Standard Dev Workflow)
Since Team Backend runs FastAPI directly in a local virtual environment (`.venv`), connect through the host port **`3307`** using the synchronous `pymysql` driver (as defined in `sourceCode/BE/database.py`):

```bash
# In your local .env or terminal environment:
# If connecting to Team Lead's host across Wi-Fi:
DATABASE_URL="mysql+pymysql://schedule_admin:[PASSWORD]@192.168.100.112:3307/university_assistant?charset=utf8mb4"

# If running the Docker stack on your own machine:
DATABASE_URL="mysql+pymysql://schedule_admin:[PASSWORD]@127.0.0.1:3307/university_assistant?charset=utf8mb4"
```

*Code implementation in `database.py`:*
```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://schedule_admin:[PASSWORD]@127.0.0.1:3307/university_assistant?charset=utf8mb4",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

#### 2. Backend Running Inside Docker Container
When packaged inside a Docker container attached to `internal_bridge`, use Docker DNS name `db` and container port `3306`:
```python
# Synchronous PyMySQL:
DATABASE_URL = "mysql+pymysql://schedule_admin:[PASSWORD]@db:3306/university_assistant?charset=utf8mb4"

# Asynchronous aiomysql (if using create_async_engine):
DATABASE_URL = "mysql+aiomysql://schedule_admin:[PASSWORD]@db:3306/university_assistant"
```

---

## 3. Deployment & Host Operations (`assistant_deploy/`)

### 3.1. Environment Setup (`.env`)
Before launching the Docker stack, create a `.env` file in `sourceCode/Database/assistant_deploy/` (you can copy from `.env.example`):

```bash
cd sourceCode/Database/assistant_deploy
cp .env.example .env
```

Ensure `.env` contains:
```env
DB_ROOT_PASSWORD=your_secure_root_password
DB_USER=schedule_admin
DB_PASSWORD=your_schedule_admin_password
HF_TOKEN=your_huggingface_access_token
```

### 3.2. Common Docker Commands

```powershell
# Navigate to deployment directory
cd sourceCode\Database\assistant_deploy

# Start all services in the background
docker compose up -d

# Check live logs of the database container
docker compose logs -f db

# Check running containers
docker compose ps

# Stop all services safely
docker compose down

# Wipe database volume & reset completely (Re-runs init.sql on next startup)
docker compose down -v
```

> [!WARNING]
> **Docker Volume Reset Rule:**  
> If you update `init.sql` or change database credentials in `.env`, MySQL will **not** automatically apply them because existing data is stored in the `db_data` volume. You must run `docker compose down -v` to delete the volume before starting again.

---

## 4. Calling the AI Engine (vLLM Llama 3.1)

The Llama 3.1 model is served via vLLM with an OpenAI-compatible API.

* **Internal Endpoint (from Docker containers):** `http://llama_engine:8000/v1/chat/completions`
* **External Endpoint (from Local Developer PC):** `http://192.168.100.112:8000/v1/chat/completions` (or `http://127.0.0.1:8000/v1/chat/completions`)

### FastAPI Route Integration Example (`httpx`):

```python
import os
import httpx
from fastapi import FastAPI, Depends, HTTPException

app = FastAPI()

VLLM_ENDPOINT = os.getenv(
    "VLLM_ENDPOINT",
    "http://llama_engine:8000/v1/chat/completions"  # Use 127.0.0.1:8000 if running BE locally
)
MODEL_NAME = "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"

@app.post("/api/v1/assistant/chat")
async def chat_with_assistant(user_message: str):
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful university assistant. Use the provided context to answer questions."
            },
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 512,
        "temperature": 0.3
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(VLLM_ENDPOINT, json=payload, timeout=60.0)
            response.raise_for_status()
            ai_data = response.json()
            return {
                "status": "success",
                "reply": ai_data["choices"][0]["message"]["content"]
            }
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"AI Engine unreachable: {exc}")
```

---

## 5. Testing & Verification

### Test Backend Endpoint via cURL
```bash
curl -X POST "http://192.168.100.112:8080/api/v1/assistant/chat" \
     -H "Content-Type: application/json" \
     -d '{"user_message": "What is my schedule for today?"}'
```

### Test MySQL Connection via PowerShell
```powershell
# Test TCP connectivity to port 3307
Test-NetConnection -ComputerName 127.0.0.1 -Port 3307
```

---

## 6. Troubleshooting & Common Errors

| Error Message | Root Cause | Solution |
| :--- | :--- | :--- |
| `Only one usage of each socket address (bind: 3306)` | Host port 3306 is already used by local MySQL/XAMPP. | Keep `"3307:3306"` in `docker-compose.yml` and connect via port **`3307`**. |
| `Access denied for user 'schedule_...'` | Typo in username (e.g. `schedule_main`) or wrong password. | Verify username is exactly `schedule_admin` and matches `.env`. |
| `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified` | Docker Desktop is closed or starting up. | Open Docker Desktop and wait until the whale icon turns green (**Engine running**). |
| `socket.gaierror: getaddrinfo failed ('db')` | Python script running locally on PC tried to connect to hostname `db`. | Replace `db:3306` with `127.0.0.1:3307` or `192.168.100.112:3307`. |
| `No route to host` / `Connection timed out` to `192.168.100.112` | Developer laptop is on a different Wi-Fi subnet or blocked by firewall. | Ensure all devices are on the same Wi-Fi, or allow inbound ports 3307/8080 on the host firewall. |

---

## 7. Architectural Rules for Backend Developers

1. **Zero Direct AI Database Mutations:** The AI Engine never writes directly to `events`. It must generate a `Proposal` (`status = PROPOSED`) for user confirmation.
2. **Context Window Constraint:** System prompts must remain concise. The model context length is constrained to **2048 tokens** due to local GPU VRAM limits.
3. **Timezone Awareness:** All timestamps stored in MySQL are UTC. Use `from_db_to_vn(dt)` to serialize timestamps into `+07:00` (ISO 8601) for mobile clients.
4. **Driver Consistency:** Stick to `pymysql` and SQLAlchemy 2.0 synchronous sessions as defined in `sourceCode/BE/database.py`.

