# ARCHITECTURAL CONTRACTS & CODING RULES FOR AI ASSISTANTS

This repository implements the Backend and Database layers for the **University Life Assistant** mobile application.
- **Target Runtime & Stack:** Python `3.12.10`, FastAPI, SQLAlchemy 2.0, Pydantic v2, MySQL 8.0+ (`utf8mb4`).
- **Python 3.12 Rules:** Use modern built-in type annotations (`list[str]`, `int | None`). Never use `datetime.utcnow()` (deprecated in Python 3.12 and produces naive datetimes); always use `datetime.now(UTC_TZ)`.

When generating or modifying any code in this repository, you MUST strictly obey all rules below.

---

## 1. LOCKED SHARED CONTRACTS (DO NOT MODIFY)
- `models.py`, `database.py`, and `schema.sql` are locked shared contracts across the team.
- **Do NOT modify `models.py`, `database.py`, or `schema.sql`** unless explicitly instructed by the user for a schema migration.
- **Do NOT redefine duplicate Enums, dataclasses, or SQLAlchemy models** in your own files. Always import them directly from `models` and `database`.

---

## 2. USER AUTHENTICATION & DATA ISOLATION
- **Three-table user architecture:**
  - `User` (`users`): Stores `id` and `display_name`.
  - `AuthIdentity` (`auth_identities`): Stores authentication credentials (`provider` = `AuthProvider.PASSWORD` | `GOOGLE` | `GITHUB`, `provider_user_id`, and `hashed_password`). For username/password login, `provider_user_id` is the username.
  - `UserPreference` (`user_preferences`): Stores scheduling constraints (`sleep_start`, `sleep_end`, `min_break_minutes`, `max_block_minutes`, `slot_step_minutes`). When registering a new `User`, always create a default `UserPreference` row for that user.
- **Mandatory Ownership Check (Anti-IDOR):**
  - Every database query, update, or deletion on `Course`, `Event`, `Task`, `Proposal`, or `Reminder` MUST filter by `owner_id == current_user.id`. Never fetch or mutate a record by `id` alone without verifying `owner_id`.

---

## 3. UNIFIED CALENDAR ENTITIES (`events`, `courses`, `tasks`)
- **Single Unified Calendar Table (`events`):**
  - All calendar items with timestamps live in the `events` table (`Event` ORM model / `EventDomain` dataclass), distinguished by `kind: EventKind`:
    1. `EventKind.CLASS`: Recurring weekly university classes. Linked to a parent `Course` row via `course_id`, with `is_hard = True`. Both `title` and `room` are copied directly onto each `Event` row so calendar queries never require a SQL `JOIN` to `courses`.
    2. `EventKind.EXAM`: One-off exam sessions (`course_id = None`, `is_hard = True`).
    3. `EventKind.EVENT`: Fixed school or personal events (`course_id = None`).
    4. `EventKind.DEADLINE`: Point-in-time submission deadlines. **Stored in `events` with `start_time == end_time` (zero duration).** Because duration is 0, `EventDomain.blocks_availability` returns `False`, and the scheduling engine automatically ignores deadlines when searching for free time slots.
    5. `EventKind.TASK`: Scheduled time blocks generated after a user confirms an AI scheduling `Proposal` for a flexible `Task`.
- **Flexible Tasks (`tasks`):**
  - Unscheduled activities requested via natural language (e.g., "work on project for 3 hours") are stored in `Task` (`duration_minutes`, `priority`, `status`).
  - One `Task` can generate one or multiple `Event` rows (when a long task is split across multiple non-contiguous free slots).
- **Priority Scale:**
  - Integer `1` to `3`, where `1` is highest priority (`PriorityLevel.HIGH`), `2` is medium (`PriorityLevel.MEDIUM`), and `3` is lowest/default (`PriorityLevel.LOW`).

---

## 4. PROPOSAL STATE MACHINE & CONVERSATION FLOW (`proposals`)
- **No Direct AI Database Writes:** The AI / LLM layer NEVER writes directly to `events`. It creates a `Proposal` (`status = ProposalStatus.PROPOSED`).
- **Proposal Lifecycle (`ProposalStatus`):**
  - `PROPOSED`: Waiting for user action.
  - `CONFIRMED`: Triggered via button API (`POST /proposals/{id}/confirm`). Runs the conflict validator; if valid, creates `Event` row(s) (`kind = EventKind.TASK`, `source = EventSource.AI_CREATED`) and updates `Task.status = TaskStatus.SCHEDULED`.
  - `REJECTED`: Triggered via button API (`POST /proposals/{id}/reject`).
  - `RESCHEDULED`: Triggered when the user clicks the `Reschedule` button on Proposal `X` and submits a follow-up prompt (e.g., "move to evening"). Set Proposal `X.status = ProposalStatus.RESCHEDULED`, inherit the task context from Proposal `X`, find a new slot (excluding previously rejected/rescheduled slots), and insert a new `Proposal` with `parent_id = X.id`.
  - `ABANDONED`: When a user sends a new root prompt without `reschedule_proposal_id`, automatically call `abandon_pending_proposals(db, owner_id)` from `database.py` to transition all currently `PROPOSED` records of that user to `ABANDONED`.
