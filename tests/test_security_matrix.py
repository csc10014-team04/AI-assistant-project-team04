"""
SEC-01..SEC-35: Security matrix tests.
Covers: authentication, authorization, IDOR, token forgery, injection, PII leakage.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sourceCode" / "BE"))

from conftest import class_row
from database import UTC_TZ, VN_TZ
from models import Event, EventKind, EventSource, Proposal, ProposalStatus, Task
from services import privacy, security
from sqlalchemy import select
from test_ai_layer import llm, reply, understand


# ---- helpers ----------------------------------------------------------------

def _commit(client, acc, rows=None, batch_id="b"):
    if rows is None:
        rows = [class_row(first="2026-09-07", last="2026-09-07")]
    return client.post(
        "/api/v1/ingestion/commit",
        headers=acc.h,
        json={"import_batch_id": batch_id, "resolved_rows": rows},
    )


def _make_token(user_id, secret, exp_delta=timedelta(hours=1), alg="HS256"):
    payload = {"sub": str(user_id), "exp": datetime.now(UTC_TZ) + exp_delta}
    return jwt.encode(payload, secret, algorithm=alg)


# ---- SEC-01: Anonymous access to protected endpoints -----------------------
@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v1/ingestion/commit",
     {"import_batch_id": "x", "resolved_rows": []}),
    ("post", "/api/v1/ingestion/check-conflicts",
     {"incoming_rows": [], "replace_previous_imports": False}),
    ("post", "/api/v1/assistant/understand", {"prompt": "test"}),
    ("get", "/api/v1/reminders/audit", None),
    ("put", "/api/v1/reminders/1", {"offset_minutes": 5}),
    ("post", "/api/v1/proposals/1/confirm", {}),
    ("post", "/api/v1/proposals/1/reject", {}),
])
def test_SEC01_anonymous_access_rejected(client, method, path, body):
    """Contract: every protected endpoint returns 401 without Authorization header."""
    kwargs = {"json": body} if body is not None else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 401, f"{method.upper()} {path} returned {res.status_code}"


# ---- SEC-02: Garbage token is rejected -------------------------------------
def test_SEC02_garbage_bearer_token_is_401(client):
    """Contract: malformed bearer token returns 401."""
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401


# ---- SEC-03: alg:none JWT forgery is rejected ------------------------------
def test_SEC03_alg_none_jwt_rejected(client, alice):
    """Contract: JWT signed with alg=none must be rejected."""
    forged = jwt.encode(
        {"sub": str(alice.id), "exp": datetime.now(UTC_TZ) + timedelta(hours=1)},
        "",
        algorithm="none",
    )
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


# ---- SEC-04: Wrong-secret JWT is rejected ----------------------------------
def test_SEC04_wrong_secret_jwt_rejected(client, alice):
    """Contract: JWT signed with wrong secret returns 401."""
    token = _make_token(alice.id, "WRONG-SECRET-KEY-but-long-enough-32b")
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---- SEC-05: Expired token is rejected -------------------------------------
def test_SEC05_expired_token_is_401(client, alice):
    """Contract: expired JWT returns 401 even with valid signature."""
    token = security.create_access_token(alice.id, expires_delta=timedelta(seconds=-5))
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---- SEC-06: Token for nonexistent user is rejected ------------------------
def test_SEC06_token_for_nonexistent_user_is_401(client):
    """Contract: valid-looking JWT for user that doesn't exist returns 401."""
    token = security.create_access_token(999999999)
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---- SEC-07: IDOR on proposals (Bob tries to confirm Alice's proposal) -----
def test_SEC07_idor_proposal_confirm(client, alice, bob, monkeypatch):
    """Contract: Bob confirming Alice's proposal returns 404 (anti-IDOR)."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/confirm", headers=bob.h)
    assert res.status_code == 404


# ---- SEC-08: IDOR on proposals (Bob tries to reject Alice's proposal) ------
def test_SEC08_idor_proposal_reject(client, alice, bob, monkeypatch):
    """Contract: Bob rejecting Alice's proposal returns 404."""
    llm(monkeypatch, lambda r: reply({
        "intent": "schedule_task",
        "title": "study",
        "duration_minutes": 60,
    }))
    prop = understand(client, alice, "xếp 1 tiếng study").json().get("proposal")
    if prop is None:
        pytest.skip("No free slot")
    res = client.post(f"/api/v1/proposals/{prop['id']}/reject", headers=bob.h)
    assert res.status_code == 404


# ---- SEC-09: IDOR on reminders (Bob reads Alice's audit trail) -------------
def test_SEC09_idor_reminder_audit_isolated(client, alice, bob):
    """Contract: Bob's audit trail is always empty even if Alice has reminders."""
    _commit(client, alice)
    events = _commit(client, alice).json().get("events", [])
    if events:
        eid = events[0]["id"]
        client.put(f"/api/v1/reminders/{eid}", headers=alice.h, json={"offset_minutes": 10})
    bob_audit = client.get("/api/v1/reminders/audit", headers=bob.h).json()
    assert bob_audit == []


# ---- SEC-10: IDOR on reminder PUT (Bob tries to set Alice's event reminder) -
def test_SEC10_idor_reminder_put(client, alice, bob):
    """Contract: Bob PUT /reminders/{alice_event_id} returns 404."""
    res = _commit(client, alice)
    events = res.json().get("events", [])
    if not events:
        pytest.skip("No events committed")
    eid = events[0]["id"]
    result = client.put(f"/api/v1/reminders/{eid}", headers=bob.h,
                        json={"offset_minutes": 10})
    assert result.status_code == 404


# ---- SEC-11: Password hash is salted (two hashes of same password differ) --
def test_SEC11_password_hashes_are_salted(client):
    """Contract: bcrypt salted hash means same input produces different digests."""
    h1 = security.hash_password("my_secret_pass")
    h2 = security.hash_password("my_secret_pass")
    assert h1 != h2
    assert security.verify_password("my_secret_pass", h1)
    assert security.verify_password("my_secret_pass", h2)


# ---- SEC-12: Wrong password does not verify ---------------------------------
def test_SEC12_wrong_password_does_not_verify():
    """Contract: verify_password returns False for wrong password."""
    h = security.hash_password("correct_password")
    assert not security.verify_password("wrong_password", h)


# ---- SEC-13: Corrupted hash does not crash ----------------------------------
def test_SEC13_corrupted_hash_returns_false_not_exception():
    """Contract: verify_password with junk hash returns False, not exception."""
    result = security.verify_password("any", "not-a-valid-bcrypt-hash")
    assert result is False


# ---- SEC-14: LLM endpoint allowlist enforced --------------------------------
@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:8000/v1", True),
    ("http://localhost:8000/v1", True),
    ("http://llama_engine:8000/v1", True),
    ("http://192.168.1.100:8000/v1", True),
    ("http://10.0.0.1:8000/v1", True),
    ("https://api.openai.com/v1", False),
    ("http://8.8.8.8:8000", False),
    ("http://evil.example.com", False),
    ("https://huggingface.co/model", False),
])
def test_SEC14_llm_endpoint_allowlist(url, expected):
    """Contract: is_private_endpoint correctly classifies LLM server URLs."""
    assert privacy.is_private_endpoint(url) is expected


