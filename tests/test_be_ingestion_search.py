"""BE-21..BE-40: timetable parser (P1-4), ingestion API, conflict resolution, re-import, data isolation, search engine."""
import time as _time
from datetime import datetime

import pytest
from sqlalchemy import select

from conftest import class_row
from database import VN_TZ
from models import Course, CsvRowKind, Event, EventDomain, EventKind, EventSource
from services.parser import export_valid_rows_to_csv, parse_timetable_content

HEADER = "course_code,title,weekday,start_time,end_time,room,first_date,last_date,kind\n"
GOOD = (
    "CSC10014,Computational Thinking,MON,07:30,09:30,B11.02,2026-09-07,2026-12-14,CLASS\n"
    "MTH00003,Calculus,WED,13:30,15:30,E202,2026-09-09,2026-12-16,CLASS\n"
)


# ---------------- parser ------------------------------------------------------------------------
def test_BE21_parser_accepts_clean_csv():
    r = parse_timetable_content(HEADER + GOOD, "t.csv")
    assert len(r.valid_rows) == 2 and r.invalid_rows == [] and len(r.import_batch_id) >= 8
    assert r.valid_rows[0].start_time.hour == 7 and r.valid_rows[0].kind == CsvRowKind.CLASS


def test_BE22_parser_isolates_bad_rows_instead_of_crashing():
    bad = "BAD1,No time,TUE,,,A1,2026-09-08,2026-12-15,CLASS\n"
    r = parse_timetable_content(HEADER + GOOD + bad, "t.csv")
    assert len(r.valid_rows) == 2 and len(r.invalid_rows) == 1
    assert r.invalid_rows[0].error_code == "EMPTY_START_TIME" and r.invalid_rows[0].line_number == 4


@pytest.mark.parametrize("line", [
    "X,Bad hour,MON,25:00,26:00,R,2026-09-07,2026-09-14,CLASS",
    "X,End before start,MON,10:00,09:00,R,2026-09-07,2026-09-14,CLASS",
    "X,Bad date,MON,08:00,09:00,R,2026-13-45,2026-09-14,CLASS",
    "X,Dates reversed,MON,08:00,09:00,R,2026-10-01,2026-09-01,CLASS",
    "X,Bad kind,MON,08:00,09:00,R,2026-09-07,2026-09-14,PARTY",
    "garbage line without commas",
])
def test_BE23_parser_flags_each_kind_of_malformed_row(line):
    r = parse_timetable_content(HEADER + line + "\n", "t.csv")
    assert r.valid_rows == [] and len(r.invalid_rows) == 1, r


def test_BE24_parser_handles_empty_input_and_vietnamese_text():
    assert parse_timetable_content("", "t.csv").valid_rows == []
    vn_row = "CSC1,Nhập môn tư duy tính toán,MON,07:30,09:30,Phòng B11,2026-09-07,2026-09-14,CLASS\n"
    r = parse_timetable_content(HEADER + vn_row, "t.csv")
    assert r.valid_rows[0].title == "Nhập môn tư duy tính toán"


def test_BE25_export_then_reparse_is_lossless():
    first = parse_timetable_content(HEADER + GOOD, "t.csv")
    again = parse_timetable_content(export_valid_rows_to_csv(first.valid_rows), "t.csv")
    key = lambda rows: [(r.title, r.start_time, r.end_time, r.first_date, r.last_date, r.weekday) for r in rows]
    assert key(first.valid_rows) == key(again.valid_rows)


# ---------------- ingestion API -----------------------------------------------------------------
def test_BE26_parse_preview_from_pasted_text_needs_no_login(client):
    res = client.post("/api/v1/ingestion/parse-preview", data={"raw_content": HEADER + GOOD})
    assert res.status_code == 200
    body = res.json()
    assert body["valid_count"] == 2 and body["invalid_count"] == 0 and body["import_batch_id"]


def test_BE27_parse_preview_rejects_empty_request(client):
    assert client.post("/api/v1/ingestion/parse-preview", data={"raw_content": "   "}).status_code == 422


def test_BE28_parse_preview_file_upload_csv(client):
    """P1-4 upload path: a CSV file upload is parsed (regression test for the old UnboundLocalError)."""
    res = client.post("/api/v1/ingestion/parse-preview",
                      files={"file": ("t.csv", (HEADER + GOOD).encode("utf-8"), "text/csv")})
    assert res.status_code == 200, res.text


