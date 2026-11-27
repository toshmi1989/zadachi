"""Tasks are added by their codes only; the collector fills the rest from the site's list. A task can be deleted."""
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_site_import import PRIMARY, export, row


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        d = connect()
        d.execute("DELETE FROM tasks WHERE code IN ('ABC1234','XYZ9999','HUC5926','FIL0001')")
        d.execute("DELETE FROM users WHERE name IN ('Fill Person','Other Person')")
        d.commit()
        d.close()


def hdr(admin):
    return {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "codes"}).json()["key"], "content-type": "application/octet-stream"}


def task(admin, code):
    return admin.get(f"/api/tasks?q={code}&size=5&status=all").json()["items"][0]


def test_tasks_are_added_by_codes_only_the_rest_waits_for_the_script(admin):
    r = admin.post("/api/tasks/by-codes", json={"codes": "abc1234, XYZ9999\nBAD  HUC5926 abc1234"}).json()
    assert r["created"] == ["ABC1234", "XYZ9999", "HUC5926"] and r["invalid"] == ["BAD"] and r["existing"] == []
    r2 = admin.post("/api/tasks/by-codes", json={"codes": ["ABC1234", "XYZ9999", "FIL0001"]}).json()
    assert r2["existing"] == ["ABC1234", "XYZ9999"] and r2["created"] == ["FIL0001"]
    t = task(admin, "ABC1234")
    assert t["pending"] and t["by_code"] and t["text"] == "" and t["status"] == "todo" and t["manual"]
    assert admin.post("/api/tasks/by-codes", json={"codes": ""}).status_code == 400
    assert admin.post("/api/tasks/by-codes", json={"codes": " ".join(f"AAA{i:04d}" for i in range(301))}).status_code == 400
    assert TestClient(app).post("/api/tasks/by-codes", json={"codes": "ABC1234"}).status_code == 401
    p = admin.get("/api/tasks-pending").json()
    assert p["count"] == 4 and "HUC5926" in p["codes"]
    h = hdr(admin)
    plan = TestClient(app).get("/api/sync/export-plan", headers=h)
    assert plan.status_code == 200 and plan.json()["pending"] == 4                                  # the collector learns that tasks wait for their data
    job = TestClient(app).get("/api/sync/job", headers=h).json()
    assert {"ABC1234", "XYZ9999", "HUC5926"} <= {x["code"] for x in job["items"]}                # they are read like every task of the site


def test_the_script_fills_the_tasks_from_the_list_of_the_site(admin):
    h = hdr(admin)
    data = export([row("ABC1234", PRIMARY, "Fill Person", "20.12.2026", text="1-банд-банд\nПодготовить заключение"), row("OTH9999", PRIMARY, "Other Person", "20.12.2026")])
    assert admin.post("/api/sync/export?source=x&fill=1", content=data).status_code in (401, 403)
    r = admin.post("/api/sync/export?source=x&fill=1", content=data, headers=h).json()
    assert r["fill"] and r["filled"] == 1 and set(r["pending"]) == {"XYZ9999", "HUC5926", "FIL0001"}
    t = task(admin, "ABC1234")
    assert not t["pending"] and "Подготовить заключение" in t["text"] and t["due"] == "2026-12-20" and t["assignee_raw"] == "Fill Person" and t["assignee_id"] and t["kind"]
    assert not admin.get("/api/tasks?q=OTH9999&status=all").json()["items"]                      # a task nobody asked for is not created
    assert admin.get("/api/tasks-pending").json()["count"] == 3
    # an ordinary export (the normal path) fills the others too
    data2 = export([row("XYZ9999", PRIMARY, "Fill Person", "21.12.2026", text="2-банд-банд\nДругая задача")])
    r2 = admin.post("/api/sync/export?source=y", content=data2, headers=h).json()
    assert r2["filled"] == 1 and set(r2["pending"]) == {"HUC5926", "FIL0001"}
    assert "Другая задача" in task(admin, "XYZ9999")["text"]


