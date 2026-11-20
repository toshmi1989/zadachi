import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app

HEAD = ["№", "Ҳужжат тури", "Ҳужжат рақами ва санаси", "Топшириқ мазмуни", "Топшириқ муддати", "Ёпиш муддати", "Масъул ҳодим", "Топшириқ ижроси", "Топшириқ коди"]


def xlsx(rows, title="ТОПШИРИҚЛАР КЕСИМИДА"):
    wb = openpyxl.Workbook()
    wb.active.title = "Лист1"
    ws = wb.create_sheet(title)
    ws.append(["2026 йил топшириқлари"])
    ws.append([])
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


ROWS = [
    [1, "Қарор", "ПҚ-20 \n 20.01.2026", "1-банд\nМатн один", "25.12.2026", "2026-11-10", "Ivanov Ivan Ivanovich", "Бажарилмаган", "AAA0001"],      # overdue
    [2, "Фармон", "ПФ-21 \n 16.02.2026", "2-банд\nМатн два", "25.12.2026", "2026-11-20", "Ivanov Ivan Ivanovich", "Бажарилмаган\nЯкунлаш", "AAA0002"],  # week
    [3, "ВМ", "ВМҚ-9 \n 12.06.2026", "Матн уч", "25.12.2026", "30.112026", "Petrov Pyotr", "Бажарилган", "AAA0003"],                                 # typo date, done
    [4, "Қарор", "ПҚ-20 \n 20.01.2026", "4-банд\nМатн тўрт", "31.12.2026", "16.17.2026", "Petrov Pyotr", "Маълумот учун қабул қилинган", "AAA0004"],  # bad date, info
    [5, "Қарор", "ПҚ-20 \n 20.01.2026", "5-банд\nМатн беш", "31.12.2026", None, "", "Бажарилмаган", "AAA0005"],                                       # unassigned
]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        r = c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert r.status_code == 303
        yield c


def upload(c, data, dry):
    return c.post(f"/api/import?dry={dry}", files={"file": ("x.xlsx", data)})


def test_import_dry_run_writes_nothing(admin):
    r = upload(admin, xlsx(ROWS), 1)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["created"] == 5 and s["dry"] and len(s["new_people"]) == 2
    assert admin.get("/api/dashboard").json()["totals"]["total"] == 0


def test_import_parses_and_reports(admin):
    s = upload(admin, xlsx(ROWS), 0).json()
    assert s["created"] == 5 and not s["dry"]
    assert any("16.17.2026" in w for w in s["warnings"]), s["warnings"]          # an impossible date is reported, not guessed
    t = {x["code"]: x for x in admin.get("/api/tasks?size=100").json()["items"]}
    assert t["AAA0003"]["close_date"] == "2026-11-30"                           # the typo 30.112026 is understood
    assert t["AAA0004"]["close_date"] is None and t["AAA0004"]["status"] == "info"
    assert t["AAA0002"]["status"] == "todo" and t["AAA0002"]["tag"] == "Якунлаш"
    assert t["AAA0001"]["point"] == "1-банд" and t["AAA0001"]["text"] == "Матн один"
    assert t["AAA0001"]["doc_no"] == "ПҚ-20" and t["AAA0001"]["doc_date"] == "2026-01-20"
    assert t["AAA0005"]["assignee_id"] is None


def test_buckets_and_dashboard(admin):
    d = admin.get("/api/dashboard?by=close").json()
    T = d["totals"]
    assert (T["overdue"], T["week"], T["done"], T["info"], T["total"]) == (1, 1, 1, 1, 5)
    assert T["later"] == 1  # the unassigned task has no closing date, so its official term 31.12 is used
    assert sum(p["total"] for p in d["people"]) == 5
    d2 = admin.get("/api/dashboard?by=due").json()["totals"]
    assert d2["overdue"] == 0 and d2["later"] == 3  # by the official term nothing is overdue yet


