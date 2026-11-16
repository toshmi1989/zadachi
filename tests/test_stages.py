"""The way of a task on the site (Justice -> Cabinet -> Chamber of Accounts) and the automatic application of what the site says."""
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import ijro
from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", "Stage Person", "Бажарилмаган", f"ST000{i}"] for i in range(4)]


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def snap(types=(), status=0, done=False, due=None, **kw):
    base = {"found": 1, "repeatable": 0, "periods": "[]", "is_done": int(done), "site_status": status, "due_ms": due, "is_secret": 0,
            "answers": json.dumps([{"sender_type": t, "at_ms": 1000 + i, "state": 1, "active": 1, "text": ""} for i, t in enumerate(types)])}
    return base | kw


def test_stage_of_every_step():
    S = ijro.stage_of
    assert S(snap(status=0))["code"] == "none" and S(snap(status=0))["n"] == -1
    assert S(snap(status=2))["code"] == "answered"                                         # an answer exists, but its way is not known
    assert S(snap([10], 2))["code"] == "moj" and S(snap([10], 2))["n"] == 1
    assert S(snap([10, 25], 2))["code"] == "cab" and S(snap([10, 25], 2))["n"] == 2
    assert S(snap([10, 25, 35], 2))["code"] == "chamber" and S(snap([10, 25, 35], 2))["n"] == 3
    assert S(snap([10, 25, 35, 45], 20, done=True))["code"] == "removed"                   # 45 = Nazoratdan yechildi: removed from control, done
    assert S(snap([10, 25, 35, 45], 21, done=True))["n"] == 4
    w = S(snap([10, 25, 35, 45], 2))                                                      # the answer of removal, but the site has not marked the task done yet
    assert w["code"] == "removed_wait" and not w["attention"]
    d = S(snap([10, 25, 35, 49], 2, due=ms(2027, 3, 1)))                                    # 49 from the Chamber: the task stays open, the term changes
    assert d["code"] == "info" and d["attention"] and d["new_due"] == "2027-03-01" and d["n"] == 3
    assert S(snap([10, 25, 35, 49], 2, due=ms(2027, 3, 1)), dates=False)["new_due"] is None   # no dates for people who must not see them
    assert S(snap([10, 25, 35, 44], 2))["code"] == "info"                                  # 44 Maʼlumot uchun qabul qilindi (never seen yet, but it is in the site's table)
    assert S(snap([10, 25, 35, 99], 2))["code"] == "chamber_other" and S(snap([10, 25, 35, 99], 2))["attention"]
    assert S(snap([10, 29], 2))["code"] == "returned" and S(snap([10, 25, 18], 2))["code"] == "returned"
    assert S(snap(found=0))["code"] == "not_found"
    assert S(snap(repeatable=1, periods=json.dumps([{"order": 1, "recipient_status": 0, "due_ms": ms(2026, 12, 1)}])))["code"] == "periodic"


def test_comment_of_the_chamber_names_the_case():
    def with_text(text):
        s = snap([10, 25, 35, 49], 2)
        a = json.loads(s["answers"]); a[-1]["text"] = text; s["answers"] = json.dumps(a); return s
    assert ijro.stage_of(with_text("Маълумот учун қабул қилинди"))["label"] == "Маълумот учун қабул қилинди"
    assert ijro.stage_of(with_text("Қўшимча маълумот тақдим этинг"))["label"] == "Қўшимча маълумот сўрови"


def test_the_active_answer_decides():
    s = snap([10, 25, 35])
    a = json.loads(s["answers"])
    for x in a:
        x["active"] = 0
    a[1]["active"] = 1                                                                      # the site marks the Justice answer as the current one
    s["answers"] = json.dumps(a)
    assert ijro.stage_of(s)["code"] == "cab"
    for x in a:
        x["active"] = 0                                                                     # nothing active: the newest one
    s["answers"] = json.dumps(a)
    assert ijro.stage_of(s)["code"] == "chamber"


def test_the_latest_answer_decides_not_the_order_of_arrival():
    s = snap([10, 25])
    a = json.loads(s["answers"]); a.reverse(); s["answers"] = json.dumps(a)                 # the site may return them newest first
    assert ijro.stage_of(s)["code"] == "cab"


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c


@pytest.fixture(scope="module")
def key(admin):
    return admin.post("/api/sync/keys", json={"name": "stages"}).json()["key"]


def push(key, code, answers, status, done=False, due=None):
    it = {"code": code, "found": True, "section": "president", "recipient_id": "rid-" + code, "status": status, "is_done": done, "due_ms": due, "answers_loaded": True,
          "answers": [{"sender_type": t, "state": 1, "at_ms": 1000 + i, "active": True, "text": ""} for i, t in enumerate(answers)]}
    r = TestClient(app).post("/api/sync/ingest", json={"items": [it]}, headers={"authorization": "Bearer " + key})
    assert r.status_code == 200, r.text
    return r.json()


def task(admin, code):
    return admin.get(f"/api/tasks?q={code}").json()["items"][0]


