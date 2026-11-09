"""RG-01..RG-05: confirmed timetable rows are indexed for retrieval (P1-4)."""
from conftest import class_row
from services import rag


def commit(client, acc, batch, rows, replace=False):
    res = client.post("/api/v1/ingestion/commit", headers=acc.h,
                      json={"import_batch_id": batch, "resolved_rows": rows, "replace_previous_imports": replace})
    assert res.status_code == 200, res.text
    return res


def test_RG01_commit_indexes_the_timetable_and_retrieval_finds_the_class(client, alice):
    commit(client, alice, "b1", [class_row(code="CSC10014", title="Computational Thinking", weekday="MON", room="B11.02")])
    hits = rag.retrieve(alice.id, "Computational Thinking thứ 2 phòng nào", k=1)
    assert hits and "Computational Thinking" in hits[0].text and "Thứ 2" in hits[0].text and "B11.02" in hits[0].text
    assert hits[0].source == "timetable-b1"


def test_RG02_second_import_keeps_the_first_unless_replacing(client, alice):
    commit(client, alice, "b1", [class_row(code="MTH1", title="Calculus", weekday="TUE")])
    commit(client, alice, "b2", [class_row(code="PHY1", title="Physics", weekday="WED")])
    assert {h.source for h in rag.VectorIndex(alice.id).search("class", 10)} == {"timetable-b1", "timetable-b2"}
    commit(client, alice, "b3", [class_row(code="CHM1", title="Chemistry", weekday="THU")], replace=True)
    assert {h.source for h in rag.VectorIndex(alice.id).search("class", 10)} == {"timetable-b3"}


def test_RG03_each_user_has_a_private_index(client, alice, bob):
    commit(client, alice, "b1", [class_row(title="Secret Seminar")])
    assert rag.retrieve(bob.id, "Secret Seminar", k=3) == []


def test_RG04_indexing_failure_never_breaks_the_import(client, alice, monkeypatch):
    monkeypatch.setattr(rag, "index_timetable_rows", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert commit(client, alice, "b1", [class_row()]).json()["created_count"] > 0


def test_RG05_row_description_is_readable_vietnamese_with_dates():
    from types import SimpleNamespace
    from datetime import date, time
    row = SimpleNamespace(course_code="X1", title="Lab", kind="CLASS", weekday="SAT", room=None,
                          start_time=time(7, 30), end_time=time(9, 0), first_date=date(2026, 9, 7), last_date=date(2026, 12, 1))
    assert rag.describe_timetable_row(row) == "X1 Lab (CLASS): Thứ 7 07:30-09:00, từ 2026-09-07 đến 2026-12-01"
