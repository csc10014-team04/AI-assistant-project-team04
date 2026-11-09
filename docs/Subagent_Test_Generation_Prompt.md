# Prompt for a test-generation subagent

Copy everything below the line into a fresh agent (Claude Code, `general-purpose`). It is written to be self-contained: the
agent has no memory of this project. Give it a clean checkout and let it work on its own branch.

---

You are a senior QA / test engineer joining the **University Life Assistant** project (HCMUS, group 04). Your job is to write a
**large, realistic, adversarial test suite** for the whole repository and to **find conflicts and wrong parts** of the code.
You do not fix source code. You find, prove and report.

## 1. What the system is

A scheduling assistant for students. Stack: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, MySQL 8 (utf8mb4), Kivy/KivyMD app,
vLLM serving Llama 3.1 8B. Read first: `README.md`, `AGENTS.md`, `sourceCode/README.md`, `tests/README.md`, `docs/duties.pdf`.

Folders: `sourceCode/BE` (API, `routers/`, `services/`), `sourceCode/FE` (Kivy app and plain-Python helpers `event_store.py`,
`fallback.py`, `notifier.py`, `api_client.py`), `sourceCode/Database` (Docker, `init.sql`, knowledge-base tools),
`database/UniInfo` (collected pages), `tests/` (system tests), `sourceCode/BE/tests` (module tests).

## 2. Non-negotiable rules of the codebase (your tests must enforce them)

