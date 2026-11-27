"""
QA: data-quality measurements of the university knowledge base (tables kb_*) in the backend MySQL database.

Standard / method : ISO/IEC 25012 (data quality model) and ISO/IEC 25024 (measurement); ISO 8000-8.
                    Dimensions: completeness, uniqueness, consistency, credibility (grounding in the cited source page),
                    currentness, privacy (no contact data), review status, coverage.
Run               : python "QA  docs/kb_quality.py"          (MySQL must be running; credentials are read from
                    sourceCode/Database/assistant_deploy/.env, or from the DATABASE_URL environment variable)
Outputs           : printed report, QA  docs/kb_quality_results.json, QA  docs/kb_sample_for_review.csv
                    (a seeded random sample that a human checks against the source page; two reviewers -> Cohen's kappa)
Read-only: the script never writes to the database.
"""
import csv
import json
import math
import os
import random
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import pymysql

QA_DIR = Path(__file__).resolve().parent
ROOT = next(p for p in QA_DIR.resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())
UNIINFO = ROOT / "database" / "UniInfo"
SAMPLE_SIZE = 110  # plan minimum 100, +10%
SEED = 20261119


def load_env() -> dict:
    env = {}
    path = ROOT / "sourceCode" / "Database" / "assistant_deploy" / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)", line)
            if m and not line.lstrip().startswith("#"):
                env[m.group(1)] = m.group(2).strip().strip('"')
    return env


def connect():
    env = load_env()
    return pymysql.connect(host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "3307")),
                           user=env.get("DB_USER", "root"), password=env.get("DB_PASSWORD", ""),
                           database=os.getenv("DB_NAME", "university_assistant"), charset="utf8mb4")


def fold(text: str) -> str:
    nfd = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return re.sub(r"\s+", " ", "".join(c for c in nfd if unicodedata.category(c) != "Mn")).strip()


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0 rows)"
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.1%}  [95% CI {lo:.1%} to {hi:.1%}]"


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# a Vietnamese phone number; the look-behind skips digit groups inside DOI/ISSN strings such as 10.1007/s10618-025-01168-6
PHONE = re.compile(r"(?<![\d/.\-])(?:\+?84|0)(?:[\s.-]?\d){8,10}(?![\d\-])")


