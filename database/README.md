# database

Data files that are **not code**.

| Folder | What it holds |
|---|---|
| [`UniInfo/`](UniInfo/README.md) | Public information about the university collected from the HCMUS websites: one Markdown file per page, `index.json`, and `structured/*.json` (lecturers, departments, programmes, publications, research groups) ready to load into the `kb_*` tables. |

The code that produces and loads these files, and the MySQL schema, are in
[`../sourceCode/Database/knowledgebase`](../sourceCode/Database/knowledgebase/README.md); the Docker setup and the scheduling
schema are in [`../sourceCode/Database`](../sourceCode/Database/README.md). Private student data is **never** stored here
(see [`../sourceCode/Database/user_data`](../sourceCode/Database/user_data/README.md)).
