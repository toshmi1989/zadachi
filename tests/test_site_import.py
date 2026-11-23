"""The raw export of edo.ijro.uz: our departments only, a window of terms, status, texts, and what a re-import must never touch."""
import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import ijro, site_import
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
        d.execute("DELETE FROM users WHERE name IN ('Sitea Primary','Siteb Ambulance','Sitec Foreign','Old Person','Sited Finance')")
        d.execute("DELETE FROM unit_aliases")
        d.commit()
        d.close()


def post(admin, rows, dry=1, window=("2026-12-01", "2026-12-31"), ai=0, mode="base", extra=""):
    return admin.post(f"/api/import?dry={dry}&due_from={window[0]}&due_to={window[1]}&ai={ai}&mode={mode}{extra}", files={"file": ("e.xlsx", export(rows))})


def xlsx_old():
    from test_app import xlsx
    return xlsx([[1, "Қарор", "ПҚ-1 \n 01.01.2026", "1-банд\nТекст", "31.12.2026", "2026-12-01", "Old Person", "Бажарилмаган", "OLD0001"]])


def sync_settings(admin, **kw):
    r = admin.put("/api/settings", json={"sync": kw})
    assert r.status_code == 200, r.text


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
    sync_settings(admin, sync_apply="base")                                                           # this test is about adding tasks: the setting is "also add new tasks"
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
    sync_settings(admin, sync_apply="status")


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