- **Task Splitting Storage (`extra_slots_json`):**
  - For a single continuous slot, store `start_time` and `end_time` on `Proposal` and leave `extra_slots_json = None`.
  - When a task is split into multiple time blocks, store the first block in `start_time`/`end_time` and remaining blocks as a JSON list of `{"start_time": "...", "end_time": "..."}` in `extra_slots_json`.

---

## 5. TIMETABLE FILE PARSING & RE-IMPORT (`ParseBatchResult`)
- **Intermediate CSV Schema:**
  - Columns: `course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind`
  - Valid `kind` values in CSV (`CsvRowKind`): `CLASS`, `EXAM`, `DEADLINE`, `EVENT`.
  - Time format: `HH:MM` (24-hour). Date format: `YYYY-MM-DD`. Encoding: `UTF-8`.
- **Error Isolation (Human-in-the-Loop Preview):**
  - The parser MUST NOT crash or silently drop unparseable lines. It must return `ParseBatchResult(import_batch_id, valid_rows, invalid_rows)` from `models.py` so the frontend can display valid rows alongside flagged invalid rows for user correction or explicit skipping.
- **Safe Re-import Replacement:**
  - Imported events have `source = EventSource.IMPORTED` and an `import_batch_id`. When a student uploads a new timetable file to replace the old one, only soft-delete existing events where `source == EventSource.IMPORTED`, preserving `AI_CREATED` and `MANUAL` events.

---

## 6. TIMEZONE & 15-MINUTE GRID CONVENTIONS
- **No Naive Datetimes:** Every `datetime` object in Python domain logic MUST be timezone-aware (`tzinfo` set to `UTC_TZ` or `VN_TZ` imported from `database.py`). Passing a naive `datetime` to `TimeSlot`, `EventDomain`, or `to_db_utc` will raise a `ValueError`.
- **Database Storage in UTC:** MySQL `DATETIME` columns store UTC values. Always call `to_db_utc(dt)` from `database.py` before saving to MySQL, and call `from_db_to_vn(dt)` when serializing timestamps to ISO 8601 (`+07:00`) for mobile JSON responses.
- **15-Minute Granularity:** All time values are truncated to the minute (`second = 0`). Candidate slots from the scheduling engine and manual fallback picker must align to 15-minute increments (`:00`, `:15`, `:30`, `:45`) using `round_up_to_15m(dt)`.

---

## 7. SOFT DELETE vs. HARD DELETE RULES
- **Soft Delete (`deleted_at`):** Used on `courses`, `events`, and `tasks`.
  - To delete a record, set `record.deleted_at = datetime.now(UTC_TZ).replace(tzinfo=None)`.
  - **Every SELECT query on `courses`, `events`, and `tasks` MUST filter `deleted_at.is_(None)`.** Always use `active_events_stmt`, `active_courses_stmt`, and `active_tasks_stmt` from `database.py`.
- **State-Tracked (Never Deleted):** `proposals` has no `deleted_at` column and rows are never deleted; state is tracked via `Proposal.status`.
- **Hard Delete:** Only used for transient/ephemeral data (canceled staging previews, expired auth tokens).

---

## 8. GRACEFUL AI FALLBACK & REMINDERS
- **4 AI Failure Conditions:** Inference timeout, LLM process crash/connection error, JSON schema validation failure, or unresolvable semantic intent.
  - On any of these 4 failures, log an `AiErrorLog` entry and immediately return a fallback response (`fallback_mode = True`) containing candidate free `TimeSlot`s computed by the pure-Python deterministic engine so the mobile UI can open the manual slot picker without crashing.
- **Reminders (`reminders`):**
  - At most 1 reminder per `Event` (`event_id` is `UNIQUE`).
  - Notifications are scheduled locally on the mobile device. Whenever an event is rescheduled or soft-deleted, the API response MUST return the updated/canceled reminder timestamps so the mobile client can cancel the old local alarm and schedule the new one.
