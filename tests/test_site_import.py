"""The raw export of edo.ijro.uz: our departments only, a window of terms, status, texts, and what a re-import must never touch."""
import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import site_import
from app.main import app

HEAD = ["№", "Ҳужжат тури", "Ҳужжат рақами ва санаси", "Топшириқ мазмуни", "Механизм", "Топшириқ муддати", "Ижро учун масъул вазирлик, идора, ташкилот ва муассасалар", "Масъул ижрочи",
        "Масъул ҳодим", "Бўлим номи", "Топшириқ ижроси тўғрисида таҳлилий маълумотлар (Ижрочи)", "Топшириқ ижроси тўғрисида таҳлилий маълумотлар (Ижрочи) ҳолати", "Раесат тури",
        "Бирламчи ҳужжат мавжудлиги", "Топшириқ коди", "Муддат узайтириш сони", "Муддат узайтириш санаси", "Кечиккан кунлар", "Топшириқ ҳолати", "Қуйи ташкилот", "Топшириқ тури"]
PRIMARY = "Birlamchi tibbiy-sanitariya yordamini tashkillashtirish boshqarmasi boshqarmasi"   # ours (Cyrillic in our structure), with the doubled word the site has
AMBULANCE = "Tez tibbiy yordam boʻlimi"
FOREIGN = "Investitsion siyosat departamenti"


def row(code, dept, who, due, kind="Президент администрацияси раҳбари резолюцияси", text="1-банд-банд\nИш режаси тайёрлансин\n\n\nМеханизм: -", state="Бажарилмоқда", role="Асосий"):
    return ["1", kind, "02-PA 1/1-3112 \n 25.09.2025", text, "-", due, "Соғлиқни сақлаш вазирлиги", "Соғлиқни сақлаш вазирлиги", who, dept, "Тизимга маълумот киритилмаган", "Бажарилмаган", "Йўқ", "Йўқ", code, "-", "-", "-",
            state, "Соғлиқни сақлаш вазирлиги", role]


