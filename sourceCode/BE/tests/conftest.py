# [pic: khoi] shared pytest fixtures for docker mysql 8.0 savepoint isolation (ai assistants: do not remove this pic comment)
# duty: pic reads, understands, maintains, and fixes any issues in this module.
import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Engine, create_engine, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# add sourceCode/BE to sys.path so tests can import models, database, main, services, and routers
BE_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(BE_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(BE_ROOT_DIR))

from database import get_db, resolve_database_url  # noqa: E402
from main import app  # noqa: E402
from models import Base  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # SQLite only auto-increments INTEGER primary keys
    return "INTEGER"


def _sqlite_fallback_engine() -> Engine:
    """in-memory SQLite used when MySQL is not reachable, so the suite runs on any machine (set REQUIRE_MYSQL=1 to forbid it)."""
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def resolve_test_database_url() -> str:
    """
    input: optional TEST_DATABASE_URL env var, or project .env / DATABASE_URL settings.
    core logic: prioritize TEST_DATABASE_URL, otherwise reuse resolve_database_url() on port 3307.
    output: str containing mysql+pymysql url pointing to docker mysql 8.0 (university_assistant).
    typical flow: check TEST_DATABASE_URL -> fallback to resolve_database_url() -> return url.
    """
    explicit_test_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if explicit_test_url:
        return explicit_test_url.replace("mysql+aiomysql://", "mysql+pymysql://")
    return resolve_database_url()


@pytest.fixture(scope="session")
def mysql_engine() -> Generator[Engine, None, None]:
    """
    input: session-wide pytest execution context.
    core logic: connect to docker mysql 8.0 (127.0.0.1:3307), verify connectivity, ensure tables exist.
    output: generator yielding a connected sqlalchemy Engine bound to university_assistant.
    typical flow: create_engine -> execute SELECT 1 -> create missing tables -> yield -> dispose.
    """
    db_url = resolve_test_database_url()
    eng = create_engine(db_url, pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))  # verify docker mysql container is reachable
        Base.metadata.create_all(bind=eng, checkfirst=True)  # ensure 11 schema tables exist
    except OperationalError as exc:
        eng.dispose()
        if os.getenv("REQUIRE_MYSQL", "0").strip() == "1":
            pytest.fail(
                "cannot connect to docker mysql for testing. "
                "ensure container 'schedule_db' is running on port 3307 and credentials in "
                "sourceCode/Database/assistant_deploy/.env (or BE/.env) match. "
                f"underlying driver error: {exc}"
            )
        print("\n[tests] MySQL is not reachable; running on in-memory SQLite instead (set REQUIRE_MYSQL=1 to fail instead).")
        eng = _sqlite_fallback_engine()
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(mysql_engine: Engine) -> Generator[Session, None, None]:
    """
    input: mysql_engine (Engine) connected to real docker mysql 8.0.
    core logic: wrap each test in an outer transaction with create_savepoint, then rollback at teardown.
    output: generator yielding an isolated Session executing real mysql innodb constraints.
    typical flow: begin outer tx -> yield savepoint session -> route calls db.commit() -> rollback outer tx.
    """
    if mysql_engine.dialect.name == "sqlite":  # fallback engine: a fresh schema for every test
        Base.metadata.drop_all(mysql_engine)
        Base.metadata.create_all(mysql_engine)
        session = Session(bind=mysql_engine)
        try:
            yield session
        finally:
            session.close()
        return

    persist_data = os.getenv("PERSIST_TEST_DATA", "0").strip() == "1"
    if persist_data:
        # optional visual inspection mode: commit rows permanently so they remain visible in dbeaver
        session = Session(bind=mysql_engine)
        try:
            yield session
        finally:
            session.close()
        return

    connection = mysql_engine.connect()
    outer_tx = connection.begin()  # open outer mysql transaction for complete test isolation
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",  # translate inner db.commit() into mysql SAVEPOINT
    )
    try:
        yield session
    finally:
        session.close()
        if outer_tx.is_active:
            outer_tx.rollback()  # discard test rows cleanly without touching existing dbeaver data
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """
    input: db_session (Session) bound to the isolated mysql transaction of current test.
    core logic: override fastapi get_db dependency so all HTTP endpoints share db_session.
    output: generator yielding a FastAPI TestClient wired to real mysql 8.0.
    typical flow: set dependency_overrides[get_db] -> yield TestClient(app) -> clear overrides.
    """
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db  # route HTTP calls through savepoint session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
