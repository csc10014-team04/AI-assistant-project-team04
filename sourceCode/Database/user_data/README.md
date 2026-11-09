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
| The same tables as a definition file; optionally a one-file SQLite copy for development | `user_data_schema.sql` (MySQL), `user_data.db` (SQLite, ignored by git) | see the section below |
| Login token on the phone | `auth_session.json` next to the app | **not encrypted yet** (open item) |

The MySQL data physically lives in the Docker volume `db_data` of `sourceCode/Database/assistant_deploy`.
The table definitions are in `assistant_deploy/init.sql` (the authority) and `sourceCode/BE/models.py`.

## Rules

1. Every query on user tables filters by `owner_id` (a user must never see another user's rows).
2. Never put real student data into `samples/`, tests, screenshots or issues. Use invented names.
3. Back up the MySQL volume and the `RAG_DATA_DIR` folder together and keep the same `DATA_ENCRYPTION_KEY`; without the key the index files cannot be read.
4. To erase a user completely: delete the user row (cascades to preferences, tasks, events, proposals, reminders) and delete `owner_<id>.idx`.
5. Public information about the university (faculties, lecturers, courses) is **not** user data: it belongs in [`../knowledgebase`](../knowledgebase/README.md).

## The user-data database (MySQL)

User data lives in the **MySQL 8** database of the project (`university_assistant`, Docker container `schedule_db`, port 3307).
Its definition is in this folder:

| File | What it is |
|---|---|
| [`user_data_schema.sql`](user_data_schema.sql) | the MySQL tables for user data: `users`, `auth_identities`, `user_preferences`, `courses`, `tasks`, `proposals`, `events`, `reminders`, plus the backend's log tables `ai_error_logs` (holds the user's cleaned prompts), `inference_queue_logs`, `telemetry_metric_logs`. Every table is `CREATE TABLE IF NOT EXISTS`, so it can be applied to a database that has some of them. **Generated** from `../assistant_deploy/init.sql`, never edited by hand. |
| [`create_user_db.py`](create_user_db.py) | creates the database and the missing tables on MySQL, lists row counts, regenerates the SQL file, or builds a SQLite copy |

```powershell
# 1. MySQL must be running (a fresh Docker start already runs init.sql, which creates the same tables)
cd sourceCode/Database/assistant_deploy ; docker compose up -d db

# 2. create / complete the user-data tables (never drops anything)
python sourceCode/Database/user_data/create_user_db.py              # connection: --url, else $env:DATABASE_URL, else assistant_deploy/.env (127.0.0.1:3307)
python sourceCode/Database/user_data/create_user_db.py --check      # tables and row counts

# or apply the file with the MySQL client
docker exec -i schedule_db mysql -u<DB_USER> -p university_assistant < sourceCode/Database/user_data/user_data_schema.sql

# after a change to init.sql (a locked team contract): regenerate the file; a test fails if you forget
python sourceCode/Database/user_data/create_user_db.py --export-sql
```

Rules
- The script **never drops** tables on MySQL. To start from nothing: `docker compose down -v` in `assistant_deploy` (this deletes every user).
- The file holds **no data**, only structure. The database itself holds real accounts: never commit a dump of it, never attach it to an issue.
- The public university knowledge base is a different file and different tables (`../knowledgebase/search_engine_schema.sql`, `kb_*`).
- The password column stores only a bcrypt hash; the login token on the phone is not part of this database.

### Optional: a one-file SQLite copy for development
`python sourceCode/Database/user_data/create_user_db.py --sqlite` creates `user_data.db` here (ignored by git) from the same models, so the backend can run on a PC without Docker (`$env:DATABASE_URL = "sqlite:///<printed path>"`). `--reset` (SQLite only) deletes it. Limits: SQLite does not enforce `ON DELETE CASCADE` for the backend's connection, so deleting a user leaves rows behind, and column defaults are applied by the app, not by the file. The shared host uses MySQL.

## samples/

`samples/timetable_sample.csv` is a fictional timetable in the import format
(`course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`; times `HH:MM`, dates `YYYY-MM-DD`,
kinds `CLASS`, `EXAM`, `DEADLINE`, `EVENT`). Use it to try `POST /api/v1/ingestion/parse-preview`.
