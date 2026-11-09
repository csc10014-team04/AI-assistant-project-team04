"""
Create the USER DATA database as one local file: sourceCode/Database/user_data/user_data.db (SQLite).

It holds exactly the tables that describe a student (accounts, preferences, courses, events, tasks, proposals,
reminders) plus the three log tables the backend writes to, with the same columns and constraints as the real schema
(`sourceCode/BE/models.py`, `assistant_deploy/init.sql`). Use it to run the whole backend on one PC without Docker:

    python sourceCode/Database/user_data/create_user_db.py                 # create (does nothing if the file exists)
    python sourceCode/Database/user_data/create_user_db.py --reset         # delete the file and create it again
    python sourceCode/Database/user_data/create_user_db.py --check         # list tables and row counts

    $env:DATABASE_URL = "sqlite:///<path printed by the script>"           # then start the backend as usual
    python -m uvicorn main:app --port 8080                                 # in sourceCode/BE

The file contains REAL user data once somebody registers: it is ignored by git (see .gitignore in this folder), never
copy it into a commit, a screenshot or an issue. MySQL in Docker stays the database of the shared host; this file is for
development and demos.

SQLite does not enforce ON DELETE CASCADE unless a connection turns foreign keys on; this script does for its own
connection, the backend does not. Deleting a user on SQLite therefore leaves that user's rows behind: use MySQL for that.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import BigInteger, create_engine, event, inspect, text
from sqlalchemy.ext.compiler import compiles

HERE = Path(__file__).resolve().parent
BE_DIR = HERE.parent.parent / "BE"
DEFAULT_DB = HERE / "user_data.db"

if str(BE_DIR) not in sys.path:
    sys.path.insert(0, str(BE_DIR))

from models import Base  # noqa: E402  (the real table definitions; never redefined here)

USER_TABLES = ["users", "auth_identities", "user_preferences", "courses", "tasks", "proposals", "events", "reminders"]
LOG_TABLES = ["ai_error_logs", "inference_queue_logs", "telemetry_metric_logs"]


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # SQLite only auto-numbers INTEGER primary keys
    return "INTEGER"


def make_engine(path: Path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # enforce foreign keys and cascades for this script's own connection
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def create(path: Path = DEFAULT_DB, reset: bool = False) -> Path:
    path = Path(path)
    if reset and path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(path)
    Base.metadata.create_all(engine)  # existing tables are left alone, so running it twice is safe
    engine.dispose()
    return path


def summary(path: Path = DEFAULT_DB) -> dict[str, int]:
    engine = make_engine(path)
    try:
        counts = {}
        with engine.connect() as conn:
            for name in sorted(inspect(engine).get_table_names()):
                counts[name] = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
        return counts
    finally:
        engine.dispose()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", type=Path, default=DEFAULT_DB, help="database file (default: user_data/user_data.db)")
    ap.add_argument("--reset", action="store_true", help="DELETE the existing file (and all users in it), then create it again")
    ap.add_argument("--check", action="store_true", help="only list the tables and their row counts")
    args = ap.parse_args()
    if args.check:
        if not args.path.exists():
            print(f"no database at {args.path}")
            return 1
    else:
        existed = args.path.exists()
        create(args.path, args.reset)
        print(("re-created" if args.reset and existed else "kept" if existed else "created"), args.path)
    for table, rows in summary(args.path).items():
        kind = "user data" if table in USER_TABLES else "log" if table in LOG_TABLES else "other"
        print(f"  {table:24s} {rows:6d} rows   ({kind})")
    print(f'\nuse it:  $env:DATABASE_URL = "sqlite:///{args.path.resolve().as_posix()}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