def test_month_cards_match_the_lists(admin):
    """The cards of the dashboard can be switched to one month: the numbers of a month are exactly what the list shows for that month."""
    import calendar
    d = admin.get("/api/dashboard?by=close").json()
    mk = d["month_kpi"]
    assert mk and set(mk) == set(d["months"])
    for ym, m in mk.items():
        assert m["total"] == m["overdue"] + m["week"] + m["month"] + m["later"] + m["done"] + m["info"] and m["nodate"] == 0     # a task with a date is in exactly one group
        assert m["open"] == m["total"] - m["done"] - m["info"]
        last = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
        rng = f"date_from={ym}-01&date_to={ym}-{last:02d}&by=close"
        n = lambda extra="": admin.get(f"/api/tasks?{rng}{extra}").json()["total"]
        assert n() == m["total"] and n("&status=open") == m["open"] and n("&status=done") == m["done"]
        assert n("&bucket=overdue") == m["overdue"] and n("&bucket=week") == m["week"]
    assert sum(m["total"] for m in mk.values()) <= d["totals"]["total"]       # the tasks without a date are in no month


def test_filters(admin):
    n = lambda q: admin.get("/api/tasks?" + q).json()["total"]
    assert n("bucket=overdue") == 1 and n("bucket=week") == 1 and n("status=done") == 1
    assert n("assignee=0") == 1 and n("doc=ПҚ-20") == 3 and n("kind=ВМ") == 1 and n("q=Матн%20уч") == 1
    assert n("date_from=2026-11-16&date_to=2026-11-22&status=open") == 1
    assert admin.get("/api/tasks?bucket=bogus").status_code == 400


def test_reimport_is_idempotent_and_keeps_manual_edits(admin):
    t = {x["code"]: x for x in admin.get("/api/tasks?size=100").json()["items"]}
    ivanov = t["AAA0001"]["assignee_id"]
    petrov = t["AAA0003"]["assignee_id"]
    r = admin.patch(f"/api/tasks/{t['AAA0001']['id']}", json={"assignee_id": petrov, "status": "progress", "close_date": "2026-12-01"})
    assert r.status_code == 200 and r.json()["changed"]
    s = upload(admin, xlsx(ROWS), 0).json()
    assert s["created"] == 0 and s["unchanged"] == 5 - 0 and s["kept_manual"] == 1
    after = admin.get(f"/api/tasks/{t['AAA0001']['id']}").json()
    assert after["assignee_id"] == petrov != ivanov and after["status"] == "progress" and after["close_date"] == "2026-12-01"
    assert [e["field"] for e in after["events"]][:1] and len(after["events"]) == 3
    # the next export changes the text: the task is updated, the manual fields stay
    rows = [list(r) for r in ROWS]
    rows[0][3] = "1-банд\nЯнги матн"
    s = upload(admin, xlsx(rows), 0).json()
    assert s["updated"] == 1
    again = admin.get(f"/api/tasks/{t['AAA0001']['id']}").json()
    assert again["text"] == "Янги матн" and again["status"] == "progress"


def test_edit_validation_and_done_at(admin):
    tid = admin.get("/api/tasks?q=AAA0002").json()["items"][0]["id"]
    assert admin.patch(f"/api/tasks/{tid}", json={"status": "nope"}).status_code == 400
    assert admin.patch(f"/api/tasks/{tid}", json={"close_date": "31.12.2026"}).status_code == 400
    assert admin.patch(f"/api/tasks/{tid}", json={"close_date": "2026-02-30"}).status_code == 400
    assert admin.patch(f"/api/tasks/{tid}", json={"assignee_id": 9999}).status_code == 400
    r = admin.patch(f"/api/tasks/{tid}", json={"status": "done"}).json()
    assert r["done_at"] and admin.patch(f"/api/tasks/{tid}", json={"status": "done"}).json()["changed"] is False
    assert admin.patch(f"/api/tasks/{tid}", json={"status": "todo"}).json()["done_at"] is None


