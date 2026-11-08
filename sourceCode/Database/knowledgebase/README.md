# knowledgebase: public university information for the AI

This folder holds the **public information about the university** that the assistant uses to answer questions such as
*"Thầy này dạy môn gì, là ai, có thành tích gì?"* or *"Khoa này gồm những môn nào?"*.
It is filled by a polite web collector (`crawler/`) from the five official websites below. It contains **no student data**
(that is in [`../user_data`](../user_data/README.md)).

```
 official websites ──► crawler/kb_crawler.py ──► database/UniInfo/<site>/*.md + index.json ──► load_into_backend_kb.py ──► backend search index ──► AI answer + source link
   (public pages)         (robots.txt obeyed)        (readable text, contacts removed)        (one-time / on refresh)        (/api/v1/search/academic/ask)
```

## 1. Sources

| Site id | Website | What it is | Pages collected (2026-11-09) | robots.txt (checked 2026-11-09) |
|---|---|---|---|---|
| `hcmus` | https://hcmus.edu.vn/ | University (Trường ĐH Khoa học Tự nhiên, ĐHQG-HCM): organisation, councils, faculties and institutes | **8** (limit 12) | `Crawl-delay: 10`, nothing disallowed. The crawler waits 10 s per request, so this site is slow. Most of its other pages are short news notices with too little text, so the run was stopped at 8 useful pages. |
| `fit` | https://www.fit.hcmus.edu.vn/ | Faculty of Information Technology: staff list, programmes (standard, advanced...), news and achievements | **40** | none published (the server answers an HTML error page) |
| `fbb` | https://fbb.hcmus.edu.vn/ | Faculty of Biology - Biotechnology | **40** | disallows `/admin/`, `/cache/`, `/includes/`... and query URLs |
| `chemistry` | https://chemistry.hcmus.edu.vn/ | Faculty of Chemistry | **0** (its home page is only an error screen) | disallows `/api/account`, `/api/users/`, `/management/`. The site is built by scripts in the browser, so a simple downloader receives an error screen instead of content; the crawler recognises and discards such pages (see section 5). |
| `math` | https://www.math.hcmus.edu.vn/ | Faculty of Mathematics and Computer Science: programmes, staff, departments | **40** | none published |

Total: **128 pages, about 940,000 characters, 1.4 MB**, which the loader turns into about 3,300 searchable chunks.

The list, the page limits and the keywords that decide which pages are visited first are in [`sources.json`](sources.json).
The collected pages are stored in **[`database/UniInfo/`](../../../database/UniInfo/README.md)** at the repository root. The exact result of the last run (pages per site, when, size, hash) is in [`database/UniInfo/index.json`](../../../database/UniInfo/index.json).

## 2. Folder layout

```
sourceCode/Database/knowledgebase/        the TOOLS and the rules (code, no collected content)
├── README.md              this file
├── sources.json           sites, limits, user agent, priority keywords, skipped file types
├── search_engine_schema.sql   MySQL tables (kb_*) for the search engine; separate from the scheduling init.sql
├── requirements.txt       beautifulsoup4 (only needed for collecting, not for the backend)
└── crawler/
    ├── README.md
    ├── kb_crawler.py      1. collects the pages
    ├── kb_extract.py      2. turns pages into lecturers / departments / programmes / publications (JSON)
    ├── kb_load.py         3. puts those rows into the kb_* MySQL tables
    └── load_into_backend_kb.py   (alternative) puts the pages into the backend's text search index

database/UniInfo/                         the COLLECTED DATA (output of the tools; see its README)
├── README.md
├── index.json             every collected page: site, url, title, file, fetched_at, sha256, chars
├── hcmus/ fit/ fbb/ math/ one Markdown file per page (chemistry: none, see section 5)
└── structured/            faculties.json, departments.json, lecturers.json, programs.json, achievements.json
```

