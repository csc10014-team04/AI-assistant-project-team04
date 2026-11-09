"""
Create the USER DATA database. Default: MySQL 8 (the Docker database). A one-file SQLite copy is available with --sqlite.

User data = accounts, preferences, courses, tasks, proposals, events, reminders, plus the three log tables the backend
writes to. The MySQL definition is `user_data_schema.sql` in this folder; it is GENERATED from the authoritative
`assistant_deploy/init.sql` (same columns, defaults and constraints, every table `CREATE TABLE IF NOT EXISTS`), so the two
cannot drift (a test regenerates it and compares).

    python sourceCode/Database/user_data/create_user_db.py                  # MySQL: create the database and the tables that are missing
    python sourceCode/Database/user_data/create_user_db.py --check          # MySQL: tables and row counts
    python sourceCode/Database/user_data/create_user_db.py --export-sql     # regenerate user_data_schema.sql from init.sql
    python sourceCode/Database/user_data/create_user_db.py --sqlite         # instead: one local file user_data.db (development)

MySQL connection: --url, else $env:DATABASE_URL, else the backend's own rules (assistant_deploy/.env, 127.0.0.1:3307).
The script never drops anything on MySQL. To start from nothing: `docker compose down -v` in assistant_deploy.

Docker already runs init.sql on the first start, so on a fresh Docker database you do not need this script. Use it when the
tables are missing in an existing database or in a MySQL server that was not started by docker-compose.
Real user data lives in this database: it is private, never commit a dump of it.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import BigInteger, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.compiler import compiles

HERE = Path(__file__).resolve().parent
BE_DIR = HERE.parent.parent / "BE"
INIT_SQL = HERE.parent / "assistant_deploy" / "init.sql"
SCHEMA_SQL = HERE / "user_data_schema.sql"
DEFAULT_SQLITE = HERE / "user_data.db"

if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

USER_TABLES = ["users", "auth_identities", "user_preferences", "courses", "tasks", "proposals", "events", "reminders"]
LOG_TABLES = ["ai_error_logs", "inference_queue_logs", "telemetry_metric_logs"]


# =============================================================================== MySQL: schema file generated from init.sql
HEADER = """-- USER DATA schema for MySQL 8 (accounts, preferences, courses, tasks, proposals, events, reminders + the backend's log tables).
-- GENERATED from sourceCode/Database/assistant_deploy/init.sql by `python sourceCode/Database/user_data/create_user_db.py --export-sql`.
-- Do not edit by hand: change init.sql (a locked team contract) and regenerate. Every table is CREATE TABLE IF NOT EXISTS, so this
-- file can be applied to a database that already has some of them:
--   docker exec -i schedule_db mysql -u<DB_USER> -p university_assistant < sourceCode/Database/user_data/user_data_schema.sql
-- The public university knowledge base (tables kb_*) is a different file: sourceCode/Database/knowledgebase/search_engine_schema.sql.
-- This database holds personal data: never commit a dump of it.

CREATE DATABASE IF NOT EXISTS university_assistant
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE university_assistant;

"""


def render_schema(init_sql: Path = INIT_SQL) -> str:
    """the CREATE TABLE statements of init.sql, made re-runnable, behind a header."""
    text_ = init_sql.read_text(encoding="utf-8")
    blocks = re.findall(r"(?:--[^\n]*\n)*CREATE TABLE\s+\w+\s*\(.*?\)\s*ENGINE=[^;]*;", text_, flags=re.DOTALL)
    out = []
    for block in blocks:
        body = re.sub(r"^\s*--[^\n]*\n", "", block)  # drop comment lines that sit in front of a statement
        out.append(re.sub(r"CREATE TABLE\s+(\w+)", r"CREATE TABLE IF NOT EXISTS \1", body, count=1))
    return HEADER + "\n\n".join(out) + "\n"


def schema_statements(schema_sql: Path = SCHEMA_SQL) -> list[str]:
    """the executable statements of the schema file (comments removed)."""
    body = "\n".join(l for l in schema_sql.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def mysql_url(explicit: str | None = None) -> str:
    import os

    url = explicit or os.getenv("DATABASE_URL", "").strip()
    if not url:
        from database import resolve_database_url  # the backend's own rules

        url = resolve_database_url()
    return url.replace("mysql+aiomysql://", "mysql+pymysql://")


def create_mysql(url: str) -> list[str]:
    """create the database when it is missing, then every missing table. Returns the tables that now exist."""
    target = make_url(url)
    if target.get_backend_name() != "mysql":
        raise ValueError(f"not a MySQL url: {target.render_as_string(hide_password=True)} (use --sqlite for the file database)")
    server = create_engine(target.set(database=None))
    with server.begin() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{target.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    server.dispose()
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in schema_statements():
            if statement.upper().startswith(("CREATE DATABASE", "USE ")):
                continue  # the database was created above and the connection is already bound to it
            conn.execute(text(statement))
    names = sorted(inspect(engine).get_table_names())
    engine.dispose()
    return names


def count_rows(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return {n: conn.execute(text(f"SELECT COUNT(*) FROM `{n}`")).scalar() for n in sorted(inspect(engine).get_table_names())}
    finally:
        engine.dispose()


# =============================================================================== SQLite: one local file (development)
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # SQLite only auto-numbers INTEGER primary keys
    return "INTEGER"


def make_engine(path: Path):
    engine = create_engine(f"sqlite:///{Path(path).as_posix()}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # enforce foreign keys and cascades for this script's own connection
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def create(path: Path = DEFAULT_SQLITE, reset: bool = False) -> Path:
    """SQLite file built from the ORM models (sourceCode/BE/models.py); running it twice keeps the data."""
    from models import Base

    path = Path(path)
    if reset and path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(path)
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def summary(path: Path = DEFAULT_SQLITE) -> dict[str, int]:
    engine = make_engine(path)
    try:
        with engine.connect() as conn:
            return {n: conn.execute(text(f'SELECT COUNT(*) FROM "{n}"')).scalar() for n in sorted(inspect(engine).get_table_names())}
    finally:
        engine.dispose()


# =============================================================================== command line
def _print_counts(counts: dict[str, int]) -> None:
    for table, rows in counts.items():
        kind = "user data" if table in USER_TABLES else "log" if table in LOG_TABLES else "other"
        print(f"  {table:24s} {rows:6d} rows   ({kind})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", action="store_true", help="use a local SQLite file instead of MySQL")
    ap.add_argument("--path", type=Path, default=DEFAULT_SQLITE, help="SQLite file (default: user_data/user_data.db)")
    ap.add_argument("--reset", action="store_true", help="SQLite only: DELETE the file and every user in it, then recreate it")
    ap.add_argument("--url", help="MySQL url, e.g. mysql+pymysql://user:password@127.0.0.1:3307/university_assistant")
    ap.add_argument("--check", action="store_true", help="only list the tables and their row counts")
    ap.add_argument("--export-sql", action="store_true", help="regenerate user_data_schema.sql from init.sql and stop")
    args = ap.parse_args()

    if args.export_sql:
        SCHEMA_SQL.write_text(render_schema(), encoding="utf-8")
        print("written", SCHEMA_SQL)
        return 0

    if args.sqlite:
        if args.check:
            if not args.path.exists():
                print(f"no database at {args.path}")
                return 1
        else:
            existed = args.path.exists()
            create(args.path, args.reset)
            print(("re-created" if args.reset and existed else "kept" if existed else "created"), args.path)
        _print_counts(summary(args.path))
        print(f'\nuse it:  $env:DATABASE_URL = "sqlite:///{args.path.resolve().as_posix()}"')
        return 0

    if args.reset:
        print("--reset exists only for --sqlite. MySQL is never dropped by this script (use `docker compose down -v` in assistant_deploy).")
        return 2
    url = mysql_url(args.url)
    shown = make_url(url).render_as_string(hide_password=True)
    try:
        if not args.check:
            names = create_mysql(url)
            print(f"MySQL ready at {shown}: {len(names)} tables")
        _print_counts(count_rows(url))
    except Exception as exc:  # connection refused, wrong password ...
        print(f"cannot reach MySQL at {shown}: {type(exc).__name__}: {str(exc)[:200]}")
        print("is the container running?  cd sourceCode/Database/assistant_deploy ; docker compose up -d db")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
