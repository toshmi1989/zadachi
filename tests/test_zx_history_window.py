"""The history of answers: only the last month is read and kept (a setting). Today in the tests is 2026-11-16."""
import calendar
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"ПҚ-8{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", "Window Person", "Бажарилмаган", f"HW000{i}"] for i in range(4)]
MS = lambda y, m, d, h=12: calendar.timegm(datetime.datetime(y, m, d, h).timetuple()) * 1000
OLD, NEW = MS(2026, 7, 13), MS(2026, 11, 10)


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c
        c.put("/api/settings", json={"sync": {"history_days": "0"}})


def key(admin):
    return {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "w"}).json()["key"]}


def ans(t, at, text="Ответ"):
    return {"sender_type": t, "state": 1, "at_ms": at, "active": False, "text": text, "org": "Орган", "pd": None}


def snap(code, answers):
    return {"code": code, "found": True, "section": "president", "recipient_id": "r-" + code, "status": 2, "is_done": False, "answers_loaded": True, "answers": answers, "answers_total": len(answers)}


def card(admin, code):
    t = admin.get(f"/api/tasks?q={code}&size=3").json()["items"][0]
    return admin.get(f"/api/tasks/{t['id']}").json()["site"]


def test_the_setting_and_the_job(admin):
    assert admin.put("/api/settings", json={"sync": {"history_days": "45"}}).status_code == 400
    assert admin.put("/api/settings", json={"sync": {"history_days": "30"}}).status_code == 200
    assert TestClient(app).get("/api/sync/job", headers=key(admin)).json()["answers_days"] == 30
    assert "history_days" in str(admin.get("/api/settings").json()["sync"])


def test_old_answers_are_not_kept_and_the_stage_comes_from_the_recent_ones(admin):
    h = key(admin)
    r = TestClient(app).post("/api/sync/ingest", json={"run_id": 0, "items": [snap("HW0000", [ans(10, OLD), ans(25, OLD + 3600000), ans(10, NEW, "Свежий ответ")])]}, headers=h)
    assert r.status_code == 200
    s = card(admin, "HW0000")
    assert [a["text"] for a in s["answers"]] == ["Свежий ответ"]                                   # July is not kept
    assert s["answers_total"] == 3 and s["answers_days"] == 30
    assert s["stage"]["code"] == "moj"                                                              # the stage is read from the recent answer


def test_a_task_whose_last_answer_is_older_than_the_window_says_so_and_is_not_guessed(admin):
    h = key(admin)
    TestClient(app).post("/api/sync/ingest", json={"run_id": 0, "items": [snap("HW0001", [ans(10, OLD), ans(25, OLD + 3600000), ans(35, OLD + 7200000)])]}, headers=h)
    s = card(admin, "HW0001")
    assert s["answers"] == [] and s["answers_total"] == 3
    assert s["stage"]["code"] == "quiet" and "30" in s["stage"]["label"]
    # on the dashboard such a task is under «Другое», it is not «Ответ не введён»
    t = admin.get("/api/tasks?q=HW0001&size=3").json()["items"][0]
    assert t["id"] in [x["id"] for x in admin.get("/api/tasks?stage=other&status=open&size=200").json()["items"]]


def test_what_was_stored_before_is_hidden_by_the_window_at_once_and_everything_with_zero(admin):
    h = key(admin)
    admin.put("/api/settings", json={"sync": {"history_days": "0"}})                                # the whole history: stored as it is
    TestClient(app).post("/api/sync/ingest", json={"run_id": 0, "items": [snap("HW0002", [ans(10, OLD, "Июльский"), ans(10, NEW, "Свежий")])]}, headers=h)
    assert len(card(admin, "HW0002")["answers"]) == 2
    admin.put("/api/settings", json={"sync": {"history_days": "30"}})                               # a month: the old one is hidden without a new synchronisation
    s = card(admin, "HW0002")
    assert [a["text"] for a in s["answers"]] == ["Свежий"] and s["answers_total"] == 2
    admin.put("/api/settings", json={"sync": {"history_days": "90"}})                               # three months: July (125 days ago) is still outside
    assert [a["text"] for a in card(admin, "HW0002")["answers"]] == ["Свежий"]
    admin.put("/api/settings", json={"sync": {"history_days": "0"}})
    assert len(card(admin, "HW0002")["answers"]) == 2