def test_the_ordinary_import_only_updates_statuses_of_tasks_in_the_base(admin):
    far = ("2000-01-01", "2099-12-31")
    base = [row("SX0100", PRIMARY, "Sitea Primary", "25.12.2028"), row("SX0101", PRIMARY, "Sitea Primary", "25.12.2026")]
    r = post(admin, base, dry=0, window=far).json()                                              # the base load: new tasks are created
    assert r["created"] == 2 and r["mode"] == "base"
    t = admin.get("/api/tasks?q=SX0101").json()["items"][0]
    assert admin.patch(f"/api/tasks/{t['id']}", json={"status": "progress"}).status_code == 200      # a manual edit: the file must not overwrite it
    new = [row("SX0100", PRIMARY, "Sitea Primary", "25.12.2028", state="Бажарилган", text="1-банд\nДругой текст"),   # done on the site; the text differs but is not ours to change
           row("SX0101", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган"),
           row("SX0102", PRIMARY, "Sitea Primary", "25.12.2026")]                                   # not in the base
    pre = post(admin, new, dry=1, mode="status").json()
    assert pre["created"] == 0 and pre["updated"] == 1 and pre["kept_manual"] == 1 and pre["missing"] == 1 and pre["new_people"] == []
    assert admin.get("/api/tasks?q=SX0100").json()["items"][0]["status"] != "done"                    # a preview writes nothing
    r = post(admin, new, dry=0, mode="status").json()                                               # no window: a term in 2028 is updated all the same
    assert r["mode"] == "status" and r["updated"] == 1 and r["created"] == 0 and r["missing"] == 1
    a = admin.get("/api/tasks?q=SX0100").json()["items"][0]
    assert a["status"] == "done" and a["text"].startswith("Иш режаси тайёрлансин")                   # the status followed, the text did not
    assert admin.get("/api/tasks?q=SX0101").json()["items"][0]["status"] == "progress"             # the manual edit stays
    assert admin.get("/api/tasks?q=SX0102").json()["total"] == 0                                    # never created by an ordinary import
    again = post(admin, new, dry=0, mode="status").json()
    assert again["updated"] == 0 and again["unchanged"] == 1
    assert post(admin, new, mode="bogus").status_code == 400


def test_the_collector_follows_the_setting_for_what_a_list_does(admin):
    from datetime import timedelta
    from app.db import connect, today
    d0 = connect(); d0.execute("DELETE FROM unit_aliases"); d0.commit(); d0.close()
    due = (today() + timedelta(days=20)).strftime("%d.%m.%Y")
    k = admin.post("/api/sync/keys", json={"name": "mode-test"}).json()["key"]
    h = {"authorization": "Bearer " + k, "content-type": "application/octet-stream"}
    data = export([row("SX0110", PRIMARY, "Sitea Primary", due)])
    sync_settings(admin, sync_apply="status")
    r = admin.post("/api/sync/export?source=a", content=data, headers=h).json()
    assert r["mode"] == "status" and r["created"] == 0 and r["missing"] == 1                         # only statuses: the new task is counted, not created
    assert admin.get("/api/tasks?q=SX0110").json()["total"] == 0
    sync_settings(admin, sync_apply="base")
    r = admin.post("/api/sync/export?source=b", content=data, headers=h).json()
    assert r["mode"] == "base" and r["created"] == 1
    sync_settings(admin, sync_apply="base", base_back="", base_fwd="0")                              # a window: from "no limit" back to "today" forward
    far = export([row("SX0111", PRIMARY, "Sitea Primary", (today() + timedelta(days=20)).strftime("%d.%m.%Y"))])
    assert admin.post("/api/sync/export?source=c", content=far, headers=h).json()["created"] == 0   # 20 days ahead is outside "0 days ahead"
    sync_settings(admin, sync_apply="status", base_back="30", base_fwd="60")
    admin.delete(f"/api/sync/keys/{admin.get('/api/sync/keys').json()['items'][0]['id']}")


def test_the_download_plan_follows_the_setting(admin):
    sync_settings(admin, sync_source="lists")
    k = admin.post("/api/sync/keys", json={"name": "plan"}).json()["key"]
    head = {"authorization": "Bearer " + k}
    plan = admin.get("/api/sync/export-plan", headers=head).json()
    assert plan["mode"] == "lists" and [x["id"] for x in plan["sections"]] == ["president", "government", "president_admin"]     # one list per section ...
    assert plan["tabs"] == [{"id": "all", "statuses": []}] and ijro.export_files() == 3                                              # ... every status at once: three files
    assert [x for x in plan["sections"] if x["id"] == "government"][0]["type_ids"] == ["68d805f2c8d2f3123184e0f4"]                   # the cabinet: only the kind that is kept
    sync_settings(admin, sync_source="tabs")
    plan = admin.get("/api/sync/export-plan", headers=head).json()
    assert plan["mode"] == "tabs" and len(plan["sections"]) == 3 and len(plan["tabs"]) == 3 and ijro.export_files() == ijro.EXPORT_FILES == 9
    sync_settings(admin, sync_source="lists")
    admin.delete(f"/api/sync/keys/{admin.get('/api/sync/keys').json()['items'][0]['id']}")


def test_the_settings_of_the_import_are_explained_and_validated(admin):
    s = admin.get("/api/settings").json()["sync"]
    fields = {f["key"]: f for f in s["fields"]}
    assert set(fields) == {"base_f_dept", "base_f_exec", "base_f_kind", "base_f_window", "base_manual", "base_absent", "sync_source", "sync_apply", "base_back", "base_fwd", "history_scope", "history_date", "history_statuses", "sync_parallel"}
    assert [fields[k]["value"] for k in ("base_f_dept", "base_f_exec", "base_f_kind", "base_f_window")] == ["1", "0", "0", "0"]     # departments are filtered; the files are already selected otherwise
    assert all(fields[k]["kind"] == "switch" and fields[k]["help"] for k in ("base_f_dept", "base_f_exec", "base_f_kind", "base_f_window"))
    assert fields["base_manual"]["value"] == "overwrite" and fields["base_absent"]["value"] == "gone"                  # the base overwrites; what is not in it leaves the dashboard
    groups = {g["id"] for g in admin.get("/api/settings").json()["sync"]["groups"]}
    assert groups == {"base", "history", "lists"} and {f["group"] for f in s["fields"]} == groups
    assert all(o["help"] for f in s["fields"] if f["kind"] == "choice" for o in f["options"])        # every choice says what it does
    assert fields["sync_source"]["value"] == "lists" and fields["sync_apply"]["value"] == "status" and fields["history_scope"]["value"] == "all"   # the defaults
    assert fields["history_statuses"]["value"] == "open" and fields["history_date"]["value"] == "close"
    for bad in ({"sync_source": "nope"}, {"history_scope": ""}, {"base_back": "-5"}, {"base_fwd": "abc"}, {"base_back": "99999"}, {"unknown": "1"}):
        assert admin.put("/api/settings", json={"sync": bad}).status_code == 400, bad
    assert admin.put("/api/settings", json={"sync": {}}).status_code == 400
    assert admin.put("/api/settings", json={"sync": {"base_back": "", "history_scope": "all"}}).status_code == 200
    got = {f["key"]: f["value"] for f in admin.get("/api/settings").json()["sync"]["fields"]}
    assert got["base_back"] == "" and got["history_scope"] == "all"
    sync_settings(admin, base_back="30", history_scope="all")


def _statuses():
    from app.db import connect
    c = connect()
    try:
        return {r["id"]: r["status"] for r in c.execute("SELECT id, status FROM tasks")}
    finally:
        c.close()


def _restore(before):
    """The base load takes absent tasks off the dashboard: the tests of other modules share this database, so the statuses are put back."""
    from app.db import connect
    c = connect()
    for i, st in before.items():
        c.execute("UPDATE tasks SET status=? WHERE id=?", (st, i))
    c.commit(); c.close()


def test_the_base_overwrites_hand_edits_and_takes_absent_tasks_off(admin):
    far = ("2000-01-01", "2099-12-31")
    assert post(admin, [row("SX0200", PRIMARY, "Sitea Primary", "25.12.2026"), row("SX0201", PRIMARY, "Sitea Primary", "25.12.2026"),
                        row("SX0202", PRIMARY, "Sitea Primary", "25.12.2026")], dry=0, window=far).json()["created"] == 3
    t = admin.get("/api/tasks?q=SX0200").json()["items"][0]
    assert admin.patch(f"/api/tasks/{t['id']}", json={"status": "progress", "close_date": "2026-12-15"}).status_code == 200
    new = [row("SX0200", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган"), row("SX0201", PRIMARY, "Sitea Primary", "25.12.2026"),
           row("SX0203", PRIMARY, "Sitea Primary", "25.12.2026")]                                   # SX0202 is not in the new base
    keep = post(admin, new, dry=1, window=far).json()                                               # the API default: hand edits stay, nothing leaves
    assert keep["kept_manual"] == 1 and keep["overwritten"] == 0 and "absent_tasks" not in keep
    pre = post(admin, new, dry=1, window=far, extra="&overwrite=1&replace=1").json()
    assert pre["overwritten"] == 1 and pre["created"] == 1 and pre["kept_manual"] == 0
    ab = pre["absent_tasks"]
    assert any(x["code"] == "SX0202" for x in ab["sample"]) and ab["count"] >= 1 and not any(x["code"] in ("SX0200", "SX0201", "SX0203") for x in ab["sample"])
    assert admin.get("/api/tasks?q=SX0200").json()["items"][0]["status"] == "progress"              # a preview writes nothing
    before = _statuses()
    try:
        assert ab["needs_confirm"]                                                                   # nearly every other open task of this database is "absent": more than a quarter
        refused = post(admin, new, dry=0, window=far, extra="&overwrite=1&replace=1")
        assert refused.status_code == 400 and "подтверд" in refused.text and _statuses() == before   # an incomplete load is stopped before anything is written
        r = post(admin, new, dry=0, window=far, extra="&overwrite=1&replace=1&confirm=1").json()
        assert r["overwritten"] == 1 and r["absent_tasks"]["taken_off"] == ab["count"]
        a = admin.get("/api/tasks?q=SX0200").json()["items"][0]
        assert a["status"] == "done" and a["close_date"] == "2026-12-15"                           # the file won; a closing date that is not in the file is not erased
        assert admin.get("/api/tasks?q=SX0202&status=gone").json()["total"] == 1                    # taken off, not deleted
        assert admin.get("/api/tasks?q=SX0203").json()["total"] == 1
        back = post(admin, new + [row("SX0202", PRIMARY, "Sitea Primary", "25.12.2026")], dry=0, window=far, extra="&overwrite=1").json()
        assert admin.get("/api/tasks?q=SX0202").json()["items"][0]["status"] == "todo" and back["updated"] >= 1      # it comes back when a later base has it
    finally:
        _restore(before)


def test_several_files_are_one_base(admin):
    far = ("2000-01-01", "2099-12-31")
    one = [row("SX0210", PRIMARY, "Sitea Primary", "25.12.2026")]
    two = [row("SX0211", PRIMARY, "Sitea Primary", "25.12.2026")]
    assert post(admin, one + two, dry=0, window=far).json()["created"] == 2
    url = f"/api/import?dry=1&due_from={far[0]}&due_to={far[1]}&ai=0&overwrite=1&replace=1"
    both = admin.post(url, files=[("file", ("a.xlsx", export(one))), ("file", ("b.xlsx", export(two)))]).json()
    assert both["rows"] == 2 and not any(x["code"] in ("SX0210", "SX0211") for x in both["absent_tasks"]["sample"])      # judged together: neither leaves
    only = admin.post(url, files=[("file", ("a.xlsx", export(one)))]).json()
    assert any(x["code"] == "SX0211" for x in only["absent_tasks"]["sample"])                      # one file alone would take the other one off: that is why the preview says so
    mixed = admin.post(url, files=[("file", ("a.xlsx", export(one))), ("file", ("old.xlsx", xlsx_old()))])
    assert mixed.status_code == 400
    assert admin.post(url, files=[("file", ("a.xlsx", export(one)))] * 11).status_code == 400       # at most ten files


def test_the_filters_of_a_loaded_file_are_independent(admin):
    rows = [row("SX0300", PRIMARY, "Sitea Primary", "25.12.2026"),                                              # ours
            row("SX0301", FOREIGN, "Sitec Foreign", "25.12.2026"),                                              # a department that is not in the structure
            row("SX0302", PRIMARY, "Sitea Primary", "25.12.2026", executor="Таълим ва илм-фан вазирлиги"),     # another executor
            row("SX0303", PRIMARY, "Sitea Primary", "25.12.2026", role="Ҳамижрочи"),                          # a co-executor
            row("SX0304", PRIMARY, "Sitea Primary", "25.12.2026", kind="Бош вазир топшириқлари"),               # a kind of the cabinet's list that is not kept
            row("SX0305", PRIMARY, "Sitea Primary", "25.12.2031")]                                              # far outside any window
    win = ("2026-12-01", "2026-12-31")
    flags = lambda d, e, k, w: f"&f_dept={d}&f_exec={e}&f_kind={k}&f_window={w}"
    allon = post(admin, rows, dry=1, window=win, extra=flags(1, 1, 1, 1)).json()                              # every filter: the old strict selection
    assert allon["rows"] == 1 and allon["site"]["skipped"]["not_ours"] == 1 and allon["site"]["skipped"]["executor"] == 1
    assert post(admin, rows, dry=1, window=win).json()["rows"] == 1                                            # the API default is every filter on
    dept = post(admin, rows, dry=1, window=win, extra=flags(1, 0, 0, 0)).json()                               # the default of the settings: only the departments are filtered
    assert dept["rows"] == 5 and dept["site"]["skipped"]["not_ours"] == 1 and dept["site"]["skipped"]["executor"] == 0 and dept["site"]["skipped"]["window"] == 0
    none = post(admin, rows, dry=1, window=win, extra=flags(0, 0, 0, 0)).json()                               # no filter: every row
    assert none["rows"] == 6 and none["site"]["skipped"] == {"window": 0, "not_ours": 0, "coexec": 0, "executor": 0}
    ex = post(admin, rows, dry=1, window=win, extra=flags(0, 1, 0, 0)).json()
    assert ex["rows"] == 5 and ex["site"]["skipped"]["executor"] == 1
    kd = post(admin, rows, dry=1, window=win, extra=flags(0, 0, 1, 0)).json()
    assert kd["rows"] == 4 and kd["site"]["skipped"]["coexec"] == 1 and kd["site"]["skipped"]["doc_type"] == 1
    wd = post(admin, rows, dry=1, window=win, extra=flags(0, 0, 0, 1)).json()
    assert wd["rows"] == 5 and wd["site"]["skipped"]["window"] == 1
    r = post(admin, rows, dry=0, extra=flags(0, 0, 0, 0)).json()
    assert r["created"] == 6
    got = {c: admin.get(f"/api/tasks?q={c}").json()["items"][0] for c in ("SX0301", "SX0305")}
    assert got["SX0301"]["unit"] in ("", None) and got["SX0305"]["eff"] is not None                          # the foreign department's task is «Без отдела»; a far term is kept


def test_the_departments_of_a_file_can_be_added_to_the_structure(admin):
    from app.db import connect
    c = connect(); before = c.execute("SELECT COUNT(*) FROM units").fetchone()[0]; c.close()
    names = ["Tibbiyot taʼlimi va ilm-fan departamenti", "Moliya-iqtisod departamenti", PRIMARY]                  # the last one is the structure's own department (written in Latin)
    r = admin.post("/api/import/add-units", json={"names": names}).json()
    assert r == {"created": 2, "skipped": 1}                                                                  # a name that already matches the structure is not added again
    assert admin.post("/api/import/add-units", json={"names": names}).json() == {"created": 0, "skipped": 3}   # and nothing is added twice
    c = connect(); after = c.execute("SELECT COUNT(*) FROM units").fetchone()[0]
    added = [x["name"] for x in c.execute("SELECT name, num, parent_id FROM units ORDER BY id DESC LIMIT 2")]
    c.close()
    assert after == before + 2 and set(added) == set(names[:2])
    for bad in ({"names": []}, {"names": ["x"] * 101}, {"names": [1]}, {"names": ["  "]}, {}):
        assert admin.post("/api/import/add-units", json=bad).status_code == 400, bad
    d = post(admin, [row("SX0310", "Moliya-iqtisod departamenti", "Sited Finance", "25.12.2026")], dry=0, extra="&f_dept=0&f_exec=0&f_kind=0&f_window=0").json()
    assert d["created"] == 1 and admin.get("/api/tasks?q=SX0310").json()["items"][0]["unit"].startswith("Moliya")      # now the task goes to its department
    c = connect()                                                                                             # put the structure back: the other modules share this database
    ids = "SELECT id FROM units WHERE name LIKE 'Moliya%' OR name LIKE 'Tibbiyot ta%'"
    c.execute(f"UPDATE users SET unit_id = NULL WHERE unit_id IN ({ids})")
    c.execute(f"DELETE FROM units WHERE id IN ({ids})")
    c.commit(); c.close()


def test_the_loaded_base_replaces_everything_done_tasks_and_old_proposals_included(admin):
    from app.db import connect
    far = ("2000-01-01", "2099-12-31")
    flags = "&overwrite=1&replace=1&confirm=1&f_dept=0&f_exec=0&f_kind=0&f_window=0"
    assert post(admin, [row("SX0400", PRIMARY, "Sitea Primary", "25.12.2026"), row("SX0401", PRIMARY, "Sitea Primary", "25.12.2026", state="Бажарилган"),
                        row("SX0402", PRIMARY, "Sitea Primary", "25.12.2026")], dry=0, window=far).json()["created"] == 3
    c = connect()
    c.execute("UPDATE tasks SET close_date='2026-11-10', close_src='rule', close_note='by the history' WHERE code='SX0402'")      # only a proposal: nobody confirmed it
    c.execute("UPDATE tasks SET close_date='2026-12-15' WHERE code='SX0400'")                                                    # a date a person set
    c.commit(); c.close()
    before = _statuses()
    try:
        new = [row("SX0400", PRIMARY, "Sitea Primary", "25.12.2026"), row("SX0402", PRIMARY, "Sitea Primary", "25.12.2026")]       # SX0401 (done) is not in the new files
        pre = post(admin, new, dry=1, window=far, extra=flags).json()["absent_tasks"]
        assert any(x["code"] == "SX0401" and x["status"] == "done" for x in pre["sample"]) and pre["done"] >= 1 and pre["total"] >= pre["count"]    # a done task goes as well
        r = post(admin, new, dry=0, window=far, extra=flags).json()
        assert r["absent_tasks"]["taken_off"] == pre["count"]
        assert admin.get("/api/tasks?q=SX0401&status=gone").json()["total"] == 1 and admin.get("/api/tasks?q=SX0401").json()["total"] == 0
        a, b = (admin.get(f"/api/tasks?q={code}").json()["items"][0] for code in ("SX0400", "SX0402"))
        assert a["close_date"] == "2026-12-15"                                                                                    # a confirmed date stays
        assert b["close_date"] is None and b["close_src"] == ""                                                                   # a proposal of the old base is gone: the month follows the official term
    finally:
        _restore(before)
