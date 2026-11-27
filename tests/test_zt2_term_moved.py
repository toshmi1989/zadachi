"""The official term of an open task moves to another month (November -> December): November is done, December carries the open work (two records, one code)."""
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_site_import import PRIMARY, row
from test_zs_periods import EXT, MS, load, mine


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'TM000%' OR site_code LIKE 'TM000%'"); d.execute("DELETE FROM users WHERE name='Term Person'"); d.commit(); d.close()


def test_an_import_that_moves_the_term_to_another_month_closes_the_old_month(admin):
    load(admin, [row("TM0001", PRIMARY, "Term Person", "25.11.2026")])
    r = load(admin, [row("TM0001", PRIMARY, "Term Person", "25.12.2026")])
    t = mine(admin, "TM0001")
    assert r["term_moved"] == 1 and [(x["due"], x["status"]) for x in t] == [("2026-11-25", "done"), ("2026-12-25", "todo")]
    assert t[0]["code"] == t[1]["code"] == "TM0001"                                                              # one code shown at two terms, like a periodic task
    nov, dec = (admin.get(f"/api/dashboard?by=due&period={m}").json() for m in ("2026-11", "2026-12"))
    n = lambda d: sum(v["done"] + v["open"] for v in d["none"]["months"].values()) if d["none"] else 0
    cells = lambda d, k: [x["months"].get(k) for x in ([d["none"]] if d["none"] else []) + d["rows"] if x["months"].get(k)]
    assert any(c["done"] >= 1 for c in cells(nov, "2026-11")) and any(c["open"] >= 1 for c in cells(dec, "2026-12"))   # November counts it done, December not done
    again = load(admin, [row("TM0001", PRIMARY, "Term Person", "25.12.2026")])
    assert again["term_moved"] == 0 and again["created"] == 0 and len(mine(admin, "TM0001")) == 2                     # the same file again changes nothing
    old = admin.get(f"/api/tasks/{t[0]['id']}").json()
    assert any(e["field"] == "term" for e in old["events"]) and old["status"] == "done"                                # the history says why
    conn = connect()
    assert conn.execute("SELECT status_manual FROM tasks WHERE id=?", (t[0]["id"],)).fetchone()[0] == 1               # the site does not reopen the closed month
    conn.close()


def test_a_move_inside_the_month_or_of_a_done_task_changes_the_same_record(admin):
    load(admin, [row("TM0002", PRIMARY, "Term Person", "10.11.2026")])
    r = load(admin, [row("TM0002", PRIMARY, "Term Person", "28.11.2026")])
    assert r["term_moved"] == 0 and [x["due"] for x in mine(admin, "TM0002")] == ["2026-11-28"]                      # same month: the day only moves
    load(admin, [row("TM0003", PRIMARY, "Term Person", "10.11.2026", state="Бажарилган")])
    r = load(admin, [row("TM0003", PRIMARY, "Term Person", "10.12.2026", state="Бажарилган")])
    assert r["term_moved"] == 0 and len(mine(admin, "TM0003")) == 1                                                  # a done task is not split


def test_an_extension_in_the_file_closes_the_old_month_too(admin):
    load(admin, [row("TM0004", PRIMARY, "Term Person", "25.11.2026")])
    moved = row("TM0004", PRIMARY, "Term Person", "25.01.2027")
    moved[EXT] = "1"
    r = load(admin, [moved])
    assert r["term_moved"] == 1 and [(x["due"], x["status"]) for x in mine(admin, "TM0004")] == [("2026-11-25", "done"), ("2027-01-25", "todo")]


def test_the_synchronisation_sees_the_term_move_between_two_checks(admin):
    load(admin, [row("TM0005", PRIMARY, "Term Person", "25.11.2026")])
    h = {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": "tm"}).json()["key"]}
    anon = TestClient(app)

    def ingest(due):
        return anon.post("/api/sync/ingest", json={"run_id": 0, "items": [{"code": "TM0005", "found": True, "section": "president", "recipient_id": "r", "status": 0, "is_done": False,
                                                                           "repeatable": False, "due_ms": MS(*due), "answers": []}]}, headers=h).json()
    assert ingest((2026, 11, 25))["term_split"] == 0                                                                # the first reading: nothing moved
    assert len(mine(admin, "TM0005")) == 1
    assert ingest((2026, 12, 25))["term_split"] == 1                                                                # the site moved the term to December
    t = mine(admin, "TM0005")
    assert [(x["due"], x["status"]) for x in t] == [("2026-11-25", "done"), ("2026-12-25", "todo")]
    assert ingest((2026, 12, 25))["term_split"] == 0 and len(mine(admin, "TM0005")) == 2                            # a repeated reading does not split again
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM ijro_snapshots WHERE task_id IN (?, ?)", (t[0]["id"], t[1]["id"])).fetchone()[0] == 2     # both have what was read from the site
    conn.close()
    # a periodic task on the site is never treated as a moved term
    load(admin, [row("TM0006", PRIMARY, "Term Person", "25.11.2026")])
    for due in ((2026, 11, 25), (2026, 12, 25)):
        out = anon.post("/api/sync/ingest", json={"run_id": 0, "items": [{"code": "TM0006", "found": True, "section": "president", "recipient_id": "r", "status": 0, "is_done": False,
                                                                          "repeatable": True, "due_ms": MS(*due), "periods": [], "answers": []}]}, headers=h).json()
        assert out["term_split"] == 0
    assert len(mine(admin, "TM0006")) == 1