def test_BE29_resolve_preview_merges_corrections_and_skips(client):
    preview = client.post("/api/v1/ingestion/parse-preview",
                          data={"raw_content": HEADER + GOOD + "BAD,No time,TUE,,,A1,2026-09-08,2026-12-15,CLASS\n"}).json()
    assert preview["invalid_count"] == 1
    bad_line = preview["invalid_rows"][0]["line_number"]
    fixed = {"line_number": bad_line, "course_code": "BAD", "title": "No time", "kind": "CLASS", "weekday": "TUE",
             "start_time": "10:00", "end_time": "12:00", "first_date": "2026-09-08", "last_date": "2026-12-15", "room": "A1"}
    res = client.post("/api/v1/ingestion/resolve-preview", json={
        "import_batch_id": preview["import_batch_id"], "valid_rows": preview["valid_rows"],
        "corrected_rows": [fixed], "skipped_line_numbers": []})
    assert res.status_code == 200 and res.json()["total_accepted"] == 3
    assert "BAD" in res.json()["exported_csv"]


def test_BE30_check_conflicts_groups_weekly_series_into_one_card(client, alice):
    rows = [class_row(code="A", title="Math", start="08:00", end="10:00"),
            class_row(code="B", title="Physics", start="09:00", end="11:00")]  # same weekday, 4 weeks overlapping
    res = client.post("/api/v1/ingestion/check-conflicts", headers=alice.h, json={"incoming_rows": rows})
    assert res.status_code == 200
    cards = res.json()["conflict_cards"]
    assert len(cards) == 1, "4 weekly overlaps must collapse into ONE card, not 4"
    assert {cards[0]["option_a"]["title"], cards[0]["option_b"]["title"]} == {"Math", "Physics"}


def test_BE31_back_to_back_classes_are_not_conflicts(client, alice):
    rows = [class_row(code="A", title="Math", start="08:00", end="10:00"),
            class_row(code="B", title="Physics", start="10:00", end="12:00")]
    res = client.post("/api/v1/ingestion/check-conflicts", headers=alice.h, json={"incoming_rows": rows})
    assert res.json()["conflict_cards"] == [] and len(res.json()["non_conflicting_rows"]) == 2


def test_BE32_commit_expands_weekly_occurrences_in_vn_time(client, alice):
    res = client.post("/api/v1/ingestion/commit", headers=alice.h,
                      json={"import_batch_id": "batch-1", "resolved_rows": [class_row()]})
    assert res.status_code == 200
    body = res.json()
    assert body["created_count"] == 4  # Mondays 7, 14, 21, 28 Sep
    first = body["events"][0]
    assert first["start_time"].startswith("2026-09-07T07:30:00") and first["start_time"].endswith("+07:00")
    assert first["is_hard"] is True and first["kind"] == "CLASS" and first["source"] == "IMPORTED"
    assert first["room"] == "B11.02" and first["title"] == "Computational Thinking"


def test_BE33_commit_stores_utc_and_links_course(client, alice, db):
    client.post("/api/v1/ingestion/commit", headers=alice.h,
                json={"import_batch_id": "b", "resolved_rows": [class_row()]})
    ev = db.scalars(select(Event).where(Event.owner_id == alice.id).order_by(Event.start_time)).first()
    assert ev.start_time == datetime(2026, 9, 7, 0, 30)  # 07:30+07:00 stored as 00:30 UTC
    course = db.get(Course, ev.course_id)
    assert course.owner_id == alice.id and course.course_code == "CSC10014"


def test_BE34_reimport_replaces_only_imported_events(client, alice, db):
    manual = Event(owner_id=alice.id, title="Gym", kind=EventKind.EVENT, source=EventSource.MANUAL,
                   start_time=datetime(2026, 9, 8, 1), end_time=datetime(2026, 9, 8, 2))
    db.add(manual)
    db.commit()
    client.post("/api/v1/ingestion/commit", headers=alice.h, json={"import_batch_id": "old", "resolved_rows": [class_row()]})
    client.post("/api/v1/ingestion/commit", headers=alice.h, json={
        "import_batch_id": "new", "replace_previous_imports": True,
        "resolved_rows": [class_row(code="NEW", title="New Course", start="13:00", end="15:00")]})
    live = db.scalars(select(Event).where(Event.owner_id == alice.id, Event.deleted_at.is_(None))).all()
    assert {e.title for e in live} == {"Gym", "New Course"}  # manual kept, old import soft-deleted
    old = db.scalars(select(Event).where(Event.import_batch_id == "old")).all()
    assert old and all(e.deleted_at is not None for e in old)  # soft delete, rows still exist


