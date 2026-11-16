"""Structure of the department: units, people in units, the matrix unit x kind of document."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_app import xlsx

K = ["Фармон", "Қарор", "Баён", "ВМ", "ПА"]
ROWS = []
# Aliyev: 2 Фармон + 1 ВМ (will sit in division I-1), Valiyev: 1 Қарор + 1 ПА (management II), Gulov: 1 Баён (no unit), one task without an assignee
for i, (kind, who, close) in enumerate([("Фармон", "Aliyev Ali", "2026-11-10"), ("Фармон", "Aliyev Ali", "2026-11-30"), ("ВМ", "Aliyev Ali", "2026-12-20"),
                                        ("Қарор", "Valiyev Vali", "2026-11-12"), ("ПА", "Valiyev Vali", "2026-12-01"), ("Баён", "Gulov Gul", "2026-11-30"), ("Қарор", "", "2026-11-30")]):
    ROWS.append([i + 1, kind, f"ДОК-{i} \n 01.01.2026", f"{i}-банд\nUN{i}", "31.12.2026", close, who, "Бажарилмаган", f"UN000{i}"])


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c


def units(admin):
    return {(u["num"], u["parent_id"]): u for u in admin.get("/api/units").json()["items"]}


def user(admin, login):
    return [u for u in admin.get("/api/users").json()["items"] if u["login"] == login][0]


def test_seed_matches_the_structure_of_the_department(admin):
    items = admin.get("/api/units").json()["items"]
    tops = [u for u in items if not u["parent_id"]]
    assert [u["num"] for u in tops] == ["I", "II", "III", "IV", "V", "VI"]
    assert tops[0]["name"] == "Тиббий хизматлар бошқармаси" and tops[5]["name"] == "Ташхислаш хизмати бўлими"
    kids = lambda t: [u["name"] for u in items if u["parent_id"] == t["id"]]
    assert len(kids(tops[0])) == 4 and len(kids(tops[2])) == 2 and kids(tops[1]) == [] and kids(tops[3]) == []
    assert kids(tops[0])[2] == "Тез тиббий ёрдам бўлими"
    assert [u["id"] for u in items] == sorted(u["id"] for u in items)          # display order: a management, then its divisions


def test_only_admin_manages_units(admin):
    uid = user(admin, "aliyev.a")["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    u.post("/login", data={"login": "aliyev.a", "password": pw})
    assert u.get("/api/units").status_code == 403 and u.post("/api/units", json={"name": "x"}).status_code == 403
    assert u.patch(f"/api/users/{uid}", json={"unit_id": 1}).status_code == 403
    assert "units" in u.get("/api/meta").json()                                    # the list for the filter is open to every signed-in user


def test_assign_people_and_rollup(admin):
    ut = units(admin)
    top1 = [u for u in ut.values() if u["num"] == "I" and not u["parent_id"]][0]
    div11 = [u for u in ut.values() if u["parent_id"] == top1["id"] and u["num"] == "1"][0]
    top2 = [u for u in ut.values() if u["num"] == "II" and not u["parent_id"]][0]
    assert admin.patch(f"/api/users/{user(admin, 'aliyev.a')['id']}", json={"unit_id": div11["id"]}).status_code == 200
    assert admin.patch(f"/api/users/{user(admin, 'valiyev.v')['id']}", json={"unit_id": top2["id"]}).status_code == 200
    assert admin.patch(f"/api/users/{user(admin, 'aliyev.a')['id']}", json={"unit_id": 9999}).status_code == 400
    assert user(admin, "aliyev.a")["unit"].startswith("Туман")
    d = admin.get("/api/dashboard").json()["units"]
    assert d["columns"][:5] == K                                                    # kinds in the requested order
    rows = {r["id"]: r for r in d["rows"]}
    # division I-1: Aliyev's tasks only (UN0000..UN0002): 2 Фармон + 1 ВМ, one overdue (close 2026-11-10 < today 2026-11-16)
    c11 = rows[div11["id"]]["cells"]
    assert c11["Фармон"]["total"] == 2 and c11["ВМ"]["total"] == 1 and c11["Фармон"]["overdue"] == 1 and c11["Қарор"]["total"] == 0
    # the management includes its divisions
    assert rows[top1["id"]]["cells"]["Фармон"]["total"] >= c11["Фармон"]["total"] and rows[top1["id"]]["sum"]["total"] >= rows[div11["id"]]["sum"]["total"]
    c2 = rows[top2["id"]]["cells"]
    assert c2["Қарор"]["total"] == 1 and c2["ПА"]["total"] == 1 and c2["Қарор"]["overdue"] == 1
    # the total row adds up to every task, including people without a department and unassigned tasks
    tot = admin.get("/api/dashboard").json()
    assert d["total"]["sum"]["total"] == tot["totals"]["total"]
    assert d["none"] and d["none"]["cells"]["Баён"]["total"] >= 1 and d["none"]["cells"]["Қарор"]["total"] >= 1


def test_filter_tasks_by_unit(admin):
    ut = units(admin)
    top1 = [u for u in ut.values() if u["num"] == "I" and not u["parent_id"]][0]
    div11 = [u for u in ut.values() if u["parent_id"] == top1["id"] and u["num"] == "1"][0]
    q = lambda s: {t["code"] for t in admin.get("/api/tasks?size=200&" + s).json()["items"]}
    assert {"UN0000", "UN0001", "UN0002"} <= q(f"unit={div11['id']}")
    assert {"UN0000", "UN0001", "UN0002"} <= q(f"unit={top1['id']}")               # the management includes the division
    assert q(f"unit={div11['id']}&kind=ВМ") & {"UN0000", "UN0001", "UN0002"} == {"UN0002"}
    none = q("unit=0")
    assert {"UN0005", "UN0006"} <= none and not none & {"UN0000", "UN0003"}       # Gulov and the unassigned task have no department
    t = admin.get(f"/api/tasks?q=UN0000").json()["items"][0]
    assert t["unit"].startswith("Туман")


def test_edit_structure(admin):
    r = admin.post("/api/units", json={"name": "Новое управление"})
    assert r.status_code == 200
    nid = r.json()["id"]
    new = [u for u in admin.get("/api/units").json()["items"] if u["id"] == nid][0]
    assert new["num"] == "VII" and not new["parent_id"]
    d = admin.post("/api/units", json={"name": "Новый отдел", "parent_id": nid}).json()["id"]
    assert [u for u in admin.get("/api/units").json()["items"] if u["id"] == d][0]["num"] == "1"
    items = admin.get("/api/units").json()["items"]
    ids = [u["id"] for u in items]
    assert ids.index(d) == ids.index(nid) + 1                                      # a division stands right after its management
    assert admin.post("/api/units", json={"name": "Отдел в отделе", "parent_id": d}).status_code == 400
    assert admin.post("/api/units", json={"name": "  "}).status_code == 400
    assert admin.patch(f"/api/units/{nid}", json={"name": "Переименовано"}).status_code == 200
    # people block hiding and deleting
    uid = user(admin, "gulov.g")["id"]
    admin.patch(f"/api/users/{uid}", json={"unit_id": d})
    assert admin.patch(f"/api/units/{nid}", json={"active": False}).status_code == 400            # somebody works in a division of it
    assert admin.delete(f"/api/units/{d}").status_code == 400
    admin.patch(f"/api/users/{uid}", json={"unit_id": None})
    assert user(admin, "gulov.g")["unit_id"] is None
    assert admin.delete(f"/api/units/{d}").status_code == 200 and admin.delete(f"/api/units/{nid}").status_code == 200
    assert admin.delete("/api/units/99999").status_code == 404


def test_hidden_unit_leaves_pickers_but_keeps_history(admin):
    r = admin.post("/api/units", json={"name": "Временное управление"}).json()["id"]
    admin.patch(f"/api/units/{r}", json={"active": False})
    assert r not in [u["id"] for u in admin.get("/api/meta").json()["units"]]
    assert admin.patch(f"/api/users/{user(admin, 'gulov.g')['id']}", json={"unit_id": r}).status_code == 400   # cannot assign to a hidden unit
    assert admin.delete(f"/api/units/{r}").status_code == 200


# ---------------------------------------------------------------- people x deadlines, split by the day of the month

MROWS = [[i + 1, "Қарор", f"МД-{i} \n 01.01.2026", f"{i}-банд\nM{i}", "31.12.2026", d, "Monthly Mona", st, f"MN000{i}"]
         for i, (d, st) in enumerate([("2026-11-05", "Бажарилмаган"), ("2026-11-10", "Бажарилган"), ("2026-11-12", "Бажарилмаган"), ("2026-11-15", "Бажарилмаган"),
                                      ("2026-11-18", "Бажарилмаган"), ("2026-11-25", "Бажарилмаган"), ("2026-11-30", "Бажарилмаган"), ("2026-12-03", "Бажарилмаган"), (None, "Бажарилмаган")])]


def test_month_split_of_a_person(admin):
    assert admin.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(MROWS))}).status_code == 200
    d = admin.get("/api/dashboard").json()
    assert "2026-11" in d["months"] and "2026-12" in d["months"] and d["months"] == sorted(d["months"])
    mona = [p for p in d["people"] if p["name"] == "Monthly Mona"][0]
    nov, dec = mona["months"]["2026-11"], mona["months"]["2026-12"]
    assert (nov["d10"], nov["d15"], nov["d20"], nov["d31"]) == (2, 2, 1, 2)       # 5th and 10th | 12th and 15th | 18th | 25th and 30th
    assert nov["total"] == 7 and nov["done"] == 1                                  # the 10th is done
    assert dec["d10"] == 1 and dec["d31"] == 1 and dec["total"] == 2              # the 3rd, and the task without a closing date: the administrator's fallback is the official term, 31 Dec
    assert mona["total"] == 9 and nov["total"] + dec["total"] == 9
    # the list opened from a cell has exactly the same tasks
    n = admin.get(f"/api/tasks?assignee={mona['id']}&date_from=2026-11-11&date_to=2026-11-15").json()["total"]
    assert n == nov["d15"]
    assert admin.get(f"/api/tasks?assignee={mona['id']}&date_from=2026-11-01&date_to=2026-11-30&status=done").json()["total"] == nov["done"]
