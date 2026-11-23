"""A status that a person set by hand is final for the site: the task is not read from the official site any more and its status is never changed by it."""
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"МС-{i} \n 01.01.2026", f"{i}-банд\nText {i}", "31.12.2026", "2026-12-01", "Manual Person", "Бажарилмаган", f"SM000{i}"] for i in range(5)]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'SM000%'"); d.execute("DELETE FROM users WHERE name='Manual Person'"); d.commit(); d.close()


def one(admin, code):
    return admin.get(f"/api/tasks?q={code}&size=3&status=all").json()["items"][0]


def key(admin):
    return {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "ms"}).json()["key"]}


def snap(code, **kw):
    base = {"code": code, "found": True, "section": "president", "recipient_id": "r-" + code, "status": 0, "is_done": False, "answers": [], "answers_loaded": True}
    return base | kw


def test_a_status_set_by_hand_takes_the_task_out_of_the_check(admin):
    t = one(admin, "SM0000")
    assert not t["status_manual"]
    assert admin.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).status_code == 200
    assert one(admin, "SM0000")["status_manual"] is True
    p = one(admin, "SM0004")
    assert admin.patch(f"/api/tasks/{p['id']}", json={"status": "progress"}).status_code == 200          # not only «done»: any status set by hand
    anon = TestClient(app)
    admin.put("/api/settings", json={"sync": {"history_statuses": "all", "history_scope": "all"}})          # even when the history of the done tasks is wanted
    job = anon.get("/api/sync/job", headers=key(admin)).json()
    codes = {x["code"] for x in job["items"]}
    assert "SM0001" in codes and "SM0000" not in codes and "SM0004" not in codes and job["manual_locked"] >= 2
    admin.put("/api/settings", json={"sync": {"history_statuses": "open"}})


def test_the_site_never_changes_such_a_task(admin):
    anon, h = TestClient(app), key(admin)
    ans = [{"sender_type": 10, "state": 1, "at_ms": 1800000000000, "active": True, "text": "", "org": "", "pd": None}]
    out = anon.post("/api/sync/ingest", json={"run_id": 0, "items": [snap("SM0004", status=2, answers=ans), snap("SM0002", status=2, answers=ans), snap("SM0000", status=0)]}, headers=h).json()
    assert one(admin, "SM0004")["status"] == "progress" and one(admin, "SM0000")["status"] == "done"          # kept as the person set them
    assert one(admin, "SM0002")["status"] == "progress" and not one(admin, "SM0002")["status_manual"]       # an ordinary task follows the site, and that is not a manual choice
    assert out["moved"]["progress"] == 1
    t = one(admin, "SM0000")
    card = admin.get(f"/api/tasks/{t['id']}").json()["site"]
    assert card["locked"] is True and card["diff"] is False and card["site_open_we_done"] is False             # no «site disagrees» warning for it
    # the review of the differences does not list it either
    assert "SM0000" not in {i["code"] for i in admin.get("/api/sync/review").json()["items"]}


def test_taking_the_status_of_the_site_is_not_a_manual_choice(admin):
    admin.put("/api/sync/settings", json={"auto_apply": False})
    try:
        anon, h = TestClient(app), key(admin)
        anon.post("/api/sync/ingest", json={"run_id": 0, "items": [snap("SM0003", status=20, is_done=True)]}, headers=h)
        t = one(admin, "SM0003")
        r = admin.post("/api/sync/apply", json={"task_ids": [t["id"]]})
        assert r.status_code == 200 and one(admin, "SM0003")["status"] == "done" and not one(admin, "SM0003")["status_manual"]
    finally:
        admin.put("/api/sync/settings", json={"auto_apply": True})


def test_the_check_can_be_turned_back_on_and_an_overwriting_load_does_it_too(admin):
    t = one(admin, "SM0000")
    assert admin.post(f"/api/tasks/{t['id']}/site-check", json={"on": True}).json()["status_manual"] is False
    assert not one(admin, "SM0000")["status_manual"]
    assert admin.post(f"/api/tasks/{t['id']}/site-check", json={"on": False}).json()["status_manual"] is True
    assert admin.post("/api/tasks/987654/site-check", json={"on": True}).status_code == 404
    assert TestClient(app).post(f"/api/tasks/{t['id']}/site-check", json={"on": True}).status_code == 401
    # a base load that overwrites what a person set gives the task back to the site's check
    r = admin.post("/api/import?dry=0&overwrite=1", files={"file": ("x.xlsx", xlsx(ROWS))})
    assert r.status_code == 200
    assert one(admin, "SM0000")["status"] == "todo" and not one(admin, "SM0000")["status_manual"]


def test_an_employee_who_marks_their_task_done_locks_it_too(admin):
    admin.post("/api/users", json={"name": "Manual Person", "login": "manual.p", "role": "user"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "manual.p"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    u.post("/login", data={"login": "manual.p", "password": pw})
    t = one(admin, "SM0001")
    assert u.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).status_code == 200
    assert one(admin, "SM0001")["status_manual"] is True