def test_answer_on_the_site_moves_the_task_to_in_progress_by_itself(admin, key):
    assert task(admin, "ST0000")["status"] == "todo"
    assert push(key, "ST0000", [10], 2)["auto_applied"] == 1
    t = admin.get(f"/api/tasks/{task(admin, 'ST0000')['id']}").json()
    assert t["status"] == "progress" and t["site"]["stage"]["code"] == "moj"
    assert t["events"][0]["who"].startswith("Автоматически")                                   # the history says who did it
    push(key, "ST0000", [10, 25, 35], 2)                                                      # on its way, but the Chamber has not decided
    assert task(admin, "ST0000")["status"] == "progress" and task(admin, "ST0000")["site"]["stage"]["code"] == "chamber"


def test_removed_from_control_is_done(admin, key):
    push(key, "ST0001", [10, 25, 35, 45], 20, done=True)
    t = task(admin, "ST0001")
    assert t["status"] == "done" and t["site"]["stage"]["code"] == "removed"


def test_accepted_for_information_reopens_the_task_with_the_new_term(admin, key):
    tid = task(admin, "ST0002")["id"]
    assert admin.patch(f"/api/tasks/{tid}", json={"status": "done"}).status_code == 200        # somebody marked it done after the answer was sent
    assert task(admin, "ST0002")["status"] == "done"
    old_due = admin.get(f"/api/tasks/{tid}?by=due").json()["due"]
    push(key, "ST0002", [10, 25, 35, 49], 2, due=ms(2027, 3, 1))
    full = admin.get(f"/api/tasks/{tid}?by=due").json()
    assert full["status"] == "progress"                                                       # the task is not done: the Chamber only took it for information
    assert full["due"] == "2027-03-01" and old_due != "2027-03-01"
    assert full["site"]["stage"]["code"] == "info" and full["site"]["stage"]["new_due"] == "2027-03-01"
    assert any(e["field"] == "due" for e in full["events"])
    # asking again changes nothing more
    assert push(key, "ST0002", [10, 25, 35, 49], 2, due=ms(2027, 3, 1))["auto_applied"] == 0


def test_stage_filter_and_the_funnel_on_the_dashboard(admin, key):
    got = admin.get("/api/tasks?stage=info").json()
    assert [t["code"] for t in got["items"]] == ["ST0002"]
    assert [t["code"] for t in admin.get("/api/tasks?stage=chamber").json()["items"]] == ["ST0000"]
    st = admin.get("/api/dashboard").json()["stages"]
    by = {s["code"]: s["count"] for s in st["steps"]}
    assert by["info"] == 1 and by["chamber"] == 1 and st["attention"] >= 1
    assert st["unchecked"] >= 1                                                               # ST0003 was never read from the site
    assert admin.get("/api/tasks?stage=unchecked").json()["total"] >= 1


def test_switched_off_the_site_changes_nothing(admin, key):
    assert admin.put("/api/sync/settings", json={"auto_apply": False}).status_code == 200
    try:
        assert push(key, "ST0003", [10, 25, 35, 45], 20, done=True)["auto_applied"] == 0
        assert task(admin, "ST0003")["status"] == "todo"
        assert task(admin, "ST0003")["site"]["diff"] is True                                  # but it is proposed on the review screen
    finally:
        admin.put("/api/sync/settings", json={"auto_apply": True})


def test_employee_sees_the_stage_but_never_the_official_term(admin, key):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"].startswith("stage")][0]
    pw = admin.post(f"/api/users/{uid['id']}/password", json={}).json()["password"]
    emp = TestClient(app)
    emp.post("/login", data={"login": uid["login"], "password": pw})
    tid = task(admin, "ST0002")["id"]
    t = emp.get(f"/api/tasks/{tid}").json()
    assert t["site"]["stage"]["code"] == "info" and "new_due" not in t["site"]["stage"]
    assert all(e["field"] != "due" for e in t["events"]) and "2027-03-01" not in json.dumps(t)
    row = emp.get("/api/tasks?q=ST0002").json()["items"][0]
    assert row["site"]["stage"]["label"] == "Қўшимча маълумот сўрови"


def test_answers_of_one_day_are_not_mixed_up():
    s = snap([35, 25, 10])                                                                  # newest first, all with the same moment (the site gave only a date)
    a = json.loads(s["answers"])
    for x in a:
        x["at_ms"] = 5000
    s["answers"] = json.dumps(a)
    assert ijro.stage_of(s)["code"] == "chamber"                                            # the later step of the chain wins, not the order of arrival


def test_under_review_mark_does_not_hide_the_chamber():
    s = snap([10, 25, 35, 49, 124], 1, due=ms(2027, 3, 1))                                  # status 1, the Chamber returned it and the executor is already reviewing
    g = ijro.stage_of(s)
    assert g["code"] == "info" and "рассматривает" in g["hint"]


def test_status_one_with_answers_means_in_work(admin, key):
    uid = task(admin, "ST0003")["id"]
    assert push(key, "ST0003", [10, 25], 1)["auto_applied"] == 1                              # status 1 is not understood, but the answers are: in work
    t = admin.get(f"/api/tasks/{uid}").json()
    assert t["status"] == "progress" and t["site"]["stage"]["code"] == "cab" and "статус 1" in t["site"]["label"]
    assert admin.patch(f"/api/tasks/{uid}", json={"status": "done"}).status_code == 200
    push(key, "ST0003", [10, 25], 1)
    t = admin.get(f"/api/tasks/{uid}").json()
    assert t["status"] == "done" and t["site"]["site_open_we_done"] is True                  # not reverted by itself: only flagged
