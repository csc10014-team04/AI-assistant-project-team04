"""
QA: database-backed checks that need a real MySQL (they cannot run in the in-memory test suite).

  1. find_user_free_slots (reads UserPreference + events from MySQL) must equal the pure engine find_free_slots
     applied to the same data: 200 random calendars (differential test).
  2. Soft-deleted events never block free time; other users' events never block; respect_preferences=False ignores
     sleep time and breaks; stored times round-trip UTC <-> +07:00 without drifting.
  3. Foreign keys cascade: deleting a user removes its events, tasks and preferences (BE_QA.md section 8).

Standard / method : ISO/IEC 25010 functional correctness; differential testing; ISO/IEC/IEEE 29119-4.
Run               : python "QA  docs/db_checks.py"      (MySQL on 127.0.0.1:3307, credentials from assistant_deploy/.env)
Safety            : creates one throw-away user (display_name QA_db_checks_*) and deletes it at the end.
"""
import os
import random
import re
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

QA_DIR = Path(__file__).resolve().parent
ROOT = next(p for p in QA_DIR.resolve().parents if (p / "sourceCode" / "BE" / "models.py").is_file())
BE = ROOT / "sourceCode" / "BE"
sys.path.insert(0, str(BE))

# database.py reads DB_* from the environment / .env; reuse the deploy credentials without printing them
env_file = ROOT / "sourceCode" / "Database" / "assistant_deploy" / ".env"
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(DB_USER|DB_PASSWORD)\s*=\s*(.*)", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip().strip('"'))
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3307")

from sqlalchemy import select, text  # noqa: E402

from database import SessionLocal, VN_TZ, to_db_utc, from_db_to_vn  # noqa: E402
from models import Event, EventKind, EventSource, Task, User, UserPreference  # noqa: E402
from services.search_engine import find_free_slots, find_user_free_slots  # noqa: E402

N_CASES = 200  # plan minimum 150 (+33%)
RESULTS = []


