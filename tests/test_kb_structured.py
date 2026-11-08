"""KS-01..KS-14: structured extraction (pages -> rows) and loading into the kb_* tables (SQLite stands in for MySQL)."""
import json
import re
import sys

import pytest

pytest.importorskip("bs4")
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from conftest import REPO_ROOT  # noqa: E402

CRAWLER = REPO_ROOT / "sourceCode" / "Database" / "knowledgebase" / "crawler"
sys.path.insert(0, str(CRAWLER))
import kb_extract as ex  # noqa: E402
import kb_load  # noqa: E402
from services.kb_models import (  # noqa: E402
    KbAchievement, KbBase, KbDepartment, KbFaculty, KbLecturer, KbProgram, KbSource,
)

UNIINFO = REPO_ROOT / "database" / "UniInfo"
SEARCH_SQL = REPO_ROOT / "sourceCode" / "Database" / "knowledgebase" / "search_engine_schema.sql"

FIT_LIST = """# Thông tin đội ngũ
Cán bộ giảng dạy - Cơ hữu
- GS.TS. Lê Hoài Bắc
- PGS.TS. Đinh Điền
- TS. Ngô Huy Biên
- Phòng Đào tạo 2025
"""
FIT_BIOS = """### ĐỘI NGŨ GIẢNG VIÊN
GS.TS. Lê Hoài Bắc hiện là Trưởng Bộ môn Khoa học Máy tính. Ông tốt nghiệp tiến sĩ năm 1999.
Danh sách bài báo
https://dblp.uni-trier.de/pers/hd/l/Le:Bac
- Trí tuệ Nhân tạo
- Khai thác dữ liệu
PGS.TS. Đinh Điền hiện là Phó trưởng Bộ môn Công nghệ Tri thức, Khoa Công nghệ Thông tin, ĐHKHTN. Ông tốt nghiệp tiến sĩ.
https://www.fit.hcmus.edu.vn/~ddien
- Truy tìm thông tin
"""
MATH = """## Danh sách đội ngũ theo bộ môn

### Bộ môn Đại số
Phòng F210
Lý thuyết nhóm; Lý thuyết vành và mô-đun; Đại số tính toán.
Trưởng bộ môn GS.TS. Mai Hoàng Biên Phó Trưởng bộ môn TS. Lê Văn Luyện

#### GS.TS. Mai Hoàng Biên
Giảng viên cao cấp

#### TS. Lê Văn Luyện
Giảng viên

#### TS. Trịnh Thanh Đèo

### Bộ môn Giải tích
Phòng E201A

#### PGS.TS. Nguyễn Văn A
"""
PUBS = """#### Công bố khoa học
2025
- Bui, Hung; Le, Bac Hoai Fusing attention. Expert Systems, Volume 299; Elsevier; DOI: 10.1/x
Bui, Hung; Le, Bac Hoai
Fusing global attention and self-attention for tabular data.
Expert Systems with Applications, Volume 299; Elsevier Ltd; ISSN: 09574174
DOI: 10.1016/j.eswa.2025.130220
2023
- Vo Hoai Viet, Dinh Dien Vehicle Tracking Based on Deep learning, IJEM, Vol. 14, 2023
"""


# ---------------- extractors -------------------------------------------------------------------
def test_KS01_titles_are_split_from_names():
    assert ex.split_title("PGS. TS. Đinh Điền") == ("PGS.TS.", "Đinh Điền")
    assert ex.split_title("TS. Ngô Huy Biên") == ("TS.", "Ngô Huy Biên")
    assert ex.split_title("GS. Nguyễn Văn A") == ("GS.", "Nguyễn Văn A")
    assert ex.split_title("Phòng Đào tạo") == (None, "Phòng Đào tạo")


def test_KS02_fit_staff_list_keeps_titled_people_only():
    rows = ex.extract_fit_staff_list(FIT_LIST)
    assert [r["full_name"] for r in rows] == ["Lê Hoài Bắc", "Đinh Điền", "Ngô Huy Biên"]  # "Phòng Đào tạo 2025" is not a person
    assert rows[0]["academic_title"] == "GS.TS."


