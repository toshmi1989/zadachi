"""«Слить с…»: a unit is merged into another one: its people (and their tasks), the names of the site, and the unit itself goes."""
import os

import pytest
from fastapi.testclient import TestClient

from app import backup, db, site_import
from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"МЖ-{i} \n 01.01.2026", f"{i}-банд\nМерж {i}", "31.12.2026", "2026-12-10", "Merge Person", "Бажарилмаган", f"MG000{i}"] for i in range(3)]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c


def test_a_unit_is_merged_into_another_with_its_people_tasks_and_site_name(admin):
    mgmt = admin.post("/api/units", json={"name": "Управление для слияния", "num": "MX"}).json()["id"]
    kid = admin.post("/api/units", json={"name": "Отдел-приёмник", "parent_id": mgmt, "num": "2"}).json()["id"]
    top = admin.post("/api/units", json={"name": "Даволаш тест департаменти", "num": "MY"}).json()["id"]
    pid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "merge.p"][0]["id"]
    assert admin.patch(f"/api/users/{pid}", json={"unit_id": top}).status_code == 200
    admin.put("/api/import/aliases", json={"aliases": {site_import.skeleton("Даволаш тест департаменти"): top}})
    assert admin.patch(f"/api/units/{kid}", json={"active": False}).status_code == 200                  # the target may be hidden: it comes back
    rows = {r["id"]: r for r in admin.get("/api/dashboard").json()["rows"]}
    assert rows[top]["sum"]["open"] == 3
    # refusals
    assert admin.post(f"/api/units/{top}/merge", json={"into": top}).status_code == 400
    assert admin.post(f"/api/units/{top}/merge", json={}).status_code == 400
    assert admin.post(f"/api/units/{mgmt}/merge", json={"into": top}).status_code == 400                # a management with divisions is not merged
    assert admin.post(f"/api/units/{top}/merge", json={"into": 987654}).status_code == 404
    assert admin.post(f"/api/units/{mgmt}/merge", json={"into": kid}).status_code == 400
    before = set(os.listdir(backup.DIR)) if os.path.isdir(backup.DIR) else set()
    r = admin.post(f"/api/units/{top}/merge", json={"into": kid})
    assert r.status_code == 200 and r.json()["people"] == 1 and r.json()["tasks"] == 3 and r.json()["backup"] in set(os.listdir(backup.DIR)) - before
    ids = {u["id"]: u for u in admin.get("/api/units").json()["items"]}
    assert top not in ids and ids[kid]["active"] and ids[mgmt]["active"] and ids[kid]["people"] == 1
    assert [u for u in admin.get("/api/users").json()["items"] if u["login"] == "merge.p"][0]["unit"].startswith("Отдел-приёмник")
    rows = {r["id"]: r for r in admin.get("/api/dashboard").json()["rows"]}
    assert rows[kid]["sum"]["open"] == 3 and rows[mgmt]["sum"]["open"] == 3                            # the tasks are in the division and in its management
    c = db.connect()
    key = site_import.skeleton("Даволаш тест департаменти")
    assert c.execute("SELECT unit_id FROM unit_aliases WHERE alias_key=?", (key,)).fetchone()[0] == kid  # the next export with this name goes to the unit it was merged into
    assert c.execute("SELECT COUNT(*) FROM audit WHERE action='unit.merge'").fetchone()[0] == 1
    c.close()
    assert admin.post(f"/api/units/{top}/merge", json={"into": kid}).status_code == 404                # it is gone


def test_only_the_administrator_merges(admin):
    a = admin.post("/api/units", json={"name": "Один", "num": "MZ"}).json()["id"]
    b = admin.post("/api/units", json={"name": "Два", "num": "MW"}).json()["id"]
    assert TestClient(app).post(f"/api/units/{a}/merge", json={"into": b}).status_code == 401
