"""The Chamber accepted the answer for information: if the term of the task was changed on the site AFTER that, nothing waits for us: the task moves from «Палата вернула» to «Другое»."""
import calendar
import datetime
import json

import pytest
from fastapi.testclient import TestClient

from app import ijro
from app.main import app
from test_app import xlsx

MS = lambda y, m, d, h=12: calendar.timegm(datetime.datetime(y, m, d, h).timetuple()) * 1000
ANSWER = MS(2026, 11, 6, 12)          # «Маълумот учун қабул қилинди»
HOUR = 3600 * 1000


def snap(**kw):
    base = {"found": 1, "repeatable": 0, "periods": "[]", "is_done": 0, "site_status": 2, "due_ms": MS(2026, 12, 5), "is_secret": 0, "task_id": 1,
            "answers": json.dumps([{"sender_type": t, "at_ms": ANSWER - (3 - i) * HOUR, "state": 1, "active": 1, "text": "Маълумот учун қабул қилинди" if t == 44 else ""} for i, t in enumerate([10, 25, 35, 44])])}
    return base | kw


def test_the_stage_depends_on_when_the_term_was_changed(admin):
    S = ijro.stage_of
    assert S(snap())["code"] == "info"                                                   # nothing is known about a change: as before, the Chamber returned it
    assert S(snap(updated_ms=ANSWER - 2 * HOUR))["code"] == "info"                        # the site changed the task before the answer
    assert S(snap(updated_ms=ANSWER + 60 * 1000))["code"] == "info"                       # the answer and the term are one action (a minute apart)
    after = S(snap(updated_ms=ANSWER + 6 * 24 * HOUR))
    assert after["code"] == "info_term" and not after["attention"] and "изменён" in after["label"] and after["new_due"] == "2026-12-05"
    assert S(snap(ext_date="2026-11-10"))["code"] == "info_term"                          # the list of the site says: the term was extended on 10.11, the answer is of 6.11
    assert S(snap(ext_date="2026-11-06"))["code"] == "info_term"                          # the same day as the answer counts (the term moved by the answer itself)
    assert S(snap(ext_date="2026-11-01"))["code"] == "info"                               # the extension is older than the answer
    assert S(snap(due_mod_ms=ANSWER + 2 * HOUR))["code"] == "info_term"                   # the card's own modification date
    assert S(snap(due_mod_ms=ANSWER - 2 * HOUR))["code"] == "info"
    # the real cards: the flag of the card + the moment of the last change of the task
    assert S(snap(due_changed=1, updated_ms=ANSWER + 34))["code"] == "info_term"          # the term was moved by the very answer (the task changed 34 ms after it): dealt with
    assert S(snap(due_changed=1, updated_ms=ANSWER + 3 * 24 * HOUR))["code"] == "info_term"  # moved later
    assert S(snap(due_changed=1))["code"] == "info_term"                                  # the flag alone, no time known
    assert S(snap(due_changed=0, updated_ms=ANSWER + 3 * 24 * HOUR))["code"] == "info"    # the card says the term was never changed
    assert S(snap(due_changed=1, updated_ms=ANSWER - 3 * 24 * HOUR))["code"] == "info"    # the task was last changed long before the answer
    assert S(snap(due_changed=1, ext_date="2026-11-01"))["code"] == "info"                # the list says the extension is older than the answer: the Chamber answered after it
    assert S(snap(due_changed=1, ext_date="2026-11-06"))["code"] == "info_term"           # the same day as the answer: counts
    ev = S(snap(ext_date="2026-11-10"))["evidence"]
    assert "06.11.2026" in ev and "10.11.2026" in ev                                      # the administrator is shown the dates the decision stands on
    assert "нет" in S(snap())["evidence"] and "evidence" not in S(snap(), dates=False) or S(snap(), dates=False)["evidence"] == ""
    assert S(snap(term_seen_ms=ANSWER + HOUR))["code"] == "info_term"                      # the synchronisation saw the term change after the answer
    assert S(snap(term_seen_ms=ANSWER - HOUR))["code"] == "info"


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        rows = [[i + 1, "Қарор", f"ПҚ-7{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", "Term Person", "Бажарилмаган", f"IT000{i}"] for i in range(2)]
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(rows))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c
        from app.db import connect
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'IT000%'"); d.execute("DELETE FROM users WHERE name='Term Person'"); d.commit(); d.close()


