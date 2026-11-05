# University Life Assistant

**An AI scheduling assistant for HCMUS students.** It turns a messy timetable (PDF, photo, CSV, markdown, pasted text)
and plain-language requests such as *"xếp cho mình 3 tiếng làm đồ án CTDL tuần này, không làm buổi tối nhé"* into a
conflict-free calendar, with the student confirming every change.

Group 04 · CSC10014 Computational Thinking · 10-week project · Team: Ngô Vũ Khôi Nguyên, Huỳnh Nhật Duy, Nguyễn Tường Lâm,
Đinh Quang Thịnh, Trương Anh Khôi, Phạm Phúc Nguyên.

---

## 1. The problem

First- and second-year students juggle academic data scattered over several HCMUS platforms (Portal for schedules, Moodle for
assignments, …) on top of a hectic timetable. This project consolidates it into one system driven by natural language.

| | |
|---|---|
| **Users** | HCMUS students |
| **Inputs** | Timetable files (PDF, image/OCR, markdown, raw text) · natural-language requests · priority (user-set or AI-inferred) · in-chat Accept / Reject / Reschedule · username+password or Google/GitHub OAuth |
| **Outputs** | Visual calendar with busy blocks and suggested free slots · conversational answers with the scheduling rationale · local notifications before flagged events · IT logs (latency, VRAM/RAM, queue depth, AI error taxonomy, reminder audit trail) |

### Success criteria (what "done" means)

| Area | Target |
|---|---|
| Correctness | 100 % of suggested slots have **zero overlap** with fixed academic (hard) events and exactly match the requested duration |
| AI reliability | ≥ 98 % of model replies match the JSON schema; **zero temporal hallucinations** (every date comes from the database or the clock, never the model) |
| Performance | Free-slot search over one semester ≤ 200 ms · end-to-end AI request ≤ 4 s on the host machine |
| Fault tolerance | Any AI timeout or failure opens a manual slot picker within 1 s; the app never crashes |
| Privacy | Personal schedule data never goes to public APIs; only authenticated endpoints; data isolated per user |

### Edge cases the system handles

No free block long enough (split the task or demote lower priorities) · vague dates ("sớm", "tuần sau") · requests that collide
with a fixed class · abandoning a suggestion by starting a new request · non-diacritic Vietnamese, teencode, profanity, emoji and special characters.

---

## 2. How it works

```
 Android app (FE)              Backend (FastAPI, sourceCode/BE)                      Host machine (Docker)
┌────────────────┐  HTTPS/   ┌──────────────────────────────────────────┐        ┌──────────────────────┐
│ calendar       │  JSON+JWT │ auth ─ ingestion ─ assistant ─ reminders │  SQL   │ MySQL 8.0  (:3307)   │
│ chat + buttons │──────────▶│  │        │          │            │      │───────▶│ utf8mb4, UTC times   │
│ manual picker  │           │  │   parser/OCR   normalizer      audit   │        └──────────────────────┘
│ local alarms   │◀──────────│  │   validator    temporal                │  HTTP  ┌──────────────────────┐
└────────────────┘           │  │   (hard-conflict) NLU ─ FIFO queue ────│───────▶│ vLLM (:8000)         │
                             │  └─ RAG index (encrypted, per user)       │        │ Llama-3.1-8B AWQ-INT4│
                             └──────────────────────────────────────────┘        └──────────────────────┘
```

Key rules (enforced in code, see `AGENTS.md`):

1. **The AI never writes to the calendar.** It only creates a `Proposal` (`PROPOSED`). The student confirms, rejects or asks to reschedule; only `CONFIRMED` creates events.
2. **A deterministic engine, not the LLM, finds free time.** The LLM only extracts intent, duration, title and the user's own date words.
3. **Every record belongs to one user.** Every query filters by `owner_id`; deleted rows are soft-deleted.
4. **Times are stored in UTC** and returned to the phone as ISO-8601 `+07:00`, on a 15-minute grid.
5. **If the AI fails** (timeout, crash, bad JSON, unclear intent) the API still answers `200` with `fallback_mode = true` so the app can open the manual picker.

### Feature status

| Duty | Feature | State |
|---|---|---|
| P1-1 | Android calendar UI | ❌ not started (`sourceCode/FE` is empty) |
| P1-2 | Privacy isolation (auth-only API, PII redaction, private-host-only LLM calls, encrypted index) | ✅ |
| P1-3 | Username/password auth, bcrypt, JWT | ✅ |
| P1-4 | Timetable ingestion with preview, error isolation, conflict cards, safe re-import | ✅ (file-upload path has a known bug, see `tests/README.md`) |
| P1-5 | Availability engine ≤ 200 ms (`find_free_slots`) | ❌ stub (`NotImplementedError`) |
| P1-6 | Zero-overlap validator | ✅ |
| P1-7 | Natural-language understanding | ✅ |
| P1-8 / P1-9 | Chat buttons · manual fallback UI | ❌ frontend; server side (`fallback_mode`) ✅ |
| P2-1…3, 6 | Few-shot JSON pipeline, PDF/image RAG, date ambiguity, input normalizer | ✅ |
| P2-4, 5 | Task splitting / priority queue | ⏳ needs P1-5 |
| P2-7 | Abandon pending proposals on a new request | ✅ |
| P2-8 | Google / GitHub OAuth | ⏳ schema ready, not implemented |
| P2-9 | Local notifications | ⏳ server side done (`/reminders`); needs the Android app |
| P2-10…13 | FIFO inference queue, telemetry, AI error log, reminder audit | ✅ |

