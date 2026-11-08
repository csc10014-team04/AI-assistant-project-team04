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

## Files and cases (195 tests, 0 expected failures)

| File | IDs | Covers |
|---|---|---|
| `test_be_domain_and_auth.py` | BE-01..20 | timezone/15-min grid, deadlines, hard-conflict validator (P1-6), bcrypt, JWT tampering/expiry/alg-none, register/login (P1-3), every protected endpoint rejects anonymous callers |
| `test_be_ingestion_search.py` | BE-21..40 | CSV parser error isolation (P1-4), preview/resolve API, conflict cards, weekly expansion in +07:00/UTC, safe re-import, owner isolation, search engine (P1-5) |
| `test_be_proposals.py` | PR-01..12 | proposal lifecycle: create (no event written), confirm with conflict re-check, reject, reschedule chain, abandonment, owner isolation, manual picker (placement, validation, rollback) |
| `test_be_scheduling.py` | SC-01..10 | task splitting (P2-4), priority queue and dropped low-priority items (P2-5) |
| `test_be_oauth.py` | OA-01..09 | Google / GitHub sign-in with a fake provider (P2-8) |
| `test_be_rag_timetable.py` | RG-01..05 | confirmed timetable rows indexed for retrieval (P1-4) |
| `test_fe_fallback.py` | FB-01..06 | client AI timeout and offline manual-picker parsing (P1-9) |
| `test_fe_notifier.py` | NT-01..08 | local reminder scheduling and delivery audit (P2-9) |
| `test_kb_crawler.py` | KB-01..11 | knowledge-base collector (offline): text extraction, contact redaction, URL rules, robots.txt, accent folding, loader into the search index |
| `test_database_layer.py` | DB-01..20 | `init.sql` ↔ ORM parity (tables, columns, enums), CHECK/UNIQUE constraints, soft-delete helpers, proposal abandonment, docker-compose ports/secrets/volumes, `.env` hygiene |
| `test_ai_layer.py` | AI-01..20 | NLU through the API (P1-7, P2-1), dirty input (P2-6), ambiguity (P2-3), AI failure fallback + taxonomy log (P1-9, P2-12), privacy (P1-2), RAG isolation (P2-2), proposal abandonment (P2-7), reminder audit (P2-13) |
| `test_frontend.py` | FE-01..12 | existing Kivy status page (stubbed), missing Android calendar / chat buttons / manual-picker deliverables (P1-1, P1-8, P1-9), JSON contract the app consumes |

## Known defects and gaps

None open: every earlier expected failure (DEFECT-01 file upload crash, DEFECT-02 vague dates, DEFECT-03 hard-coded IP,
GAP-01..04 engine / chat UI / fallback / Android spec) was fixed and its `xfail` marker removed. New gaps should be added
as `@pytest.mark.xfail(strict=True, reason="...")` tests so they stay visible and turn red when fixed.

What is still NOT covered by automated tests: the live model (JSON adherence >= 98 %, latency < 4 s), real Android
devices (AlarmManager, buildozer build), MySQL-only behaviour (run `sourceCode/BE/tests` against the host database),
and encryption of MySQL data at rest.
