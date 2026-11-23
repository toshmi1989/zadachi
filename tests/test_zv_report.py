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
        mg1 = c.post("/api/units", json={"name": "Управление отчёта один", "num": "RX"}).json()["id"]
        dv = c.post("/api/units", json={"name": "Отдел отчёта", "parent_id": mg1, "num": "1"}).json()["id"]
        mg2 = c.post("/api/units", json={"name": "Управление отчёта два", "num": "RY"}).json()["id"]
        users = {u["login"]: u["id"] for u in c.get("/api/users").json()["items"]}
        c.patch(f"/api/users/{users['repaliyev.a']}", json={"unit_id": dv})
        c.patch(f"/api/users/{users['repvaliyev.v']}", json={"unit_id": mg2})
        yield c
        d = connect()
        d.execute("DELETE FROM tasks WHERE code LIKE 'RP%'")
        d.execute("DELETE FROM users WHERE name LIKE 'Rep%'")
        d.execute("DELETE FROM units WHERE name LIKE '%отчёта%'")
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
    d = admin.get("/api/dashboard").json()["total"]["months"]["2026-12"]
    tot = ln["Департамент бўйича жами:"]
    assert tot[2] == d["done"] + d["open"] and tot[3] == (d["done"] or None) and tot[5] == (d["open"] or None)      # the total line is the dashboard's December
    mg1, dv, mg2 = ln["Управление отчёта один"], ln["Отдел отчёта"], ln["Управление отчёта два"]
    # Aliyev (division of the first management): Фармон done, Қарор open, ВМ open
    assert dv[2:7] == [3, 1, 33, 2, None]
    assert mg1[2] == 3 and mg1[3] == 1                                                      # the management includes its division
    assert dv[7:10] == [2, 1, 1] and dv[10:13] == [None, None, None] and dv[13:16] == [1, None, 1]    # Фармон+Қарор+Баён | ПА | ВМ: total, done, left
    # Valiyev (the second management): ПА done + ПА open in December (the January one is not in this month)
    assert mg2[2:6] == [2, 1, 50, 1] and mg2[10:13] == [2, 1, 1] and mg2[7:10] == [None, None, None]
    assert ln["Бўлинма кўрсатилмаган (Без отдела)"][2] >= 1


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


def task_rows(ws):
    """The lines of a sheet of tasks: those that have a code in the second column (the group lines are merged and have none)."""
    return [r for r in range(4, ws.max_row + 1) if ws.cell(r, 2).value]


def test_the_file_has_the_tasks_behind_the_numbers_in_groups(admin):
    r = admin.get("/api/report.xlsx?month=2026-12")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["ТАҲЛИЛИ", "Задачи по отделам", "Задачи по этапам", "Все задачи"]
    total = wb["ТАҲЛИЛИ"].cell(8, 3).value                                               # «Департамент бўйича жами»: the tasks of the summary
    for name in wb.sheetnames[1:]:
        assert len(task_rows(wb[name])) == total, name                                 # every sheet has exactly the tasks of the summary
    flat = wb["Все задачи"]
    head = [c.value for c in flat[3]]
    assert head[:3] == ["№", "Код", "Вид"] and "Этап согласования" in head and "Отдел" in head and "Официальный срок" in head
    assert flat.auto_filter.ref and flat.auto_filter.ref.startswith("A3:")                  # filters on the flat list
    codes = {flat.cell(r, 2).value for r in task_rows(flat)}
    assert {"RP0000", "RP0001", "RP0002", "RP0003", "RP0004", "RP0006"} <= codes and "RP0005" not in codes     # December only: RP0005 is of January
    # by departments: the management line with its numbers, then its division
    ws = wb["Задачи по отделам"]
    heads = [str(ws.cell(r, 1).value) for r in range(4, ws.max_row + 1) if not ws.cell(r, 2).value and ws.cell(r, 1).value]
    assert any(h.startswith("RX") or "Управление отчёта один" in h for h in heads) and any("Отдел отчёта" in h for h in heads) and all("задач:" in h for h in heads)
    mg = next(r for r in range(4, ws.max_row + 1) if "Управление отчёта один" in str(ws.cell(r, 1).value))
    assert "задач: 3" in str(ws.cell(mg, 1).value) and ws.row_dimensions[mg + 2].outlineLevel == 2     # the tasks of a division are one level in (they can be folded)
    # by stages
    st = wb["Задачи по этапам"]
    stage_heads = [str(st.cell(r, 1).value) for r in range(4, st.max_row + 1) if not st.cell(r, 2).value and st.cell(r, 1).value and " — " in str(st.cell(r, 1).value)]
    assert any(h.startswith("Выполнено —") for h in stage_heads) and any(h.startswith("Не проверялись —") or h.startswith("Ответ не введён —") for h in stage_heads)


def test_the_specialist_file_has_no_official_term(admin):
    admin.post("/api/users", json={"name": "Rep Special", "login": "rep.special", "role": "specialist"})
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "rep.special"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    s = TestClient(app)
    s.post("/login", data={"login": "rep.special", "password": pw})
    r = s.get("/api/report.xlsx?month=")
    assert r.status_code == 200
    flat = openpyxl.load_workbook(io.BytesIO(r.content))["Все задачи"]
    head = [c.value for c in flat[3]]
    assert "Официальный срок" not in head and "Срок исполнения (дата закрытия)" in head
    d = connect(); d.execute("DELETE FROM users WHERE login='rep.special'"); d.commit(); d.close()
