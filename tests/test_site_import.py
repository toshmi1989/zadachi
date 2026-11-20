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


def row(code, dept, who, due, kind="Президент администрацияси раҳбари резолюцияси", text="1-банд-банд\nИш режаси тайёрлансин\n\n\nМеханизм: -", state="Бажарилмоқда", role="Асосий",
        executor="Соғлиқни сақлаш вазирлиги"):
    return ["1", kind, "02-PA 1/1-3112 \n 25.09.2025", text, "-", due, "Соғлиқни сақлаш вазирлиги", executor, who, dept, "Тизимга маълумот киритилмаган", "Бажарилмаган", "Йўқ", "Йўқ", code, "-", "-", "-",
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
    assert r["site"]["skipped"] == {"window": 1, "not_ours": 1, "coexec": 0, "executor": 0} and r["created"] == 3 and r["dry"] is True
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


def test_the_collector_sends_the_export_and_it_is_imported_at_once(admin):
    from datetime import timedelta
    from app.db import today
    due = (today() + timedelta(days=20)).strftime("%d.%m.%Y")
    from app.db import connect
    d0 = connect(); d0.execute("DELETE FROM unit_aliases"); d0.commit(); d0.close()                # earlier tests may have remembered a department as "not ours"
    k = admin.post("/api/sync/keys", json={"name": "export-test"}).json()["key"]
    h = {"authorization": "Bearer " + k, "content-type": "application/octet-stream"}
    data = export([row("SX0040", PRIMARY, "Sitea Primary", due), row("SX0041", FOREIGN, "Sitec Foreign", due), row("SX0042", PRIMARY, "Sitea Primary", due, role="Ҳамижрочи")])
    assert admin.post("/api/sync/export?source=pa", content=data).status_code in (401, 403)        # no key: refused (a cookie alone does not open this door)
    assert admin.post("/api/sync/export", content=b"not an excel", headers=h).status_code == 400
    r = admin.post("/api/sync/export?source=pa&last=0", content=data, headers=h).json()
    assert r["created"] == 1 and r["skipped"]["not_ours"] == 1 and r["skipped"]["coexec"] == 1 and r["closing"] is None
    assert FOREIGN in r["unmapped"]                                                                    # not mapped yet: reported, the person decides once on the import screen
    t = admin.get("/api/tasks?q=SX0040").json()["items"][0]
    assert t["code"] == "SX0040"
    r2 = admin.post("/api/sync/export?source=pa&last=1", content=data, headers=h).json()
    assert r2["created"] == 0 and r2["unchanged"] == 1                                                 # a second run changes nothing
    d = admin.get("/api/sync/keys").json()["items"][0]
    admin.delete(f"/api/sync/keys/{d['id']}")


def test_of_the_cabinet_list_only_the_new_resolution_kind_is_kept(admin):
    k = "Ўзбекистон Республикаси Президенти Администрацияси раҳбари топшириқлари"
    r = post(admin, [row("SX0050", PRIMARY, "Sitea Primary", "25.12.2026", kind="Вазирлар маҳкамаси қарори (Янги)"),
                     row("SX0051", PRIMARY, "Sitea Primary", "25.12.2026", kind="Вазирлар Маҳкамаси қарорлари"),
                     row("SX0052", PRIMARY, "Sitea Primary", "25.12.2026", kind="Бош вазир топшириқлари"),
                     row("SX0053", PRIMARY, "Sitea Primary", "25.12.2026", kind="  " + k.upper() + " "),
                     row("SX0054", PRIMARY, "Sitea Primary", "25.12.2026", kind="Қарор")]).json()          # a kind of another list is not touched
    assert r["site"]["skipped"]["doc_type"] == 3 and r["site"]["tasks"] == 2 and r["created"] == 2


def test_tasks_the_site_no_longer_lists_leave_the_dashboard_but_only_after_a_complete_run(admin):
    import uuid
    from datetime import timedelta
    from app import ijro
    from app.db import connect, now, today
    due = (today() + timedelta(days=20)).strftime("%d.%m.%Y")
    d0 = connect(); d0.execute("DELETE FROM unit_aliases"); d0.commit(); d0.close()
    k = admin.post("/api/sync/keys", json={"name": "stale-test"}).json()["key"]
    h = {"authorization": "Bearer " + k, "content-type": "application/octet-stream"}
    # on the platform already (an earlier import): a wanted task, one of an unwanted kind, one the site closed meanwhile, one never checked
    c = connect()
    for code, kind in (("SX0060", "ВМ"), ("SX0061", "ВМ"), ("SX0062", "ВМ"), ("SX0063", "ВМ")):
        c.execute("INSERT INTO tasks(code, kind, text, due, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (code, kind, "t", today().isoformat(), "todo", now(), now()))
    ids = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM tasks WHERE code LIKE 'SX006%'")}
    c.commit(); c.close()
    run = str(uuid.uuid4())
    data = export([row("SX0060", PRIMARY, "Sitea Primary", due, kind="Вазирлар маҳкамаси қарори (Янги)"), row("SX0061", PRIMARY, "Sitea Primary", due, kind="Бош вазир топшириқлари")])
    def snap(code, status, found=1):
        d = connect()
        d.execute("INSERT OR REPLACE INTO ijro_snapshots(task_id, found, site_status, is_done, checked_at) VALUES (?,?,?,?,?)", (ids[code], found, status, 1 if status in (20, 21) else 0, now()))
        d.commit(); d.close()
    for i in range(ijro.EXPORT_FILES):                                                           # the six files of a run (here the same one six times)
        assert admin.post(f"/api/sync/export?source=x{i}&run={run}", content=data, headers=h).status_code == 200
    snap("SX0060", 1); snap("SX0061", 1); snap("SX0062", 20)                                       # SX0063 is never checked
    # an incomplete run proves nothing
    r = admin.post("/api/sync/finish", json={"run": run, "complete": False}, headers={"authorization": "Bearer " + k}).json()
    assert r["judged"] is False and admin.get(f"/api/tasks?q=SX0061").json()["total"] == 1
    r = admin.post("/api/sync/finish", json={"run": str(uuid.uuid4()), "complete": True}, headers={"authorization": "Bearer " + k}).json()
    assert r["judged"] is False                                                                    # unknown run: no files received
    r = admin.post("/api/sync/finish", json={"run": run, "complete": True}, headers={"authorization": "Bearer " + k}).json()
    assert r["judged"] and r["stale"] == 1 and r["archived"] == 1 and r["unsure"] >= 2, r          # only SX0061; the closed one and the unchecked one are left alone
    got = {x["code"]: x["status"] for x in admin.get("/api/tasks?q=SX006&size=50").json()["items"]}
    assert "SX0061" not in got and got["SX0060"] == "todo" and got["SX0062"] == "todo" and got["SX0063"] == "todo"     # off the lists
    assert admin.get("/api/tasks?q=SX0061&status=gone").json()["total"] == 1                       # but not deleted
    ev = admin.get(f"/api/tasks/{ids['SX0061']}").json()
    assert "Нет на сайте" in json.dumps(ev, ensure_ascii=False)
    # listed again: back by itself
    data2 = export([row("SX0061", PRIMARY, "Sitea Primary", due, kind="Президент администрацияси раҳбари резолюцияси")])
    assert admin.post("/api/sync/export?source=back", content=data2, headers=h).status_code == 200
    assert admin.get("/api/tasks?q=SX0061").json()["items"][0]["status"] == "todo"
    d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'SX006%'"); d.commit(); d.close()
    admin.delete("/api/sync/keys/" + str(admin.get("/api/sync/keys").json()["items"][0]["id"]))


def test_many_stale_tasks_wait_for_the_administrator_and_the_dashboard_skips_gone(admin):
    import uuid
    from app import ijro
    from app.db import connect, now, today
    k = admin.post("/api/sync/keys", json={"name": "stale-test2"}).json()["key"]
    h = {"authorization": "Bearer " + k, "content-type": "application/octet-stream"}
    c = connect()
    c.execute("INSERT INTO tasks(code, kind, text, due, status, created_at, updated_at) VALUES ('SX0070','ВМ','t',?, 'todo', ?, ?)", (today().isoformat(), now(), now()))
    tid = c.execute("SELECT id FROM tasks WHERE code='SX0070'").fetchone()["id"]
    c.execute("INSERT OR REPLACE INTO ijro_snapshots(task_id, found, site_status, is_done, checked_at) VALUES (?,1,1,0,?)", (tid, now()))
    c.commit(); c.close()
    assert admin.put("/api/sync/settings", json={"auto_archive": False}).status_code == 200      # the automatic removal is off: the decision waits
    run = str(uuid.uuid4())
    data = export([row("SX0071", PRIMARY, "Sitea Primary", "25.12.2026")])
    for i in range(ijro.EXPORT_FILES):
        admin.post(f"/api/sync/export?source=y{i}&run={run}", content=data, headers=h)
    r = admin.post("/api/sync/finish", json={"run": run, "complete": True}, headers={"authorization": "Bearer " + k}).json()
    assert r["archived"] == 0 and r["waiting"] >= 1
    assert any(x["code"] == "SX0070" for x in admin.get("/api/sync/stale").json()["items"])
    before = admin.get("/api/dashboard").json()
    assert admin.post("/api/sync/archive", json={"task_ids": [tid]}).json()["archived"] == 1
    assert admin.post("/api/sync/archive", json={"task_ids": [tid]}).json()["archived"] == 0        # only what the last run proposed, once
    assert admin.get("/api/tasks?q=SX0070").json()["total"] == 0
    after = admin.get("/api/dashboard").json()
    assert after["totals"]["total"] == before["totals"]["total"] - 1                                   # the dashboard no longer counts it
    admin.put("/api/sync/settings", json={"auto_archive": True})
    d = connect(); d.execute("DELETE FROM tasks WHERE code IN ('SX0070','SX0071')"); d.commit(); d.close()
    admin.delete("/api/sync/keys/" + str(admin.get("/api/sync/keys").json()["items"][0]["id"]))


def test_the_done_tab_is_exported_but_does_not_count_as_open_on_the_site(admin):
    from app import ijro
    assert [t["id"] for t in ijro.EXPORT_TABS] == ["in_progress", "overdue", "done"] and ijro.EXPORT_FILES == 9
    assert not ({20, 21, 31} & ijro.SITE_OPEN_STATUSES) and {-1, 0, 1, 2, 3, 4, 10, 14} <= ijro.SITE_OPEN_STATUSES
    r = post(admin, [row("SX0080", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган"), row("SX0081", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилмасдан ёпилган")], dry=0).json()
    got = {x["code"]: x["status"] for x in admin.get("/api/tasks?q=SX008&size=20").json()["items"]}
    assert got == {"SX0080": "done", "SX0081": "info"}                                           # done, and closed without execution (for information)
    from app.db import connect
    d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'SX008%'"); d.commit(); d.close()


def test_only_rows_whose_main_executor_is_the_health_ministry_are_taken(admin):
    due = "25.12.2026"
    rows = [row("SX0090", PRIMARY, "Sitea Primary", due),                                                      # ours
            row("SX0091", PRIMARY, "Sitea Primary", due, executor="Таълим ва илм-фан вазирлиги"),               # our department, but another main executor
            row("SX0092", PRIMARY, "Sitea Primary", due, executor="Sog'liqni saqlash vazirligi"),              # the same ministry written in Latin
            row("SX0093", PRIMARY, "Sitea Primary", due, executor="Соғлиқни сақлаш вазирлиги ҳузуридаги агентлик"),   # a longer name is another body
            row("SX0094", PRIMARY, "Sitea Primary", due, executor="")]
    r = post(admin, rows, dry=0).json()
    assert r["site"]["skipped"]["executor"] == 3 and r["created"] == 2
    got = {c: admin.get(f"/api/tasks?q={c}").json()["total"] for c in ("SX0090", "SX0091", "SX0092", "SX0093", "SX0094")}
    assert got == {"SX0090": 1, "SX0091": 0, "SX0092": 1, "SX0093": 0, "SX0094": 0}


def test_an_export_without_the_executor_column_is_refused_not_emptied(admin):
    head = [h for h in HEAD if h != "Масъул ижрочи"]
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(head)
    r0 = row("SX0095", PRIMARY, "Sitea Primary", "25.12.2026"); ws.append(r0[:7] + r0[8:])
    b = io.BytesIO(); wb.save(b)
    resp = admin.post("/api/import?dry=1&ai=0", files={"file": ("e.xlsx", b.getvalue())})
    assert resp.status_code == 400 and "Масъул ижрочи" in resp.text


def test_departments_of_other_executors_are_not_asked_about(admin):
    rows = [row("SX0096", PRIMARY, "Sitea Primary", "25.12.2026"),
            row("SX0097", FOREIGN, "Sitec Foreign", "25.12.2026", executor="Таълим ва илм-фан вазирлиги")]
    r = post(admin, rows).json()
    names = [d["name"] for d in r["site"]["departments"]]
    assert PRIMARY in names and FOREIGN not in names                       # the department of a foreign executor is not offered for mapping
    assert r["site"]["file_tasks"] == 2 and r["site"]["skipped"]["executor"] == 1
