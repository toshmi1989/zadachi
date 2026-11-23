"""Several people press «Синхронизировать» at once: every task is read by one of them. And what an answer in the approval chain does to a periodic task."""
import calendar
import datetime

import pytest
from fastapi.testclient import TestClient

from app import ijro
from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"ПҚ-9{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", "Share Person", "Бажарилмаган", f"SH000{i}"] for i in range(4)]
MS = lambda y, m, d: calendar.timegm(datetime.date(y, m, d).timetuple()) * 1000


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        assert c.put("/api/sync/settings", json={"auto_apply": True}).status_code == 200
        yield c


def key_of(admin, name):
    return {"authorization": "Bearer " + admin.post("/api/sync/keys", json={"name": name}).json()["key"]}


def test_two_people_do_not_read_the_same_tasks(admin):
    a, b = key_of(admin, "A"), key_of(admin, "B")
    anon = TestClient(app)
    ja, jb = anon.get("/api/sync/job", headers=a).json(), anon.get("/api/sync/job", headers=b).json()
    codes = [x["code"] for x in ja["items"] if x["code"].startswith("SH")][:4]
    assert len(codes) == 4 and ja["parallel"] == 3
    ga = anon.post("/api/sync/claim", json={"run_id": ja["run_id"], "codes": codes[:2]}, headers=a).json()
    assert ga == {"granted": codes[:2], "taken": []}
    gb = anon.post("/api/sync/claim", json={"run_id": jb["run_id"], "codes": codes}, headers=b).json()
    assert gb["granted"] == codes[2:] and gb["taken"] == codes[:2]                       # the first two are A's: B gets the other two
    ga2 = anon.post("/api/sync/claim", json={"run_id": ja["run_id"], "codes": codes[:2]}, headers=a).json()
    assert ga2["granted"] == codes[:2]                                                    # one's own claim is never in one's way
    # what B has read a moment ago is not read by A again; what A reads itself it may read again
    assert anon.post("/api/sync/ingest", json={"run_id": jb["run_id"], "items": [{"code": codes[2], "found": True, "section": "president", "recipient_id": "x", "status": 0, "is_done": False, "answers": []}]}, headers=b).status_code == 200
    gc = anon.post("/api/sync/claim", json={"run_id": ja["run_id"], "codes": [codes[2]]}, headers=a).json()
    assert gc == {"granted": [], "taken": [codes[2]]}
    gd = anon.post("/api/sync/claim", json={"run_id": jb["run_id"], "codes": [codes[2]]}, headers=b).json()
    assert gd["granted"] == [codes[2]]
    # a claim runs out: a person who closed the tab does not hold the tasks for ever
    old = ijro.CLAIM_MINUTES
    ijro.CLAIM_MINUTES = -1
    try:
        assert anon.post("/api/sync/claim", json={"run_id": jb["run_id"], "codes": codes[:2]}, headers=b).json()["granted"] == codes[:2]
    finally:
        ijro.CLAIM_MINUTES = old
    # a bad request is refused, a key is needed
    assert anon.post("/api/sync/claim", json={"run_id": "x", "codes": "y"}, headers=a).status_code == 400
    assert anon.post("/api/sync/claim", json={"run_id": 1, "codes": []}).status_code == 401


def test_the_parallelism_is_a_setting(admin):
    assert "sync_parallel" in str(admin.get("/api/settings").json()["sync"])                      # it is on the Settings page with its explanation
    assert admin.put("/api/settings", json={"sync": {"sync_parallel": "5"}}).status_code == 200
    assert TestClient(app).get("/api/sync/job", headers=key_of(admin, "P")).json()["parallel"] == 5
    assert admin.put("/api/settings", json={"sync": {"sync_parallel": "9"}}).status_code == 400
    assert admin.put("/api/settings", json={"sync": {"sync_parallel": "3"}}).status_code == 200


def test_a_periodic_task_in_the_approval_chain_moves_to_in_progress_and_the_summary_counts_it(admin):
    anon, h = TestClient(app), key_of(admin, "C")
    tid = [t for t in admin.get("/api/tasks?q=SH0001&size=5").json()["items"]][0]
    assert tid["status"] == "todo"
    due = MS(2026, 12, 31)
    periods = [{"order": 1, "status": 10, "recipient_status": 20, "due_ms": MS(2026, 11, 30)}, {"order": 2, "status": 0, "recipient_status": 0, "due_ms": due}]
    snap = {"code": "SH0001", "found": True, "section": "president", "recipient_id": "r1", "status": 0, "is_done": False, "repeatable": True, "periods": periods, "answers_loaded": True,
            "answers": [{"sender_type": 10, "state": 1, "at_ms": MS(2026, 11, 20), "active": True, "text": "Ответ", "org": "Исполнитель", "pd": due}]}
    r = anon.post("/api/sync/ingest", json={"run_id": 0, "items": [snap]}, headers=h).json()
    assert r["moved"] == {"done": 0, "progress": 1, "due": 0}, r
    assert admin.get(f"/api/tasks/{tid['id']}").json()["status"] == "progress"
    # an earlier period answered, the current one has no answer: the task stays as it was
    t2 = admin.get("/api/tasks?q=SH0002&size=5").json()["items"][0]
    snap2 = dict(snap, code="SH0002", answers=[{"sender_type": 10, "state": 1, "at_ms": MS(2026, 10, 20), "active": True, "text": "Ответ", "org": "", "pd": MS(2026, 11, 30)}])
    r2 = anon.post("/api/sync/ingest", json={"run_id": 0, "items": [snap2]}, headers=h).json()
    assert r2["moved"]["progress"] == 0 and admin.get(f"/api/tasks/{t2['id']}").json()["status"] == "todo"
