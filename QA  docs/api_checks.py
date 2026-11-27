"""
QA: black-box API checks against a RUNNING backend (the 24+ cases listed in QA_Guide.md part D).

Standard / method : ISO/IEC 25010 functional correctness; business rules and status codes from BE_QA.md sections 2 and 7.
Run               : python "QA  docs/api_checks.py"                                # backend on http://127.0.0.1:8080
                    python "QA  docs/api_checks.py" --fallback-base http://127.0.0.1:8081   # also test AI-outage behaviour
                    python "QA  docs/api_checks.py" --perf 60                      # also measure latency of /assistant/understand
Safety            : it creates users named qa_<random> / display_name QA_<random> and a few events. Use it on a LOCAL backend
                    and a throw-away database. Do NOT point it at a shared host unless the owner agreed (users cannot be
                    deleted through the API; see QA_Guide.md part F).
The second backend for --fallback-base must be started with VLLM_ENDPOINT=http://127.0.0.1:1/v1/chat/completions.
"""
import argparse
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

VN = timezone(timedelta(hours=7))
QA_DIR = Path(__file__).resolve().parent
RESULTS: list[dict] = []


def iso(dt: datetime) -> str:
    return dt.astimezone(VN).strftime("%Y-%m-%dT%H:%M:%S+07:00")


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method, path, token=None, json_body=None, params=None, timeout=60):
        h = {"Authorization": f"Bearer {token}"} if token else {}
        t0 = time.perf_counter()
        r = requests.request(method, self.base + path, headers=h, json=json_body, params=params, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = r.text
        return r.status_code, r.headers, body, ms


def check(cid, desc, expected, actual, ok):
    RESULTS.append({"id": cid, "desc": desc, "expected": expected, "actual": str(actual)[:160], "pass": bool(ok)})
    print(f"  {'PASS' if ok else 'FAIL'}  {cid}  {desc}   expected: {expected}   actual: {str(actual)[:120]}")


def new_user(c: Client, prefix="qa"):
    name = f"{prefix}_{random.randint(10000, 99999)}"
    s, _, b, _ = c.call("POST", "/api/v1/auth/register", json_body={"username": name, "password": "Passw0rd!", "display_name": f"QA_{name}"})
    assert s == 201, f"register failed: {s} {b}"
    return name, b["access_token"]


def run(base: str, fallback_base: str | None, perf: int) -> int:
    c = Client(base)
    print(f"# api_checks  {datetime.now():%Y-%m-%d %H:%M}  base={base}\n")
    s, _, _, _ = c.call("GET", "/health")
    if s != 200:
        print("backend not reachable:", s)
        return 2

    # ---------------------------------------------------------------- auth
    print("## auth")
    name_a, tok_a = new_user(c)
    name_b, tok_b = new_user(c)
    s, _, _, _ = c.call("POST", "/api/v1/auth/register", json_body={"username": name_a, "password": "Passw0rd!", "display_name": "dup"})
    check("API-01", "register with a taken username", 409, s, s == 409)
    s, _, _, _ = c.call("POST", "/api/v1/auth/register", json_body={"username": "qa_short_pw", "password": "12345", "display_name": "x"})
    check("API-02", "password of 5 characters is rejected", 422, s, s == 422)
    s, _, _, _ = c.call("POST", "/api/v1/auth/login", json_body={"username": name_a, "password": "wrong-password"})
    check("API-03", "login with a wrong password", 401, s, s == 401)
    s, _, _, _ = c.call("GET", "/api/v1/search/events", params={"q": "x"})
    check("API-04", "protected endpoint without a token", 401, s, s == 401)
    s, _, _, _ = c.call("POST", "/api/v1/auth/login", json_body={"username": name_a, "password": "Passw0rd!"})
    check("API-04b", "login with the correct password", 200, s, s == 200)

    # ---------------------------------------------------------------- events
    print("## events")
    base_day = (datetime.now(VN) + timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = base_day.replace(hour=14), base_day.replace(hour=15)
    s, h, ev, _ = c.call("POST", "/api/v1/events", tok_a, {"title": "QA event A", "kind": "EVENT", "start_time": iso(start), "end_time": iso(end), "room": "R1"})
    check("API-05", "create a valid event", 201, s, s == 201)
    ev_id = ev["id"] if s == 201 else -1
    s, _, _, _ = c.call("POST", "/api/v1/events", tok_a, {"title": "QA zero", "kind": "EVENT", "start_time": iso(start), "end_time": iso(start)})
    check("API-06", "end_time == start_time on a non-deadline event", 422, s, s == 422)
    s, h, _, _ = c.call("PATCH", f"/api/v1/events/{ev_id}", tok_b, {"title": "hacked"})
    check("API-07a", "user B patches user A's event (IDOR)", "404 + BE_BUSINESS_RULE_REJECTION", f"{s} {h.get('X-Error-Source', '')[:30]}", s == 404 and (h.get("X-Error-Source") or "").startswith("BE_BUSINESS_RULE_REJECTION"))
    s, _, _, _ = c.call("DELETE", f"/api/v1/events/{ev_id}", tok_b)
    check("API-07b", "user B deletes user A's event (IDOR)", 404, s, s == 404)
    s, _, ex, _ = c.call("POST", "/api/v1/events", tok_a, {"title": "QA exam", "kind": "EXAM", "start_time": iso(start + timedelta(days=1)), "end_time": iso(end + timedelta(days=1))})
    exam_id = ex["id"] if s == 201 else -1
    s, _, _, _ = c.call("PATCH", f"/api/v1/events/{exam_id}", tok_a, {"start_time": iso(start + timedelta(days=1, hours=1))})
    check("API-09a", "change the time of a hard (EXAM) event", 400, s, s == 400)
    s, _, _, _ = c.call("PATCH", f"/api/v1/events/{exam_id}", tok_a, {"title": "QA exam renamed", "is_important": True})
    check("API-09b", "rename / mark important on a hard event is allowed", 200, s, s == 200)
    s, _, _, _ = c.call("DELETE", f"/api/v1/events/{ev_id}", tok_a)
    check("API-08a", "soft delete an event", 204, s, s == 204)
    s, _, _, _ = c.call("DELETE", f"/api/v1/events/{ev_id}", tok_a)
    check("API-08b", "delete the same event again", 404, s, s == 404)

    # ---------------------------------------------------------------- routing and diagnostic headers
    print("## routing / headers")
    s, h, _, _ = c.call("GET", "/api/v1/khong-ton-tai", tok_a)
    check("API-10", "unknown route", "404 + FASTAPI_ROUTER_URL_NOT_FOUND", f"{s} {h.get('X-Error-Source', '')[:34]}", s == 404 and (h.get("X-Error-Source") or "").startswith("FASTAPI_ROUTER_URL_NOT_FOUND"))
    s, h, _, _ = c.call("GET", "/health")
    rid, pt = h.get("X-Request-ID", ""), h.get("X-Process-Time-Ms", "")
    check("API-11", "diagnostic headers on every response", "X-Request-ID (8 hex) and X-Process-Time-Ms", f"{rid} {pt}", re.fullmatch(r"[0-9a-f]{8}", rid or "") and re.fullmatch(r"\d+(\.\d+)?", pt or ""))

    # ---------------------------------------------------------------- AI scheduling flow (uses the real LLM if the backend has one)
    print("## assistant")
    s, _, u1, _ = c.call("POST", "/api/v1/assistant/understand", tok_a, {"prompt": "xếp 2 tiếng học bài ngày mai"})
    prop = (u1 or {}).get("proposal") if s == 200 else None
    check("API-12", "schedule a 2-hour task for tomorrow", "200 + proposal", f"{s} proposal={'yes' if prop else 'no'} fallback={(u1 or {}).get('nlu', {}).get('fallback_mode') if s == 200 else '-'}", s == 200 and prop)
    if prop:
        s, _, cf, _ = c.call("POST", f"/api/v1/proposals/{prop['id']}/confirm", tok_a)
        check("API-14", "confirm the proposal", "200 + events + reminders", f"{s} events={len((cf or {}).get('events', [])) if s == 200 else '-'}", s == 200 and (cf or {}).get("events") and "reminders" in cf)
        s, _, _, _ = c.call("POST", f"/api/v1/proposals/{prop['id']}/confirm", tok_a)
        check("API-15", "confirm the same proposal again", 409, s, s == 409)
    s, _, u2, _ = c.call("POST", "/api/v1/assistant/understand", tok_a, {"prompt": "xếp 1 tiếng đọc sách ngày mai"})
    p2 = (u2 or {}).get("proposal") if s == 200 else None
    if p2:
        s, _, _, _ = c.call("POST", f"/api/v1/proposals/{p2['id']}/reject", tok_a)
        check("API-16a", "reject a proposal", 200, s, s == 200)
        s, _, _, _ = c.call("POST", f"/api/v1/proposals/{p2['id']}/confirm", tok_a)
        check("API-16b", "confirm after reject", 409, s, s == 409)
    else:
        check("API-16", "reject a proposal (needs a proposal)", "proposal", s, False)
    s, _, u3, _ = c.call("POST", "/api/v1/assistant/understand", tok_a, {"prompt": "xếp lịch học bài"})
    nlu = (u3 or {}).get("nlu", {}) if s == 200 else {}
    check("API-13", "task without a duration asks a clarification", "needs_clarification and no proposal", f"{s} nc={nlu.get('needs_clarification')} proposal={bool((u3 or {}).get('proposal'))}", s == 200 and nlu.get("needs_clarification") is True and not (u3 or {}).get("proposal"))
    s, _, u4, _ = c.call("POST", "/api/v1/assistant/understand", tok_a, {"prompt": "ngày mai có lịch gì"})
    check("API-20", "a schedule question typed in the chat box", "redirect_target = search_home", (u4 or {}).get("redirect_target") if s == 200 else s, s == 200 and (u4 or {}).get("redirect_target") == "search_home")
    s, _, u5, _ = c.call("POST", "/api/v1/assistant/understand", tok_a, {"prompt": "asdf qwer"})
    n5 = (u5 or {}).get("nlu", {}) if s == 200 else {}
    check("API-25", "nonsense input: unknown intent, no proposal, and it is not reported as an AI failure", "200, intent=unknown, fallback_mode=false", f"{s} {n5.get('intent')} fallback={n5.get('fallback_mode')}", s == 200 and n5.get("intent") == "unknown" and not n5.get("fallback_mode") and not (u5 or {}).get("proposal"))

    # ---------------------------------------------------------------- manual slot picker
    print("## manual slot")
    slot = (base_day + timedelta(days=2)).replace(hour=10)
    c.call("POST", "/api/v1/events", tok_a, {"title": "QA busy", "kind": "EVENT", "start_time": iso(slot), "end_time": iso(slot + timedelta(hours=1))})
    s, _, _, _ = c.call("POST", "/api/v1/proposals/manual", tok_a, {"title": "QA manual", "duration_minutes": 60, "slot_start": iso(slot), "slot_end": iso(slot + timedelta(hours=1))})
    check("API-17", "manual slot that collides with an existing event", 409, s, s == 409)
    s, _, _, _ = c.call("POST", "/api/v1/proposals/manual", tok_a, {"title": "QA manual", "duration_minutes": 60, "slot_start": iso(slot.replace(minute=7) + timedelta(days=1)), "slot_end": iso(slot.replace(minute=7) + timedelta(days=1, hours=1))})
    check("API-18", "manual slot start not on the 15-minute grid", 422, s, s == 422)
    ok_slot = slot + timedelta(days=2, hours=3)
    s, _, _, _ = c.call("POST", "/api/v1/proposals/manual", tok_a, {"title": "QA manual ok", "duration_minutes": 60, "slot_start": iso(ok_slot), "slot_end": iso(ok_slot + timedelta(hours=1))})
    check("API-17b", "manual slot in free time", 201, s, s == 201)

    # ---------------------------------------------------------------- search and academic
    print("## search")
    for cid, phrase in (("API-21", "xếp cho mình 2 tiếng học bài"), ("API-21b", "xếp 2 tiếng học bài"), ("API-21c", "lên lịch học bài ngày mai")):
        s, _, se, _ = c.call("GET", "/api/v1/search/events", tok_a, params={"q": phrase})
        got = (se or {}).get("redirect_target") if s == 200 else s
        check(cid, f"scheduling command typed in the search box: '{phrase}'", "redirect_target = chat_home", got, s == 200 and got == "chat_home")
    s, _, se2, _ = c.call("GET", "/api/v1/search/events", tok_a, params={"q": "QA exam"})
    check("API-26", "search finds the user's own event and not another user's", "own event found", f"{s} total={(se2 or {}).get('total')}", s == 200 and (se2 or {}).get("total", 0) >= 1)
    s, _, se3, _ = c.call("GET", "/api/v1/search/events", tok_b, params={"q": "QA exam"})
    check("API-26b", "user B cannot see user A's events in search", "total = 0", f"{s} total={(se3 or {}).get('total')}", s == 200 and (se3 or {}).get("total") == 0)
    s, _, ac, ms = c.call("POST", "/api/v1/search/academic/ask", tok_a, {"query": "cách nấu phở bò"}, timeout=60)
    ans = ((ac or {}).get("answer") or "").lower() if s == 200 else ""
    refused = any(k in ans for k in ("không thể", "không có thông tin", "xin lỗi", "không được đề cập"))
    check("API-22", "out-of-scope academic question is refused", "200 and a refusal", f"{s} refused={refused} citations={len((ac or {}).get('citations', [])) if s == 200 else '-'} ({ms:.0f} ms)", s == 200 and refused)
    check("API-22b", "...and no unrelated citations are shown with the refusal", "0 citations", len((ac or {}).get("citations", [])) if s == 200 else "-", s == 200 and not (ac or {}).get("citations"))

    # ---------------------------------------------------------------- import
    print("## import")
    s, _, pp, _ = c.call("POST", "/api/v1/ingestion/parse-preview", tok_a, {"raw_content": "xin chào, đây không phải thời khóa biểu", "filename": "note.txt"})
    check("API-23", "a text that is not a timetable", "422 or 200 with 0 rows", f"{s} valid={(pp or {}).get('valid_count') if s == 200 else '-'}", s == 422 or (s == 200 and (pp or {}).get("valid_count") == 0))
    day0 = (datetime.now(VN) + timedelta(days=1)).date()
    wd = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][(day0 + timedelta(days=7)).weekday()]

    def commit(batch, title, replace):
        row = {"line_number": 2, "course_code": "QA101", "title": title, "kind": "CLASS", "start_time": "07:30", "end_time": "09:30",
               "first_date": day0.isoformat(), "last_date": (day0 + timedelta(days=21)).isoformat(), "weekday": wd, "room": "QA"}
        return c.call("POST", "/api/v1/ingestion/commit", tok_a, {"import_batch_id": batch, "resolved_rows": [row], "replace_previous_imports": replace})

    s, _, c1, _ = commit("qa-batch-1", "QA Import First", False)
    check("API-24a", "commit a timetable", "200 and events created", f"{s} created={(c1 or {}).get('created_count') if s == 200 else '-'}", s == 200 and (c1 or {}).get("created_count", 0) > 0)
    c.call("POST", "/api/v1/events", tok_a, {"title": "QA Manual Keep", "kind": "EVENT", "start_time": iso(base_day + timedelta(days=4, hours=16)), "end_time": iso(base_day + timedelta(days=4, hours=17))})
    s, _, c2, _ = commit("qa-batch-2", "QA Import Second", True)
    def exact(title):
        _, _, r, _ = c.call("GET", "/api/v1/search/events", tok_a, params={"q": title})
        return sum(1 for e in (r or {}).get("events", []) if e["title"] == title)

    old, new, keep = exact("QA Import First"), exact("QA Import Second"), exact("QA Manual Keep")
    check("API-24b", "replace_previous_imports: old import removed, new present, manual event kept", "old=0 new>0 manual>=1", f"commit={s} old={old} new={new} manual={keep}", s == 200 and old == 0 and new > 0 and keep >= 1)

    # ---------------------------------------------------------------- AI outage on a second backend
    if fallback_base:
        print("## AI outage (backend started with an unreachable VLLM_ENDPOINT)")
        f = Client(fallback_base)
        _, tok_f = new_user(f, "qaf")
        ok_all, fb = True, 0
        for i, prompt in enumerate(["xếp 2 tiếng học bài ngày mai", "xếp 90 phút ôn thi thứ sáu", "xếp 1 tiếng đọc sách hôm nay"]):
            s, _, uf, ms = f.call("POST", "/api/v1/assistant/understand", tok_f, {"prompt": prompt})
            nf = (uf or {}).get("nlu", {}) if s == 200 else {}
            slots = (uf or {}).get("available_slots", []) if s == 200 else []
            good = s == 200 and nf.get("fallback_mode") is True and len(slots) > 0
            fb += good
            check(f"API-19.{i + 1}", f"AI down: '{prompt}'", "200, fallback_mode=true, available_slots>0, no 500", f"{s} fallback={nf.get('fallback_mode')} slots={len(slots)} ({ms:.0f} ms)", good)
        s, _, acf, _ = f.call("POST", "/api/v1/search/academic/ask", tok_f, {"query": "điều kiện tốt nghiệp là gì"})
        check("API-19.4", "AI down: academic question", "200, fallback_mode=true", f"{s} fallback={(acf or {}).get('fallback_mode') if s == 200 else '-'}", s == 200 and (acf or {}).get("fallback_mode") is True)

    # ---------------------------------------------------------------- latency of /assistant/understand
    perf_summary = None
    if perf:
        print(f"\n## latency of POST /assistant/understand ({perf} sequential calls, real LLM)")
        prompts = ["xếp 2 tiếng học bài ngày mai", "xếp 90 phút ôn thi thứ sáu", "xếp 45 phút đọc sách cuối tuần", "xếp 3 tiếng làm đồ án tuần sau",
                   "tuần này mình có lịch gì", "xóa buổi gym ngày mai", "dời buổi họp sang thứ 6", "hôm nay trời đẹp quá", "xếp 1 tiếng họp nhóm thứ 4",
                   "xep 30 phut chay bo hom nay", "xếp 2 giờ học tiếng Anh tuần sau", "khi nào mình rảnh"]
        _, tok_p = new_user(c, "qap")
        wall, be, fb_n, bad = [], [], 0, 0
        for i in range(perf):
            s, h, body, ms = c.call("POST", "/api/v1/assistant/understand", tok_p, {"prompt": prompts[i % len(prompts)]})
            if s != 200:
                bad += 1
                continue
            wall.append(ms)
            be.append(float(h.get("X-Process-Time-Ms", "nan")))
            fb_n += bool(body.get("nlu", {}).get("fallback_mode"))

        def pc(v, p):
            v = sorted(x for x in v if x == x)
            return v[max(0, math.ceil(p / 100 * len(v)) - 1)] if v else float("nan")

        perf_summary = {"calls": perf, "non_200": bad, "fallback": fb_n, "wall_ms": {p: round(pc(wall, p)) for p in (50, 95, 99)},
                        "backend_ms": {p: round(pc(be, p)) for p in (50, 95, 99)}}
        print(f"  calls={perf} non-200={bad} fallback={fb_n}  wall p50/p95/p99 = {perf_summary['wall_ms']}  backend (X-Process-Time-Ms) = {perf_summary['backend_ms']}")

    n_pass = sum(r["pass"] for r in RESULTS)
    print(f"\n== {n_pass}/{len(RESULTS)} checks passed ==")
    (QA_DIR / "api_check_results.json").write_text(json.dumps({"base": base, "measured_at": datetime.now().isoformat(timespec="seconds"), "results": RESULTS, "perf": perf_summary}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--fallback-base", default=None)
    ap.add_argument("--perf", type=int, default=0)
    a = ap.parse_args()
    sys.exit(run(a.base, a.fallback_base, a.perf))
