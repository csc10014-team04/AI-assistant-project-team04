# UniInfo: collected public information about the university

**Output of the crawler** (`sourceCode/Database/knowledgebase/crawler/`). Do not edit by hand: re-run the tools instead.
Rules, sources and limits are in [`sourceCode/Database/knowledgebase/README.md`](../../sourceCode/Database/knowledgebase/README.md).

| Path | What it is |
|---|---|
| `<site id>/<page>.md` | one collected page. Starts with a front-matter block (`source_url`, `site`, `site_name`, `title`, `fetched_at`, `sha256`), then the page text |
| `index.json` | list of every collected page (site, url, title, file, fetched_at, sha256, size) |
| `structured/*.json` | rows extracted from the pages, ready for the `kb_*` tables: `faculties`, `departments`, `lecturers`, `programs`, `achievements` (each row has a `source_url`) |

Site ids: `hcmus` (university), `fit` (Information Technology), `fbb` (Biology - Biotechnology), `math` (Mathematics and Computer Science). `chemistry` has no folder: its site returned only an error screen.

Phone numbers and e-mail addresses were removed from the text when it was saved. Only public pages were read, with `robots.txt` obeyed.

Refresh: `kb_crawler.py` (pages), then `kb_extract.py` (structured JSON), then `kb_load.py` (MySQL).
