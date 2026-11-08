# knowledgebase: public university information for the AI

This folder holds the **public information about the university** that the assistant uses to answer questions such as
*"Thầy này dạy môn gì, là ai, có thành tích gì?"* or *"Khoa này gồm những môn nào?"*.
It is filled by a polite web collector (`crawler/`) from the five official websites below. It contains **no student data**
(that is in [`../user_data`](../user_data/README.md)).

```
 official websites ──► crawler/kb_crawler.py ──► data/<site>/*.md + data/index.json ──► load_into_backend_kb.py ──► backend search index ──► AI answer + source link
   (public pages)         (robots.txt obeyed)        (readable text, contacts removed)        (one-time / on refresh)        (/api/v1/search/academic/ask)
```

## 1. Sources

| Site id | Website | What it is | Pages collected (2026-11-09) | robots.txt (checked 2026-11-09) |
|---|---|---|---|---|
| `hcmus` | https://hcmus.edu.vn/ | University (Trường ĐH Khoa học Tự nhiên, ĐHQG-HCM): organisation, councils, faculties and institutes | **8** (limit 12) | `Crawl-delay: 10`, nothing disallowed. The crawler waits 10 s per request, so this site is slow. Most of its other pages are short news notices with too little text, so the run was stopped at 8 useful pages. |
| `fit` | https://www.fit.hcmus.edu.vn/ | Faculty of Information Technology: staff list, programmes (standard, advanced...), news and achievements | **40** | none published (the server answers an HTML error page) |
| `fbb` | https://fbb.hcmus.edu.vn/ | Faculty of Biology - Biotechnology | **40** | disallows `/admin/`, `/cache/`, `/includes/`... and query URLs |
| `chemistry` | https://chemistry.hcmus.edu.vn/ | Faculty of Chemistry | **1** (home page only) | disallows `/api/account`, `/api/users/`, `/management/`. The site is built by scripts in the browser, so a simple downloader sees almost no text (see section 5). |
| `math` | https://www.math.hcmus.edu.vn/ | Faculty of Mathematics and Computer Science: programmes, staff, departments | **40** | none published |

Total: **129 pages, about 940,000 characters, 1.4 MB**, which the loader turns into about 3,300 searchable chunks.

The list, the page limits and the keywords that decide which pages are visited first are in [`sources.json`](sources.json).
The exact result of the last run (how many pages per site, when, size, hash) is in [`data/index.json`](data/index.json).

## 2. Folder layout

```
knowledgebase/
├── README.md              this file
├── sources.json           sites, limits, user agent, priority keywords, skipped file types
├── requirements.txt       beautifulsoup4 (only needed for collecting, not for the backend)
├── crawler/
│   ├── README.md
│   ├── kb_crawler.py      the collector
│   └── load_into_backend_kb.py   puts the collected pages into the backend search index
└── data/                  OUTPUT of the crawler (do not edit by hand)
    ├── README.md
    ├── index.json         every collected page: site, url, title, file, fetched_at, sha256, chars
    ├── hcmus/ fit/ fbb/ chemistry/ math/    one Markdown file per page
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
```
- A re-run keeps the old date of pages whose text did not change and replaces the ones that did.
- `--site <id>` collects one site only; `--max-pages N` limits each site.
- Run it **at most about once a month**; faculty pages change slowly and the sites are small servers.
- Output stays in this folder, so it is easy to review with `git diff`.

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
- **Script-built pages.** A page that is drawn by JavaScript after loading contains almost no text for a simple downloader. The Faculty of Chemistry site is one of these, so few or no pages could be collected from it; the crawler logs "too little text" for such pages. Options: ask the faculty for an export, or add a browser-based collector later.
- **PDFs are skipped** (curricula, decisions, course outlines are often PDFs). They can be added by hand with `/academic/documents`, which can read PDFs.
- **Search quality.** The index uses a lightweight offline embedding, good for Vietnamese keywords and names but not for deep paraphrases. In a trial with the collected pages, "Khoa Toán - Tin học có những ngành nào" found the right programme page, but a query naming one lecturer returned a staff page of another faculty. That is why exact lecturer and course questions should move to the structured tables in section 7.
- **Freshness.** Every page carries `fetched_at`. Timetables, teaching assignments and staff lists change each semester.
- **Accuracy is the website's.** The collector copies what the pages say. Wrong or outdated page = wrong answer. The citation (`source_url`) lets the user check.
- **Lecturer data is personal data** even when public. Keep to professional information published by the faculty, never add private details, and delete a person's entries if they ask.

## 6. Legal and ethical notes

The pages are public and are read slowly, once in a while, for a student project, with robots.txt obeyed. Content remains the property of the university and the faculties; this folder is a study index with a link back to every source. Do not republish it as a product, and re-check each site's terms before any wider use. If a faculty asks you to stop or remove something, delete the files and the index chunks.

## 7. Next step: structured tables (planned)

Plain text is good for "tell me about this faculty". Exact questions ("which courses does lecturer X teach?") are answered better from tables. The plan, once the team agrees to change the locked schema:

| Table | Main columns |
|---|---|
| `faculties` | name, `name_folded` (no accents), url, description |
| `lecturers` | faculty, full name, `name_folded`, degree/title, position, bio, source_url |
| `courses` | faculty, code, name, `name_folded`, credits, description, source_url |
| `course_lecturers` | course, lecturer, semester |
| `achievements` | lecturer, kind (award / publication / research), year, text, source_url |

The Markdown files here are the raw material: a parser per site fills the tables, a person reviews them, and the assistant's language-understanding step maps questions to fixed, parameterised queries (the model never writes SQL).

## 8. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `ModuleNotFoundError: bs4` | `pip install -r sourceCode/Database/knowledgebase/requirements.txt` |
| A site returns no pages | it may be script-built, down, or blocking the User-Agent; the crawler prints the status for each page |
| It is very slow on `hcmus` | that site asks for a 10-second delay (`Crawl-delay: 10`); lower `max_pages` for a trial |
| Loader prints `failed: [...]` | the page had no readable text; delete that file or re-crawl |
| Loader indexes but answers are empty | the server must use the same `RAG_DATA_DIR` and `DATA_ENCRYPTION_KEY` as the loader |
| Vietnamese looks garbled in the terminal | display encoding only; the files are UTF-8 |
