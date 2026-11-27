"""
QA reproduction of BUG B-15: the first POST /api/v1/assistant/understand hangs when the table `pending_clarifications`
does not exist yet (a MySQL volume created before that table was added to init.sql).

Cause (found by reading SHOW PROCESSLIST): routers/assistant.py `_ensure_clarification_table` runs
`CREATE TABLE pending_clarifications (... FOREIGN KEY -> users)` on a SECOND connection while the request's own session
still holds an open transaction that has read `users`. The DDL waits for a metadata lock that the same request holds,
so the request never returns (and the module-level lock `_clarification_table_lock` stays held, blocking every later call).

How to run (destructive for the table only, on a LOCAL throw-away database):
    1. start the backend:  cd sourceCode/BE ; uvicorn main:app --port 8080     (fresh process: the 'table ready' flag is False)
    2. python "QA  docs/repro_clarification_deadlock.py"
The script drops the (empty) table, calls understand with a 15-second timeout, prints the blocking lock, then repairs the
situation (kills the stuck connections and re-creates the table from init.sql).
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

QA_DIR = Path(__file__).resolve().parent
ROOT = next(p for p in QA_DIR.resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())
sys.path.insert(0, str(QA_DIR))
import kb_quality as k  # noqa: E402  (reuses its .env reader and connection helper)

BASE = "http://127.0.0.1:8080"


def root_conn():
    env = k.load_env()
    import pymysql
    return pymysql.connect(host="127.0.0.1", port=3307, user="root", password=env["DB_ROOT_PASSWORD"], database="university_assistant", charset="utf8mb4", autocommit=True)


def main() -> int:
    c = root_conn()
    cur = c.cursor()
    cur.execute("DROP TABLE IF EXISTS pending_clarifications")
    print("dropped pending_clarifications (it is recreated at the end)")
    name = f"qa_dl_{datetime.now():%H%M%S}"
    r = requests.post(f"{BASE}/api/v1/auth/register", json={"username": name, "password": "Passw0rd!", "display_name": f"QA_{name}"}, timeout=20)
    token = r.json()["access_token"]
    t0 = datetime.now()
    try:
        r = requests.post(f"{BASE}/api/v1/assistant/understand", headers={"Authorization": f"Bearer {token}"}, json={"prompt": "xếp 1 tiếng đọc sách ngày mai"}, timeout=15)
        print(f"RESULT: answered with {r.status_code} after {(datetime.now() - t0).total_seconds():.1f} s  -> the bug did NOT reproduce (already fixed?)")
        reproduced = False
    except requests.exceptions.ReadTimeout:
        print("RESULT: no answer after 15 s  -> bug reproduced")
        reproduced = True
    cur.execute("SHOW FULL PROCESSLIST")
    stuck = [row for row in cur.fetchall() if row[1] != "root" and row[3] == "university_assistant"]
    for row in stuck:
        print(f"  connection {row[0]:3} state={row[6]!r:36} idle/running {row[5]:>3}s  {(row[7] or '')[:60].replace(chr(10), ' ')!r}")
    for row in stuck:
        cur.execute(f"KILL {row[0]}")
    sql = (ROOT / "sourceCode" / "Database" / "assistant_deploy" / "init.sql").read_text(encoding="utf-8")
    ddl = re.search(r"CREATE TABLE pending_clarifications \(.*?\) ENGINE=InnoDB[^;]*;", sql, re.S).group(0)
    cur.execute("DROP TABLE IF EXISTS pending_clarifications")
    cur.execute(ddl)
    print("repaired: stuck connections killed, table re-created from init.sql")
    return 1 if reproduced else 0


if __name__ == "__main__":
    sys.exit(main())