### Format of a collected page
```
---
source_url: https://www.fit.hcmus.edu.vn/gioi-thieu/thong-tin-doi-ngu     <- where the fact came from (shown as a citation)
site: fit
site_name: Khoa Công nghệ Thông tin
title: "Thông tin đội ngũ - Khoa Công Nghệ Thông Tin ..."
fetched_at: 2026-11-09T00:04:55+07:00                                     <- when it was read; the facts can be older or newer
sha256: <hash of the text>                                                 <- detects changes on the next run
---

# Thông tin đội ngũ
## Cán bộ giảng dạy - Cơ hữu
- GS.TS. Lê Hoài Bắc
- PGS.TS. Đinh Điền
...
```
Headings (`#`), paragraphs, bullet lists and tables (`cell | cell`) are kept; menus, footers, scripts, forms and sidebars are dropped.

## 3. How to collect (and refresh) the data

```powershell
pip install -r sourceCode/Database/knowledgebase/requirements.txt          # once
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py --site fit --max-pages 5    # quick trial
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py                              # all sites (about 10 minutes, mostly waiting)
python sourceCode/Database/knowledgebase/crawler/kb_extract.py                              # pages -> structured JSON rows
```
- A re-run keeps the old date of pages whose text did not change and replaces the ones that did.
- `--site <id>` collects one site only; `--max-pages N` limits each site.
- Run it **at most about once a month**; faculty pages change slowly and the sites are small servers.
- Output goes to `database/UniInfo/`, so it is easy to review with `git diff`.

### What the collector does and does NOT do (rules)
- Reads and obeys `robots.txt` (Disallow and Crawl-delay) and waits at least 2 seconds between requests.
- Identifies itself with its own User-Agent (see `sources.json`) and stops a page at 2 MB.
- Visits only public HTML pages of the same site, never logs in, never follows URLs with query strings, and skips files (PDF, Word, images, video), login/admin paths and feeds.
- Visits pages whose address or link text contains words like *giới thiệu, giảng viên, đội ngũ, bộ môn, chương trình, môn học, thành tích, nghiên cứu* first.
- **Removes e-mail addresses and phone numbers** from the saved text (privacy: the assistant must not hand them out).
- Keeps only the text, not the original HTML, images or downloads.
- Is not a bypass tool: if a site forbids a path, the crawler skips it.

## 4. How the AI uses it

1. **Load** the pages into the backend's shared academic index (uses the same `DATA_ENCRYPTION_KEY` / `RAG_DATA_DIR` as the server, so run it with the server's environment):
   ```powershell
   python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py --dry-run     # count pages first
   python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py               # index them
   ```
   Each page becomes one source named `<site>__<file>.md`; loading again replaces its chunks, never duplicates them.
2. **Ask**: `POST /api/v1/search/academic/ask` with `{"query": "Khoa CNTT gồm những chương trình nào?"}`. The backend retrieves the most similar chunks, gives them to the model, and returns the answer with citations. If the model is down it returns the matching excerpts instead (fallback mode).
3. **Ground rule**: the answer must come from the retrieved text. If nothing matches, the assistant says it has no information instead of guessing about a person.

Alternative to the loader: upload one page by hand with `POST /api/v1/search/academic/documents` (authenticated).

## 5. Limits you should know