def test_history_is_append_only():
    import sqlite3
    from app import db
    c = sqlite3.connect(db.DB_PATH)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE task_events SET new='x'")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM audit")
    c.close()


def user_client(login, password):
    c = TestClient(app)
    c.__enter__()
    assert c.post("/login", data={"login": login, "password": password}, follow_redirects=False).status_code == 303
    return c


def test_users_roles_and_permissions(admin):
    # Excel people were created by the import (login ivanov.i, no usable password); the admin issues a password
    users = {u["login"]: u for u in admin.get("/api/users").json()["items"]}
    assert users["ivanov.i"]["tasks"] == 1 and users["petrov.p"]["role"] == "user"
    pw = admin.post(f"/api/users/{users['ivanov.i']['id']}/password", json={}).json()["password"]
    assert pw and len(pw) == 10
    assert admin.post("/api/users", json={"login": "ivanov.i", "name": "X"}).status_code == 400   # duplicate login
    r = admin.post("/api/users", json={"login": "new.one", "name": "New One", "role": "user", "password": "longenough1"})
    assert r.status_code == 200 and r.json()["password"] is None
    assert admin.post("/api/users", json={"login": "bad login", "name": "X"}).status_code == 400
    # an employee created by the import has no password: nobody can log in as them
    c = TestClient(app)
    assert c.post("/login", data={"login": "petrov.p", "password": ""}, follow_redirects=False).status_code in (401, 422)
    u = user_client("ivanov.i", pw)
    assert u.get("/api/dashboard").status_code == 200
    assert u.get("/api/tasks").status_code == 200                                 # default: only their own tasks
    tid = u.get("/api/tasks?q=AAA0002").json()["items"][0]["id"]
    assert u.patch(f"/api/tasks/{tid}", json={"assignee_id": 1}).status_code == 403   # the status of their own task is theirs to change, nothing else
    assert u.post("/api/tasks/bulk", json={"ids": [tid], "status": "done"}).status_code == 403
    for path in ("/api/users", "/api/settings", "/api/import/history", "/api/audit"):
        assert u.get(path).status_code == 403, path
    assert u.post("/api/import?dry=1", files={"file": ("x.xlsx", b"x")}).status_code == 403
    own = u.get("/api/tasks").json()
    assert own["total"] >= 1 and all(t["assignee_id"] == own["items"][0]["assignee_id"] for t in own["items"])
    assert u.get(f"/api/tasks/{admin.get('/api/tasks?assignee=0').json()['items'][0]['id']}").status_code == 404
    admin.put("/api/settings", json={"users_tasks": "none"})
    assert u.get("/api/tasks").status_code == 403 and u.get("/api/dashboard").status_code == 200
    admin.put("/api/settings", json={"users_tasks": "all"})
    # unauthenticated
    assert TestClient(app).get("/api/dashboard").status_code == 401


def test_admin_cannot_lock_everyone_out(admin):
    me = admin.get("/api/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"active": False}).status_code == 400
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "user"}).status_code == 400


def test_password_change_and_reset(admin):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "ivanov.i"][0]["id"]
    new = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    assert len(new) == 10
    u = user_client("ivanov.i", new)
    assert u.post("/api/me/password", json={"old": "wrong", "new": "longenough1"}).status_code == 400
    assert u.post("/api/me/password", json={"old": new, "new": "short"}).status_code == 400
    assert u.post("/api/me/password", json={"old": new, "new": "longenough1"}).status_code == 200


def test_bad_uploads(admin):
    assert upload(admin, b"not excel", 1).status_code == 400
    wb = openpyxl.Workbook()
    b = io.BytesIO()
    wb.save(b)
    r = upload(admin, b.getvalue(), 1)
    assert r.status_code == 400 and "колонки" in r.json()["error"]


def test_export_and_cross_site(admin):
    r = admin.get("/api/tasks.xlsx?status=open")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert admin.post("/api/backup", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert admin.post("/api/backup", json={}).status_code == 200
