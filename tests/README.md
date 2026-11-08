# System test suite (tester-owned)

Black-box / integration tests for **Backend, Database and Frontend**. They only *read* `sourceCode/`; nothing under
`sourceCode/` is modified. The module-level tests that the developers wrote stay in `sourceCode/BE/tests/`.

## Run

```bash
pip install -r sourceCode/BE/requirements.txt pytest   # fastapi, sqlalchemy, httpx, pyjwt, bcrypt, cryptography, python-multipart
python -m pytest tests -v                              # from the repository root
python -m pytest tests -rx                             # also list every known defect / gap (xfail reasons)
```

- **Default database: in-memory SQLite.** No Docker, fresh schema for every test, runs in ~15 s.
- **Against real MySQL:** `set TEST_DATABASE_URL=mysql+pymysql://user:pw@127.0.0.1:3307/<scratch_schema>` first.
  Tables are dropped and recreated per test, so use a scratch schema, never `university_assistant` with real data.
- The AI engine (vLLM) is always simulated: down by default, scripted per test. No GPU needed.
- Runtime files (AI error log, reminder audit, RAG index) are redirected to pytest temp folders.

## Files and cases (134 test runs: 130 pass, 4 expected failures)

| File | IDs | Covers |
|---|---|---|
| `test_be_domain_and_auth.py` | BE-01..20 | timezone/15-min grid, deadlines, hard-conflict validator (P1-6), bcrypt, JWT tampering/expiry/alg-none, register/login (P1-3), every protected endpoint rejects anonymous callers |
| `test_be_ingestion_search.py` | BE-21..40 | CSV parser error isolation (P1-4), preview/resolve API, conflict cards, weekly expansion in +07:00/UTC, safe re-import, owner isolation, search engine (P1-5) |
| `test_be_proposals.py` | PR-01..12 | proposal lifecycle: create (no event written), confirm with conflict re-check, reject, reschedule chain, abandonment, owner isolation, manual picker (placement, validation, rollback) |
| `test_database_layer.py` | DB-01..20 | `init.sql` ↔ ORM parity (tables, columns, enums), CHECK/UNIQUE constraints, soft-delete helpers, proposal abandonment, docker-compose ports/secrets/volumes, `.env` hygiene |
| `test_ai_layer.py` | AI-01..20 | NLU through the API (P1-7, P2-1), dirty input (P2-6), ambiguity (P2-3), AI failure fallback + taxonomy log (P1-9, P2-12), privacy (P1-2), RAG isolation (P2-2), proposal abandonment (P2-7), reminder audit (P2-13) |
| `test_frontend.py` | FE-01..12 | existing Kivy status page (stubbed), missing Android calendar / chat buttons / manual-picker deliverables (P1-1, P1-8, P1-9), JSON contract the app consumes |

## Known defects and gaps (tests marked `xfail(strict=True)`)

A strict xfail turns **red the moment the developer fixes it**, which is the signal to delete the marker and keep the test as regression.

| ID | Test | Owner | Finding |
|---|---|---|---|
| DEFECT-01 | BE-28 | BE (Lâm) | `POST /ingestion/parse-preview` with a **file upload** always crashes: `filename` is used before it is assigned (`UnboundLocalError`). Only the pasted-text path works. |
| DEFECT-02 | AI-10 | AI | Vague dates ("sớm", "dạo này") are never captured by the NLU date regex, so the clarifying question in `temporal.py` is unreachable for them. |
| DEFECT-03 | FE-06 | FE | `frontend/main.py` hard-codes `http://26.211.52.63:8080`. |
| GAP-02 | FE-07 | FE | No Android project (Kotlin/Java or manifest); the app is a Kivy desktop app (P1-1). |

Closed since the first version (markers removed, tests now pass): GAP-01 `find_free_slots` implemented (BE-39, BE-40); GAP-03/04 chat buttons and fallback handling exist (FE-09, FE-10, FE-08 are keyword checks on the source only).

## Not covered here (needs a device or live services)

Real MySQL behaviour of foreign-key cascades (run with `TEST_DATABASE_URL`), real vLLM latency/adherence
(`python sourceCode/BE/tools/eval_nlu.py`), OCR on photographed timetables (needs Tesseract), Android notifications firing
on time, and load tests with concurrent users.