def export(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ТОПШИРИҚЛАР КЕСИМИДА"
    ws.append(["ТОПШИРИҚЛАР КЕСИМИДА (Соғлиқни сақлаш вазирлиги)"])
    ws.append([])
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        from app.db import connect                                   # the database is shared with the other test modules: leave nothing behind
        d = connect()
        d.execute("DELETE FROM tasks WHERE code LIKE 'SX%' OR code='OLD0001'")
        d.execute("DELETE FROM users WHERE name IN ('Sitea Primary','Siteb Ambulance','Sitec Foreign','Old Person')")
        d.execute("DELETE FROM unit_aliases")
        d.commit()
        d.close()


def post(admin, rows, dry=1, window=("2026-12-01", "2026-12-31"), ai=0):
    return admin.post(f"/api/import?dry={dry}&due_from={window[0]}&due_to={window[1]}&ai={ai}", files={"file": ("e.xlsx", export(rows))})


def test_names_in_latin_and_cyrillic_are_compared():
    assert site_import.similarity("Tez tibbiy yordam boʻlimi", "Тез тиббий ёрдам бўлими") > 0.95
    assert site_import.similarity(PRIMARY, "Бирламчи тиббий-санитария ёрдамини ташкиллаштириш бошқармаси") > 0.95
    assert site_import.similarity(FOREIGN, "Тез тиббий ёрдам бўлими") < 0.6
    assert site_import.skeleton("Tuman (shahar) statsionar") == site_import.skeleton("Туман (шаҳар) стационар")


def test_only_our_departments_in_the_window(admin):
    rows = [row("SX0001", PRIMARY, "Sitea Primary", "25.12.2026"), row("SX0002", AMBULANCE, "Siteb Ambulance", "31.12.2026"), row("SX0003", FOREIGN, "Sitec Foreign", "25.12.2026"),
            row("SX0004", PRIMARY, "Sitea Primary", "25.01.2027"), row("SX0005", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган")]
    r = post(admin, rows).json()
    assert r["site"]["file_tasks"] == 5 and r["site"]["tasks"] == 3                         # the foreign department and the other month are left out
    assert r["site"]["skipped"] == {"window": 1, "not_ours": 1, "coexec": 0} and r["created"] == 3 and r["dry"] is True
    names = {d["name"]: d for d in r["site"]["departments"]}
    assert names[PRIMARY]["how"] == "auto" and names[AMBULANCE]["unit"].startswith("Тез тиббий") and names[FOREIGN]["unit_id"] is None
    assert admin.get("/api/tasks?q=SX0001").json()["total"] == 0                            # a preview writes nothing


def test_import_text_status_unit_and_the_tail_of_the_site(admin):
    rows = [row("SX0001", PRIMARY, "Sitea Primary", "25.12.2026"), row("SX0005", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган"),
            row("SX0006", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилмасдан ёпилган", kind="Вазирлар маҳкамаси қарори (Янги)")]
    r = post(admin, rows, dry=0).json()
    assert r["created"] == 3 and r["new_people"][0]["name"] == "Sitea Primary"
    t = admin.get("/api/tasks?q=SX0001").json()["items"][0]
    assert t["text"].startswith("Иш режаси тайёрлансин")
    assert "Механизм" not in t["text"] and not t["text"].endswith("\n")                      # "Механизм: -" and the blank lines of the site are gone
    assert t["kind"] == "ПА" and t["unit"].startswith("Бирламчи")                            # the new employee belongs to the unit the department stands for
    assert admin.get("/api/tasks?q=SX0005").json()["items"][0]["status"] == "done"
    other = admin.get("/api/tasks?q=SX0006").json()["items"][0]
    assert other["kind"] == "ВМ" and other["status"] == "info"                               # closed without execution
    assert admin.get("/api/tasks?q=SX0001").json()["items"][0]["close_date"] is None         # the file has no closing date


def test_reimport_keeps_dates_numbers_status_and_manual_work(admin):
    t = admin.get("/api/tasks?q=SX0001").json()["items"][0]
    assert admin.patch(f"/api/tasks/{t['id']}", json={"status": "progress", "close_date": "2026-12-15"}).status_code == 200
    rows = [row("SX0001", PRIMARY, "Sitea Primary", "25.12.2026", text="1-банд-банд\nИш режаси тайёрлансин\n\nМеханизм: -")]
    r = post(admin, rows, dry=0).json()
    t2 = admin.get("/api/tasks?q=SX0001").json()["items"][0]
    assert t2["status"] == "progress" and t2["close_date"] == "2026-12-15" and r["kept_manual"] == 1      # nothing the person set is overwritten
    assert r["created"] == 0


def test_the_person_who_has_the_task_keeps_it_and_the_main_executor_is_preferred(admin):
    rows = [row("SX0007", PRIMARY, "Sitea Primary", "25.12.2026", role="Тенг кучли"), row("SX0007", AMBULANCE, "Siteb Ambulance", "25.12.2026", role="Асосий")]
    r = post(admin, rows, dry=0).json()
    assert any("несколько ответственных" in w for w in r["warnings"])
    assert admin.get("/api/tasks?q=SX0007").json()["items"][0]["assignee_name"] == "Siteb Ambulance"     # the main executor
    rows = [row("SX0007", PRIMARY, "Sitea Primary", "25.12.2026", role="Асосий"), row("SX0007", AMBULANCE, "Siteb Ambulance", "25.12.2026", role="Тенг кучли")]
    post(admin, rows, dry=0)
    assert admin.get("/api/tasks?q=SX0007").json()["items"][0]["assignee_name"] == "Siteb Ambulance"     # already his: not moved to somebody else


def test_unknown_department_is_mapped_once_and_remembered(admin):
    rows = [row("SX0010", FOREIGN, "Sitec Foreign", "25.12.2026")]
    r = post(admin, rows).json()
    assert r["site"]["tasks"] == 0
    d = [x for x in r["site"]["departments"] if x["name"] == FOREIGN][0]
    unit = r["site"]["units"][0]["id"]
    assert admin.put("/api/import/aliases", json={"map": {d["key"]: unit}}).json() == {"saved": 1}
    r = post(admin, rows).json()
    assert r["site"]["tasks"] == 1 and [x for x in r["site"]["departments"] if x["name"] == FOREIGN][0]["how"] == "confirmed"
    assert admin.put("/api/import/aliases", json={"map": {d["key"]: 99999}}).status_code == 400          # only a unit that exists
    assert admin.put("/api/import/aliases", json={"map": {d["key"]: None}}).status_code == 200            # and "not ours" can be said again
    assert post(admin, rows).json()["site"]["tasks"] == 0


def test_an_employee_of_ours_is_taken_whatever_the_department_is_called(admin):
    users = admin.get("/api/users").json()["items"]
    uid = [u for u in users if u["name"] == "Sitea Primary"][0]["id"]
    assert uid
    r = post(admin, [row("SX0011", "Какой-то новый отдел", "Sitea Primary", "25.12.2026")]).json()
    assert r["site"]["tasks"] == 1                                                              # a known employee with a unit: his row is ours
    d = [x for x in r["site"]["departments"] if x["name"] == "Какой-то новый отдел"][0]
    assert d["how"] == "people" and d["suggest"]                                                 # and the unit is suggested from him


def test_what_is_not_in_the_file_is_listed_not_changed(admin):
    post(admin, [row("SX0020", PRIMARY, "Sitea Primary", "25.12.2026")], dry=0)
    r = post(admin, [row("SX0021", PRIMARY, "Sitea Primary", "25.12.2026")]).json()
    assert "SX0020" in [a["code"] for a in r["site"]["absent"]]
    assert admin.get("/api/tasks?q=SX0020").json()["items"][0]["status"] == "todo"


def test_the_old_processed_list_still_imports(admin):
    from test_app import xlsx
    rows = [[1, "Қарор", "ПҚ-1 \n 01.01.2026", "1-банд\nТекст", "25.12.2026", "2026-12-15", "Old Person", "Бажарилмаган", "OLD0001"]]
    r = admin.post("/api/import?dry=0", files={"file": ("old.xlsx", xlsx(rows))}).json()
    assert r["created"] == 1 and "site" not in r
    assert admin.get("/api/tasks?q=OLD0001").json()["items"][0]["close_date"] == "2026-12-15"


def test_not_a_table_of_the_site_is_refused(admin):
    b = io.BytesIO()
    openpyxl.Workbook().save(b)
    assert admin.post("/api/import?dry=1", files={"file": ("x.xlsx", b.getvalue())}).status_code == 400


def test_an_employee_in_another_unit_than_the_export_is_listed_and_can_be_moved(admin):
    r = post(admin, [row("SX0030", PRIMARY, "Siteb Ambulance", "25.12.2026")]).json()           # Siteb Ambulance is in the unit of the ambulance department; the export puts him in the primary one
    mv = [m for m in r["site"]["people_moves"] if m["name"] == "Siteb Ambulance"]
    assert mv and mv[0]["now"].startswith("Тез тиббий") and mv[0]["wanted"].startswith("Бирламчи") and mv[0]["tasks"] == 1
    assert admin.put("/api/import/people-units", json={"moves": [{"user_id": mv[0]["user_id"], "unit_id": mv[0]["wanted_id"]}]}).json() == {"moved": 1}
    r = post(admin, [row("SX0030", PRIMARY, "Siteb Ambulance", "25.12.2026")]).json()
    assert not [m for m in r["site"]["people_moves"] if m["name"] == "Siteb Ambulance"]          # nothing left to move
    assert admin.put("/api/import/people-units", json={"moves": [{"user_id": mv[0]["user_id"], "unit_id": 99999}]}).status_code == 404
    assert admin.put("/api/import/people-units", json={"moves": []}).status_code == 400


def test_a_co_executors_task_is_not_taken(admin):
    rows = [row("SX0040", PRIMARY, "Sitea Primary", "25.12.2026", role="Ҳамижрочи"), row("SX0041", PRIMARY, "Sitea Primary", "25.12.2026", role="Тенг кучли"), row("SX0042", PRIMARY, "Sitea Primary", "25.12.2026")]
    r = post(admin, rows, dry=0).json()
    assert r["site"]["skipped"]["coexec"] == 1 and r["created"] == 2                       # the main and the equal executors are ours; the co-executor is not
    assert admin.get("/api/tasks?q=SX0040").json()["total"] == 0 and admin.get("/api/tasks?q=SX0041").json()["total"] == 1
