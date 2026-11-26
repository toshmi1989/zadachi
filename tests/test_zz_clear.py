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


def test_the_erase_can_be_limited_to_a_group_a_year_a_type_or_a_document(admin):
    rows = [[1, "Қарор", "ПҚ-7 \n 01.01.2026", "1-банд\nТекст", "31.12.2026", "2026-12-01", "Part Person", "Бажарилмаган", "PT0001"],
            [2, "Фармон", "ПФ-8 \n 01.01.2027", "1-банд\nТекст", "31.12.2027", "2027-12-02", "Part Person", "Бажарилмаган", "PT0002"],
            [3, "Фармон", "ПФ-8 \n 01.01.2027", "2-банд\nТекст", "31.12.2027", "2027-12-03", "Part Person", "Бажарилган", "PT0003"]]
    assert admin.post("/api/import?dry=0", files={"file": ("p.xlsx", xlsx(rows))}).status_code == 200
    q = lambda **k: admin.get("/api/import/clear", params=k).json()
    full = q()
    assert full["tasks"] >= 3 and {"scopes", "years", "kinds", "docs"} <= set(full["options"])
    assert {y["v"] for y in full["options"]["years"]} >= {"2026", "2027"} and "Фармон" in {k["v"] for k in full["options"]["kinds"]}
    assert q(year="2027")["tasks"] == 2 and q(year="2027", kind="Фармон")["tasks"] == 2 and q(year="2026", kind="Фармон")["tasks"] == 0
    assert q(doc="ПФ-8")["tasks"] == 2 and q(scope="main")["tasks"] == full["tasks"] and q(scope="vm")["tasks"] == 0
    for bad_q in ({"scope": "nope"}, {"year": "20x7"}):                                              # a mistake never widens the erase
        assert admin.get("/api/import/clear", params=bad_q).status_code == 400
        assert admin.post("/api/import/clear", json={**bad_q, "confirm": "ОЧИСТИТЬ"}).status_code == 400
    assert admin.post("/api/import/clear", json={"year": "2027"}).status_code == 400                   # the word is needed for a part too
    assert admin.post("/api/import/clear", json={"year": "1999", "confirm": "ОЧИСТИТЬ"}).status_code == 400   # nothing falls under the choice
    r = admin.post("/api/import/clear", json={"year": "2027", "kind": "Фармон", "confirm": "ОЧИСТИТЬ"})
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert q()["tasks"] == full["tasks"] - 2 and q(doc="ПФ-8")["tasks"] == 0 and q(doc="ПҚ-7")["tasks"] == 1      # only the chosen part went
    cn = db.connect()
    assert "2027" in cn.execute("SELECT details FROM audit WHERE action='tasks.clear' ORDER BY id DESC LIMIT 1").fetchone()[0]
    cn.close()


def test_only_the_administrator_clears(admin):
    admin.post("/api/users", json={"name": "Not Admin", "login": "not.admin", "role": "specialist"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "not.admin"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    s = TestClient(app)
    s.post("/login", data={"login": "not.admin", "password": pw})
    assert s.get("/api/import/clear").status_code == 403 and s.post("/api/import/clear", json={"confirm": "ОЧИСТИТЬ"}).status_code == 403
    assert TestClient(app).post("/api/import/clear", json={"confirm": "ОЧИСТИТЬ"}).status_code == 401
