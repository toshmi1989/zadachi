"""The dashboard for a chosen year or month: the numbers are those of that period, and the lists behind them agree."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.db import connect
from app.main import app
from test_app import xlsx

DATA = [("2026-12-10", "Бажарилган"), ("2026-12-20", "Бажарилмаган"), ("2027-01-15", "Бажарилмаган"), ("2027-03-05", "Бажарилган"), ("2027-03-25", "Бажарилмаган"), ("2027-03-26", "Бажарилмаган")]
ROWS = [[i + 1, "Қарор", f"ПР-{i} \n 01.01.2026", f"{i}-банд\nPR{i}", "31.12.2027", close, "Period Person", state, f"PD000{i}"] for i, (close, state) in enumerate(DATA)]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c
        d = connect(); d.execute("DELETE FROM tasks WHERE code LIKE 'PD000%'"); d.execute("DELETE FROM users WHERE name='Period Person'"); d.commit(); d.close()


def test_the_period_narrows_every_number_and_matches_the_lists(admin):
    whole = admin.get("/api/dashboard").json()
    assert {"2026-12", "2027-01", "2027-03"} <= set(whole["periods"]) and whole["period"] == ""
    for period, lo, hi in (("2027", "2027-01-01", "2027-12-31"), ("2027-03", "2027-03-01", "2027-03-31"), ("2026", "2026-01-01", "2026-12-31")):
        d = admin.get(f"/api/dashboard?period={period}").json()
        assert d["period"] == period and set(d["periods"]) == set(whole["periods"])       # the choices stay the same whatever is chosen
        assert all(m.startswith(period) for m in d["months"])
        for status, key in (("done", "done"), ("open", "open")):
            n = admin.get(f"/api/tasks?status={status}&date_from={lo}&date_to={hi}&size=1").json()["total"]
            assert d["totals"][key] == n, (period, status)                                 # the tile opens exactly the list of the same period
        assert d["totals"]["done"] + d["totals"]["open"] + d["totals"]["info"] == d["totals"]["total"]
        assert d["total"]["sum"]["open"] == d["totals"]["open"]
    mar = admin.get("/api/dashboard?period=2027-03").json()["totals"]
    assert mar["done"] >= 1 and mar["open"] >= 2
    year = admin.get("/api/dashboard?period=2027").json()["totals"]
    assert year["total"] >= mar["total"] + 1                                               # the year has January too
    assert whole["totals"]["total"] >= year["total"]
    empty = admin.get("/api/dashboard?period=1999").json()
    assert empty["totals"]["total"] == 0 and empty["rows"] is not None


def test_the_period_is_checked_and_the_report_follows_it(admin):
    for bad in ("2027-13", "27", "2027-3", "abc", "2027-03-01"):
        assert admin.get(f"/api/dashboard?period={bad}").status_code == 400, bad
    r = admin.get("/api/report.xlsx?month=2027")
    assert r.status_code == 200 and "2027 йилга белгиланган" in openpyxl.load_workbook(io.BytesIO(r.content)).active["A1"].value
    m = admin.get("/api/report.xlsx?month=2027-03")
    assert "2027 йил март ойига белгиланган" in openpyxl.load_workbook(io.BytesIO(m.content)).active["A1"].value
    assert admin.get("/api/report.xlsx?month=2027-3").status_code == 400


def test_an_administrator_can_see_the_numbers_as_everybody_else_does(admin):
    """Others see only the closing date: a task without one is in no month and no year. The administrator's default also counts the official term."""
    assert admin.get("/api/dashboard?by=strict").json()["by"] == "strict" and admin.get("/api/dashboard?by=due").json()["by"] == "due" and admin.get("/api/dashboard").json()["by"] == "close"
    d = connect(); d.execute("DELETE FROM tasks WHERE code='PD9001'"); d.commit(); d.close()
    rows = [[1, "Қарор", "ПР-9 \n 01.01.2026", "9-банд\nPD9001", "20.08.2026", "", "Period Person", "Бажарилмаган", "PD9001"]]       # an official term, no closing date
    assert admin.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(rows))}).status_code == 200
    mine = lambda by: admin.get(f"/api/dashboard?period=2026-08&by={by}").json()["totals"]["total"]
    assert mine("close") >= mine("strict") + 1                      # the administrator's default counts it in August, the others' view does not
    d = connect(); d.execute("DELETE FROM tasks WHERE code='PD9001'"); d.commit(); d.close()