def test_KS03_fit_bios_give_position_department_link_and_topics():
    bacs, dien = ex.extract_fit_bios(FIT_BIOS)
    assert bacs["full_name"] == "Lê Hoài Bắc" and bacs["position"] == "Trưởng bộ môn Khoa học Máy tính" and bacs["department"] == "Khoa học Máy tính"
    assert bacs["profile_url"] == "https://dblp.uni-trier.de/pers/hd/l/Le:Bac" and "Môn học / lĩnh vực: Trí tuệ Nhân tạo; Khai thác dữ liệu" in bacs["bio"]
    assert dien["position"] == "Phó trưởng bộ môn Công nghệ Tri thức" and dien["profile_url"].endswith("~ddien")


def test_KS04_math_departments_members_ranks_and_heads():
    depts, people = ex.extract_math_departments(MATH)
    assert [d["name"] for d in depts] == ["Đại số", "Giải tích"] and "Lý thuyết nhóm" in depts[0]["description"]
    by = {p["full_name"]: p for p in people}
    assert by["Mai Hoàng Biên"]["position"] == "Trưởng bộ môn Đại số" and by["Lê Văn Luyện"]["position"] == "Phó trưởng bộ môn Đại số"
    assert by["Trịnh Thanh Đèo"]["position"] is None and by["Nguyễn Văn A"]["department"] == "Giải tích"
    assert by["Lê Văn Luyện"]["bio"] == "Giảng viên - Bộ môn Đại số."


def test_KS05_publications_are_parsed_with_year_authors_and_title():
    pubs = ex.extract_publications(PUBS)
    assert [p["year"] for p in pubs] == [2025, 2023]
    assert pubs[0]["authors"] == "Bui, Hung; Le, Bac Hoai" and pubs[0]["title"].startswith("Fusing global attention")
    assert "Elsevier" in pubs[0]["details"] and pubs[1]["authors"] == "" and "Vehicle Tracking" in pubs[1]["title"]


def test_KS06_lecturers_are_matched_to_publications_by_name_not_by_accident():
    lecs = [{"full_name": "Lê Hoài Bắc"}, {"full_name": "Đinh Điền"}, {"full_name": "Vũ Hải Quân"}]
    a, b = ex.extract_publications(PUBS)
    assert [l["full_name"] for l in ex.match_lecturers(a, lecs)] == ["Lê Hoài Bắc"]  # "Le, Bac Hoai": same words, other order
    assert [l["full_name"] for l in ex.match_lecturers(b, lecs)] == ["Đinh Điền"]     # plain text "Dinh Dien"; Vo Hoai Viet is nobody here


def test_KS07_programme_gets_name_description_and_code():
    body = "# Ngành Toán tin\n" + "Đào tạo cử nhân có nền tảng kết hợp giữa Toán học và Khoa học máy tính, lập trình, thiết kế thuật toán.\nMã ngành 7460117\n"
    prog = ex.extract_program("math", "https://x/dao-tao", "Khoa Toán - Tin học - Ngành Toán tin", body)
    assert prog["name"] == "Ngành Toán tin" and "Mã ngành 7460117" in prog["description"] and prog["level"] == "undergraduate"
    assert ex.extract_program("math", "u", "Khoa Toán - Tin học - X", "short") is None