def check(cid, desc, ok, detail=""):
    RESULTS.append((cid, desc, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {cid}  {desc}  {detail}")


def mk_user(db, tag):
    u = User(display_name=f"QA_db_checks_{tag}")
    db.add(u)
    db.flush()
    db.add(UserPreference(user_id=u.id, sleep_start=dtime(23, 30), sleep_end=dtime(6, 30), min_break_minutes=15, max_block_minutes=180, slot_step_minutes=15))
    db.flush()
    return u


def add_event(db, owner, start, end, kind=EventKind.EVENT, deleted=False):
    ev = Event(owner_id=owner, title="QA db event", kind=kind, source=EventSource.MANUAL, start_time=to_db_utc(start), end_time=to_db_utc(end),
               is_hard=kind in (EventKind.CLASS, EventKind.EXAM))
    if deleted:
        ev.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)  # the column stores naive UTC
    db.add(ev)
    db.flush()
    return ev


def slots(lst):
    return [(s.start, s.end) for s in lst]


def main() -> int:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        print("cannot connect to MySQL:", type(exc).__name__)
        return 2
    rng = random.Random(20261119)
    user = mk_user(db, "main")
    other = mk_user(db, "other")
    db.commit()
    base = datetime(2026, 12, 7, 0, 0, tzinfo=VN_TZ)  # a Monday far from "today"
    print(f"# db_checks  {datetime.now():%Y-%m-%d %H:%M}\n")

    try:
        # ------------------------------------------------------------ 1. differential test
        print("## 1. find_user_free_slots vs the pure engine on the same MySQL data")
        mismatches = 0
        for case in range(N_CASES):
            db.query(Event).filter(Event.owner_id == user.id).delete()
            pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
            pref.sleep_start = dtime(rng.choice([21, 22, 23, 0]), rng.choice([0, 15, 30]))
            pref.sleep_end = dtime(rng.choice([5, 6, 7]), rng.choice([0, 15, 30]))
            pref.min_break_minutes = rng.choice([0, 5, 15, 30])
            pref.slot_step_minutes = rng.choice([15, 15, 30])
            db.flush()
            ws = base + timedelta(days=rng.randint(0, 3), minutes=rng.choice([0, 0, 30, 7, 600]))
            we = ws + timedelta(minutes=rng.choice([480, 1440, 2880]))
            for _ in range(rng.randint(0, 18)):
                s = ws + timedelta(minutes=rng.randint(-60, int((we - ws).total_seconds() // 60)))
                add_event(db, user.id, s, s + timedelta(minutes=rng.choice([15, 30, 60, 90, 120, 180])), rng.choice([EventKind.CLASS, EventKind.EXAM, EventKind.EVENT, EventKind.TASK]))
            if rng.random() < 0.3:
                add_event(db, user.id, ws + timedelta(hours=5), ws + timedelta(hours=5), EventKind.DEADLINE)
            if rng.random() < 0.25:  # a soft-deleted event must not matter
                add_event(db, user.id, ws + timedelta(hours=2), ws + timedelta(hours=6), EventKind.CLASS, deleted=True)
            db.flush()
            dur = rng.choice([15, 30, 60, 90, 120])
            got = slots(find_user_free_slots(db, user.id, ws, we, dur))
            live = db.scalars(select(Event).where(Event.owner_id == user.id, Event.deleted_at.is_(None))).all()
            want = slots(find_free_slots([e.to_domain() for e in live], ws.astimezone(VN_TZ), we.astimezone(VN_TZ), dur, sleep_start=pref.sleep_start,
                                         sleep_end=pref.sleep_end, min_break_minutes=pref.min_break_minutes, slot_step_minutes=pref.slot_step_minutes))
            mismatches += got != want
        check("DB-01", f"find_user_free_slots equals the pure engine on {N_CASES} random calendars stored in MySQL", mismatches == 0, f"mismatches={mismatches}")

        # ------------------------------------------------------------ 2. isolation, soft delete, preferences, time round-trip
        print("## 2. isolation and rules")
        db.query(Event).filter(Event.owner_id.in_([user.id, other.id])).delete()
        pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
        pref.sleep_start, pref.sleep_end, pref.min_break_minutes, pref.slot_step_minutes = dtime(23, 30), dtime(6, 30), 15, 15  # reset what part 1 randomised
        db.flush()
        ws, we = base.replace(hour=8), base.replace(hour=18)
        empty = slots(find_user_free_slots(db, user.id, ws, we, 60))
        add_event(db, other.id, base.replace(hour=10), base.replace(hour=12), EventKind.CLASS)
        check("DB-02", "another user's event does not block my free time", slots(find_user_free_slots(db, user.id, ws, we, 60)) == empty)
        add_event(db, user.id, base.replace(hour=10), base.replace(hour=12), EventKind.CLASS, deleted=True)
        check("DB-03", "a soft-deleted event does not block free time", slots(find_user_free_slots(db, user.id, ws, we, 60)) == empty)
        add_event(db, user.id, base.replace(hour=10), base.replace(hour=11), EventKind.TASK)
        blocked = slots(find_user_free_slots(db, user.id, ws, we, 60))
        check("DB-04", "a live event (with the 15-minute break) splits the free time", len(blocked) == 2 and blocked[0][1] == base.replace(hour=9, minute=45) and blocked[1][0] == base.replace(hour=11, minute=15), str(blocked)[:90])
        no_pref = slots(find_user_free_slots(db, user.id, base.replace(hour=5), base.replace(hour=9), 30, respect_preferences=False))
        with_pref = slots(find_user_free_slots(db, user.id, base.replace(hour=5), base.replace(hour=9), 30))
        check("DB-05", "respect_preferences=False ignores sleep time; True respects it", no_pref and no_pref[0][0] == base.replace(hour=5) and with_pref and with_pref[0][0] == base.replace(hour=6, minute=30))
        pref.sleep_start, pref.sleep_end = dtime(1, 0), dtime(7, 0)
        db.flush()
        moved = slots(find_user_free_slots(db, user.id, base.replace(hour=5), base.replace(hour=9), 30))
        check("DB-06", "a changed sleep window takes effect on the next query", moved and moved[0][0] == base.replace(hour=7), str(moved)[:60])
        ev = add_event(db, user.id, base.replace(hour=15, minute=15), base.replace(hour=16, minute=45))
        db.commit()
        db.expire_all()
        back = db.get(Event, ev.id)
        check("DB-07", "stored UTC time round-trips to the same +07:00 time", from_db_to_vn(back.start_time) == base.replace(hour=15, minute=15) and from_db_to_vn(back.end_time) == base.replace(hour=16, minute=45))

        # ------------------------------------------------------------ 3. cascade delete
        print("## 3. cascade delete")
        db.add(Task(owner_id=other.id, title="QA task", duration_minutes=60))
        db.commit()
        oid = other.id
        db.execute(text("DELETE FROM users WHERE id = :i"), {"i": oid})
        db.commit()
        left = {t: db.execute(text(f"SELECT COUNT(*) FROM {t} WHERE {col} = :i"), {"i": oid}).scalar() for t, col in (("events", "owner_id"), ("tasks", "owner_id"), ("user_preferences", "user_id"))}
        check("DB-08", "deleting a user cascades to events, tasks and preferences", all(v == 0 for v in left.values()), str(left))
    finally:
        db.rollback()
        db.execute(text("DELETE FROM users WHERE display_name LIKE 'QA_db_checks_%'"))
        db.commit()
        db.close()

    n_ok = sum(1 for r in RESULTS if r[2])
    print(f"\n== {n_ok}/{len(RESULTS)} checks passed ==")
    return 0 if n_ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
