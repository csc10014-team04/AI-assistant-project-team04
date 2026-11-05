"""BE-01..BE-20: domain rules (AGENTS.md sections 3, 6), validator (P1-6) and authentication (P1-3)."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from database import UTC_TZ, VN_TZ, from_db_to_vn, round_up_to_15m, to_db_utc
from models import EventDomain, EventKind, EventSource, TimeSlot
from services import security
from services.validator import check_hard_conflict


def vn(h, m=0, day=7):
    return datetime(2026, 9, day, h, m, tzinfo=VN_TZ)


def ev(start, end, kind=EventKind.CLASS, hard=True, **kw):
    return EventDomain(id=kw.pop("id", 1), owner_id=1, title="x", start_time=start, end_time=end,
                       kind=kind, source=EventSource.IMPORTED, is_hard=hard, **kw)


# ---------------- domain / timezone -------------------------------------------------------------
def test_BE01_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        TimeSlot(datetime(2026, 9, 7, 8), datetime(2026, 9, 7, 9))
    with pytest.raises(ValueError):
        to_db_utc(datetime(2026, 9, 7, 8))


def test_BE02_vn_to_utc_roundtrip_is_exact():
    stored = to_db_utc(vn(7, 30))
    assert stored == datetime(2026, 9, 7, 0, 30) and stored.tzinfo is None  # 07:30+07 -> 00:30 UTC, naive
    assert from_db_to_vn(stored).isoformat() == "2026-09-07T07:30:00+07:00"


@pytest.mark.parametrize("minute,expected", [(0, 0), (1, 15), (14, 15), (15, 15), (16, 30), (46, 0)])
def test_BE03_round_up_to_15_minute_grid(minute, expected):
    out = round_up_to_15m(vn(8, minute))
    assert out.minute == expected and out.second == 0
    assert out >= vn(8, minute).replace(second=0)


def test_BE04_deadline_is_zero_duration_and_never_blocks():
    t = vn(23, 59)
    deadline = ev(t, t, kind=EventKind.DEADLINE, hard=True)
    assert deadline.is_deadline and not deadline.blocks_availability
    with pytest.raises(ValueError):
        ev(t, t + timedelta(hours=1), kind=EventKind.DEADLINE)  # deadline with duration is illegal


def test_BE05_slot_overlap_semantics():
    a = TimeSlot(vn(8), vn(10))
    assert a.overlaps(TimeSlot(vn(9), vn(11)))
    assert not a.overlaps(TimeSlot(vn(10), vn(12)))  # touching boundary is not an overlap
    assert a.duration_minutes() == 120 and a.is_aligned_to_step(15)


# ---------------- validator (P1-6: zero overlap with hard constraints) --------------------------
def test_BE06_hard_conflict_detected():
    classes = [ev(vn(8), vn(10), id=1), ev(vn(13), vn(15), id=2)]
    hits = check_hard_conflict(TimeSlot(vn(9), vn(11)), classes)
    assert [h.id for h in hits] == [1]


def test_BE07_boundary_touch_and_free_slot_are_allowed():
    classes = [ev(vn(8), vn(10))]
    assert check_hard_conflict(TimeSlot(vn(10), vn(11)), classes) == []
    assert check_hard_conflict(TimeSlot(vn(6), vn(8)), classes) == []


def test_BE08_soft_events_and_deadlines_do_not_block():
    soft = ev(vn(8), vn(10), kind=EventKind.TASK, hard=False)
    deadline = ev(vn(9), vn(9), kind=EventKind.DEADLINE, hard=True)
    assert check_hard_conflict(TimeSlot(vn(8), vn(10)), [soft, deadline]) == []


def test_BE09_candidate_inside_and_around_hard_event():
    exam = ev(vn(9), vn(10), kind=EventKind.EXAM)
    assert check_hard_conflict(TimeSlot(vn(9, 15), vn(9, 45)), [exam])  # fully inside
    assert check_hard_conflict(TimeSlot(vn(8), vn(12)), [exam])  # fully around


# ---------------- security helpers --------------------------------------------------------------
def test_BE10_password_hash_is_salted_and_verifiable():
    h1, h2 = security.hash_password("hunter22"), security.hash_password("hunter22")
    assert h1 != h2 and "hunter22" not in h1
    assert security.verify_password("hunter22", h1) and not security.verify_password("wrong", h1)
    assert security.verify_password("x", "not-a-bcrypt-hash") is False  # corrupted hash must not 500


def test_BE11_token_roundtrip_and_tamper():
    token = security.create_access_token(42)
    assert security.decode_access_token(token) == 42
    with pytest.raises(Exception) as exc:
        security.decode_access_token(token[:-3] + "abc")
    assert getattr(exc.value, "status_code", None) == 401


def test_BE12_expired_and_alg_none_tokens_rejected():
    expired = security.create_access_token(1, expires_delta=timedelta(seconds=-5))
    with pytest.raises(Exception) as exc:
        security.decode_access_token(expired)
    assert exc.value.status_code == 401
    forged = jwt.encode({"sub": "1", "exp": datetime.now(UTC_TZ) + timedelta(hours=1)}, "", algorithm="none")
    with pytest.raises(Exception) as exc2:
        security.decode_access_token(forged)
    assert exc2.value.status_code == 401


# ---------------- auth API ----------------------------------------------------------------------
def test_BE13_register_creates_user_identity_and_default_preferences(client, db):
    from sqlalchemy import select
    from models import AuthIdentity, AuthProvider, UserPreference

    res = client.post("/api/v1/auth/register", json={"username": "newbie", "password": "secret123", "display_name": "N"})
    assert res.status_code == 201 and res.json()["token_type"] == "bearer"
    uid = res.json()["user_id"]
    ident = db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == uid))
    assert ident.provider == AuthProvider.PASSWORD and ident.hashed_password != "secret123"
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == uid))
    assert pref is not None and pref.slot_step_minutes == 15 and pref.min_break_minutes == 15


def test_BE14_duplicate_username_is_409(client, alice):
    res = client.post("/api/v1/auth/register", json={"username": "alice", "password": "secret123", "display_name": "A2"})
    assert res.status_code == 409


@pytest.mark.parametrize("body", [
    {"username": "ab", "password": "secret123", "display_name": "x"},      # username too short
    {"username": "okname", "password": "123", "display_name": "x"},        # password too short
    {"username": "okname", "password": "secret123", "display_name": ""},   # empty display name
    {"username": "okname"},                                                # missing fields
])
def test_BE15_register_input_validation(client, body):
    assert client.post("/api/v1/auth/register", json=body).status_code == 422


def test_BE16_login_success_and_failures(client, alice):
    ok = client.post("/api/v1/auth/login", json={"username": "alice", "password": "secret123"})
    assert ok.status_code == 200 and ok.json()["user_id"] == alice.id
    assert client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "ghost", "password": "secret123"}).status_code == 401


def test_BE17_login_does_not_reveal_which_field_was_wrong(client, alice):
    bad_pw = client.post("/api/v1/auth/login", json={"username": "alice", "password": "nope"}).json()
    bad_user = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"}).json()
    assert bad_pw == bad_user


@pytest.mark.parametrize("path,method,body", [
    ("/api/v1/ingestion/check-conflicts", "post", {"incoming_rows": []}),
    ("/api/v1/ingestion/commit", "post", {"import_batch_id": "b", "resolved_rows": []}),
    ("/api/v1/assistant/understand", "post", {"prompt": "xếp 2 tiếng"}),
    ("/api/v1/assistant/index-file", "post", None),
    ("/api/v1/reminders/audit", "get", None),
    ("/api/v1/reminders/1", "put", {"offset_minutes": 5}),
])
def test_BE18_every_protected_endpoint_rejects_anonymous(client, path, method, body):
    res = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert res.status_code == 401, f"{method.upper()} {path} answered {res.status_code} without a token"


def test_BE19_garbage_and_foreign_tokens_rejected(client, alice):
    assert client.get("/api/v1/reminders/audit", headers={"Authorization": "Bearer garbage"}).status_code == 401
    foreign = jwt.encode({"sub": str(alice.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                         "some-other-secret-that-is-long-enough-32b", algorithm="HS256")
    assert client.get("/api/v1/reminders/audit", headers={"Authorization": f"Bearer {foreign}"}).status_code == 401


def test_BE20_token_for_deleted_user_rejected(client):
    token = security.create_access_token(999999)  # valid signature, user does not exist
    assert client.get("/api/v1/reminders/audit", headers={"Authorization": f"Bearer {token}"}).status_code == 401