# ---------------- loader -----------------------------------------------------------------------
@pytest.fixture()
def kb_db():
    engine = create_engine("sqlite://")
    KbBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def make_uniinfo(tmp_path):
    (tmp_path / "structured").mkdir(parents=True)
    pages = [{"site": "fit", "url": "https://www.fit.hcmus.edu.vn/p1", "title": "T", "file": "fit/p1.md",
              "fetched_at": "2026-11-09T00:04:55+07:00", "sha256": "ab", "chars": 10}]
    (tmp_path / "index.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    src = "https://www.fit.hcmus.edu.vn/p1"
    rows = {
        "faculties": [{"site_id": "fit", "description": "Mô tả khoa", "source_url": src}],
        "departments": [{"site_id": "fit", "name": "Khoa học Máy tính", "description": "", "source_url": src}],
        "lecturers": [{"site_id": "fit", "full_name": "Lê Hoài Bắc", "academic_title": "GS.TS.", "department": "Khoa học Máy tính",
                       "position": "Trưởng bộ môn Khoa học Máy tính", "bio": "bio", "profile_url": None, "source_url": src}],
        "programs": [{"site_id": "fit", "name": "Chương trình chuẩn", "level": "undergraduate", "description": "d", "source_url": src}],
        "achievements": [{"site_id": "fit", "lecturer": "Lê Hoài Bắc", "kind": "PUBLICATION", "year": 2025, "title": "Paper", "details": "x", "source_url": src}],
    }
    for name, data in rows.items():
        (tmp_path / "structured" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_KS08_loader_fills_every_table_with_folded_names_and_sources(kb_db, tmp_path):
    counts = kb_load.load(kb_db, make_uniinfo(tmp_path))
    kb_db.commit()
    assert counts == {"sources": 1, "faculties": 4, "departments": 1, "lecturers": 1, "programs": 1, "achievements": 1}
    lec = kb_db.scalar(select(KbLecturer))
    assert lec.name_folded == "le hoai bac" and lec.academic_title == "GS.TS." and lec.source_id is not None
    assert kb_db.get(KbDepartment, lec.department_id).name == "Khoa học Máy tính"
    assert kb_db.scalar(select(KbFaculty).where(KbFaculty.site_id == "fit")).description == "Mô tả khoa"


def test_KS09_loading_twice_never_duplicates(kb_db, tmp_path):
    kb_load.load(kb_db, make_uniinfo(tmp_path))
    again = kb_load.load(kb_db, tmp_path)
    assert again == {"sources": 0, "faculties": 0, "departments": 0, "lecturers": 0, "programs": 0, "achievements": 0}
    assert kb_db.scalar(select(func.count()).select_from(KbAchievement)) == 1


def test_KS10_new_rows_wait_for_review_and_approve_publishes_them(kb_db, tmp_path):
    kb_load.load(kb_db, make_uniinfo(tmp_path))
    assert {x.review_status for x in kb_db.scalars(select(KbLecturer))} == {"PENDING"}
    assert kb_db.scalar(select(KbAchievement)).review_status == "PENDING"
    kb_load.load(kb_db, tmp_path, approve=True)
    assert {x.review_status for x in kb_db.scalars(select(KbLecturer))} == {"APPROVED"}


def test_KS11_a_lecturer_unknown_to_the_faculty_list_does_not_get_achievements(kb_db, tmp_path):
    root = make_uniinfo(tmp_path)
    (root / "structured" / "achievements.json").write_text(json.dumps(
        [{"site_id": "fit", "lecturer": "Người Lạ", "kind": "PUBLICATION", "year": 2024, "title": "x", "source_url": None}]), encoding="utf-8")
    assert kb_load.load(kb_db, root)["achievements"] == 0


# ---------------- models versus SQL file, and the real collected data ---------------------------
def test_KS12_orm_models_list_the_same_columns_as_the_sql_file():
    sql = SEARCH_SQL.read_text(encoding="utf-8")
    for table in KbBase.metadata.sorted_tables:
        block = re.search(rf"CREATE TABLE IF NOT EXISTS {table.name} \((.*?)\) ENGINE", sql, re.DOTALL).group(1)
        sql_cols = {m.group(1) for m in re.finditer(r"^\s{4}(\w+)\s+(?:INT|VARCHAR|CHAR|TEXT|DATETIME|BOOLEAN|DECIMAL|SMALLINT|ENUM)", block, re.MULTILINE)}
        assert sql_cols == {c.name for c in table.columns}, table.name


def test_KS13_models_use_their_own_base_not_the_scheduling_one():
    from models import Base
    assert not set(KbBase.metadata.tables) & set(Base.metadata.tables) and all(t.startswith("kb_") for t in KbBase.metadata.tables)


def test_KS14_real_crawled_data_loads_and_answers_the_example_questions(kb_db):
    counts = kb_load.load(kb_db, UNIINFO, approve=True)
    assert counts["lecturers"] >= 250 and counts["programs"] >= 5 and counts["departments"] >= 10 and counts["achievements"] >= 100
    # "Thầy Đinh Điền là ai, dạy bộ môn nào?"
    dien = kb_db.scalar(select(KbLecturer).where(KbLecturer.name_folded == "dinh dien"))
    assert dien.academic_title == "PGS.TS." and "Công nghệ Tri thức" in dien.position and dien.source_id
    # "Khoa Toán - Tin học gồm bộ môn nào?"
    math = kb_db.scalar(select(KbFaculty).where(KbFaculty.site_id == "math"))
    names = {d.name for d in kb_db.scalars(select(KbDepartment).where(KbDepartment.faculty_id == math.id))}
    assert {"Đại số", "Giải tích"} <= names
    # every row cites a collected page
    assert kb_db.scalar(select(func.count()).select_from(KbLecturer).where(KbLecturer.source_id.is_(None))) == 0
