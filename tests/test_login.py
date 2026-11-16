"""Sign-in by picking a name from the list."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from test_app import xlsx

ROWS = [[1, "Қарор", "ПҚ-3 \n 01.01.2026", "1-банд\nТекст", "31.12.2026", "2026-12-01", "Karimov Anvar", "Бажарилмаган", "LG0001"],
        [2, "Қарор", "ПҚ-3 \n 01.01.2026", "2-банд\nТекст", "31.12.2026", "2026-12-01", "Nazarova Malika", "Бажарилмаган", "LG0002"]]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c


def users(admin):
    return {u["login"]: u for u in admin.get("/api/users").json()["items"]}


def listed():
    r = TestClient(app).get("/api/login-users")          # no session: the sign-in page is public
    assert r.status_code == 200
    return r.json()


def test_list_hides_people_without_password_and_admins(admin):
    d = listed()
    names = [p["name"] for p in d["items"]]
    assert d["enabled"] and "Karimov Anvar" not in names and "Nazarova Malika" not in names   # imported people cannot sign in yet
    uid = users(admin)["karimov.a"]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    d = listed()
    names = [p["name"] for p in d["items"]]
    assert "Karimov Anvar" in names and "Nazarova Malika" not in names and "Администратор" not in names
    assert all(set(p) == {"id", "name"} for p in d["items"])   # no login, no role, nothing else
    admin.pw = pw


def test_pick_and_sign_in(admin):
    uid = users(admin)["karimov.a"]["id"]
    c = TestClient(app)
    r = c.post("/login", data={"uid": str(uid), "password": admin.pw}, follow_redirects=False)
    assert r.status_code == 303 and c.get("/api/me").json()["login"] == "karimov.a"
    bad = TestClient(app).post("/login", data={"uid": str(uid), "password": "wrong"}, follow_redirects=False)
    assert bad.status_code == 401 and "Неверный пароль" in bad.text and f'data-uid="{uid}"' in bad.text   # the same person stays selected
    # the typed login still works
    assert TestClient(app).post("/login", data={"login": "karimov.a", "password": admin.pw}, follow_redirects=False).status_code == 303


def test_pick_is_refused_for_unlisted_accounts(admin):
    me = admin.get("/api/me").json()
    r = TestClient(app).post("/login", data={"uid": str(me["id"]), "password": "secret123"}, follow_redirects=False)
    assert r.status_code == 401                            # administrators sign in by login only
    nid = users(admin)["nazarova.m"]["id"]                 # no password issued yet
    assert TestClient(app).post("/login", data={"uid": str(nid), "password": "x"}, follow_redirects=False).status_code == 401
    assert TestClient(app).post("/login", data={"uid": "abc", "password": "x"}, follow_redirects=False).status_code == 401
    assert TestClient(app).post("/login", data={"uid": "1; DROP TABLE users", "password": "x"}, follow_redirects=False).status_code == 401


def test_switch_off_hides_list_and_blocks_pick(admin):
    uid = users(admin)["karimov.a"]["id"]
    assert admin.put("/api/settings", json={"login_list": False}).status_code == 200
    assert listed() == {"enabled": False, "items": []}
    assert TestClient(app).post("/login", data={"uid": str(uid), "password": admin.pw}, follow_redirects=False).status_code == 401
    assert TestClient(app).post("/login", data={"login": "karimov.a", "password": admin.pw}, follow_redirects=False).status_code == 303
    admin.put("/api/settings", json={"login_list": True})
    assert "Karimov Anvar" in [p["name"] for p in listed()["items"]]


def test_error_page_does_not_reflect_markup():
    r = TestClient(app).post("/login", data={"login": '"><script>alert(1)</script>', "password": "x"}, follow_redirects=False)
    assert r.status_code == 401 and "<script>alert(1)" not in r.text


def test_only_admin_changes_the_switch(admin):
    uid = users(admin)["karimov.a"]["id"]
    u = TestClient(app)
    u.post("/login", data={"uid": str(uid), "password": admin.pw})
    assert u.put("/api/settings", json={"login_list": False}).status_code == 403


def test_backfill_marks_existing_accounts_that_already_log_in():
    c = sqlite3.connect(":memory:")
    c.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY, role TEXT);
        CREATE TABLE audit(user_id INTEGER, action TEXT, entity_id INTEGER);
        INSERT INTO users VALUES (1,'admin'),(2,'user'),(3,'user'),(4,'user');
        INSERT INTO audit VALUES (2,'login.ok',NULL),(NULL,'user.password',3);""")
    c.execute("ALTER TABLE users ADD COLUMN pw_set INTEGER NOT NULL DEFAULT 0")
    c.execute(db.BACKFILL_PW_SET)
    assert dict(c.execute("SELECT id, pw_set FROM users")) == {1: 1, 2: 1, 3: 1, 4: 0}
