"""UD-01..UD-07: the local user-data database (sourceCode/Database/user_data/create_user_db.py)."""
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

from conftest import BE_DIR, REPO_ROOT

USER_DATA = REPO_ROOT / "sourceCode" / "Database" / "user_data"
sys.path.insert(0, str(USER_DATA))
import create_user_db as cud  # noqa: E402
from models import Base  # noqa: E402


@pytest.fixture()
def db_file(tmp_path):
    return cud.create(tmp_path / "u.db")


def test_UD01_creates_exactly_the_user_tables_and_the_log_tables(db_file):
    names = set(inspect(create_engine(f"sqlite:///{db_file.as_posix()}")).get_table_names())
    assert names == set(cud.USER_TABLES) | set(cud.LOG_TABLES) == set(Base.metadata.tables)


def test_UD02_user_tables_are_the_ones_describing_a_student():
    assert set(cud.USER_TABLES) == {"users", "auth_identities", "user_preferences", "courses", "tasks", "proposals", "events", "reminders"}
    assert not any(t.startswith("kb_") for t in cud.USER_TABLES + cud.LOG_TABLES)  # public knowledge base is a different database


def test_UD03_running_twice_keeps_the_data_and_reset_deletes_it(tmp_path):
    path = cud.create(tmp_path / "u.db")
    engine = cud.make_engine(path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (display_name) VALUES ('An')"))
    engine.dispose()
    cud.create(path)
    assert cud.summary(path)["users"] == 1
    cud.create(path, reset=True)
    assert cud.summary(path)["users"] == 0


def test_UD04_foreign_keys_and_cascade_work_on_the_script_connection(db_file):
    engine = cud.make_engine(db_file)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, display_name) VALUES (1, 'An')"))
        conn.execute(text("INSERT INTO user_preferences (user_id, sleep_start, sleep_end, min_break_minutes, max_block_minutes, slot_step_minutes) "
                          "VALUES (1, '23:30:00', '06:30:00', 15, 180, 15)"))
        conn.execute(text("DELETE FROM users WHERE id = 1"))
        assert conn.execute(text("SELECT COUNT(*) FROM user_preferences")).scalar() == 0  # cascade
    with pytest.raises(Exception), engine.begin() as conn:
        conn.execute(text("INSERT INTO user_preferences (user_id, sleep_start, sleep_end, min_break_minutes, max_block_minutes, slot_step_minutes) "
                          "VALUES (999, '23:30:00', '06:30:00', 15, 180, 15)"))  # no such user


def test_UD05_the_real_backend_runs_on_the_file_register_login_and_data_are_stored(tmp_path):
    path = cud.create(tmp_path / "backend.db")
    code = (
        "from fastapi.testclient import TestClient\n"
        "from main import app\n"
        "c = TestClient(app)\n"
        "assert c.get('/health/db').json()['database'] == 'ok'\n"
        "r = c.post('/api/v1/auth/register', json={'username':'dev_user','password':'secret123','display_name':'Dev'})\n"
        "assert r.status_code == 201, r.text\n"
        "h = {'Authorization': 'Bearer ' + r.json()['access_token']}\n"
        "assert c.post('/api/v1/auth/login', json={'username':'dev_user','password':'secret123'}).status_code == 200\n"
        "assert c.post('/api/v1/tasks', headers=h, json={'title':'hoc bai','duration_minutes':60}).status_code == 201\n"
    )
    env = {"DATABASE_URL": f"sqlite:///{path.as_posix()}", "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           "PATH": __import__("os").environ.get("PATH", "")}
    res = subprocess.run([sys.executable, "-c", code], cwd=BE_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr[-800:]
    counts = cud.summary(path)
    assert counts["users"] == counts["auth_identities"] == counts["user_preferences"] == counts["tasks"] == 1  # registration made the 3 rows


def test_UD06_password_is_stored_only_as_a_hash(tmp_path):
    path = cud.create(tmp_path / "h.db")
    code = ("from fastapi.testclient import TestClient\nfrom main import app\n"
            "TestClient(app).post('/api/v1/auth/register', json={'username':'dev_user','password':'secret123','display_name':'Dev'})\n")
    import os
    env = {"DATABASE_URL": f"sqlite:///{path.as_posix()}", "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("PATH", "")}
    subprocess.run([sys.executable, "-c", code], cwd=BE_DIR, env=env, capture_output=True, timeout=120, check=True)
    with cud.make_engine(path).connect() as conn:
        stored = conn.execute(text("SELECT hashed_password FROM auth_identities")).scalar()
    assert stored and "secret123" not in stored and stored.startswith("$2")  # bcrypt


def test_UD07_the_database_file_can_never_be_committed():
    ignore = (USER_DATA / ".gitignore").read_text(encoding="utf-8")
    assert "\n*\n" in "\n" + ignore + "\n"          # everything is ignored ...
    assert "!create_user_db.py" in ignore            # ... except the script that creates the file
    assert "!user_data.db" not in ignore and "!*.db" not in ignore