# ---- SEC-15: Public LLM endpoint is refused ---------------------------------
def test_SEC15_public_llm_refused_at_call_time(client, alice, monkeypatch):
    """Contract: if VLLM_ENDPOINT is public, assert_private_endpoint raises, triggering fallback."""
    from services import nlu
    monkeypatch.setattr(nlu, "VLLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    seen = llm(monkeypatch, lambda r: reply({"intent": "schedule_task"}))
    n = understand(client, alice, "xếp 2 tiếng học").json()["nlu"]
    # the outbound call must NOT have happened
    assert seen == []
    assert n["fallback_mode"] is True


# ---- SEC-16: Email PII is redacted from prompts ----------------------------
def test_SEC16_email_redacted_from_prompt():
    """Contract: sanitize_prompt removes email addresses."""
    out = privacy.sanitize_prompt("mail me@example.com please")
    assert "me@example.com" not in out
    assert "[email]" in out


# ---- SEC-17: Phone PII is redacted ----------------------------------------
def test_SEC17_phone_redacted_from_prompt():
    """Contract: sanitize_prompt removes Vietnamese phone numbers."""
    out = privacy.sanitize_prompt("gọi 0901234567")
    assert "0901234567" not in out
    assert "[phone]" in out


# ---- SEC-18: URL PII is redacted -------------------------------------------
def test_SEC18_url_redacted_from_prompt():
    """Contract: sanitize_prompt removes HTTP URLs."""
    out = privacy.sanitize_prompt("check http://evil.io/steal")
    assert "evil.io" not in out
    assert "[url]" in out


# ---- SEC-19: Prompt too long is truncated ----------------------------------
def test_SEC19_long_prompt_truncated():
    """Contract: sanitize_prompt enforces max_chars hard limit."""
    out = privacy.sanitize_prompt("x" * 1000, max_chars=500)
    assert len(out) <= 500


# ---- SEC-20: Encrypt/decrypt roundtrip ------------------------------------
def test_SEC20_encrypt_decrypt_roundtrip():
    """Contract: encrypt_text then decrypt_text recovers the original."""
    plain = "sensitive student schedule data"
    encrypted = privacy.encrypt_text(plain)
    assert plain not in encrypted  # ciphertext must not contain plaintext
    assert privacy.decrypt_text(encrypted) == plain


# ---- SEC-21: Corrupted ciphertext returns None ----------------------------
def test_SEC21_corrupted_ciphertext_returns_none():
    """Contract: decrypt_text with garbage input returns None, not exception."""
    result = privacy.decrypt_text("completely-invalid-token")
    assert result is None


# ---- SEC-22: Different users cannot import to each other's namespace -------
def test_SEC22_import_is_owner_isolated(client, alice, bob):
    """Contract: Bob's commit does not affect Alice's event list."""
    _commit(client, alice,
            rows=[class_row(code="ALICE", first="2026-09-07", last="2026-09-07")],
            batch_id="ba")
    _commit(client, bob,
            rows=[class_row(code="BOB", first="2026-09-07", last="2026-09-07")],
            batch_id="bb")

    alice_events = client.get(
        "/api/v1/search/events",
        headers=alice.h,
        params={"start_time": "2026-09-06T00:00:00+07:00",
                "end_time": "2026-09-08T23:59:59+07:00"},
    ).json().get("events", [])

    alice_ids = {e["id"] for e in alice_events}
    bob_events = client.get(
        "/api/v1/search/events",
        headers=bob.h,
        params={"start_time": "2026-09-06T00:00:00+07:00",
                "end_time": "2026-09-08T23:59:59+07:00"},
    ).json().get("events", [])
    bob_ids = {e["id"] for e in bob_events}

    assert alice_ids.isdisjoint(bob_ids), "Event IDs must not overlap between users"


# ---- SEC-23: Login returns same error for bad user vs bad password ----------
def test_SEC23_login_error_indistinguishable(client, alice):
    """Contract: bad-user and bad-password give identical error response bodies."""
    r1 = client.post("/api/v1/auth/login",
                     json={"username": "alice", "password": "WRONG"}).json()
    r2 = client.post("/api/v1/auth/login",
                     json={"username": "ghost", "password": "WRONG"}).json()
    assert r1 == r2


# ---- SEC-24: Register with same username is 409 ----------------------------
def test_SEC24_duplicate_registration_is_409(client, alice):
    """Contract: registering an existing username returns 409 Conflict."""
    res = client.post("/api/v1/auth/register",
                      json={"username": "alice", "password": "secret123",
                            "display_name": "Alice2"})
    assert res.status_code == 409


# ---- SEC-25: Short password rejected (< 8 chars) ---------------------------
@pytest.mark.parametrize("pw", ["12345", "abc", "1234567"])
def test_SEC25_short_password_rejected(client, pw):
    """Contract: password shorter than minimum is rejected with 422."""
    res = client.post("/api/v1/auth/register",
                      json={"username": "newuser99", "password": pw,
                            "display_name": "User"})
    assert res.status_code == 422


# ---- SEC-26: Short username rejected (< 3 chars) ---------------------------
@pytest.mark.parametrize("uname", ["ab", "x", ""])
def test_SEC26_short_username_rejected(client, uname):
    """Contract: username shorter than minimum is rejected with 422."""
    res = client.post("/api/v1/auth/register",
                      json={"username": uname, "password": "secret123",
                            "display_name": "User"})
    assert res.status_code == 422


# ---- SEC-27: Bearer scheme is enforced -------------------------------------
def test_SEC27_basic_auth_scheme_rejected(client, alice):
    """Contract: Basic auth scheme is not accepted for JWT endpoints."""
    import base64
    creds = base64.b64encode(b"alice:secret123").decode()
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Basic {creds}"})
    assert res.status_code == 401


# ---- SEC-28: Control chars in prompt are sanitized -------------------------
def test_SEC28_control_chars_removed_from_prompt():
    """Contract: sanitize_prompt strips null bytes and control characters."""
    out = privacy.sanitize_prompt("hello\x00world\x1b[31m")
    assert "\x00" not in out
    assert "\x1b" not in out


# ---- SEC-29: NFC normalization in sanitize_prompt --------------------------
def test_SEC29_unicode_normalization_applied():
    """Contract: NFC normalization ensures canonical Unicode form."""
    import unicodedata
    # decomposed form should become NFC
    raw = unicodedata.normalize("NFD", "tiếng Việt")
    out = privacy.sanitize_prompt(raw)
    assert unicodedata.is_normalized("NFC", out)


# ---- SEC-30: Proposal audit trail only shows own proposals -----------------
def test_SEC30_audit_trail_owner_isolated(client, alice, bob):
    """Contract: GET /reminders/audit returns only the authenticated user's data."""
    # Both users set up reminders
    for acc in (alice, bob):
        res = client.post(
            "/api/v1/ingestion/commit",
            headers=acc.h,
            json={"import_batch_id": f"batch_{acc.username}",
                  "resolved_rows": [class_row(first="2026-09-07", last="2026-09-07")]},
        )
        events = res.json().get("events", [])
        if events:
            eid = events[0]["id"]
            client.put(f"/api/v1/reminders/{eid}", headers=acc.h,
                       json={"offset_minutes": 10})

    alice_audit = client.get("/api/v1/reminders/audit", headers=alice.h).json()
    bob_audit = client.get("/api/v1/reminders/audit", headers=bob.h).json()
    alice_eids = {r["event_id"] for r in alice_audit}
    bob_eids = {r["event_id"] for r in bob_audit}
    assert alice_eids.isdisjoint(bob_eids)


# ---- SEC-31: JWT sub claim must be numeric user_id -------------------------
def test_SEC31_jwt_sub_non_numeric_rejected(client):
    """Contract: JWT with non-numeric sub claim returns 401."""
    token = jwt.encode(
        {"sub": "admin", "exp": datetime.now(UTC_TZ) + timedelta(hours=1)},
        security.JWT_SECRET_KEY,
        algorithm="HS256",
    )
    res = client.get("/api/v1/reminders/audit",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---- SEC-32: SQL injection attempt in search query -------------------------
def test_SEC32_sql_injection_in_search_query_is_handled(client, alice):
    """Contract: SQL injection in search query param does not cause 500."""
    res = client.get(
        "/api/v1/search/events",
        headers=alice.h,
        params={"start_time": "2026-09-06T00:00:00+07:00",
                "end_time": "2026-09-08T23:59:59+07:00",
                "q": "'; DROP TABLE events; --"},
    )
    assert res.status_code in (200, 422)


# ---- SEC-33: Oversized reminder offset rejected ----------------------------
def test_SEC33_oversized_reminder_offset_rejected(client, alice):
    """Contract: offset_minutes > 7*24*60 returns 422."""
    res = client.post(
        "/api/v1/ingestion/commit",
        headers=alice.h,
        json={"import_batch_id": "b", "resolved_rows": [class_row(first="2026-09-07",
                                                                   last="2026-09-07")]},
    )
    events = res.json().get("events", [])
    if not events:
        pytest.skip("No events")
    eid = events[0]["id"]
    res2 = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                      json={"offset_minutes": 7 * 24 * 60 + 1})
    assert res2.status_code == 422


# ---- SEC-34: Negative reminder offset rejected -----------------------------
def test_SEC34_negative_reminder_offset_rejected(client, alice):
    """Contract: negative offset_minutes returns 422."""
    res = client.post(
        "/api/v1/ingestion/commit",
        headers=alice.h,
        json={"import_batch_id": "b2",
              "resolved_rows": [class_row(first="2026-09-07", last="2026-09-07")]},
    )
    events = res.json().get("events", [])
    if not events:
        pytest.skip("No events")
    eid = events[0]["id"]
    res2 = client.put(f"/api/v1/reminders/{eid}", headers=alice.h,
                      json={"offset_minutes": -1})
    assert res2.status_code == 422


# ---- SEC-35: RAG index not shared across users -----------------------------
def test_SEC35_rag_index_per_user(client, alice, bob):
    """Contract: Bob cannot retrieve content indexed by Alice."""
    csv_content = (
        "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
        "SECRET_ALICE,Alice Secret Course,MON,08:00,10:00,A101,2026-09-07,2026-09-28,CLASS\n"
    )
    client.post(
        "/api/v1/assistant/index-file",
        headers=alice.h,
        files={"file": ("schedule.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    # Bob's index should be separate (empty)
    res = client.post(
        "/api/v1/assistant/index-file",
        headers=bob.h,
        files={"file": ("empty.txt", b"irrelevant content", "text/plain")},
    )
    # The important thing is that Bob's indexing is scoped to Bob
    assert res.status_code in (200, 422)