- **Names and titles, not full profiles.** For example, the IT faculty's staff page lists names with academic titles (GS.TS., PGS.TS., TS.). Per-lecturer pages with courses taught and achievements exist only where the site publishes them as ordinary web pages, and the crawler only reaches the pages it finds by following links within the page limit.
- **Script-built pages.** A page that is drawn by JavaScript after loading contains no text for a simple downloader. The Faculty of Chemistry site is one of these: it answered with an error screen, which the crawler discards, so **no Chemistry data exists yet**. Options: ask the faculty for an export, or add a browser-based collector later.
- **PDFs are skipped** (curricula, decisions, course outlines are often PDFs). They can be added by hand with `/academic/documents`, which can read PDFs.
- **Search quality.** The index uses a lightweight offline embedding, good for Vietnamese keywords and names but not for deep paraphrases. In a trial with the collected pages, "Khoa Toán - Tin học có những ngành nào" found the right programme page, but a query naming one lecturer returned a staff page of another faculty. That is why exact lecturer and course questions should move to the structured tables in section 7.
- **Freshness.** Every page carries `fetched_at`. Timetables, teaching assignments and staff lists change each semester.
- **Accuracy is the website's.** The collector copies what the pages say. Wrong or outdated page = wrong answer. The citation (`source_url`) lets the user check.
- **Lecturer data is personal data** even when public. Keep to professional information published by the faculty, never add private details, and delete a person's entries if they ask.

## 6. Legal and ethical notes

The pages are public and are read slowly, once in a while, for a student project, with robots.txt obeyed. Content remains the property of the university and the faculties; this folder is a study index with a link back to every source. Do not republish it as a product, and re-check each site's terms before any wider use. If a faculty asks you to stop or remove something, delete the files and the index chunks.

## 7. The search-engine database schema (separate from scheduling)

The MySQL database has **two schema files**, kept apart on purpose:

| File | Holds | Table names | Data |
|---|---|---|---|
| [`../assistant_deploy/init.sql`](../assistant_deploy/init.sql) | **scheduling**: users, tasks, proposals, events, reminders, logs | `users`, `courses`, `tasks`, `events`... | private, per student, filtered by `owner_id` |
| [`search_engine_schema.sql`](search_engine_schema.sql) (this folder) | **search engine**: faculties, lecturers, courses, achievements | all start with `kb_` | public, no user data |

