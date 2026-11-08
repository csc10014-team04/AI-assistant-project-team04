"""
Feed the collected knowledge-base pages into the backend's shared academic search index, so
POST /api/v1/search/academic/ask can answer from them (retrieval-augmented generation).

Each Markdown page becomes one indexed source named "<site>__<file>.md"; running it again replaces that
page's chunks instead of duplicating them. The index is encrypted with the backend's DATA_ENCRYPTION_KEY, so run
this with the SAME environment (RAG_DATA_DIR, DATA_ENCRYPTION_KEY) as the server.

    python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py --dry-run
    python sourceCode/Database/knowledgebase/crawler/load_into_backend_kb.py --site fit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent
BE_DIR = KB_DIR.parent.parent / "BE"
DATA_DIR = KB_DIR / "data"


def load(data_dir: Path = DATA_DIR, site: str | None = None, dry_run: bool = False, rag_dir: Path | None = None) -> dict:
    """returns {"pages": n, "chunks": n, "failed": [(file, reason)]}"""
    if str(BE_DIR) not in sys.path:
        sys.path.insert(0, str(BE_DIR))
    from services.search_engine import ingest_academic_document  # imported late: needs the backend packages

    result = {"pages": 0, "chunks": 0, "failed": []}
    for md in sorted(data_dir.glob("*/*.md")):
        if site and md.parent.name != site:
            continue
        name = f"{md.parent.name}__{md.name}"
        if dry_run:
            result["pages"] += 1
            continue
        try:
            result["chunks"] += ingest_academic_document(md.read_bytes(), name, directory=rag_dir)
            result["pages"] += 1
        except ValueError as exc:  # unreadable or empty page
            result["failed"].append((name, str(exc)))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site")
    ap.add_argument("--dry-run", action="store_true", help="only count the pages that would be indexed")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = ap.parse_args()
    out = load(args.data_dir, args.site, args.dry_run)
    print(("would index" if args.dry_run else "indexed"), f"{out['pages']} pages, {out['chunks']} chunks; failed: {out['failed']}")
    return 1 if out["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
