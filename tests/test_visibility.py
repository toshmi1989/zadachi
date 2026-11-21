"""The official term ("Топшириқ муддати") is for administrators only: everybody else sees the closing date."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import db, reminders
from app.main import app
from test_app import xlsx

ROWS = [  # today is 2026-11-16
    [1, "Қарор", "ПҚ-5 \n 01.01.2026", "1-банд\nЗакрытие завтра", "31.12.2026", "2026-11-17", "Visible Vera", "Бажарилмаган", "VS0001"],
    [2, "Қарор", "ПҚ-5 \n 01.01.2026", "2-банд\nДаты закрытия нет", "2026-11-17", None, "Visible Vera", "Бажарилмаган", "VS0002"],
    [3, "Қарор", "ПҚ-5 \n 01.01.2026", "3-банд\nПросрочено по закрытию", "31.12.2026", "2026-11-10", "Visible Vera", "Бажарилмаган", "VS0003"],
]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c


@pytest.fixture(scope="module")
def vera(admin):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "visible.v"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    c = TestClient(app)
    c.post("/login", data={"login": "visible.v", "password": pw})
    c.uid = uid
    return c


def items(client, qs=""):
    return {t["code"]: t for t in client.get("/api/tasks?size=200&q=VS000" + qs).json()["items"]}


def test_admin_still_sees_both_dates(admin):
    t = items(admin)
    assert t["VS0001"]["due"] == "2026-12-31" and t["VS0001"]["close_date"] == "2026-11-17"
    assert t["VS0002"]["eff"] == "2026-11-17"           # the administrator's fallback: no closing date, so the official term


def test_user_gets_no_official_term_anywhere_in_tasks(vera):
    t = items(vera)
    assert set(t) == {"VS0001", "VS0002", "VS0003"}
    assert all(x["due"] is None for x in t.values())
    assert t["VS0001"]["eff"] == "2026-11-17" and t["VS0001"]["days"] == 1
    assert t["VS0002"]["eff"] is None and t["VS0002"]["bucket"] == "nodate"       # no fallback to the official term
    assert t["VS0003"]["bucket"] == "overdue"
    one = vera.get(f"/api/tasks/{t['VS0001']['id']}").json()
    assert one["due"] is None and "2026-12-31" not in str(one)
    assert "2026-12-31" not in vera.get("/api/tasks?size=200&q=VS000").text


def test_user_cannot_ask_for_the_official_term(vera, admin):
    assert items(vera, "&by=due") == items(vera)                                  # the parameter is ignored
    r = vera.get("/api/tasks?size=200&q=VS000&sort=due&dir=desc").json()
    assert r["by"] == "strict" and all(t["due"] is None for t in r["items"])
    tid = items(vera)["VS0001"]["id"]
    assert vera.get(f"/api/tasks/{tid}?by=due").json()["due"] is None
    assert items(admin, "&by=due")["VS0001"]["eff"] == "2026-12-31"               # the administrator can


def test_user_dashboard_is_built_on_the_closing_date_only(admin, vera):
    a, u = admin.get("/api/dashboard?by=due").json(), vera.get("/api/dashboard?by=due").json()
    assert u["by"] == "strict" and a["by"] == "due"
    s = vera.get("/api/dashboard?by=close").json()
    assert s["rows"] == u["rows"] and s["total"] == u["total"] and s["months"] == u["months"]       # the same numbers whatever the parameter says
    assert u["total"]["nodate"]["open"] >= 1                                       # a task with only an official term has no month for a user (the term is not shown to them)
    assert a["by"] == "due" and "2026-12" in a["months"]                           # the administrator can place it by the official term


def test_export_has_no_official_term_column_for_a_user(vera, admin):
    def head(c):
        r = c.get("/api/tasks.xlsx?q=VS000")
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        return [x.value for x in ws[1]], [[x.value for x in row] for row in ws.iter_rows(min_row=2)]
    uh, urows = head(vera)
    ah, arows = head(admin)
    assert "Срок (официальный)" not in uh and "Срок (официальный)" in ah
    assert "2026-12-31" not in str(urows) and "2026-12-31" in str(arows)


def test_reminders_to_a_user_use_the_closing_date_only(vera, admin):
    c = db.connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (vera.uid,)).fetchone()
        g = reminders.global_cfg(c)
        g["by"] = "due"                                                            # even if the administrator's reminder basis is the official term
        dg = reminders.build_digest(c, u, g, reminders.user_cfg(u, g), db.today(), overdue_due=True, everything=True)
        codes = {t["code"] for t in dg["overdue"]} | {t["code"] for ts in dg["groups"].values() for t in ts}
        assert codes == {"VS0001", "VS0003"}                                        # VS0002 has no closing date: it is not announced
        text = reminders.render(u, dg, g, db.today())
        assert "VS0002" not in text and "31.12" not in text
    finally:
        c.close()
