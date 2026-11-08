"""
Turn the collected Markdown pages (database/UniInfo/<site>/*.md) into structured rows for the search-engine tables
(search_engine_schema.sql): faculties, departments, lecturers, programs and achievements (publications).

Output: database/UniInfo/structured/*.json  (plain, reviewable files; nothing is written to a database here)
Then: kb_load.py puts them into MySQL as review_status = PENDING (or APPROVED with --approve).

Design rules
  * one small extractor per page family, each tested on a fixture; a page that does not look like its family is skipped
  * only facts the page states are copied; nothing is inferred except the department of a person ("Trưởng Bộ môn X")
  * every row keeps `source_url` so an answer can cite its page
  * what the sites do NOT publish as text is left empty (course lists are in PDFs; see knowledgebase/README.md)

    python sourceCode/Database/knowledgebase/crawler/kb_extract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = KB_DIR.parents[2] / "database" / "UniInfo"
OUT_DIR = DATA_DIR / "structured"
SEP = chr(10) + "---" + chr(10)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_crawler import fold, parse_front_matter  # noqa: E402

TITLE_RE = re.compile(r"^((?:(?:GS|PGS)\.\s*)?(?:TS|ThS|CN|KS|BS)\.|(?:GS|PGS)\.)\s*(\S.*)$")
HEAD_ROLE_RE = re.compile(r"(Phó\s+trưởng|Phó\s+Trưởng|Trưởng)\s+[Bb]ộ\s+môn\s+([^.,;]+?)(?=\.|,|;|\s+(?:Khoa|của|tại|và)\b|$)")


# ----------------------------------------------------------------------------- small helpers
def split_title(text: str) -> tuple[str | None, str]:
    """'PGS. TS. Đinh Điền' -> ('PGS.TS.', 'Đinh Điền'); a name without a title -> (None, name)."""
    text = re.sub(r"\s+", " ", text).strip(" -•\t")
    m = TITLE_RE.match(text)
    if not m:
        return None, text
    return re.sub(r"\s+", "", m.group(1)), m.group(2).strip()


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(fold(re.sub(r"[^\w\s]", " ", name)).split())


def page_body(md: str) -> tuple[dict, str]:
    meta = parse_front_matter(md)
    return meta, md.split(SEP, 1)[-1]


def first_paragraph(body: str, min_chars: int = 80) -> str:
    for line in body.splitlines():
        s = line.strip()
        if len(s) >= min_chars and not s.startswith(("#", "-", "|", "http")):
            return s[:1500]
    return ""


# ----------------------------------------------------------------------------- extractors (pure functions)
def extract_fit_staff_list(body: str) -> list[dict]:
    """FIT 'Thông tin đội ngũ': bullet lines such as '- PGS.TS. Đinh Điền' -> lecturers with a title."""
    out = []
    for line in body.splitlines():
        if not line.startswith("- "):
            continue
        title, name = split_title(line[2:])
        if title and 2 <= len(name.split()) <= 6 and not re.search(r"\d", name):
            out.append({"full_name": name, "academic_title": title})
    return out


def extract_fit_bios(body: str) -> list[dict]:
    """FIT 'Đội ngũ giảng viên': '<title> <name> hiện là <role>. ...' paragraph, optional profile link, bullet topics."""
    lines = body.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^((?:(?:GS|PGS)\.\s*)?(?:TS|ThS)?\.?)\s*((?:[A-ZĐÀ-Ỹ][\wà-ỹ'-]*\s+){1,5}[A-ZĐÀ-Ỹ][\wà-ỹ'-]*)\s+hiện\s+(?:là|đang|công tác)", line)
        if not m or not re.match(r"^(GS|PGS|TS|ThS)", line):
            continue
        title, name = split_title(line[: m.end(2)])
        profile, topics = None, []
        for nxt in lines[i + 1 : i + 40]:
            if re.match(r"^(GS|PGS|TS|ThS)\.?\s.*\bhiện\b", nxt):
                break
            if nxt.startswith("- "):
                topics.append(nxt[2:].strip())
            elif nxt.startswith("http") and profile is None:
                profile = nxt.strip()
        role = HEAD_ROLE_RE.search(line)
        bio = line.strip()[:1200]
        if topics:
            bio += " Môn học / lĩnh vực: " + "; ".join(topics[:20]) + "."
        out.append({"full_name": name, "academic_title": title, "bio": bio, "profile_url": profile,
                    "position": f"{role.group(1).capitalize()} bộ môn {role.group(2).strip()}" if role else None,
                    "department": role.group(2).strip() if role else None})
    return out


def extract_math_departments(body: str) -> tuple[list[dict], list[dict]]:
    """Math faculty 'Đội ngũ chuyên môn': '### Bộ môn X' blocks with '#### <title> <name>' members and a rank line."""
    depts: list[dict] = []
    people: list[dict] = []
    lines = body.splitlines()
    current: dict | None = None
    for i, line in enumerate(lines):
        if line.startswith("### Bộ môn"):
            current = {"name": re.sub(r"^###\s*Bộ môn\s*", "", line).strip(), "description": "", "heads": ""}
            for nxt in lines[i + 1 : i + 8]:
                if nxt.startswith("#"):
                    break
                if nxt.startswith("Trưởng bộ môn") or nxt.startswith("Phó"):
                    current["heads"] = nxt
                elif not nxt.startswith("Phòng") and len(nxt) > 20:
                    current["description"] = ("Hướng chuyên môn: " + nxt.strip())[:600]
            depts.append(current)
        elif line.startswith("#### ") and current is not None:
            title, name = split_title(line[5:])
            if not title or not (2 <= len(name.split()) <= 6):
                continue
            rank = next((x.strip() for x in lines[i + 1 : i + 3] if x.strip() and not x.startswith("#")), "")
            heads = current["heads"]
            full = f"{title} {name}"
            position = None
            if re.search(rf"Phó\s+[Tt]rưởng\s+bộ\s+môn\s+{re.escape(full)}", heads):
                position = "Phó trưởng bộ môn " + current["name"]
            elif re.search(rf"Trưởng\s+bộ\s+môn\s+{re.escape(full)}", heads):
                position = "Trưởng bộ môn " + current["name"]
            people.append({"full_name": name, "academic_title": title, "department": current["name"], "position": position,
                           "bio": f"{rank} - Bộ môn {current['name']}." if rank and len(rank) < 60 else None})
    return [{"name": d["name"], "description": d["description"]} for d in depts], people


def extract_program(site_id: str, url: str, title: str, body: str) -> dict | None:
    """a programme page (FIT / Math): name from the page, first real paragraph as description."""
    clean = re.sub(r"\s*-\s*Khoa.*$", "", title).strip()
    clean = re.sub(r"^Khoa Toán - Tin học - ", "", clean).strip()
    if not clean:
        return None
    para = first_paragraph(body)
    code = re.search(r"Mã ngành\s+(\d{6,8}\w*)", body)
    if code:
        para = f"{para} Mã ngành {code.group(1)}.".strip()
    if len(para) < 40:
        return None
    return {"name": clean, "level": "undergraduate", "description": para}


def extract_publications(body: str) -> list[dict]:
    """FIT 'Công bố khoa học': year headings followed by bullet entries; structured entries list authors on the next line."""
    pubs: list[dict] = []
    lines = body.splitlines()
    year: int | None = None
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if re.fullmatch(r"(19|20)\d{2}", s):
            year = int(s)
        elif s.startswith("- ") and year:
            block = [lines[i][2:].strip()]
            j = i + 1
            while j < len(lines) and not lines[j].startswith("- ") and not re.fullmatch(r"(19|20)\d{2}", lines[j].strip()) and not lines[j].startswith("#"):
                block.append(lines[j].strip())
                j += 1
            authors, title, venue = "", block[0], ""
            if len(block) >= 4 and ";" in block[1] or (len(block) >= 3 and "," in block[1] and len(block[1]) < 200 and block[1] in block[0]):
                authors, title, venue = block[1], block[2], " ".join(block[3:])
            pubs.append({"year": year, "authors": authors, "title": title[:480], "details": venue[:900], "raw": block[0][:1200]})
            i = j
            continue
        i += 1
    return pubs


def match_lecturers(pub: dict, lecturers: list[dict]) -> list[dict]:
    """lecturers named as authors: SCOPUS style 'Le, Bac Hoai' (same words, any order) or a plain 'Vo Hoai Viet' inside the text."""
    found: list[dict] = []
    author_sets = [name_tokens(a) for a in pub["authors"].split(";") if a.strip()] if pub["authors"] else []
    folded_raw = " " + fold(re.sub(r"[^\w\s]", " ", pub["raw"])) + " "
    for lec in lecturers:
        toks = name_tokens(lec["full_name"])
        if len(toks) < 2:
            continue
        if toks in author_sets or (not author_sets and " " + " ".join(fold(lec["full_name"]).split()) + " " in folded_raw):
            found.append(lec)
    return found


# ----------------------------------------------------------------------------- driver
def build(data_dir: Path = DATA_DIR) -> dict[str, list[dict]]:
    pages: dict[str, tuple[dict, str]] = {}
    for md in sorted(data_dir.glob("*/*.md")):
        meta, body = page_body(md.read_text(encoding="utf-8"))
        if "source_url" in meta:
            pages[meta["source_url"]] = (meta, body)

    def find(site: str, *needles: str):
        for url, (meta, body) in pages.items():
            if meta.get("site") == site and all(n in url for n in needles):
                return url, meta, body
        return None

    faculties, depts, lecturers, programs, achievements = [], [], {}, [], []

    def add_lecturer(site: str, url: str, row: dict) -> None:
        key = (site, " ".join(fold(row["full_name"]).split()))
        cur = lecturers.setdefault(key, {"site_id": site, "full_name": row["full_name"], "academic_title": None, "department": None,
                                         "position": None, "bio": None, "profile_url": None, "source_url": url})
        for field in ("academic_title", "department", "position", "bio", "profile_url"):
            if row.get(field) and not cur.get(field):
                cur[field] = row[field]

    # faculty descriptions: one explicit "about" page per faculty (chemistry's site is script-built: no text page exists)
    about = {"fit": "https://www.fit.hcmus.edu.vn/gioi-thieu-chung",
             "math": "https://www.math.hcmus.edu.vn/gioi-thieu",
             "fbb": "https://fbb.hcmus.edu.vn/ve-khoa-sinh-hoc-cong-nghe-sinh-hoc.html"}
    for site, url in about.items():
        if url in pages:
            para = first_paragraph(pages[url][1], 100)
            if para:
                faculties.append({"site_id": site, "description": para, "source_url": url})

    # FIT lecturers
    fit_list = find("fit", "thong-tin-doi-ngu")
    if fit_list:
        for row in extract_fit_staff_list(fit_list[2]):
            add_lecturer("fit", fit_list[0], row)
    fit_bios = find("fit", "sau-dai-hoc", "giang-vien")
    if fit_bios:
        for row in extract_fit_bios(fit_bios[2]):
            add_lecturer("fit", fit_bios[0], row)
            if row.get("department"):
                depts.append({"site_id": "fit", "name": row["department"], "description": "", "source_url": fit_bios[0]})

    # Math departments and lecturers (Vietnamese page only)
    math_page = next(((u, m, b) for u, (m, b) in pages.items() if m.get("site") == "math" and u.endswith("/gioi-thieu/doi-ngu-chuyen-mon") and "/en/" not in u), None)
    if math_page:
        d_rows, p_rows = extract_math_departments(math_page[2])
        depts += [{"site_id": "math", **d, "source_url": math_page[0]} for d in d_rows]
        for row in p_rows:
            add_lecturer("math", math_page[0], row)

    # programmes
    for url, (meta, body) in pages.items():
        site, path = meta.get("site"), url.split("://", 1)[1].split("/", 1)[-1]
        if site == "fit" and re.match(r"dai-hoc/(chuong-trinh-chuan|chuong-trinh-tien-tien|chat-luong-cao|cu-nhan-tai-nang|tri-tue-nhan-tao)$", path) \
                or site == "fit" and path == "sau-dai-hoc/chuong-trinh-viet-phap":
            prog = extract_program(site, url, meta.get("title", ""), body)
        elif site == "math" and re.match(r"dao-tao-dai-hoc/chuong-trinh-(chuan|tcta|cntn)(/nganh-[\w-]+)?$", path):
            prog = extract_program(site, url, meta.get("title", ""), body)
            if prog:
                kind = re.search(r"chuong-trinh-(chuan|tcta|cntn)", path).group(1)
                suffix = {"chuan": "Chương trình chuẩn", "tcta": "Tăng cường tiếng Anh", "cntn": ""}[kind]
                if suffix and suffix not in prog["name"]:
                    prog["name"] = f"{prog['name']} - {suffix}"
        else:
            continue
        if prog:
            programs.append({"site_id": site, **prog, "source_url": url})

    # FIT publications -> achievements of matching lecturers
    pub_page = find("fit", "nghien-cuu", "cong-bo-khoa-hoc")
    fit_lecturers = [l for l in lecturers.values() if l["site_id"] == "fit"]
    if pub_page and fit_lecturers:
        for pub in extract_publications(pub_page[2]):
            for lec in match_lecturers(pub, fit_lecturers):
                achievements.append({"site_id": "fit", "lecturer": lec["full_name"], "kind": "PUBLICATION", "year": pub["year"],
                                     "title": pub["title"], "details": pub["details"], "source_url": pub_page[0]})

    uniq = {(d["site_id"], " ".join(fold(d["name"]).split())): d for d in depts}
    return {"faculties": faculties, "departments": list(uniq.values()), "lecturers": list(lecturers.values()),
            "programs": programs, "achievements": achievements}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result = build()
    for name, rows in result.items():
        (OUT_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {k: len(v) for k, v in result.items()}
    print("structured rows:", counts, "->", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
