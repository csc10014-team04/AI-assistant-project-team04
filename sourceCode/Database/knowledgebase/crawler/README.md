# crawler

Tools that fill and use the knowledge base. Run everything from the repository root.

| File | Purpose |
|---|---|
| `kb_crawler.py` | Polite collector: reads each site's `robots.txt`, visits the most useful pages first, saves readable text as Markdown into `../data/<site>/` and updates `../data/index.json`. |
| `load_into_backend_kb.py` | Feeds the collected Markdown into the backend's academic search index so the AI can answer from it. |

```powershell
pip install -r sourceCode/Database/knowledgebase/requirements.txt
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py --site fit --max-pages 5     # trial
python sourceCode/Database/knowledgebase/crawler/kb_crawler.py                              # everything in sources.json
python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py --dry-run          # see what would be indexed
python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py                    # index it
```
Details, rules and limits: see [`../README.md`](../README.md).
