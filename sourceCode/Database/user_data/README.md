# user_data: data that belongs to individual students

Everything in this folder's scope is **personal data of the app's users**. It is private, it is never committed to git
(`.gitignore` here ignores everything except this README and the fictional files under `samples/`), and it is never sent
to a public service.

## What counts as user data and where it really lives

| Data | Stored in | Notes |
|---|---|---|
| Accounts: display name, login identity (username, or Google / GitHub id) | MySQL tables `users`, `auth_identities` | passwords are bcrypt hashes only; OAuth accounts have no password |
| Scheduling preferences: sleep window, minimum break, longest block, 15-minute grid | MySQL `user_preferences` | one row per user, created at registration |
| Timetable and calendar: classes, exams, deadlines, events, AI-created task blocks | MySQL `courses`, `events` | times stored in UTC, shown in +07:00, soft-deleted with `deleted_at` |
| To-do items and the AI's suggestions | MySQL `tasks`, `proposals` | proposals are never deleted, their `status` tracks the history |
| Reminders and their audit trail | MySQL `reminders` (+ `reminder_audit.jsonl` on the backend host) | the phone schedules the real alarm |
| A student's own uploaded timetable text (PDF, image, CSV) as search vectors | encrypted files `owner_<user id>.idx` under the backend's `RAG_DATA_DIR` (default `sourceCode/BE/data/rag/`) | encrypted with `DATA_ENCRYPTION_KEY`; one file per user, never shared |
| The same data in a single local file (development) | `user_data.db` in this folder, created by `create_user_db.py` | ignored by git; see the section below |
| Login token on the phone | `auth_session.json` next to the app | **not encrypted yet** (open item) |

The MySQL data physically lives in the Docker volume `db_data` of `sourceCode/Database/assistant_deploy`.
The table definitions are in `assistant_deploy/init.sql` (the authority) and `sourceCode/BE/models.py`.

## Rules

1. Every query on user tables filters by `owner_id` (a user must never see another user's rows).
2. Never put real student data into `samples/`, tests, screenshots or issues. Use invented names.
3. Back up the MySQL volume and the `RAG_DATA_DIR` folder together and keep the same `DATA_ENCRYPTION_KEY`; without the key the index files cannot be read.
4. To erase a user completely: delete the user row (cascades to preferences, tasks, events, proposals, reminders) and delete `owner_<id>.idx`.
5. Public information about the university (faculties, lecturers, courses) is **not** user data: it belongs in [`../knowledgebase`](../knowledgebase/README.md).

## The local user-data database (`create_user_db.py`)

For development and demos the user data can live in **one SQLite file**, `user_data.db`, in this folder, so the whole
backend runs on a single PC without Docker or MySQL.

```powershell
python sourceCode/Database/user_data/create_user_db.py              # create user_data.db (kept if it already exists)
python sourceCode/Database/user_data/create_user_db.py --check      # tables and row counts
python sourceCode/Database/user_data/create_user_db.py --reset      # DELETE the file and every user in it, then recreate

cd sourceCode/BE
$env:DATABASE_URL = "sqlite:///<path printed by the script>"
python -m uvicorn main:app --port 8080                              # register / log in from the app as usual
```

It has the same tables and constraints as the real schema (it builds them from `sourceCode/BE/models.py`, nothing is redefined):

| Group | Tables |
|---|---|
| user data | `users`, `auth_identities`, `user_preferences`, `courses`, `tasks`, `proposals`, `events`, `reminders` |
| logs the backend writes | `ai_error_logs` (contains the user's cleaned prompts), `inference_queue_logs`, `telemetry_metric_logs` |

Limits to know:
- It is **private**: once somebody registers it holds a real account. The `.gitignore` here ignores it; never commit, share or attach it.
- SQLite does not enforce `ON DELETE CASCADE` for the backend's connection, so deleting a user there leaves that user's rows behind. The script's own connection does enforce it. Use MySQL when deletion must be complete.
- It is for one user of the machine. The shared host keeps using MySQL in Docker (`../assistant_deploy`).
- The public university knowledge base is a different database (`../knowledgebase`, tables `kb_*`) and is not created here.

## samples/

`samples/timetable_sample.csv` is a fictional timetable in the import format
(`course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`; times `HH:MM`, dates `YYYY-MM-DD`,
kinds `CLASS`, `EXAM`, `DEADLINE`, `EVENT`). Use it to try `POST /api/v1/ingestion/parse-preview`.
