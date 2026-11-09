"""SS-01..SS-07: the search-engine SQL file is separate from the scheduling schema (static checks, no MySQL needed)."""
import re

from conftest import DEPLOY_DIR, REPO_ROOT

SEARCH_SQL = REPO_ROOT / "sourceCode" / "Database" / "knowledgebase" / "search_engine_schema.sql"


def tables(sql: str) -> set[str]:
    return set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", sql, re.IGNORECASE))


def search_sql() -> str:
    """the SQL without `--` comments, so words used in explanations are not mistaken for code."""
    text = SEARCH_SQL.read_text(encoding="utf-8")
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


def scheduling_sql() -> str:
    return (DEPLOY_DIR / "init.sql").read_text(encoding="utf-8")


def test_SS01_search_tables_all_start_with_kb_and_scheduling_ones_do_not():
    assert tables(search_sql()) and all(t.startswith("kb_") for t in tables(search_sql()))
    assert not any(t.startswith("kb_") for t in tables(scheduling_sql()))


def test_SS02_the_two_schemas_share_no_table_name():
    assert tables(search_sql()).isdisjoint(tables(scheduling_sql()))


def test_SS03_no_foreign_key_crosses_between_the_schemas():
    own = tables(search_sql())
    refs = set(re.findall(r"REFERENCES\s+(\w+)\s*\(", search_sql()))
    assert refs and refs <= own  # search tables reference only search tables
    sched_refs = set(re.findall(r"REFERENCES\s+(\w+)\s*\(", scheduling_sql()))
    assert not any(r.startswith("kb_") for r in sched_refs)


def test_SS04_search_schema_holds_no_user_data():
    sql = search_sql()
    assert "owner_id" not in sql and "user_id" not in sql and "hashed_password" not in sql


def test_SS05_expected_tables_exist_and_every_fact_table_keeps_its_source():
    sql = search_sql()
    assert tables(sql) == {"kb_sources", "kb_faculties", "kb_departments", "kb_lecturers", "kb_programs",
                           "kb_courses", "kb_course_lecturers", "kb_achievements"}
    for t in ("kb_lecturers", "kb_courses", "kb_achievements", "kb_programs"):
        block = re.search(rf"CREATE TABLE IF NOT EXISTS {t} \((.*?)\) ENGINE", sql, re.DOTALL).group(1)
        assert "source_id" in block and "review_status" in block, t  # cite the page; human review before publishing


def test_SS06_file_is_idempotent_utf8mb4_and_folded_names_exist():
    sql = search_sql()
    assert re.findall(r"\bCREATE TABLE\b(?! IF NOT EXISTS)", sql) == []
    assert "INSERT IGNORE" in sql and "DROP TABLE" not in sql.upper()
    assert sql.count("CHARSET=utf8mb4") == len(tables(sql))
    for t in ("kb_faculties", "kb_lecturers", "kb_courses"):
        assert "name_folded" in re.search(rf"CREATE TABLE IF NOT EXISTS {t} \((.*?)\) ENGINE", sql, re.DOTALL).group(1)


def test_SS07_docker_compose_mounts_the_search_schema_next_to_init_sql():
    compose = (DEPLOY_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./init.sql:/docker-entrypoint-initdb.d/init.sql" in compose
    assert "../knowledgebase/search_engine_schema.sql:/docker-entrypoint-initdb.d/02_search_engine.sql" in compose
