# University Life Assistant

**An AI scheduling assistant for HCMUS students.** Give it a messy timetable (PDF, photo, CSV, markdown, pasted text) and
plain-language requests such as *"xếp cho mình 3 tiếng làm đồ án CTDL tuần này, không làm buổi tối nhé"*, and it builds a
conflict-free calendar. The student confirms every change.

Group 04 · CSC10014 Computational Thinking · Team: Ngô Vũ Khôi Nguyên, Huỳnh Nhật Duy, Nguyễn Tường Lâm,
Đinh Quang Thịnh, Trương Anh Khôi.

**Where do I start?**

| I want to…                                          | Go to                                                                                     |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| just use the app                                     | [Quick start: use the app](#2-quick-start-use-the-app)                                     |
| run the whole system (database + AI + backend + app) | [Quick start: full stack](#3-quick-start-run-the-full-stack)                               |
| understand the design                                | [How it works](#4-how-it-works) and [docs/architecture.md](docs/architecture.md)            |
| change the code                                      | [Repository map](#8-repository-map), [Testing](#9-testing), [Contributing](#11-contributing) |

---

## 1. The problem

First- and second-year students juggle academic data scattered over several HCMUS platforms (Portal for schedules, Moodle for
assignments, …) on top of a hectic timetable. This project puts it into one system driven by natural language.

|                   |                                                                                                                                                                                                                                              |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Users**   | HCMUS students                                                                                                                                                                                                                               |
| **Inputs**  | Timetable files (PDF, image/OCR, markdown, raw text) · natural-language requests · priority (user-set or AI-inferred) · in-chat Accept / Reject / Reschedule · username + password or Google/GitHub OAuth                                |
| **Outputs** | Calendar with busy blocks and suggested free slots · conversational answers with the scheduling rationale · local notifications before flagged events · IT logs (latency, VRAM/RAM, queue depth, AI error taxonomy, reminder audit trail) |

### Success criteria

| Area            | Target                                                                                                                                                         |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Correctness     | 100 % of suggested slots have **zero overlap** with fixed (hard) events and match the requested duration exactly                                         |
| AI reliability  | ≥ 98 % of model replies match the JSON schema; **zero temporal hallucinations** (every date comes from the database or the clock, never from the model) |
| Performance     | Free-slot search over one semester ≤ 200 ms · end-to-end AI request ≤ 4 s on the host machine                                                               |
| Fault tolerance | Any AI timeout or failure opens a manual slot picker within 1 s; the app never crashes                                                                         |
| Privacy         | Personal schedule data never goes to public APIs; authenticated endpoints only; data isolated per user                                                         |

### Edge cases handled

No free block long enough (split the task or demote lower priorities) · vague dates ("sớm", "tuần sau") · requests that collide
with a fixed class · abandoning a suggestion by starting a new request · non-diacritic Vietnamese, teencode, profanity, emoji
and special characters.

---

## 2. Quick start: use the app

For students who only want the app. You need a backend someone else already hosts; you install **no** database or AI.

1. Install **Python 3.12 or 3.13** (Windows; Kivy 2.3.1 has prebuilt wheels only up to 3.13).
2. Install the UI packages:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-endUser.txt
   ```
3. Point the app at the host and start it:

   ```powershell
   $env:ASSISTANT_API_URL = "http://<HOST_IP>:8080"   # default: http://127.0.0.1:8080
   python sourceCode/FE/main.py
   ```
4. On the first screen register an account, then log in. Import your timetable, then ask the assistant in chat.

If the app cannot connect, check `http://<HOST_IP>:8080/health` in a browser. More detail: [sourceCode/FE/README.md](sourceCode/FE/README.md).

---

## 3. Quick start: run the full stack

For the host and for developers who run database, AI model, backend and UI themselves.

### 3.1 What you need

| Component                                 | Requirement                                                                                         |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------- |
| GPU (AI host only)                        | NVIDIA, ≥ 12 GB VRAM for the 4-bit 8B model (reference host: RTX 4090 24 GB, i9-14900K, 64 GB RAM) |
| Disk                                      | ~20 GB free (Docker images + model weights)                                                         |
| Docker Desktop                            | with NVIDIA GPU support (WSL2 on Windows): runs MySQL and vLLM                                      |
| Python                                    | **3.12 or 3.13**                                                                              |
| Tesseract OCR + Vietnamese data (`vie`) | *optional*: reading photos/scans of timetables                                                    |
| Hugging Face token                        | access to the gated Llama 3.1 model (`HF_TOKEN`)                                                  |

Developers who only touch backend or frontend code **do not need a GPU**: point them at the shared host, or run the backend
without the AI (it answers in fallback mode).

### 3.2 Configure secrets

```powershell
git clone https://github.com/csc10014-team04/AI-assistant-project-team04.git
cd AI-assistant-project-team04/sourceCode/Database/assistant_deploy
Copy-Item .env.example .env
```

Edit `.env` (never commit it):

```env
DB_ROOT_PASSWORD=choose_a_strong_root_password
DB_USER=schedule_admin
DB_PASSWORD=choose_a_strong_app_password
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
```

For anything beyond local development also set strong `JWT_SECRET_KEY` and `DATA_ENCRYPTION_KEY` (see [section 5](#5-configuration-reference)).

### 3.3 Start MySQL and the AI engine

```powershell
docker compose up -d db llama_engine    # the first start downloads the model (several minutes)
docker compose ps
docker compose logs -f llama_engine     # wait for "Application startup complete"
```

| Service        | Container                 | Host port      | Notes                                                                     |
| -------------- | ------------------------- | -------------- | ------------------------------------------------------------------------- |
| MySQL 8.0      | `schedule_db`           | **3307** | schema `university_assistant`, created from `init.sql` on first start |
| vLLM           | `local_llama_inference` | **8000** | OpenAI-compatible API, context limited to 2048 tokens                     |
| Probe backend  | `schedule_backend`      | 8080           | small diagnostics stub (`/health`, `/db_test`, `/ai_test`)          |
| Probe frontend | `schedule_frontend`     | 80             | Kivy status page                                                          |

> `init.sql` runs only on the **first** start of an empty volume. After changing it or the DB credentials run
> `docker compose down -v` (this **deletes all data**) and start again.

### 3.4 Run the real backend (FastAPI)

The probe container above is only a stub. Stop it (`docker compose stop backend`) to free port 8080, then, from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-fullStack.txt          # full-stack set: backend + UI + tests + crawler
cd sourceCode/BE
uvicorn main:app --host 0.0.0.0 --port 8080
```

The backend finds the database from `assistant_deploy/.env` (host `localhost`, port `3307`). To use a shared host instead,
create `sourceCode/BE/.env` or set the variables:

```env
DATABASE_URL=mysql+pymysql://schedule_admin:<password>@192.168.100.112:3307/university_assistant?charset=utf8mb4
VLLM_ENDPOINT=http://192.168.100.112:8000/v1/chat/completions
```

Open `http://localhost:8080/docs` for the interactive API documentation.

### 3.5 Run the app

```powershell
$env:ASSISTANT_API_URL = "http://localhost:8080"
python sourceCode/FE/main.py
```

### 3.6 Optional: OCR for photographed timetables

Install Tesseract with Vietnamese data and put `tesseract` on `PATH` (Windows: UB-Mannheim installer, tick *Vietnamese*).
Without it, text-layer PDFs and text/CSV/markdown files still work; images are rejected with a clear message.

### 3.7 Verify

```powershell
curl http://localhost:8080/health          # {"status":"ok"}
curl http://localhost:8000/v1/models       # lists the Llama model
python -m pytest tests -q                  # system tests, no Docker needed
```

### Which requirements file?

| File                                                    | For                         | Contains                                                                                                                           |
| ------------------------------------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| [requirements-endUser.txt](requirements-endUser.txt)     | people who only use the app | Kivy / KivyMD UI and its HTTP client                                                                                               |
| [requirements-fullStack.txt](requirements-fullStack.txt) | host and developers         | everything above plus FastAPI, SQLAlchemy, PyMySQL, auth, PDF/OCR, pytest, KB crawler (vLLM is installed separately or via Docker) |

---

## 4. How it works

```
 Desktop / Android app (FE)     Backend (FastAPI, sourceCode/BE)                      Host machine (Docker)
┌────────────────┐  HTTP/    ┌──────────────────────────────────────────┐        ┌──────────────────────┐
│ calendar       │  JSON+JWT │ auth ─ ingestion ─ assistant ─ reminders │  SQL   │ MySQL 8.0  (:3307)   │
│ chat + buttons │──────────▶│  │        │          │            │      │───────▶│ utf8mb4, UTC times   │
│ manual picker  │           │  │   parser/OCR   normalizer      audit   │        └──────────────────────┘
│ local alarms   │◀──────────│  │   validator    temporal                │  HTTP  ┌──────────────────────┐
└────────────────┘           │  │   (hard-conflict) NLU ─ FIFO queue ────│───────▶│ vLLM (:8000)         │
                             │  └─ RAG index (encrypted, per user)       │        │ Llama-3.1-8B AWQ-INT4│
                             └──────────────────────────────────────────┘        └──────────────────────┘
```

Key rules, enforced in code (see [AGENTS.md](AGENTS.md)):

1. **The AI never writes to the calendar.** It only creates a `Proposal` (`PROPOSED`). The student confirms, rejects or asks to reschedule; only `CONFIRMED` creates events.
2. **A deterministic engine, not the LLM, finds free time.** The LLM only extracts intent, duration, title and the user's own date words.
3. **Every record belongs to one user.** Every query filters by `owner_id`; calendar rows are soft-deleted.
4. **Times are stored in UTC** and returned as ISO-8601 `+07:00`, on a 15-minute grid.
5. **If the AI fails** (timeout, crash, bad JSON, unclear intent) the API still answers `200` with `fallback_mode = true`, so the app opens the manual picker instead of an error.

### Feature status

| Duty        | Feature                                                                                        | State                                                                                                                          |
| ----------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| P1-1        | Calendar UI (Kivy; Android build file)                                                         | 🟡 month/week calendar and search show real events; Android build not yet run on a phone                                       |
| P1-2        | Privacy isolation (auth-only API, PII redaction, private-host-only LLM calls, encrypted index) | ✅ MySQL data at rest and the phone's token file are not encrypted yet                                                         |
| P1-3        | Username/password auth, bcrypt, JWT                                                            | ✅                                                                                                                             |
| P1-4        | Timetable ingestion: preview, error isolation, conflict cards, safe re-import, search index    | ✅                                                                                                                             |
| P1-5        | Availability engine ≤ 200 ms                                                                  | ✅ sort-and-sweep, tested                                                                                                      |
| P1-6        | Zero-overlap validator                                                                         | ✅ re-checked at Accept                                                                                                        |
| P1-7        | Natural-language understanding                                                                 | ✅ accuracy on the live model not yet measured                                                                                 |
| P1-8 / P1-9 | Chat buttons · manual fallback                                                                | ✅ server and app code                                                                                                         |
| P2-1…3, 6  | Few-shot JSON pipeline, PDF/image RAG, date ambiguity, input normalizer                        | ✅                                                                                                                             |
| P2-4        | Task splitting across free gaps; low-priority tasks reported as dropped                        | ✅ an urgent task cannot displace a confirmed event                                                                            |
| P2-5        | Priority queue (`/api/v1/tasks`, `/tasks/schedule`)                                        | ✅                                                                                                                             |
| P2-7        | Abandon pending proposals on a new request                                                     | ✅                                                                                                                             |
| P2-8        | Google / GitHub OAuth                                                                          | 🟡 server done and tested with a fake provider; needs real client ids and app buttons                                          |
| P2-9        | Local notifications                                                                            | 🟡 scheduler done; AlarmManager route untested on a device                                                                     |
| P2-10…13   | FIFO inference queue, telemetry, AI error log, reminder audit                                  | ✅ no GPU load test, no dashboard                                                                                              |
| extra       | University knowledge base (`kb_*` schema, extractor, loader)                                 | 🟡 lecturers, departments, programmes, publications loaded from FIT / Math; courses and Chemistry empty; chat lookup not built |

---

## 5. Configuration reference

| Variable                                                             | Default                                                                   | Purpose                                                                   |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`  | `schedule_admin`, –, `localhost`, `3307`, `university_assistant` | database connection (or give `DATABASE_URL` directly)                   |
| `VLLM_ENDPOINT`                                                    | `http://127.0.0.1:8000/v1/chat/completions`                             | AI engine; **must be a private address** or the call is refused     |
| `LLM_ALLOWED_HOSTS`                                                | empty                                                                     | extra allowed AI hosts/CIDRs (e.g. a VPN range)                           |
| `LLM_TIMEOUT_SECONDS`                                              | `3.0`                                                                   | model timeout before falling back (1 s queue wait + 3 s = 4 s worst case) |
| `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`                  | dev key, `1440`                                                         | token signing; **change the secret outside development**            |
| `DATA_ENCRYPTION_KEY`                                              | dev key                                                                   | encrypts each user's RAG index on disk                                    |
| `INFERENCE_QUEUE_LOGGING`                                          | `0`                                                                     | `1` writes queue timings to `inference_queue_logs`                    |
| `TELEMETRY_INTERVAL_SECONDS`                                       | `0` (off)                                                               | sample RAM/VRAM/queue depth into `telemetry_metric_logs`                |
| `CORS_ORIGINS`                                                     | empty                                                                     | comma-separated browser origins (the native app needs none)               |
| `AI_ERROR_LOG_PATH`, `REMINDER_AUDIT_LOG_PATH`, `RAG_DATA_DIR` | `sourceCode/BE/logs/…`, `data/rag`                                   | runtime files (git-ignored)                                               |
| `ASSISTANT_API_URL` (app)                                          | `http://127.0.0.1:8080`                                                 | backend address used by the app                                           |
| `ASSISTANT_AI_TIMEOUT` (app)                                       | `5`                                                                     | seconds the app waits for the AI before opening the manual picker         |

---

## 6. Using the API

The app does all of this for you; the same flow through the API:

```bash
B=http://localhost:8080

# 1. Create an account -> returns an access token
curl -X POST $B/api/v1/auth/register -H "Content-Type: application/json" \
     -d '{"username":"alice","password":"secret123","display_name":"Alice"}'
TOKEN=<access_token from the response>

# 2. Preview a timetable (invalid rows are listed, never dropped silently)
curl -X POST $B/api/v1/ingestion/parse-preview -F "raw_content=@timetable.csv;type=text/plain"

# 3. Check clashes with your calendar, then save
curl -X POST $B/api/v1/ingestion/check-conflicts -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @rows.json
curl -X POST $B/api/v1/ingestion/commit          -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d @commit.json

# 4. Index a PDF/photo so the assistant knows your schedule
curl -X POST $B/api/v1/assistant/index-file -H "Authorization: Bearer $TOKEN" -F "file=@schedule.pdf"

# 5. Ask in natural language
curl -X POST $B/api/v1/assistant/understand -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"prompt":"xếp 3 tiếng làm đồ án ngày mai, không làm buổi tối"}'
```

Timetable CSV columns: `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`
(`kind` = `CLASS` | `EXAM` | `DEADLINE` | `EVENT`; times `HH:MM`, dates `YYYY-MM-DD`, UTF-8). A sample is in
[sourceCode/Database/user_data/samples/timetable_sample.csv](sourceCode/Database/user_data/samples/timetable_sample.csv).

| Area      | Endpoints (under `/api/v1`, JWT required except register/login)                                                                       |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Auth      | `POST /auth/register`, `POST /auth/login`, `GET /auth/oauth/{google\|github}/start`, `POST /auth/oauth/{provider}/exchange`      |
| Chat      | `POST /assistant/understand` (returns `nlu`, optional `proposal`), `POST /assistant/index-file`                                 |
| Proposals | `POST /proposals/{id}/confirm`, `/reject`, `POST /proposals/manual` (reschedule = `understand` with `reschedule_proposal_id`) |
| Tasks     | `POST/GET /tasks`, `PATCH/DELETE /tasks/{id}`, `POST /tasks/schedule`                                                             |
| Calendar  | `GET /search/events`, `POST /search/free-slots`, `POST /search/academic/ask`, `POST /search/academic/documents`                 |
| Import    | `POST /ingestion/parse-preview`, `/resolve-preview`, `/check-conflicts`, `/commit`                                              |
| Reminders | `PUT /reminders/{event_id}`, `POST /reminders/{event_id}/scheduled`, `/delivered`, `GET /reminders/audit`                       |
| Health    | `GET /health` (process), `GET /health/db` (database)                                                                                |

The always-current list is the Swagger page at `http://<host>:8080/docs`.

---

## 7. Troubleshooting

| Symptom                                               | Fix                                                                                                                   |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `No matching distribution found for kivy_deps…`    | use Python 3.12 or 3.13 on Windows and install from `requirements-endUser.txt` / `requirements-fullStack.txt`     |
| `Communications link failure` / timeout to MySQL    | Docker not running, wrong host IP, or Windows firewall (set the network to *Private* / open 3307)                   |
| `Access denied for user`                            | `DB_USER`/`DB_PASSWORD` differ from `assistant_deploy/.env`; after changing them run `docker compose down -v` |
| `Unknown database`                                  | the schema is `university_assistant`                                                                                |
| Port 3306 in use                                      | expected; MySQL is published on **3307**                                                                        |
| `getaddrinfo failed ('db')`                         | the hostname `db` only works inside Docker; use `localhost:3307` or the host IP                                   |
| vLLM container exits                                  | `docker compose logs llama_engine`: missing/invalid `HF_TOKEN`, no GPU in Docker, or not enough VRAM              |
| Assistant always answers with `fallback_mode: true` | the AI is unreachable, or `VLLM_ENDPOINT` is not a private address (add it to `LLM_ALLOWED_HOSTS`)                |
| Image upload rejected                                 | install Tesseract + Vietnamese data, or upload a text-layer PDF / CSV                                                 |
| App says it cannot connect                            | wrong `ASSISTANT_API_URL`, or the backend is not running                                                            |
| `401 Unauthorized`                                  | missing/expired token; log in again                                                                                   |

---

## 8. Repository map

```
AGENTS.md                      architectural contracts (read before changing code)
requirements-fullStack.txt     full-stack dependencies (host and developers)
requirements-endUser.txt       UI-only dependencies (regular users)
docs/                          duties.pdf, Problem_analysis.pdf, architecture.md, guides      -> docs/README.md
scripts/                       check_readmes.py (empty READMEs, broken links, team list)
database/UniInfo/              collected university information (pages + structured rows)   -> database/README.md
sourceCode/                                                                                  -> sourceCode/README.md
  BE/                          FastAPI backend: routers/, services/, models.py, database.py, tests/, tools/
  FE/                          the Kivy app (login, calendar, search, AI chat)                -> sourceCode/FE/README.md
  Database/                    assistant_deploy/ (docker-compose.yml, init.sql), user_data/, knowledgebase/
  AI-host/                     notes on the AI/server layer (NLU, RAG, queue, telemetry)
tests/                         system test suite (BE + DB + AI + FE + knowledge base)        -> tests/README.md
```

Locked shared files: `models.py`, `database.py` and `init.sql` change only through an agreed migration. The knowledge-base
tables live in `sourceCode/Database/knowledgebase/search_engine_schema.sql`.

---

## 9. Testing

```powershell
python -m pytest tests -rx                    # system suite: in-memory SQLite, simulated AI, ~20 s, no Docker
cd sourceCode/BE; python -m pytest            # module tests: Docker MySQL if reachable, else SQLite (REQUIRE_MYSQL=1 forbids the fallback)
python scripts/check_readmes.py               # empty READMEs, broken links, current team list
python sourceCode/BE/tools/eval_nlu.py        # JSON adherence against the live model (target ≥ 98 %)
```

[tests/README.md](tests/README.md) lists every test and what is not covered. Kivy screens cannot run in automatic tests; try them by hand.

---

## 10. Further reading

[docs/architecture.md](docs/architecture.md) · [docs/UI_design_and_BE_integration.md](docs/UI_design_and_BE_integration.md) ·
[docs/README.md](docs/README.md) (guides 1-6: AI, database, FE↔BE, smoke test, failures, duties) ·
[sourceCode/BE/README.md](sourceCode/BE/README.md) · [sourceCode/Database/README.md](sourceCode/Database/README.md)

---

## 11. Contributing

Follow [AGENTS.md](AGENTS.md): timezone-aware datetimes only, import enums/models from `models.py`, filter every query by
`owner_id` and `deleted_at`, never let the LLM write to `events`, and keep the `# [pic: …]` ownership comments. Run the test
suite before opening a pull request, and never commit `.env` files.