def test_a_loaded_base_keeps_the_tasks_added_by_code(admin):
    from test_site_import import post
    admin.put("/api/settings", json={"sync": {"base_f_dept": "0"}})
    r = post(admin, [row("SX0900", PRIMARY, "Fill Person", "25.12.2026")], dry=0, window=("2026-12-01", "2026-12-31"), extra="&replace=1&confirm=1&f_dept=0&f_window=0")
    assert r.status_code == 200
    assert task(admin, "ABC1234")["status"] != "gone" and task(admin, "HUC5926")["status"] != "gone"      # the base does not take them off; they are not in its files
    d = connect(); d.execute("DELETE FROM tasks WHERE code='SX0900'"); d.commit(); d.close()


def test_a_task_is_deleted(admin):
    t = task(admin, "FIL0001")
    assert TestClient(app).delete(f"/api/tasks/{t['id']}").status_code == 401
    r = admin.delete(f"/api/tasks/{t['id']}")
    assert r.status_code == 200 and r.json()["code"] == "FIL0001"
    assert admin.get(f"/api/tasks/{t['id']}").status_code == 404 and not admin.get("/api/tasks?q=FIL0001&status=all").json()["items"]
    assert admin.delete(f"/api/tasks/{t['id']}").status_code == 404
    c = connect()
    assert c.execute("SELECT COUNT(*) FROM audit WHERE action='task.delete'").fetchone()[0] >= 1
    c.close()
    assert admin.get("/api/tasks-pending").json()["count"] == 1


def test_an_ordinary_user_can_neither_add_nor_delete(admin):
    admin.post("/api/users", json={"name": "Plain Codes", "login": "plain.codes", "role": "user"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "plain.codes"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    u.post("/login", data={"login": "plain.codes", "password": pw})
    tid = task(admin, "ABC1234")["id"]
    assert u.post("/api/tasks/by-codes", json={"codes": "QQQ1111"}).status_code == 403
    assert u.delete(f"/api/tasks/{tid}").status_code == 403
    assert u.get("/api/tasks-pending").status_code == 403
    assert task(admin, "ABC1234")


def test_a_task_added_by_code_is_on_the_dashboard_and_a_period_says_where_it_went(admin):
    admin.post("/api/tasks/by-codes", json={"codes": "NTM0001"})
    d = admin.get("/api/dashboard").json()
    assert d["total"]["nodate"]["open"] >= 1 and d["no_term"] == 0                                          # no period: it is counted (no term, no department)
    p = admin.get("/api/dashboard?period=2026").json()
    assert p["no_term"] >= 1                                                                                # a period leaves it out, and the page tells how many such tasks there are
    c = connect(); c.execute("DELETE FROM tasks WHERE code='NTM0001'"); c.commit(); c.close()


def test_a_waiting_task_can_be_filled_by_hand_and_keeps_its_code(admin):
    admin.post("/api/tasks/by-codes", json={"codes": "QDJ8838"})
    t = task(admin, "QDJ8838")
    assert t["pending"]
    for bad in ({}, {"text": " "}, {"text": "x", "scope": "nope"}, {"text": "x", "status": "gone"}, {"text": "x", "assignee_id": 999999}, {"text": "x", "close_date": "31.12"}):
        assert admin.post(f"/api/tasks/{t['id']}/fill", json=bad).status_code == 400, bad
    r = admin.post(f"/api/tasks/{t['id']}/fill", json={"text": "Мамлакатнинг юқори иқтисодий ўсишига туртки берувчи устувор вазифаларни амалга ошириш", "kind": "Фармойиш", "doc_no": "Ф-66",
                                                       "doc_date": "2026-11-16", "point": "18.2-банд", "due": "2026-12-15", "scope": "main", "status": "progress"})
    assert r.status_code == 200
    t2 = task(admin, "QDJ8838")
    assert t2["code"] == "QDJ8838" and not t2["pending"] and t2["doc_no"] == "Ф-66" and t2["kind"] == "Фармойиш" and t2["status"] == "progress"
    assert "QDJ8838" not in admin.get("/api/tasks-pending").json()["codes"]
    c = connect(); m = c.execute("SELECT manual FROM tasks WHERE code='QDJ8838'").fetchone()[0]; c.close()
    assert m == 2                                                                                         # still the site's task: the synchronisation reads it by the code
    assert admin.post(f"/api/tasks/{t['id']}/fill", json={"text": "again"}).status_code == 400             # filled already
    c = connect(); c.execute("DELETE FROM tasks WHERE code='QDJ8838'"); c.commit(); c.close()
