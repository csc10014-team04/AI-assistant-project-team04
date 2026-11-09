# crawler

Tools that fill and use the knowledge base. Run everything from the repository root. The collected data lives in
[`database/UniInfo/`](../../../../database/UniInfo/README.md).

| File | Purpose |
|---|---|
| `kb_crawler.py` | 1. Polite collector: reads each site's `robots.txt`, visits the most useful pages first, saves readable text as Markdown into `database/UniInfo/<site>/` and updates `index.json`. |
| `kb_extract.py` | 2. Reads those pages and writes structured rows (lecturers, departments, programmes, publications) to `database/UniInfo/structured/*.json`. |
| `kb_load.py` | 3. Loads the structured rows into the `kb_*` MySQL tables (`search_engine_schema.sql`), as `PENDING` or `--approve`. |
| `load_into_backend_kb.py` | Alternative: feeds the Markdown pages into the backend's text search index (no tables needed). |

```powershell
pip install -r sourceCode/Database/knowledgebase/requirements.txt
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py --site fit --max-pages 5     # trial
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py                              # everything in sources.json
python sourceCode/Database/knowledgebase/crawler/kb_extract.py                              # pages -> JSON
python sourceCode/Database/knowledgebase/crawler/kb_load.py --dry-run                       # JSON -> tables, rolled back
python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py --dry-run          # pages -> text index (count only)
```
Details, rules and limits: see [`../README.md`](../README.md).
