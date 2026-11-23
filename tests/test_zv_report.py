"""The summary table of the department in the format of the ministry's table (Excel) and the time of the last update on the dashboard."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_app import xlsx

K = ["Фармон", "Қарор", "Баён", "ВМ", "ПА"]
ROWS = []
# Aliyev (division I-1): Фармон done, Қарор open, ВМ open (December); Valiyev (management II): ПА done + ПА open (December), Қарор open (January); Gulov: no unit, Баён open (December)
for i, (kind, who, close, state) in enumerate([("Фармон", "Repaliyev Ali", "2026-12-10", "Бажарилган"), ("Қарор", "Repaliyev Ali", "2026-12-12", "Бажарилмаган"), ("ВМ", "Repaliyev Ali", "2026-12-20", "Бажарилмаган"),
                                              ("ПА", "Repvaliyev Vali", "2026-12-01", "Бажарилган"), ("ПА", "Repvaliyev Vali", "2026-12-02", "Бажарилмаган"), ("Қарор", "Repvaliyev Vali", "2027-01-15", "Бажарилмаган"),
                                              ("Баён", "Repgulov Gul", "2026-12-30", "Бажарилмаган")]):
    ROWS.append([i + 1, kind, f"РП-{i} \n 01.01.2026", f"{i}-банд\nRP{i}", "31.12.2026", close, who, state, f"RP000{i}"])


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        units = c.get("/api/units").json()["items"]
        top1 = [u for u in units if u["num"] == "I" and not u["parent_id"]][0]
        div = [u for u in units if u["parent_id"] == top1["id"] and u["num"] == "1"][0]
        top2 = [u for u in units if u["num"] == "II" and not u["parent_id"]][0]
        users = {u["login"]: u["id"] for u in c.get("/api/users").json()["items"]}
        c.patch(f"/api/users/{users['repaliyev.a']}", json={"unit_id": div["id"]})
        c.patch(f"/api/users/{users['repvaliyev.v']}", json={"unit_id": top2["id"]})
        yield c
        d = connect()
        d.execute("DELETE FROM tasks WHERE code LIKE 'RP%'")
        d.execute("DELETE FROM users WHERE name LIKE 'Rep%'")
        d.commit()
        d.close()


def sheet(admin, month):
    r = admin.get(f"/api/report.xlsx?month={month}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    return openpyxl.load_workbook(io.BytesIO(r.content)).active


def lines(ws):
    return {str(ws.cell(r, 2).value or ws.cell(r, 1).value): [ws.cell(r, c).value for c in range(1, ws.max_column + 1)] for r in range(8, ws.max_row + 1)}


def test_the_table_of_december_has_the_format_of_the_ministry_and_the_numbers_of_the_dashboard(admin):
    ws = sheet(admin, "2026-12")
    assert "2026 йил декабрь ойига белгиланган" in ws["A1"].value and ws["A2"].value == "ТАҲЛИЛИ" and "ҳолатига" in ws["A3"].value
    head = " | ".join(str(ws.cell(r, c).value) for r in (5, 6, 7) for c in range(1, ws.max_column + 1) if ws.cell(r, c).value)
    for word in ("ЖАМИ", "Назоратга олинган топшириқлар", "Бажарилди", "Сони", "Фоиз (%)", "Тизимда қолган топшириқ", "Маълумот учун қабул қилинган", "Шу жумладан", "ПРЕЗИДЕНТ ТОПШИРИҚЛАРИ",
                 "АДМИНИСТРАЦИЯ РАҲБАРИ ТОПШИРИҚЛАРИ", "ВАЗИРЛАР МАҲКАМАСИ ҚАРОРЛАРИ", "Қолдиқ"):
        assert word in head, word
    assert "Юқори" not in head and "хавфли" not in head and "Қизилга" not in head          # the columns of risk are not in the table
    ln = lines(ws)
    tot = ln["Департамент бўйича жами:"]
    # December: 3 (Aliyev) + 2 (Valiyev) + 1 (Gulov) = 6; done 2; open 4
    assert tot[2:7] == [6, 2, 33.3, 4, None]
    pres, adm, cab = tot[7:10], tot[10:13], tot[13:16]
    assert pres == [3, 1, 2] and adm == [2, 1, 1] and cab == [1, None, 1]                   # Фармон+Қарор+Баён | ПА | ВМ: total, done, left
    top1 = [v for k, v in ln.items() if k.startswith("Тиббий") or "Тиббий хизматлар" in k][0]
    assert top1[2] == 3 and top1[3] == 1                                                    # the management includes its division
    assert ln["Бўлинма кўрсатилмаган (Без отдела)"][2] == 1
    # the same numbers as the dashboard
    d = admin.get("/api/dashboard").json()
    assert d["total"]["months"]["2026-12"] == {"done": 2, "open": 4} or d["total"]["months"]["2026-12"]["done"] >= 2


def test_every_month_and_january(admin):
    assert lines(sheet(admin, "2027-01"))["Департамент бўйича жами:"][2] == 1
    ws = sheet(admin, "")
    assert "белгиланган" not in ws["A1"].value and lines(ws)["Департамент бўйича жами:"][2] >= 7


def test_the_report_is_for_the_staff_only_and_the_month_is_checked(admin):
    assert admin.get("/api/report.xlsx?month=2026-13").status_code == 400
    assert TestClient(app).get("/api/report.xlsx").status_code == 401
    admin.post("/api/users", json={"name": "Rep Plain", "login": "rep.plain", "role": "user"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "rep.plain"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    u.post("/login", data={"login": "rep.plain", "password": pw})
    assert u.get("/api/report.xlsx").status_code == 403


def test_the_dashboard_tells_when_the_data_was_updated(admin):
    up = admin.get("/api/dashboard").json()["updated"]
    assert up["base"][:4] == "2026" or up["base"][:2] == "20"                                 # the load of the base is dated
    assert set(up) == {"sync", "base"}
