"""Three groups of tasks: Асосий ижрочи (main), Ҳамижрочи (co) and ВМ топшириқлари (the Cabinet's kinds other than «Қарор (Янги)»): each has its own load, its own dashboard and its own lists."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_site_import import PRIMARY, export, post, row

FLAGS = "&f_dept=0&f_exec=0&f_kind=0&f_window=0&overwrite=1"
OTHER_EXEC = "Таълим ва илм-фан вазирлиги"
ROWS = [row("SC0001", PRIMARY, "Scope Person", "25.12.2026"),
        row("SC0002", PRIMARY, "Scope Person", "25.12.2026", role="Ҳамижрочи", executor=OTHER_EXEC),
        row("SC0003", PRIMARY, "Scope Person", "25.12.2026", kind="Бош вазир топшириқлари")]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'SC000%' OR site_code LIKE 'SC000%'"); d.execute("DELETE FROM users WHERE name='Scope Person'"); d.commit(); d.close()


def load(admin, rows, scope, replace=0, dry=0):
    r = post(admin, rows, dry=dry, extra=FLAGS + f"&replace={replace}&confirm=1&scope={scope}")
    assert r.status_code == 200, r.text
    return r.json()


def codes(admin, scope, q="SC000"):
    return sorted(t["code"] for t in admin.get(f"/api/tasks?q={q}&scope={scope}&size=50&status=all").json()["items"])


def test_every_load_takes_only_its_own_group(admin):
    m = load(admin, ROWS, "main")
    assert m["created"] == 1 and m["site"]["skipped"]["coexec"] == 1 and m["site"]["skipped"]["doc_type"] == 1       # the other two groups are left for their own loads
    c = load(admin, ROWS, "co")
    assert c["created"] == 1 and c["site"]["skipped"]["doc_type"] == 1 and c["site"]["skipped"]["main_rows"] == 1
    v = load(admin, ROWS, "vm")
    assert v["created"] == 1 and v["site"]["skipped"]["coexec"] == 1
    assert codes(admin, "main") == ["SC0001"] and codes(admin, "co") == ["SC0002"] and codes(admin, "vm") == ["SC0003"]
    assert codes(admin, "") == ["SC0001"]                                                                           # no group: the main one, as before
    vm = admin.get("/api/tasks?q=SC0003&scope=vm").json()["items"][0]
    assert vm["kind"] == "Бош вазир топшириқлари"                                                                  # the kind of the Cabinet's list is kept as it is
    assert admin.post("/api/import?dry=1&scope=zz", files={"file": ("e.xlsx", export(ROWS))}).status_code == 400


def test_the_dashboard_of_a_group_counts_that_group_only(admin):
    for sc in ("main", "co", "vm"):
        d = admin.get(f"/api/dashboard?scope={sc}").json()
        assert d["scope"] == sc
        done = admin.get(f"/api/tasks?scope={sc}&status=done&size=1").json()["total"]
        opn = admin.get(f"/api/tasks?scope={sc}&status=open&size=1").json()["total"]
        assert d["totals"]["done"] == done and d["totals"]["open"] == opn, sc                                       # the numbers are the lists of the same group
    assert admin.get("/api/dashboard?scope=co").json()["totals"]["open"] >= 1
    assert "Бош вазир топшириқлари" in admin.get("/api/dashboard?scope=vm").json()["kinds"]
    assert admin.get("/api/dashboard?scope=zz").status_code == 400


def test_a_load_of_one_group_never_touches_the_others(admin):
    # replacing the main group with a file that has no SC0001: the co and vm tasks are not even candidates
    r = load(admin, [row("SC0009", PRIMARY, "Scope Person", "25.12.2026")], "main", replace=1, dry=1)
    sample = {x["code"] for x in r["absent_tasks"]["sample"]}
    assert "SC0001" in sample and "SC0002" not in sample and "SC0003" not in sample
    r2 = load(admin, [row("SC0009", PRIMARY, "Scope Person", "25.12.2026", role="Ҳамижрочи", executor=OTHER_EXEC)], "co", replace=1, dry=1)
    sample2 = {x["code"] for x in r2["absent_tasks"]["sample"]}
    assert "SC0002" in sample2 and "SC0001" not in sample2 and "SC0003" not in sample2


def test_the_same_code_can_be_in_two_groups(admin):
    rows = [row("SC0005", PRIMARY, "Scope Person", "25.12.2026"), row("SC0005", PRIMARY, "Scope Person", "25.12.2026", role="Ҳамижрочи", executor=OTHER_EXEC)]
    load(admin, rows, "main"); load(admin, rows, "co")
    assert codes(admin, "main", "SC0005") == ["SC0005"] and codes(admin, "co", "SC0005") == ["SC0005"]            # one task in each, the site's code shown
    c = connect()
    assert sorted(r[0] for r in c.execute("SELECT code FROM tasks WHERE site_code='SC0005' OR code='SC0005'")) == ["SC0005", "SC0005~co"]     # unique inside
    c.close()
    again = load(admin, rows, "co")
    assert again["created"] == 0                                                                                    # a second load finds its task


def test_the_synchronisation_reads_the_groups_that_are_chosen(admin):
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "grp"}).json()["key"]}
    anon = TestClient(app)
    admin.put("/api/settings", json={"sync": {"history_groups": "all"}})
    got = {x["code"]: x["section"] for x in anon.get("/api/sync/job", headers=h).json()["items"]}
    assert {"SC0001", "SC0002", "SC0003"} <= set(got) and got["SC0003"] == "government"                           # the Cabinet's list is where to look for the vm tasks
    admin.put("/api/settings", json={"sync": {"history_groups": "main"}})
    got = {x["code"] for x in anon.get("/api/sync/job", headers=h).json()["items"]}
    assert "SC0001" in got and "SC0002" not in got and "SC0003" not in got
    admin.put("/api/settings", json={"sync": {"history_groups": "all"}})


def test_the_report_names_the_group(admin):
    for sc, word in (("co", "Ҳамижрочи"), ("vm", "ВМ топшириқлари")):
        r = admin.get(f"/api/report.xlsx?scope={sc}")
        assert r.status_code == 200 and word in openpyxl.load_workbook(io.BytesIO(r.content)).active["A1"].value
    assert "(" not in openpyxl.load_workbook(io.BytesIO(admin.get("/api/report.xlsx").content)).active["A1"].value
