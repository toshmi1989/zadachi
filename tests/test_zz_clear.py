"""«Очистить базу»: erases every task after a copy of the database is made. Named so that it runs last: it empties the database that the modules share."""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import backup, db
from app.main import app
from test_app import xlsx

ROWS = [[1, "Қарор", "ПҚ-3 \n 01.01.2026", "1-банд\nТекст", "31.12.2026", "2026-12-01", "Clear Person", "Бажарилмаган", "CL0001"],
        [2, "Қарор", "ПҚ-3 \n 01.01.2026", "2-банд\nТекст", "31.12.2026", "2026-12-02", "Clear Person", "Бажарилган", "CL0002"]]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c


def test_clearing_the_base_needs_the_word_makes_a_copy_and_keeps_people(admin):
    assert admin.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
    assert admin.post("/api/tasks", json={"text": "Задача вручную"}).status_code == 200               # a manual one goes too
    info = admin.get("/api/import/clear").json()
    assert info["word"] == "ОЧИСТИТЬ" and info["tasks"] >= 3 and info["manual"] >= 1
    users_before = len(admin.get("/api/users").json()["items"])
    for bad in ({}, {"confirm": ""}, {"confirm": "очистить"}, {"confirm": "yes"}):
        assert admin.post("/api/import/clear", json=bad).status_code == 400, bad                       # nothing is erased without the word
    assert admin.get("/api/dashboard").json()["totals"]["total"] >= 3
    copies = set(os.listdir(backup.DIR))
    r = admin.post("/api/import/clear", json={"confirm": "ОЧИСТИТЬ"})
    assert r.status_code == 200 and r.json()["deleted"] == info["tasks"]
    new = set(os.listdir(backup.DIR)) - copies
    assert new and r.json()["backup"] in set(os.listdir(backup.DIR))                                   # the copy was made first
    c = sqlite3.connect(os.path.join(backup.DIR, r.json()["backup"]))
    assert c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == info["tasks"]                      # and it still has all the tasks: the erase can be undone from it
    c.close()
    assert admin.get("/api/dashboard").json()["totals"]["total"] == 0 and admin.get("/api/tasks").json()["total"] == 0
    cn = db.connect()
    assert cn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] == 0 and cn.execute("SELECT COUNT(*) FROM ijro_snapshots").fetchone()[0] == 0     # the history goes with the tasks
    assert cn.execute("SELECT COUNT(*) FROM audit WHERE action='tasks.clear'").fetchone()[0] == 1                                                      # the journal remembers it
    cn.close()
    assert len(admin.get("/api/users").json()["items"]) == users_before                                # people stay
    assert admin.get("/api/import/clear").json()["tasks"] == 0
    assert admin.post("/api/tasks", json={"text": "После очистки"}).json()["code"] == "M00001"          # the numbering of manual tasks starts again


def test_only_the_administrator_clears(admin):
    admin.post("/api/users", json={"name": "Not Admin", "login": "not.admin", "role": "specialist"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "not.admin"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    s = TestClient(app)
    s.post("/login", data={"login": "not.admin", "password": pw})
    assert s.get("/api/import/clear").status_code == 403 and s.post("/api/import/clear", json={"confirm": "ОЧИСТИТЬ"}).status_code == 403
    assert TestClient(app).post("/api/import/clear", json={"confirm": "ОЧИСТИТЬ"}).status_code == 401
