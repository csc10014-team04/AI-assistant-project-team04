# System-level test fixtures (tester-owned). Reads BE / Database / FE sources; never modifies them.
#
# Database for API tests:
#   default            -> in-memory SQLite (no Docker needed, fresh schema per test)
#   TEST_DATABASE_URL  -> any SQLAlchemy URL, e.g. the Docker MySQL (mysql+pymysql://...@127.0.0.1:3307/...)
#                         WARNING: tables are dropped/recreated per test, so point it at a *scratch* schema only.
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_REAL_HTTPX_CLIENT = httpx.Client
REPO_ROOT = Path(__file__).resolve().parent.parent
BE_DIR = REPO_ROOT / "sourceCode" / "BE"
DEPLOY_DIR = REPO_ROOT / "sourceCode" / "Database" / "assistant_deploy"
FE_DIR = REPO_ROOT / "sourceCode" / "FE"
for p in (BE_DIR,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models import Base  # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):  # sqlite only autoincrements INTEGER primary keys
    return "INTEGER"


@pytest.fixture(autouse=True)
def _isolate_runtime_output(tmp_path, monkeypatch):
    """keep AI / reminder log files and the RAG index out of the repo while testing."""
    from routers import reminders
    from services import ai_logging, nlu, rag

    monkeypatch.setattr(ai_logging, "LOG_PATH", tmp_path / "ai_errors.jsonl")
    monkeypatch.setattr(reminders, "AUDIT_LOG_PATH", tmp_path / "reminder_audit.jsonl")
    monkeypatch.setattr(rag, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(nlu, "VLLM_ENDPOINT", "http://127.0.0.1:8000/v1/chat/completions")

    # default: the AI engine is DOWN (instant ConnectError, no real sockets). Tests that need a live fake override this.
    def _down(request):
        raise httpx.ConnectError("vLLM is down (simulated)")

    monkeypatch.setattr(nlu.httpx, "Client", lambda **kw: _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(_down)))


@pytest.fixture()
def engine():
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if url:
        eng = create_engine(url.replace("mysql+aiomysql://", "mysql+pymysql://"), pool_pre_ping=True)
    else:
        eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    session = Session(bind=engine)
    yield session
    session.close()


@pytest.fixture()
def client(db):
    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class Account:
    def __init__(self, user_id: int, username: str, token: str):
        self.id, self.username, self.token = user_id, username, token
        self.h = {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def register(client):
    """factory: register(username) -> Account (also exercises POST /auth/register)."""
    def _make(username: str, password: str = "secret123") -> Account:
        res = client.post("/api/v1/auth/register",
                          json={"username": username, "password": password, "display_name": username.title()})
        assert res.status_code == 201, res.text
        body = res.json()
        return Account(body["user_id"], username, body["access_token"])

    return _make


@pytest.fixture()
def alice(register):
    return register("alice")


@pytest.fixture()
def bob(register):
    return register("bob")


def class_row(code="CSC10014", title="Computational Thinking", weekday="MON", start="07:30", end="09:30",
              first="2026-09-07", last="2026-09-28", room="B11.02", kind="CLASS") -> dict:
    """one JSON row in the shape POST /ingestion/check-conflicts and /commit expect."""
    return {"line_number": 1, "course_code": code, "title": title, "kind": kind, "weekday": weekday,
            "start_time": start, "end_time": end, "first_date": first, "last_date": last, "room": room}