def item(code, due, **kw):
    ans = [{"sender_type": t, "state": 1, "at_ms": ANSWER - (3 - i) * HOUR, "active": i == 3, "text": "Маълумот учун қабул қилинди" if t == 44 else "x", "org": "", "pd": None} for i, t in enumerate([10, 25, 35, 44])]
    return {"code": code, "found": True, "section": "president", "recipient_id": "r" + code, "status": 2, "is_done": False, "answers_loaded": True, "answers": ans, "due_ms": due, **kw}


def test_through_the_synchronisation(admin):
    anon = TestClient(app)
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "term"}).json()["key"]}
    def card(code):
        t = admin.get(f"/api/tasks?q={code}&size=3&status=all").json()["items"][0]
        return admin.get(f"/api/tasks/{t['id']}").json()
    # 1. the site's update time is later than the answer: the task is «Срок изменён…», not «Палата вернула»; its term is the site's one
    r = anon.post("/api/sync/ingest", json={"run_id": 0, "items": [item("IT0000", MS(2026, 12, 5), updated_ms=ANSWER + 5 * 24 * HOUR)]}, headers=h)
    assert r.status_code == 200
    t = card("IT0000")
    assert t["site"]["stage"]["code"] == "info_term" and t["site"]["label"].startswith("Срок изменён") and t["due"] == "2026-12-05"
    ids = {x["id"] for x in admin.get("/api/tasks?stage=other&status=open&size=200").json()["items"]}
    assert t["id"] in ids and t["id"] not in {x["id"] for x in admin.get("/api/tasks?stage=info&status=open&size=200").json()["items"]}      # in «Другое», not in «Палата вернула»
    # 2. no sign of a change: still «Палата вернула»
    anon.post("/api/sync/ingest", json={"run_id": 0, "items": [item("IT0001", MS(2026, 12, 5))]}, headers=h)
    t1 = card("IT0001")
    assert t1["site"]["stage"]["code"] == "info" and t1["id"] in {x["id"] for x in admin.get("/api/tasks?stage=info&status=open&size=200").json()["items"]}
    # 3. the term changes on the site later, the synchronisation sees it: now it moves
    anon.post("/api/sync/ingest", json={"run_id": 0, "items": [item("IT0001", MS(2026, 12, 25))]}, headers=h)
    t1 = card("IT0001")
    assert t1["site"]["stage"]["code"] == "info_term" and t1["due"] == "2026-12-25"
    # 4. the date of the extension in the site's list (Excel) decides at once, for tasks that were loaded before
    from test_site_import import HEAD, PRIMARY, export, row
    col = next(i for i, h in enumerate(HEAD) if str(h).startswith("Муддат узайтириш санаси"))
    early, late = row("IT0002", PRIMARY, "Term Person", "25.12.2026"), row("IT0003", PRIMARY, "Term Person", "25.12.2026")
    early[col], late[col] = "01.11.2026", "10.11.2026"
    r = admin.post("/api/import?dry=0&due_from=2026-12-01&due_to=2026-12-31&ai=0&f_dept=0&f_window=0", files={"file": ("e.xlsx", export([early, late]))})
    assert r.status_code == 200
    anon.post("/api/sync/ingest", json={"run_id": 0, "items": [item("IT0002", MS(2026, 12, 25)), item("IT0003", MS(2026, 12, 25))]}, headers=h)
    assert card("IT0002")["site"]["stage"]["code"] == "info" and card("IT0003")["site"]["stage"]["code"] == "info_term"
    assert "10.11.2026" in card("IT0003")["site"]["stage"]["evidence"]
    # a later import with a changed date moves the task without a new synchronisation (the date is kept with what was read from the site)
    late[col] = ""
    early[col] = "10.11.2026"
    admin.post("/api/import?dry=0&due_from=2026-12-01&due_to=2026-12-31&ai=0&f_dept=0&f_window=0", files={"file": ("e.xlsx", export([early, late]))})
    assert card("IT0002")["site"]["stage"]["code"] == "info_term" and card("IT0003")["site"]["stage"]["code"] == "info"
