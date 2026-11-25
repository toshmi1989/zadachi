"""A document of the Cabinet of Ministers ends with the Cabinet: its «Nazoratdan olishni tasdiqlandi» is the last answer, the task is done. For the President's documents it is only a step."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "ВМ", f"ВМ-{i} \n 01.01.2026", f"{i}-банд\nText {i}", "31.12.2026", "2026-12-01", "Cabinet Person", "Бажарилмаган", f"CB000{i}"] for i in range(6)]
BASE = 1_800_000_000_000


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c
        from app.db import connect
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'CB000%'"); d.execute("DELETE FROM users WHERE name='Cabinet Person'"); d.commit(); d.close()


def push(admin, code, types, section="government", status=2):
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "cb"}).json()["key"]}
    it = {"code": code, "found": True, "section": section, "recipient_id": "r" + code, "status": status, "is_done": False, "answers_loaded": True,
          "answers": [{"sender_type": t, "state": 1, "at_ms": BASE + i * 3600000, "active": i == len(types) - 1, "text": "", "org": "", "pd": None} for i, t in enumerate(types)]}
    r = TestClient(app).post("/api/sync/ingest", json={"run_id": 0, "items": [it]}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def card(admin, code):
    t = admin.get(f"/api/tasks?q={code}&size=3&status=all").json()["items"][0]
    return admin.get(f"/api/tasks/{t['id']}").json()


def test_the_cabinets_removal_ends_the_way_of_a_cabinet_document(admin):
    out = push(admin, "CB0000", [10, 25, 35])
    assert out["moved"]["done"] == 1
    c = card(admin, "CB0000")
    assert c["status"] == "done" and c["site"]["stage"]["code"] == "removed" and "Кабинет" in c["site"]["label"]


def test_for_the_presidents_documents_it_is_only_a_step(admin):
    push(admin, "CB0001", [10, 25, 35], section="president")
    c = card(admin, "CB0001")
    assert c["status"] == "progress" and c["site"]["stage"]["code"] == "chamber"                    # it goes on to the Chamber of Accounts


def test_only_when_it_is_the_last_answer(admin):
    push(admin, "CB0002", [10, 25])                                                                 # still with the Cabinet
    assert card(admin, "CB0002")["status"] == "progress" and card(admin, "CB0002")["site"]["stage"]["code"] == "cab"
    push(admin, "CB0003", [10, 25, 35, 29])                                                          # removal confirmed, then sent back to the executor
    assert card(admin, "CB0003")["status"] != "done"


def test_the_review_proposes_it_when_the_automatic_mode_is_off_and_a_manual_status_wins(admin):
    admin.put("/api/sync/settings", json={"auto_apply": False})
    try:
        push(admin, "CB0004", [10, 25, 35])
        assert card(admin, "CB0004")["status"] == "todo"
        item = [i for i in admin.get("/api/sync/review").json()["items"] if i["code"] == "CB0004"][0]
        assert item["proposed"] == "done"
        tid = item["task_id"]
        assert admin.post("/api/sync/apply", json={"task_ids": [tid]}).json()["applied"] == 1
        assert card(admin, "CB0004")["status"] == "done"
    finally:
        admin.put("/api/sync/settings", json={"auto_apply": True})
    t = admin.get("/api/tasks?q=CB0005&size=3").json()["items"][0]
    assert admin.patch(f"/api/tasks/{t['id']}", json={"status": "progress"}).status_code == 200        # a person set the status: the site does not change it
    push(admin, "CB0005", [10, 25, 35])
    assert card(admin, "CB0005")["status"] == "progress"