---

## 3. What you need

### Hardware (the AI host)

| Component | Requirement |
|---|---|
| GPU | NVIDIA with ≥ 12 GB VRAM for the 4-bit 8B model (reference host: RTX 4090 24 GB, i9-14900K, 64 GB RAM) |
| Disk | ~20 GB free (Docker images + model weights) |
| Network | Host and teammates on the same LAN/VPN if the database or AI is shared |

Developers who only work on the backend/frontend do **not** need a GPU: point them at the shared host, or run the backend with the AI switched off (it will answer in fallback mode).

### Software

| Tool | Version | Used for |
|---|---|---|
| Docker Desktop (with NVIDIA GPU support / WSL2 on Windows) | recent | MySQL, vLLM |
| Python | **3.12** | backend |
| Git | any | |
| Tesseract OCR + Vietnamese data (`vie`) | 5.x | *optional*: reading photos/scans of timetables |
| DBeaver / DataGrip | any | *optional*: inspect the database |
| Android Studio | recent | *when the Android app exists* |

### Accounts and secrets

- A **Hugging Face account and access token** with access granted to the gated Llama 3.1 model (`HF_TOKEN`).
- Choose database passwords (never commit them; `.env` is git-ignored).
- For production-like runs set strong `JWT_SECRET_KEY` and `DATA_ENCRYPTION_KEY`.
- Google/GitHub OAuth app credentials are only needed once P2-8 is implemented.

---

## 4. Deploy

### 4.1 Get the code and configure secrets

```bash
git clone https://github.com/csc10014-team04/AI-assistant-project-team04.git
cd AI-assistant-project-team04/sourceCode/Database/assistant_deploy
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env`:

```env
DB_ROOT_PASSWORD=choose_a_strong_root_password
DB_USER=schedule_admin
DB_PASSWORD=choose_a_strong_app_password
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
```

### 4.2 Start the infrastructure

```bash
docker compose up -d db llama_engine     # MySQL + AI engine (first start downloads the model, several minutes)
docker compose ps
docker compose logs -f llama_engine      # wait for "Application startup complete"
```

| Service | Container | Host port | Notes |
|---|---|---|---|
| MySQL 8.0 | `schedule_db` | **3307** | schema `university_assistant`, created from `init.sql` on first start |
| vLLM | `local_llama_inference` | **8000** | OpenAI-compatible API, context limited to **2048 tokens** |
| Probe backend | `schedule_backend` | 8080 | a small health/diagnostics stub (`/health`, `/db_test`, `/ai_test`) |
| Probe frontend | `schedule_frontend` | 80 | Kivy status page |

> `init.sql` runs only on the **first** start of an empty volume. After changing it or the DB credentials run
> `docker compose down -v` (this **deletes all data**) and start again.

### 4.3 Run the real backend (FastAPI)

The API used by the app lives in `sourceCode/BE` and runs on the host in a virtual environment (the container in 4.2 is only a probe;
stop it with `docker compose stop backend` if you want port 8080 for the real API).

```powershell
cd sourceCode/BE
python -m venv .venv
.\.venv\Scripts\Activate.ps1                 # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

The backend finds the database automatically from `assistant_deploy/.env` (`DB_USER`, `DB_PASSWORD`; host `localhost`, port `3307`).
To use a shared host instead, create `sourceCode/BE/.env` or set `DATABASE_URL`:

```env
DATABASE_URL=mysql+pymysql://schedule_admin:<password>@192.168.100.112:3307/university_assistant?charset=utf8mb4
VLLM_ENDPOINT=http://192.168.100.112:8000/v1/chat/completions
```

Open `http://localhost:8080/docs` for the interactive API documentation and `http://localhost:8080/health` for a quick check.

### 4.4 Optional: OCR for photographed timetables

Install Tesseract with Vietnamese data and make sure `tesseract` is on `PATH` (Windows: UB-Mannheim installer, tick *Vietnamese*).
Without it, PDFs with a text layer and text/CSV/markdown files still work; images are rejected with a clear message.

### 4.5 Verify the deployment

```bash
curl http://localhost:8080/health                       # {"status":"ok"}
curl http://localhost:8000/v1/models                    # lists the Llama model
python -m pytest tests -q                               # system test suite, no Docker needed
```

---

