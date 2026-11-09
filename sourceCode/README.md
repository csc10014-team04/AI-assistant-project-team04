# sourceCode

All program code of the University Life Assistant. Start with the [root README](../README.md) for the big picture.

| Folder | What it is | Language / stack | Read |
|---|---|---|---|
| [`BE/`](BE/README.md) | The **backend API**: login, timetable import, free-slot engine, proposals (Accept / Reject / Reschedule), tasks, reminders, search, AI understanding | Python 3.12, FastAPI, SQLAlchemy 2, MySQL | [BE/README.md](BE/README.md) |
| [`FE/`](FE/README.md) | The **mobile / desktop app**: login, calendar, search, AI chat | Python, Kivy + KivyMD (Android through buildozer) | [FE/README.md](FE/README.md) |
| [`Database/`](Database/README.md) | **Infrastructure and data design**: Docker Compose (MySQL, vLLM/Llama), `init.sql`, the knowledge-base tools and the `kb_*` schema | Docker, MySQL 8 | [Database/README.md](Database/README.md) |
| [`AI-host/`](AI-host/README.md) | A map of the **AI layer** (the code itself lives in `BE/services`) | notes | [AI-host/README.md](AI-host/README.md) |

How they connect:

```
 FE (app)  ──HTTP/JSON + JWT──►  BE (FastAPI, port 8080)  ──SQL──►  MySQL (Docker, port 3307)
                                      │
                                      └─HTTP─►  vLLM + Llama 3.1 8B (Docker, port 8000)

 collected university pages: ../database/UniInfo   (tools: Database/knowledgebase)
```

## Run everything (short version)

```powershell
# 1. database + AI engine (on the host PC)
cd sourceCode/Database/assistant_deploy ; Copy-Item .env.example .env ; docker compose up -d db llama_engine
# 2. backend
cd ../../BE ; python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080
# 3. app (on any PC that can reach the backend)
cd ../FE ; pip install -r requirements.txt ; $env:ASSISTANT_API_URL = "http://<HOST_IP>:8080" ; python main.py
```

Check that it works: `curl http://<HOST_IP>:8080/health` (process), `curl http://<HOST_IP>:8080/health/db` (database).
Tests: `python -m pytest tests` from the repository root (no Docker needed).

## Rules shared by all folders
- `BE/models.py`, `BE/database.py` and `Database/assistant_deploy/init.sql` are **locked contracts**: change them only by team agreement.
- Times are stored in UTC and shown as `+07:00`; every record belongs to one user (`owner_id`); the AI never writes to the calendar.
- Never commit `.env` files, tokens or real student data.