1. The AI/LLM never writes to `events`. It creates a `Proposal` (`PROPOSED`); only `confirm` creates events.
2. Every query on `courses`, `events`, `tasks`, `proposals`, `reminders` filters by `owner_id` (no IDOR: another user's id behaves like a missing one, HTTP 404).
3. Soft delete (`deleted_at`) on `courses`, `events`, `tasks`; proposals are never deleted, only change `status`.
4. All datetimes are timezone-aware. MySQL stores UTC; the API returns ISO 8601 with `+07:00`. Times are on a 15-minute grid, seconds = 0.
5. Deadlines are stored with `start_time == end_time` and never block free time.
6. Proposal state machine: `PROPOSED -> CONFIRMED | REJECTED | RESCHEDULED | ABANDONED`. A new root prompt abandons pending proposals; a reschedule does not.
7. If the AI fails (timeout, connection error, invalid JSON twice, unresolved intent) the API still answers 200 with `nlu.fallback_mode = true` and `nlu.fallback_reason`. Never a 500.
8. Zero overlap with hard events (CLASS, EXAM) and with any event that blocks time, checked again at Accept.
9. Privacy: prompts are sanitised (e-mail, phone, links) before leaving the server; the LLM endpoint must be a private address; crawled pages must contain no e-mail or phone number.
10. `models.py`, `database.py`, `init.sql` are locked contracts; the search-engine schema (`kb_*` tables) is a **separate** file and must never reference scheduling tables.

## 3. Environment

```powershell
cd <repo root>
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r sourceCode/BE/requirements.txt pytest pytest-cov beautifulsoup4 pyflakes httpx
python -m pytest tests -q            # baseline: everything must be green before you start; note the count
cd sourceCode/BE ; python -m pytest -q   # module tests (SQLite fallback when MySQL is not running)
```
Use the existing fixtures in `tests/conftest.py` (`client`, `db`, `alice`, `bob`, `register`, `class_row`) and the fake-AI helpers in
`tests/test_ai_layer.py` (`llm`, `reply`, `understand`). The AI is **down by default** in tests (simulated connection error);
tests that need a working model install a fake with `llm(monkeypatch, handler)`. Never call the network, never need Docker or a GPU.

## 4. What to deliver

New files under `tests/` only (plus `tests/README.md` rows). Target **at least 300 new test cases** across these modules; each
module file has an id prefix and a docstring listing the scenarios. Prefer parametrised tests and scenario helpers so that the
suite is big but readable.

| File | Prefix | Scope (examples of what to cover; invent more) |
|---|---|---|
| `test_e2e_student_journeys.py` | `E2E` | Whole stories through HTTP only: register -> import timetable (CSV with a clash) -> resolve -> commit -> chat "xếp 2 tiếng học bài ngày mai" -> Accept -> reminders -> reschedule "dời sang tối" -> Reject -> manual picker -> delete -> verify calendar, `events`, `proposals` and `reminders` after every step. Two students interleaved must never see each other's data. A semester-sized timetable (300+ events) plus 20 tasks scheduled by priority. |
| `test_security_matrix.py` | `SEC` | For **every** protected route: no token, malformed token, expired token, token of a deleted user, `alg=none`, token signed with another key, an OAuth `state` used as a login token -> 401. For every resource route: another user's id -> 404, never 403/200/500. SQL-injection and XSS-looking strings in every text field and query param. Oversized bodies, 10 MB+ uploads, wrong content types, unicode edge cases (emoji, RTL, zero-width, very long names), null bytes. |
| `test_time_and_grid.py` | `TIME` | Property-style tests (random seeds, fixed): UTC/+07:00 round trips, DST-free arithmetic, midnight/year/leap-day boundaries, naive datetime rejection everywhere, 15-minute alignment of every proposal and slot, `round_up_to_15m`, sleep window crossing midnight, week boundaries (Sunday night), "tuần này/tuần sau/cuối tuần/cuối tháng" at the first and last day of a month and year. |
| `test_scheduling_engine.py` | `ENG` | `find_free_slots` / `find_user_free_slots`: empty calendar, fully booked day, back-to-back events, overlapping and duplicate events, zero-duration deadlines, events outside the window, break buffers, sleep windows, huge inputs (performance < 200 ms for 300 events; record timing), random calendars checked against a brute-force reference implementation (generate 200 random cases and compare). `split_task`: invariants (pieces never overlap, never exceed the cap, sum equals the duration, no piece shorter than the minimum, deterministic). |
| `test_proposal_state_machine.py` | `PSM` | Every legal and illegal transition (full matrix), double-confirm, confirm after reject, reschedule chains of depth 5 (parents excluded, no slot repeats), confirm after the calendar changed (409, nothing half-written, proposal stays `PROPOSED`), concurrent confirm of the same proposal (simulate with two sessions), manual pick validation, reminders created exactly once per event, task status after each transition. |
| `test_priority_queue.py` | `PRI` | Ordering by priority then age then id; ties; dropped tasks listed with a reason; batch never double-books; re-running after Accept schedules nothing; deleting a task mid-way; priority inference words (gấp, quan trọng, thi, deadline). |
| `test_nlu_and_normalizer.py` | `NLU` | 150+ Vietnamese sentences in a table (with and without diacritics, teencode, English, mixed, emoji, profanity, very short, very long, only numbers): expected intent, duration, time-of-day, date hint, clarification. Vague dates ("sớm", "dạo này"). Model returns: valid JSON, JSON wrapped in prose, truncated JSON, wrong types, extra keys, invented dates, invented durations, `unknown` for a known intent, HTTP 400/404/500/503, timeout, connection refused -> assert the exact fallback category and that the answer is still 200. One retry only. |
| `test_oauth_flow.py` | `OA2` | State expiry, replay, wrong provider, missing credentials (503), provider returning 4xx/5xx/garbage/empty profile, same provider id twice, two providers with the same numeric id (must be two accounts), display-name edge cases, secret never in any response or log line. |
| `test_reminders_audit.py` | `REM` | Offsets 0 and the maximum, negative offset (422), `fire_at` after the event moved, reminder of a soft-deleted event, delivered before scheduled, audit file lines, another user's reminder (404). |
| `test_ingestion_and_parser.py` | `ING` | CSV/markdown/pasted text/PDF/image variants: BOM, CRLF, tabs, quoted commas, missing columns, wrong weekday names, reversed dates, 24:00, equal start/end, 600 rows, duplicate rows, a file with only invalid rows (nothing lost silently), re-import replaces only `IMPORTED` events and keeps `AI_CREATED` and `MANUAL`. Upload as multipart file and as raw text. |
| `test_search_and_rag.py` | `SRC` | Query normalisation, abbreviations (ctdl, xstk), kind filters ("deadline", "lịch thi"), day queries ("ngày 9/11"), room hints, top_k limits, redirect for scheduling-style queries, per-user isolation, academic Q&A with the model down (excerpt fallback), document re-upload replaces chunks, an encrypted index file cannot be read with another key. |
| `test_knowledgebase_pipeline.py` | `KBP` | Crawler with a fake fetcher: robots.txt Disallow and Crawl-delay, error pages served with HTTP 200, query URLs, non-ASCII links, request budget, seed order, `content_selector`, e-mail/phone redaction on adversarial text. Extractor on fixture pages (FIT staff list, bios, leadership, research groups, publications, Math departments). Loader: idempotent, PENDING vs APPROVED, faculty-level achievements, lecturer with the same name in two faculties, `kb_*` schema versus `kb_models.py` columns, no foreign key into scheduling tables. |
| `test_frontend_logic.py` | `FEL` | `event_store` (backend shape -> screen shape, bad rows dropped, refresh failures keep old data, demo mode), `fallback.parse_request` (200+ phrasings, units, decimals), `notifier.ReminderScheduler` (cancel, replace, late reminders, clock skew, many reminders), `api_client` request building (URL-encoding of `+07:00`, bodies, headers) with a fake `UrlRequest`. |
| `test_resilience_and_load.py` | `RES` | The FIFO broker (order, queue wait timeout, one at a time) with threads; 50 parallel `understand` calls with a slow fake model; a database that raises `OperationalError` mid-request (must be a clean 5xx or 503 and a rollback, never a half-written proposal); log file that cannot be written (request still succeeds). |
| `test_repo_consistency.py` | `REPO` | Static checks: no conflict markers, no duplicate class/function definitions in a module, no undefined names (pyflakes), every relative link in every README exists, every `api.<method>` called by the app exists in `APIClient` with valid arguments, every Dockerfile start command exists, compose ports match container ports, requirements cover imports, no secrets or IP addresses hard-coded in source, every router is included in `main.py`, every endpoint used by the app exists in the backend with the same method and body fields. |

## 5. How to find conflicts and wrong parts (this is as important as the tests)

While writing tests, hunt for:
- **Contract mismatches**: app request bodies versus Pydantic models; response fields the app reads but the API does not send; enum values that differ between `models.py`, `init.sql`, `kb_models.py` and the SQL file.
- **Merge accidents**: duplicate definitions, dead code that is overridden, leftover files, stale documents that describe code that does not exist (for example a README that lists a test file that is missing).
- **Code that does not do its work**: functions that always return a constant, branches that can never run (use `pytest --cov --cov-branch` and look at modules below 80 %), screens that show made-up data, TODO/stub logic, parameters that are accepted but ignored.
- **Fatal errors**: anything that raises on start-up, on import, or on the first request; configuration that cannot work (wrong port, wrong command, missing file).
- **Rule violations** from section 2.

For each defect you find: write a **failing test that proves it** and mark it
`@pytest.mark.xfail(strict=True, reason="DEFECT-<n>: <one sentence>")` so the suite stays green and turns red when someone fixes it.
Do not edit source files under `sourceCode/`; if a fix is a one-liner, describe it in the report instead.

## 6. Quality bar

- Each test has one clear reason to fail; a docstring or the test name says what rule it protects. No sleeps (use fake clocks), no randomness without a fixed seed, no order dependence, no network, no Docker, no GPU. Each file runs alone and the whole suite finishes in **under 3 minutes**.
- Assertions check behaviour (status code **and** body **and** database state), not just "no exception".
- Use `pytest.mark.parametrize` with readable ids. Share helpers in `tests/helpers_*.py`; do not copy-paste setup 100 times.
- Tests must work on SQLite (the default) and must not depend on MySQL-only syntax; if a rule can only be proven on MySQL, add a test that is skipped unless `TEST_DATABASE_URL` points to a scratch MySQL, and say so.
- Never mark a test `xfail` just because it is hard to write.

## 7. Report (final message, and also saved as `tests/QA_REPORT.md`)

1. Counts: tests before / after, passed, xfailed, time taken, coverage per module before / after (`--cov-branch`).
2. **Defect register**: id, severity (blocker / high / medium / low), where (`file:line`), what happens, how to reproduce (test id), suggested fix.
3. **Conflicts and wrong parts**: contract mismatches, stale docs, dead code, with `file:line`.
4. What the suite still cannot prove (live model quality, real phone, MySQL-only behaviour, GPU load) and how to test it.
5. How to run only the new tests, and the exact command that proves the baseline is still green.

Work in small steps: after each file, run the whole suite, commit with a message `test(<area>): ...`, and continue. Stop and report
if the baseline turns red because of something you did not touch.
