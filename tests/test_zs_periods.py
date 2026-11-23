"""A periodic task has a row for every period in the site's list; each period is its own task (its month, its status). A load never moves a period into another month."""
import calendar
import datetime

import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_site_import import HEAD, PRIMARY, export, post, row

EXT = next(i for i, h in enumerate(HEAD) if str(h).startswith("Муддат узайтириш сони"))
FLAGS = "&f_dept=0&f_exec=0&f_kind=0&f_window=0&overwrite=1"
MS = lambda y, m, d: calendar.timegm(datetime.date(y, m, d).timetuple()) * 1000


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'PR000%' OR site_code LIKE 'PR000%'"); d.execute("DELETE FROM users WHERE name='Periodic Person'"); d.commit(); d.close()


def mine(admin, code):
    return sorted(admin.get(f"/api/tasks?q={code}&size=50&status=all").json()["items"], key=lambda t: t["due"] or "")


def load(admin, rows, replace=0, **kw):
    r = post(admin, rows, dry=0, extra=FLAGS + f"&replace={replace}&confirm=1", **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_every_period_of_a_periodic_task_is_its_own_task(admin):
    r = load(admin, [row("PR0001", PRIMARY, "Periodic Person", "25.11.2026", state="Бажарилган"), row("PR0001", PRIMARY, "Periodic Person", "25.12.2026")])
    assert r["created"] == 2
    t = mine(admin, "PR0001")
    assert [x["due"] for x in t] == ["2026-11-25", "2026-12-25"] and {x["code"] for x in t} == {"PR0001"}      # one code, two tasks, the site's code is shown
    assert [x["status"] for x in t] == ["done", "todo"]
    again = load(admin, [row("PR0001", PRIMARY, "Periodic Person", "25.11.2026", state="Бажарилган"), row("PR0001", PRIMARY, "Periodic Person", "25.12.2026")])
    assert again["created"] == 0 and again["unchanged"] == 2                                                     # the same file again changes nothing


def test_a_load_of_other_months_adds_periods_and_leaves_december_alone(admin):
    before = admin.get("/api/dashboard?period=2026-12").json()["totals"]
    r = load(admin, [row("PR0001", PRIMARY, "Periodic Person", "25.01.2027"), row("PR0001", PRIMARY, "Periodic Person", "25.02.2027")])
    assert r["created"] == 2 and len(mine(admin, "PR0001")) == 4
    assert admin.get("/api/dashboard?period=2026-12").json()["totals"] == before                                  # December has not moved
    assert admin.get("/api/dashboard?period=2027").json()["totals"]["total"] >= 2


def test_one_row_with_a_new_term_is_the_same_task_unless_the_site_says_it_is_periodic(admin):
    load(admin, [row("PR0002", PRIMARY, "Periodic Person", "25.12.2026")])
    load(admin, [row("PR0002", PRIMARY, "Periodic Person", "25.01.2027")])                                       # an ordinary task whose term moved
    t = mine(admin, "PR0002")
    assert len(t) == 1 and t[0]["due"] == "2027-01-25"
    # the site's own list of the periods (the synchronisation) says that PR0003 is periodic: the next period is a new task
    load(admin, [row("PR0003", PRIMARY, "Periodic Person", "25.12.2026")])
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "per"}).json()["key"]}
    periods = [{"order": 1, "status": 10, "recipient_status": 20, "due_ms": MS(2026, 12, 25)}, {"order": 2, "status": 0, "recipient_status": 0, "due_ms": MS(2027, 1, 25)}]
    assert TestClient(app).post("/api/sync/ingest", json={"run_id": 0, "items": [{"code": "PR0003", "found": True, "section": "president", "recipient_id": "r", "status": 0, "is_done": False,
                                                                                   "repeatable": True, "periods": periods, "answers": []}]}, headers=h).status_code == 200
    r = load(admin, [row("PR0003", PRIMARY, "Periodic Person", "25.01.2027")])
    assert r["created"] == 1 and [x["due"] for x in mine(admin, "PR0003")] == ["2026-12-25", "2027-01-25"]


def test_an_extension_moves_the_term_of_the_same_task(admin):
    load(admin, [row("PR0004", PRIMARY, "Periodic Person", "25.12.2026")])
    moved = row("PR0004", PRIMARY, "Periodic Person", "25.02.2027")
    moved[EXT] = "1"
    r = load(admin, [moved])
    t = mine(admin, "PR0004")
    assert r["created"] == 0 and len(t) == 1 and t[0]["due"] == "2027-02-25"


def test_the_synchronisation_reads_the_code_once_and_every_period_gets_it(admin):
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "per2"}).json()["key"]}
    anon = TestClient(app)
    job = anon.get("/api/sync/job", headers=h).json()
    assert [x["code"] for x in job["items"]].count("PR0001") == 1                                                # four tasks, one read
    periods = [{"order": i + 1, "status": 0, "recipient_status": 20 if i < 2 else 0, "due_ms": MS(*d)} for i, d in enumerate([(2026, 11, 25), (2026, 12, 25), (2027, 1, 25), (2027, 2, 25)])]
    snap = {"code": "PR0001", "found": True, "section": "president", "recipient_id": "r1", "status": 0, "is_done": False, "repeatable": True, "periods": periods, "answers": []}
    out = anon.post("/api/sync/ingest", json={"run_id": job["run_id"], "items": [snap]}, headers=h).json()
    assert out["stored"] == 4                                                                                     # the four periods
    cards = [admin.get(f"/api/tasks/{t['id']}").json() for t in mine(admin, "PR0001")]
    labels = [c["site"]["label"] for c in cards]
    assert all("Период" in x or "Выполнена" in x for x in labels) and len(set(labels)) >= 2                       # each period is judged by its own term
    assert [c["status"] for c in cards][:2] == ["done", "done"]                                                   # the December period is done on the site: our December task follows it


def test_a_replacing_load_keeps_the_other_periods_of_a_code_it_contains(admin):
    r = load(admin, [row("PR0001", PRIMARY, "Periodic Person", "25.03.2027")], replace=1)
    assert r["absent_tasks"]["taken_off"] == 0 or "PR0001" not in str(r["absent_tasks"]["sample"])
    assert all(x["status"] != "gone" for x in mine(admin, "PR0001"))
