"""
Put the structured rows (database/UniInfo/structured/*.json, made by kb_extract.py) and the page list
(database/UniInfo/index.json) into the search-engine tables (search_engine_schema.sql).

  * safe to run again: rows are matched by their unique keys and updated, never duplicated
  * new rows get review_status = PENDING; use --approve to publish them (after a person looked at the JSON files)
  * never touches a scheduling table; uses the backend's DATABASE_URL (same rules as the server)

    python sourceCode/Database/knowledgebase/crawler/kb_load.py                 # fill the tables as PENDING
    python sourceCode/Database/knowledgebase/crawler/kb_load.py --approve       # ... and mark what was loaded APPROVED
    python sourceCode/Database/knowledgebase/crawler/kb_load.py --dry-run       # only count
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

KB_DIR = Path(__file__).resolve().parent.parent
BE_DIR = KB_DIR.parent.parent / "BE"
UNIINFO_DIR = KB_DIR.parents[2] / "database" / "UniInfo"
sys.path.insert(0, str(Path(__file__).resolve().parent))
if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from kb_crawler import fold  # noqa: E402
from services.kb_models import (  # noqa: E402
    KbAchievement, KbBase, KbDepartment, KbFaculty, KbLecturer, KbProgram, KbSource,
)

FACULTY_NAMES = {
    "fit": ("Khoa Công nghệ Thông tin", "FIT", "https://www.fit.hcmus.edu.vn/"),
    "fbb": ("Khoa Sinh học - Công nghệ Sinh học", "FBB", "https://fbb.hcmus.edu.vn/"),
    "chemistry": ("Khoa Hóa học", None, "https://chemistry.hcmus.edu.vn/"),
    "math": ("Khoa Toán - Tin học", None, "https://www.math.hcmus.edu.vn/"),
}


def folded(text: str) -> str:
    return " ".join(fold(text).split())


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def load(db: Session, uniinfo: Path = UNIINFO_DIR, approve: bool = False) -> dict:
    """returns how many rows of each kind were created or updated."""
    status = "APPROVED" if approve else "PENDING"
    counts = {"sources": 0, "faculties": 0, "departments": 0, "lecturers": 0, "programs": 0, "achievements": 0}

    # sources (one per collected page)
    source_ids: dict[str, int] = {}
    index_file = uniinfo / "index.json"
    pages = json.loads(index_file.read_text(encoding="utf-8"))["pages"] if index_file.is_file() else []
    for page in pages:
        h = hashlib.sha256(page["url"].encode()).hexdigest()
        row = db.scalar(select(KbSource).where(KbSource.url_hash == h))
        fetched = datetime.fromisoformat(page["fetched_at"]).replace(tzinfo=None) if page.get("fetched_at") else datetime(1970, 1, 1)
        if row is None:
            row = KbSource(site_id=page["site"], url=page["url"], url_hash=h)
            db.add(row)
            counts["sources"] += 1
        row.title, row.content_sha256, row.markdown_file, row.fetched_at = page.get("title"), page.get("sha256"), page.get("file"), fetched
        db.flush()
        source_ids[page["url"]] = row.id

    # faculties (seeded by the SQL file; created here when missing, e.g. on SQLite)
    faculty_ids: dict[str, int] = {}
    described = {f["site_id"]: f for f in _read(uniinfo / "structured" / "faculties.json")}
    for site, (name, short, home) in FACULTY_NAMES.items():
        row = db.scalar(select(KbFaculty).where(KbFaculty.site_id == site))
        if row is None:
            row = KbFaculty(site_id=site, name=name, name_folded=folded(name), short_name=short, home_url=home)
            db.add(row)
            counts["faculties"] += 1
        if site in described:
            row.description = described[site]["description"]
            row.source_id = source_ids.get(described[site]["source_url"])
        db.flush()
        faculty_ids[site] = row.id

    # departments
    dept_ids: dict[tuple[str, str], int] = {}
    for d in _read(uniinfo / "structured" / "departments.json"):
        fid = faculty_ids.get(d["site_id"])
        if fid is None:
            continue
        key = folded(d["name"])
        row = db.scalar(select(KbDepartment).where(KbDepartment.faculty_id == fid, KbDepartment.name_folded == key))
        if row is None:
            row = KbDepartment(faculty_id=fid, name=d["name"], name_folded=key, review_status=status)
            db.add(row)
            counts["departments"] += 1
        row.description = d.get("description") or row.description
        row.source_id = source_ids.get(d.get("source_url"), row.source_id)
        if approve:
            row.review_status = "APPROVED"
        db.flush()
        dept_ids[(d["site_id"], key)] = row.id

    # lecturers
    lecturer_ids: dict[tuple[str, str], int] = {}
    for l in _read(uniinfo / "structured" / "lecturers.json"):
        fid = faculty_ids.get(l["site_id"])
        if fid is None:
            continue
        key = folded(l["full_name"])
        row = db.scalar(select(KbLecturer).where(KbLecturer.faculty_id == fid, KbLecturer.name_folded == key))
        if row is None:
            row = KbLecturer(faculty_id=fid, full_name=l["full_name"], name_folded=key, review_status=status)
            db.add(row)
            counts["lecturers"] += 1
        row.academic_title = l.get("academic_title") or row.academic_title
        row.position = l.get("position") or row.position
        row.bio = l.get("bio") or row.bio
        row.profile_url = l.get("profile_url") or row.profile_url
        row.source_id = source_ids.get(l.get("source_url"), row.source_id)
        if l.get("department"):
            row.department_id = dept_ids.get((l["site_id"], folded(l["department"])), row.department_id)
        if approve:
            row.review_status = "APPROVED"
        db.flush()
        lecturer_ids[(l["site_id"], key)] = row.id

    # programmes
    for p in _read(uniinfo / "structured" / "programs.json"):
        fid = faculty_ids.get(p["site_id"])
        if fid is None:
            continue
        key = folded(p["name"])
        row = db.scalar(select(KbProgram).where(KbProgram.faculty_id == fid, KbProgram.name_folded == key))
        if row is None:
            row = KbProgram(faculty_id=fid, name=p["name"], name_folded=key, review_status=status)
            db.add(row)
            counts["programs"] += 1
        row.level, row.description = p.get("level"), p.get("description")
        row.source_id = source_ids.get(p.get("source_url"), row.source_id)
        if approve:
            row.review_status = "APPROVED"

    # achievements (publications); identified by lecturer + year + title so re-runs do not duplicate
    for a in _read(uniinfo / "structured" / "achievements.json"):
        lid = lecturer_ids.get((a["site_id"], folded(a["lecturer"])))
        if lid is None:
            continue
        exists = db.scalar(select(KbAchievement.id).where(KbAchievement.lecturer_id == lid, KbAchievement.year == a.get("year"),
                                                          KbAchievement.title == a["title"]))
        if exists:
            continue
        db.add(KbAchievement(lecturer_id=lid, kind=a.get("kind", "OTHER"), year=a.get("year"), title=a["title"], details=a.get("details"),
                             source_id=source_ids.get(a.get("source_url")), review_status=status))
        counts["achievements"] += 1
    db.flush()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--approve", action="store_true", help="mark loaded rows APPROVED (publish them to users)")
    ap.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    ap.add_argument("--uniinfo", type=Path, default=UNIINFO_DIR)
    args = ap.parse_args()
    from database import engine  # the backend's connection (DATABASE_URL / .env), imported late

    with Session(engine) as db:
        counts = load(db, args.uniinfo, args.approve)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    print(("would create (dry run)" if args.dry_run else "created"), counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
