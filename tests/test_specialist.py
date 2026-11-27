"""The specialist only VIEWS: the whole list of tasks, the dashboard, the cards, the Excel exports; every change is the administrator's.
A task added by hand (by the administrator) is never taken off the dashboard by a loaded base."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_app import xlsx
from test_site_import import PRIMARY, export, row

ROWS = [[1, "Қарор", "ПҚ-7 \n 01.01.2026", "1-банд\nТекст специалиста", "31.12.2026", "2026-12-10", "Spec Person", "Бажарилмаган", "SP0001"]]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c
        from app.db import connect
        d = connect()
        d.execute("DELETE FROM task_events WHERE task_id IN (SELECT id FROM tasks WHERE code LIKE 'SP%' OR manual=1)")
        d.execute("DELETE FROM tasks WHERE code LIKE 'SP%' OR manual=1")
        d.execute("DELETE FROM users WHERE login IN ('spec.s', 'special.ist')")
        d.commit(); d.close()


@pytest.fixture(scope="module")
def spec(admin):
    r = admin.post("/api/users", json={"name": "Special Ist", "login": "special.ist", "role": "specialist"})
    assert r.status_code == 200, r.text
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "special.ist"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    c = TestClient(app)
    assert c.post("/login", data={"login": "special.ist", "password": pw}, follow_redirects=False).status_code in (200, 303)
    c.uid = uid
    return c


def test_the_specialist_is_a_role_with_the_task_pages_only(admin, spec):
    me = spec.get("/api/me").json()
    assert me["role"] == "specialist" and me["role_label"] == "Специалист" and me["tasks"] == "all"      # the whole list, whatever «что видит пользователь» says
    for path in ("/api/users", "/api/settings", "/api/import/history", "/api/audit", "/api/sync/review", "/api/units"):
        assert spec.get(path).status_code == 403, path                                                  # nothing of the administrator's
    assert spec.post("/api/import?dry=1", files={"file": ("x.xlsx", b"x")}).status_code == 403
    assert spec.get("/api/tasks").status_code == 200 and spec.get("/api/dashboard").status_code == 200 and spec.get("/api/meta").status_code == 200


def test_the_specialist_changes_nothing(admin, spec):
    t = admin.get("/api/tasks?q=SP0001").json()["items"][0]
    assert t["can_edit"] is True and spec.get("/api/tasks?q=SP0001").json()["items"][0]["can_edit"] is False        # the administrator edits, the specialist only looks
    assert spec.get(f"/api/tasks/{t['id']}").json()["can_edit"] is False and spec.get(f"/api/tasks/{t['id']}").status_code == 200
    me_before = admin.get(f"/api/tasks/{t['id']}").json()
    assert spec.patch(f"/api/tasks/{t['id']}", json={"close_date": "2026-12-20", "assignee_id": spec.uid, "status": "progress"}).status_code == 403
    assert spec.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).status_code == 403                           # not even the status of a task that is theirs
    assert spec.post("/api/tasks/bulk", json={"ids": [t["id"]], "close_date": "2026-12-22"}).status_code == 403
    assert spec.post("/api/tasks", json={"text": "Подготовить справку по вакцинации"}).status_code == 403
    assert spec.post("/api/tasks/by-codes", json={"codes": "SPX1234"}).status_code == 403
    assert spec.post(f"/api/tasks/{t['id']}/fill", json={"text": "x"}).status_code == 403
    assert spec.post(f"/api/tasks/{t['id']}/site-check", json={"on": False}).status_code == 403
    assert spec.get("/api/tasks-pending").status_code == 403
    assert spec.delete(f"/api/tasks/{t['id']}").status_code == 403
    after = admin.get(f"/api/tasks/{t['id']}").json()
    assert after["close_date"] == me_before["close_date"] and after["status"] == me_before["status"] and after["assignee_id"] == me_before["assignee_id"]   # nothing changed
    assert spec.get("/api/report.xlsx").status_code == 200 and spec.get("/api/tasks.xlsx").status_code == 200        # exports are viewing: they stay


def test_the_specialist_never_sees_the_official_term(admin, spec):
    t = spec.get("/api/tasks?q=SP0001").json()["items"][0]
    assert t["due"] is None and spec.get(f"/api/tasks/{t['id']}").json()["due"] is None
    assert admin.get("/api/tasks?q=SP0001&by=due").json()["items"][0]["due"] == "2026-12-31"           # the administrator does
    assert spec.get("/api/dashboard?by=due").json()["by"] in ("strict", "ucl")                           # never the official term itself


def test_a_task_added_by_hand(admin, spec):
    r = admin.post("/api/tasks", json={"text": "Подготовить справку по вакцинации", "kind": "Қарор", "doc_no": "ПҚ-319 от 10.09.2026", "point": "1-банд",
                                       "close_date": "2026-12-12", "assignee_id": spec.uid, "due": "2027-01-01"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["code"].startswith("M") and t["manual"] is True and t["status"] == "todo" and t["close_date"] == "2026-12-12" and t["assignee_id"] == spec.uid
    assert admin.get(f"/api/tasks/{t['id']}?by=due").json()["due"] == "2027-01-01" and spec.get(f"/api/tasks/{t['id']}").json()["due"] is None   # the specialist does not see the official term
    a = admin.post("/api/tasks", json={"text": "Задача администратора", "due": "2027-02-01"}).json()
    assert a["code"] != t["code"] and int(a["code"][1:]) == int(t["code"][1:]) + 1                       # M00001, M00002 ...
    v = admin.post("/api/tasks", json={"text": "ВМ вручную", "scope": "vm", "kind": "ВМ", "doc_no": "VM 22/26-196", "doc_date": "2026-05-12", "point": "3-банд", "close_date": "2026-12-01", "due": "2026-12-20"}).json()
    assert admin.get(f"/api/tasks?q={v['code']}&scope=vm&status=all").json()["total"] == 1 and admin.get(f"/api/tasks?q={v['code']}&status=all").json()["total"] == 0   # it is in the chosen group only
    assert v["doc_no"] == "VM 22/26-196" and v["point"] == "3-банд" and v.get("doc_date") in (None, "2026-05-12")
    assert admin.post("/api/tasks", json={"text": "x", "scope": "nope"}).status_code == 400                # an unknown group is refused
    for bad in ({}, {"text": "  "}, {"text": "x" * 4001}, {"text": "x", "status": "done"}, {"text": "x", "assignee_id": 999999}, {"text": "x", "close_date": "not a date"}, {"text": "x", "kind": "k" * 61}):
        assert admin.post("/api/tasks", json=bad).status_code == 400, bad


def test_a_user_cannot_add_or_edit_by_hand(admin, spec):
    from app.db import connect
    c = connect()
    uid = c.execute("SELECT id FROM users WHERE name='Spec Person'").fetchone()["id"]; c.close()
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    login = [x for x in admin.get("/api/users").json()["items"] if x["id"] == uid][0]["login"]
    u.post("/login", data={"login": login, "password": pw})
    assert u.post("/api/tasks", json={"text": "x"}).status_code == 403
    assert u.post("/api/tasks/bulk", json={"ids": [1], "close_date": "2026-12-01"}).status_code == 403


def test_a_loaded_base_never_takes_a_manual_task_off(admin):
    """The base that is loaded replaces what is on the server, but a task added by hand is not in any file: it stays."""
    manual = admin.get("/api/tasks?size=200&status=open").json()["items"]
    mine = [t for t in manual if t["manual"]]
    assert mine
    far = ("2000-01-01", "2099-12-31")
    pre = admin.post(f"/api/import?dry=1&ai=0&due_from={far[0]}&due_to={far[1]}&overwrite=1&replace=1&f_dept=0&f_exec=0&f_kind=0&f_window=0",
                     files={"file": ("e.xlsx", export([row("SP9001", PRIMARY, "Sitea Primary", "25.12.2026")]))}).json()
    gone = {x["code"] for x in pre["absent_tasks"]["sample"]}
    assert not gone & {t["code"] for t in mine} and "SP0001" in gone                                  # the file's task replaces; a manual one is not even a candidate
    # nor does the history of the site try to read it
    from app import ijro
    from app.db import connect
    c = connect()
    try:
        manual = {r["code"] for r in c.execute("SELECT code FROM tasks WHERE manual=1")}
        for scope in ("month", "month_overdue", "month_next", "all"):
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('history_scope', ?)", (scope,))
            cond, args = ijro.history_filter()
            read = {r["code"] for r in c.execute("SELECT t.code FROM tasks t WHERE 1=1" + cond, args)}
            assert not read & manual, scope
        c.execute("DELETE FROM settings WHERE key='history_scope'"); c.commit()
    finally:
        c.close()