def main() -> int:
    try:
        db = connect()
    except Exception as exc:  # noqa: BLE001
        print("cannot connect to MySQL:", type(exc).__name__, str(exc)[:100])
        return 2
    cur = db.cursor(pymysql.cursors.DictCursor)

    def q(sql, args=None):
        cur.execute(sql, args or ())
        return cur.fetchall()

    def one(sql, args=None):
        return list(q(sql, args)[0].values())[0]

    R: dict = {"measured_at": datetime.now().isoformat(timespec="seconds"), "tables": {}, "checks": {}}
    print(f"# KB data quality  {R['measured_at']}  (database {os.getenv('DB_NAME', 'university_assistant')})\n")

    # ---------------------------------------------------------------- volume and review status
    print("## 1. Volume and review status")
    tables = ["kb_sources", "kb_faculties", "kb_departments", "kb_lecturers", "kb_programs", "kb_courses", "kb_course_lecturers", "kb_achievements"]
    for t in tables:
        n = one(f"SELECT COUNT(*) FROM {t}")
        status = {r["review_status"]: r["c"] for r in q(f"SELECT review_status, COUNT(*) c FROM {t} GROUP BY review_status")} if t not in ("kb_sources", "kb_faculties") else {}
        R["tables"][t] = {"rows": n, "review_status": status}
        print(f"  {t:22} rows={n:5}  {status if status else ''}")

    # ---------------------------------------------------------------- completeness
    print("\n## 2. Completeness (share of rows with the field filled)")
    spec = {
        "kb_lecturers": ["academic_title", "position", "bio", "profile_url", "department_id", "source_id"],
        "kb_programs": ["level", "description", "source_id"],
        "kb_departments": ["description", "source_id"],
        "kb_faculties": ["short_name", "home_url", "description"],
        "kb_sources": ["title", "markdown_file", "content_sha256"],
        "kb_achievements": ["year", "details", "source_id"],
    }
    R["checks"]["completeness"] = {}
    for t, cols in spec.items():
        n = R["tables"][t]["rows"]
        for c in cols:
            filled = one(f"SELECT COUNT(*) FROM {t} WHERE `{c}` IS NOT NULL AND `{c}` <> ''")
            R["checks"]["completeness"][f"{t}.{c}"] = {"filled": filled, "n": n}
            print(f"  {t}.{c:16} {pct(filled, n)}")

    # ---------------------------------------------------------------- uniqueness
    print("\n## 3. Uniqueness")
    dup_lect = q("SELECT name_folded, COUNT(*) c, COUNT(DISTINCT faculty_id) f FROM kb_lecturers GROUP BY name_folded HAVING c > 1")
    dup_hash = q("SELECT content_sha256, COUNT(*) c FROM kb_sources WHERE content_sha256 IS NOT NULL GROUP BY content_sha256 HAVING c > 1")
    dup_ach = q("SELECT lecturer_id, faculty_id, title, COUNT(*) c FROM kb_achievements GROUP BY lecturer_id, faculty_id, title HAVING c > 1")
    R["checks"]["uniqueness"] = {"lecturer_names_repeated": len(dup_lect), "identical_page_content": len(dup_hash), "duplicate_achievements": len(dup_ach)}
    print(f"  lecturer names that occur more than once : {len(dup_lect)}  (same person under two faculties, or two people with one name; needs a human look)")
    print(f"  source pages with identical content hash  : {len(dup_hash)}")
    print(f"  achievements duplicated (same owner+title): {len(dup_ach)}")

    # ---------------------------------------------------------------- consistency
    print("\n## 4. Consistency")
    orphan_dept = one("SELECT COUNT(*) FROM kb_lecturers l LEFT JOIN kb_departments d ON d.id = l.department_id WHERE l.department_id IS NOT NULL AND d.id IS NULL")
    dept_faculty_mismatch = one("SELECT COUNT(*) FROM kb_lecturers l JOIN kb_departments d ON d.id = l.department_id WHERE d.faculty_id <> l.faculty_id")
    ach_no_owner = one("SELECT COUNT(*) FROM kb_achievements WHERE lecturer_id IS NULL AND faculty_id IS NULL")
    ach_bad_year = one("SELECT COUNT(*) FROM kb_achievements WHERE year IS NOT NULL AND (year < 1950 OR year > YEAR(NOW()) + 1)")
    no_source = {t: one(f"SELECT COUNT(*) FROM {t} WHERE source_id IS NULL") for t in ("kb_lecturers", "kb_programs", "kb_departments", "kb_achievements")}
    bad_url = one("SELECT COUNT(*) FROM kb_lecturers WHERE profile_url IS NOT NULL AND profile_url <> '' AND profile_url NOT REGEXP '^https?://'")
    R["checks"]["consistency"] = {"lecturer_department_orphans": orphan_dept, "lecturer_department_faculty_mismatch": dept_faculty_mismatch,
                                   "achievements_without_owner": ach_no_owner, "achievements_year_out_of_range": ach_bad_year,
                                   "rows_without_source": no_source, "lecturer_profile_url_not_http": bad_url}
    print(f"  lecturers pointing to a missing department : {orphan_dept}")
    print(f"  lecturer's department belongs to another faculty: {dept_faculty_mismatch}")
    print(f"  achievements without lecturer or faculty   : {ach_no_owner}")
    print(f"  achievements with year outside 1950..now+1 : {ach_bad_year}")
    print(f"  rows without a cited source                : {no_source}")
    print(f"  lecturer profile_url that is not http(s)   : {bad_url}")

    # ---------------------------------------------------------------- privacy
    print("\n## 5. Privacy (the README promises that contact details were removed)")
    leaks = {}
    for t, cols in {"kb_lecturers": ["bio", "position", "profile_url", "full_name"], "kb_departments": ["description"], "kb_programs": ["description"],
                    "kb_faculties": ["description"], "kb_achievements": ["title", "details"]}.items():
        for c in cols:
            rows = q(f"SELECT id, `{c}` AS v FROM {t} WHERE `{c}` IS NOT NULL")
            e = sum(1 for r in rows if EMAIL.search(r["v"] or ""))
            p = sum(1 for r in rows if PHONE.search(r["v"] or ""))
            if e or p:
                leaks[f"{t}.{c}"] = {"email": e, "phone": p}
    R["checks"]["privacy_contact_leaks"] = leaks
    print("  fields that still contain an e-mail or phone number:", leaks if leaks else "none")

    # ---------------------------------------------------------------- credibility: is the entity in its cited page?
    print("\n## 6. Credibility: entity name appears in the cited source page (automatic grounding check)")
    src = {r["id"]: r for r in q("SELECT id, site_id, markdown_file, url FROM kb_sources")}
    page_cache: dict[int, str | None] = {}

    def page_text(sid):
        if sid not in page_cache:
            s = src.get(sid)
            path = UNIINFO / s["markdown_file"] if s and s["markdown_file"] else None  # markdown_file already starts with the site folder
            page_cache[sid] = fold(path.read_text(encoding="utf-8", errors="replace")) if path and path.is_file() else None
        return page_cache[sid]

    R["checks"]["grounding"] = {}
    for t, namecol in (("kb_lecturers", "full_name"), ("kb_programs", "name"), ("kb_departments", "name")):
        rows = q(f"SELECT id, `{namecol}` AS name, source_id FROM {t} WHERE source_id IS NOT NULL")
        found = checked = missing_file = 0
        misses = []
        for r in rows:
            txt = page_text(r["source_id"])
            if txt is None:
                missing_file += 1
                continue
            checked += 1
            if fold(r["name"]) in txt:
                found += 1
            elif len(misses) < 5:
                misses.append(r["name"])
        R["checks"]["grounding"][t] = {"found": found, "checked": checked, "source_file_missing": missing_file, "examples_not_found": misses}
        print(f"  {t:14} name found in source page: {pct(found, checked)}   (source file missing: {missing_file})")
        if misses:
            print(f"                 not found, e.g.: {misses}")

    # ---------------------------------------------------------------- currentness
    print("\n## 7. Currentness")
    lo, hi = one("SELECT MIN(fetched_at) FROM kb_sources"), one("SELECT MAX(fetched_at) FROM kb_sources")
    age = (datetime.now() - hi).days if hi else None
    R["checks"]["currentness"] = {"oldest_fetch": str(lo), "newest_fetch": str(hi), "newest_age_days": age}
    print(f"  pages fetched between {lo} and {hi}; the newest is {age} days old")

    # ---------------------------------------------------------------- coverage
    print("\n## 8. Coverage")
    per_site = {r["site_id"]: r["c"] for r in q("SELECT site_id, COUNT(*) c FROM kb_sources GROUP BY site_id")}
    fac = q("SELECT f.site_id, f.name, (SELECT COUNT(*) FROM kb_lecturers l WHERE l.faculty_id = f.id) lecturers, (SELECT COUNT(*) FROM kb_programs p WHERE p.faculty_id = f.id) programs, (SELECT COUNT(*) FROM kb_courses c WHERE c.faculty_id = f.id) courses FROM kb_faculties f")
    R["checks"]["coverage"] = {"pages_per_site": per_site, "faculties": fac}
    print(f"  pages per site: {per_site}")
    for f in fac:
        print(f"  faculty {f['site_id']:10} lecturers={f['lecturers']:4} programs={f['programs']:3} courses={f['courses']:3}")
    n_courses = R["tables"]["kb_courses"]["rows"]
    print(f"  kb_courses has {n_courses} rows" + ("  -> structured questions such as 'which courses does this faculty teach' cannot be answered from the tables" if n_courses == 0 else ""))

    # ---------------------------------------------------------------- sample for human review
    print("\n## 9. Human review sample")
    rng = random.Random(SEED)
    cand = []
    for t, namecol, extra in (("kb_lecturers", "full_name", "academic_title"), ("kb_programs", "name", "level"), ("kb_departments", "name", "description")):
        for r in q(f"SELECT id, `{namecol}` AS name, `{extra}` AS extra, source_id FROM {t} WHERE source_id IS NOT NULL"):
            cand.append((t, r["id"], r["name"], r["extra"] or "", src.get(r["source_id"], {}).get("url", "")))
    sample = rng.sample(cand, min(SAMPLE_SIZE, len(cand)))
    out = QA_DIR / "kb_sample_for_review.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["table", "id", "name", "detail", "source_url", "reviewer1_correct(Y/N)", "reviewer2_correct(Y/N)", "note"])
        for row in sample:
            w.writerow([*row, "", "", ""])
    R["checks"]["review_sample"] = {"size": len(sample), "seed": SEED, "file": out.name}
    print(f"  wrote {len(sample)} rows to {out.name}; two reviewers fill the Y/N columns, then compute Cohen's kappa and the share of Y")

    (QA_DIR / "kb_quality_results.json").write_text(json.dumps(R, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("\nresults written to kb_quality_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