## 5. Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | `schedule_admin`, –, `localhost`, `3307`, `university_assistant` | database connection (or give `DATABASE_URL` directly) |
| `VLLM_ENDPOINT` | `http://127.0.0.1:8000/v1/chat/completions` | AI engine; **must be a private address** or the call is refused |
| `LLM_ALLOWED_HOSTS` | empty | extra allowed AI hosts/CIDRs (e.g. a VPN range) |
| `LLM_TIMEOUT_SECONDS` | `3.0` | model timeout before falling back (1 s queue wait + 3 s = 4 s worst case) |
| `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES` | dev key, `1440` | token signing — **change the secret outside development** |
| `DATA_ENCRYPTION_KEY` | dev key | encrypts each user's RAG index on disk |
| `INFERENCE_QUEUE_LOGGING` | `0` | `1` writes queue timings to `inference_queue_logs` |
| `TELEMETRY_INTERVAL_SECONDS` | `0` (off) | sample RAM/VRAM/queue depth into `telemetry_metric_logs` |
| `CORS_ORIGINS` | empty | comma-separated browser origins (the native app needs none) |
| `AI_ERROR_LOG_PATH`, `REMINDER_AUDIT_LOG_PATH`, `RAG_DATA_DIR` | `sourceCode/BE/logs/…`, `data/rag` | runtime files (git-ignored) |

---

## 6. Using the system

Typical flow through the API (the Android app will do the same):

```bash
B=http://localhost:8080

# 1. Create an account → returns an access token
curl -X POST $B/api/v1/auth/register -H "Content-Type: application/json" \
     -d '{"username":"alice","password":"secret123","display_name":"Alice"}'
TOKEN=<access_token from the response>

# 2. Preview a timetable (paste text or upload a file); invalid rows are listed, never dropped silently
curl -X POST $B/api/v1/ingestion/parse-preview -F "raw_content=@timetable.csv;type=text/plain"

# 3. Check clashes with your existing calendar, choose what to keep, then save
curl -X POST $B/api/v1/ingestion/check-conflicts -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @rows.json
curl -X POST $B/api/v1/ingestion/commit          -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @commit.json

# 4. Index a PDF/photo so the assistant knows your schedule
curl -X POST $B/api/v1/assistant/index-file -H "Authorization: Bearer $TOKEN" -F "file=@schedule.pdf"

# 5. Ask in natural language
curl -X POST $B/api/v1/assistant/understand -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"prompt":"xếp 3 tiếng làm đồ án ngày mai, không làm buổi tối"}'

# 6. Reminders: the phone registers its local alarm and reports delivery
curl -X PUT  $B/api/v1/reminders/<event_id> -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"offset_minutes":30}'
```

Timetable CSV columns: `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`
(`kind` = `CLASS` | `EXAM` | `DEADLINE` | `EVENT`; times `HH:MM`, dates `YYYY-MM-DD`, UTF-8).

If the AI is down or slow, `/assistant/understand` still returns `200` with `"fallback_mode": true`, the extracted duration/title and a
message, so the client shows the manual form instead of an error.

---

## 7. Repository map

```
AGENTS.md                      architectural contracts (read before changing code)
docs/                          duties.pdf, Problem_analysis.pdf, architecture decisions
sourceCode/
  BE/                          FastAPI backend: routers/, services/, models.py, database.py, tests/, tools/
  Database/                    infra guide + assistant_deploy/ (docker-compose.yml, init.sql, .env.example)
  AI-host/                     notes on the AI/server layer (NLU, RAG, queue, telemetry)
  FE/                          Android app (to be built)
tests/                         system test suite (BE + DB + AI + FE) – see tests/README.md
```

Locked shared files: `models.py`, `database.py`, `schema`/`init.sql` change only through an agreed migration.

---

## 8. Testing

```bash
python -m pytest tests -rx          # system suite: in-memory SQLite, simulated AI, ~15 s
cd sourceCode/BE && python -m pytest  # developers' module tests against the Docker MySQL (needs `docker compose up -d db`)
python sourceCode/BE/tools/eval_nlu.py          # measure JSON adherence against the live model (target ≥ 98 %)
```

`tests/README.md` lists every test and the known defects/gaps.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `Communications link failure` / timeout to MySQL | Docker not running, wrong host IP, or Windows firewall (set the network to *Private* / open 3307) |
| `Access denied for user` | `DB_USER`/`DB_PASSWORD` differ from `assistant_deploy/.env`; after changing them run `docker compose down -v` |
| `Unknown database` | the schema is `university_assistant` |
| Port 3306 in use | expected; MySQL is published on **3307** |
| `getaddrinfo failed ('db')` | the hostname `db` only works inside Docker; use `localhost:3307` or the host IP |
| vLLM container exits | check `docker compose logs llama_engine`: missing/invalid `HF_TOKEN`, no GPU in Docker, or not enough VRAM |
| Assistant always answers with `fallback_mode: true` | the AI is unreachable or `VLLM_ENDPOINT` is not a private address (add it to `LLM_ALLOWED_HOSTS`) |
| Image upload rejected | install Tesseract + Vietnamese data, or upload a text-layer PDF / CSV |
| `401 Unauthorized` | missing/expired token → log in again |

---

## 10. Contributing

Follow `AGENTS.md`: timezone-aware datetimes only, import enums/models from `models.py`, filter every query by `owner_id`
and `deleted_at`, never let the LLM write to `events`. Run the test suite before opening a pull request, and never commit `.env` files.