They share one MySQL server and one database (`university_assistant`) but no table, key or foreign key crosses from one file to the other (scheduling already has a table called `courses`; the search engine's is `kb_courses`). The scheduling file is a locked team contract; this one can change without touching it.

| Table | Purpose |
|---|---|
| `kb_sources` | every collected page (url, hash, fetch time) so each fact can cite its source |
| `kb_faculties` | the faculties (seeded: FIT, FBB, Chemistry, Math) |
| `kb_departments` | departments (bo mon) of a faculty |
| `kb_lecturers` | name, academic title, position, bio, faculty / department |
| `kb_programs` | training programmes (standard, advanced...) |
| `kb_courses` | course code, name, credits, description |
| `kb_course_lecturers` | which lecturer teaches which course (and semester) |
| `kb_achievements` | awards, publications, research of a lecturer or a faculty |

Conventions: names are stored twice (`name` and an accent-free `name_folded`, so "thay nguyen van a" finds "Nguyễn Văn A"); every fact has `source_id`; extracted rows start as `review_status = 'PENDING'` and are shown to users only when a person marks them `APPROVED`; `is_active = false` hides a lecturer who asked to be removed. `kb_courses` allows two rows with the same name and no course code (SQL treats NULLs as different), so the loader must de-duplicate those itself.

How to apply it:
- **New database:** `docker-compose.yml` mounts the file as `/docker-entrypoint-initdb.d/02_search_engine.sql`, so it runs together with `init.sql` on the first start. Each file creates what it needs, so their order does not matter.
- **Existing database** (the init scripts do not run again on an old volume):
  ```powershell
  Get-Content sourceCode/Database/knowledgebase/search_engine_schema.sql -Raw | docker exec -i schedule_db mysql -u<DB_USER> -p<DB_PASSWORD> university_assistant
  ```
  The file is idempotent (`IF NOT EXISTS`, `INSERT IGNORE`), so running it twice is safe.
- Check: `SHOW TABLES LIKE 'kb_%';` lists 8 tables, and `SELECT short_name, name FROM kb_faculties;` shows the 4 seeded faculties.

### 7.1 Filling the tables (done for the five sites)

```powershell
python sourceCode/Database/knowledgebase/crawler/kb_extract.py     # database/UniInfo/<site>/*.md  ->  database/UniInfo/structured/*.json
python sourceCode/Database/knowledgebase/crawler/kb_load.py --dry-run   # fills the tables, then rolls back, prints the counts
python sourceCode/Database/knowledgebase/crawler/kb_load.py             # rows loaded as PENDING (not shown to users yet)
python sourceCode/Database/knowledgebase/crawler/kb_load.py --approve   # after a person checked the JSON: mark them APPROVED
```
`kb_load.py` connects like the backend does (`DATABASE_URL` or `DB_*`, port 3307), so run it on the host or with `$env:DATABASE_URL` pointing at the host. It is safe to run again: rows are matched by their unique keys and updated, never duplicated. The Python models are in `sourceCode/BE/services/kb_models.py` (own base class, separate from the scheduling models).

What the extractors found (2026-11-09):

| Table | Rows | From where |
|---|---|---|
| `kb_sources` | 128 | every collected page |
| `kb_faculties` | 4 (3 with a description) | seeded by the SQL file; Chemistry has no text page |
| `kb_departments` | 12 | FIT: from "Trưởng / Phó trưởng Bộ môn X" in staff bios (5). Math: its 7 department blocks |
| `kb_lecturers` | 340 (FIT 270, Math 70) | FIT staff list and bios; Math "Đội ngũ chuyên môn". 41 have a bio, 77 a department, 17 a head position |
| `kb_programs` | 17 | FIT programme pages (standard, advanced, high quality, talented bachelor, AI, Vietnamese-French: 6) and Math programme pages (standard, English-enhanced and talented-bachelor programmes, per major: 11) |
| `kb_achievements` | 438 | FIT "Công bố khoa học": each publication is linked to the lecturers named as authors (matched by name) |
| `kb_courses`, `kb_course_lecturers` | **0** | the faculties do not publish course lists or who teaches what as web text (they are PDFs or script-built pages) |

Honest limits of these rows
- A lecturer's **bio text** keeps the faculty's own wording, including the bulleted list of subjects and research topics under it ("Môn học / lĩnh vực: ..."). The page does not say which bullets are courses and which are research topics, so they are **not** stored as courses.
- Publication authors are matched to lecturers by their name; two lecturers with the same name would be confused. A publication whose authors are nobody on the FIT list is not stored.
- Math lecturers have only a rank and department (no bio); the Math page for a programme is a description, not a list of courses. FBB and Chemistry have no lecturer pages as text, so they have no lecturers.
- Everything starts `PENDING`. Read `database/UniInfo/structured/*.json` (or a sample of the tables) before using `--approve`.

### 7.2 Still not built
The lookup code that turns "Thầy này dạy môn gì, là ai, có thành tích gì?" into a query on these tables (language-understanding intents plus parameterised queries) is the next step. Until then the same questions can be answered from the text index (section 4).

The SQL file was syntax-checked with a MySQL parser and the loader was run against SQLite, but the tables have **not been executed on a MySQL server** (no Docker on the machine that wrote them): run `search_engine_schema.sql`, then `kb_load.py --dry-run`, once on the host.

## 8. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `ModuleNotFoundError: bs4` | `pip install -r sourceCode/Database/knowledgebase/requirements.txt` |
| A site returns no pages | it may be script-built, down, or blocking the User-Agent; the crawler prints the status for each page |
| It is very slow on `hcmus` | that site asks for a 10-second delay (`Crawl-delay: 10`); lower `max_pages` for a trial |
| Loader prints `failed: [...]` | the page had no readable text; delete that file or re-crawl |
| Loader indexes but answers are empty | the server must use the same `RAG_DATA_DIR` and `DATA_ENCRYPTION_KEY` as the loader |
| Vietnamese looks garbled in the terminal | display encoding only; the files are UTF-8 |