def test_BE35_existing_calendar_conflicts_with_new_import(client, alice):
    client.post("/api/v1/ingestion/commit", headers=alice.h, json={"import_batch_id": "b", "resolved_rows": [class_row()]})
    clash = class_row(code="Z", title="Part-time job", start="08:00", end="10:00", kind="EVENT")
    res = client.post("/api/v1/ingestion/check-conflicts", headers=alice.h, json={"incoming_rows": [clash]})
    assert len(res.json()["conflict_cards"]) == 1


def test_BE36_users_cannot_see_each_others_calendar(client, alice, bob):
    """anti-IDOR: Bob importing a class at Alice's hour must NOT be reported as a conflict."""
    client.post("/api/v1/ingestion/commit", headers=alice.h, json={"import_batch_id": "a", "resolved_rows": [class_row()]})
    res = client.post("/api/v1/ingestion/check-conflicts", headers=bob.h, json={"incoming_rows": [class_row(code="B")]})
    assert res.json()["conflict_cards"] == []


def test_BE37_replace_flag_never_touches_other_users(client, alice, bob, db):
    client.post("/api/v1/ingestion/commit", headers=alice.h, json={"import_batch_id": "a", "resolved_rows": [class_row()]})
    client.post("/api/v1/ingestion/commit", headers=bob.h,
                json={"import_batch_id": "b", "replace_previous_imports": True, "resolved_rows": [class_row(code="B")]})
    alive = db.scalars(select(Event).where(Event.owner_id == alice.id, Event.deleted_at.is_(None))).all()
    assert len(alive) == 4


@pytest.mark.parametrize("patch", [
    {"start_time": "25:00"}, {"first_date": "not-a-date"}, {"kind": "PARTY"}, {"weekday": "FUNDAY"}, {"title": None},
])
def test_BE38_commit_rejects_malformed_rows(client, alice, patch):
    row = {**class_row(), **patch}
    res = client.post("/api/v1/ingestion/commit", headers=alice.h, json={"import_batch_id": "b", "resolved_rows": [row]})
    assert res.status_code == 422


# ---------------- search engine / availability (P1-5) -------------------------------------------
def test_BE39_find_free_slots_returns_gaps_between_events():
    """P1-5: free windows between events, never overlapping a hard event."""
    from models import TimeSlot
    from services.search_engine import find_free_slots

    busy = [EventDomain(id=1, owner_id=1, title="c", start_time=datetime(2026, 9, 7, 8, tzinfo=VN_TZ),
                        end_time=datetime(2026, 9, 7, 10, tzinfo=VN_TZ), kind=EventKind.CLASS,
                        source=EventSource.IMPORTED, is_hard=True)]
    slots = find_free_slots(busy, datetime(2026, 9, 7, 7, tzinfo=VN_TZ), datetime(2026, 9, 7, 12, tzinfo=VN_TZ), 60)
    assert slots and all(isinstance(s, TimeSlot) and s.duration_minutes() >= 60 for s in slots)
    assert not any(s.overlaps(busy[0].to_slot()) for s in slots)  # zero overlap guarantee


def test_BE40_availability_engine_meets_200ms_budget_for_a_semester():
    """P1-5 performance criterion: one semester (~15 weeks x 20 classes) in < 200 ms."""
    from services.search_engine import find_free_slots

    events = [EventDomain(id=i, owner_id=1, title="c", kind=EventKind.CLASS, source=EventSource.IMPORTED, is_hard=True,
                          start_time=datetime(2026, 9, 7 + (i % 5), 7 + (i % 4) * 2, tzinfo=VN_TZ),
                          end_time=datetime(2026, 9, 7 + (i % 5), 8 + (i % 4) * 2, tzinfo=VN_TZ)) for i in range(300)]
    t0 = _time.perf_counter()
    find_free_slots(events, datetime(2026, 9, 7, 0, tzinfo=VN_TZ), datetime(2026, 12, 20, 0, tzinfo=VN_TZ), 60)
    assert (_time.perf_counter() - t0) < 0.2
