"""Server side of the synchronisation with ijro (the browser collector has its own test in tests/ijro)."""
import pytest
from fastapi.testclient import TestClient

from app import ijro
from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", "Sync Person", "Бажарилмаган", f"SY000{i}"] for i in range(3)]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        yield c


@pytest.fixture(scope="module")
def key(admin):
    return admin.post("/api/sync/keys", json={"name": "test"}).json()["key"]


def bearer(k):
    return {"authorization": "Bearer " + k}


def item(code, **kw):
    return {"code": code, "found": True, "section": "president", "recipient_id": "rid-" + code, "status": 20, "is_done": True, "answers": [], **kw}


def test_key_is_shown_once_and_only_its_hash_is_stored(admin, key):
    assert key.startswith("zk_") and len(key) > 40
    import sqlite3
    from app import db
    c = sqlite3.connect(db.DB_PATH)
    stored = [r[0] for r in c.execute("SELECT key_hash FROM sync_keys")]
    assert key not in stored and all(len(h) == 64 for h in stored)
    assert key not in str(admin.get("/api/sync/keys").json())


def test_endpoints_need_the_right_credentials(admin, key):
    anon = TestClient(app)
    assert anon.get("/api/sync/job").status_code == 401
    assert anon.get("/api/sync/job", headers=bearer("zk_wrong")).status_code == 401
    assert anon.get("/api/sync/job", headers={"authorization": "Basic abc"}).status_code == 401
    assert anon.get("/api/sync/job", headers=bearer(key)).status_code == 200
    assert anon.post("/api/sync/ingest", json={"items": []}, headers=bearer(key)).status_code == 400       # an empty packet is refused
    # a key does not open anything else
    for path in ("/api/tasks", "/api/users", "/api/sync/review", "/api/dashboard"):
        assert anon.get(path, headers=bearer(key)).status_code == 401, path
    # the session of an administrator is not a key either
    assert admin.get("/api/sync/job").status_code == 401


def test_ordinary_user_cannot_touch_sync(admin):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "sync.p"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    u = TestClient(app)
    u.post("/login", data={"login": "sync.p", "password": pw})
    for method, path in (("get", "/api/sync/review"), ("get", "/api/sync/keys"), ("post", "/api/sync/keys"), ("post", "/api/sync/apply"), ("put", "/api/sync/settings")):
        assert getattr(u, method)(path).status_code == 403, path
    tid = admin.get("/api/tasks?q=SY0000").json()["items"][0]["id"]
    assert "site" not in u.get(f"/api/tasks/{tid}").json()                                                   # what the site says is for administrators


def test_ingest_validates_and_never_creates_tasks(admin, key):
    anon = TestClient(app)
    ok = anon.post("/api/sync/ingest", json={"items": [item("SY0000"), item("NOPE000")]}, headers=bearer(key)).json()
    assert ok == {"stored": 1, "found": 1}
    assert anon.post("/api/sync/ingest", json={"items": [item("SY0000")] * 201}, headers=bearer(key)).status_code == 400
    assert anon.post("/api/sync/ingest", content=b"not json", headers=bearer(key)).status_code == 400
    assert anon.post("/api/sync/ingest", content=b"x" * 2_100_000, headers=bearer(key)).status_code == 413
    weird = item("SY0001", section="nowhere", status="20", is_done=1, answers=[{"text": "t" * 5000, "sender_type": "x", "state": None}, "junk", 5])
    assert anon.post("/api/sync/ingest", json={"items": [weird]}, headers=bearer(key)).json()["stored"] == 1
    s = admin.get(f"/api/tasks/{admin.get('/api/tasks?q=SY0001').json()['items'][0]['id']}").json()["site"]
    assert not s["found"] and s["answers"] == []                                                              # unknown section: treated as not found
    big = item("SY0002", answers=[{"text": "t" * 5000, "sender_type": 10, "state": 1, "at_ms": 1764000000000}])
    anon.post("/api/sync/ingest", json={"items": [big]}, headers=bearer(key))
    s = admin.get(f"/api/tasks/{admin.get('/api/tasks?q=SY0002').json()['items'][0]['id']}").json()["site"]
    assert len(s["answers"][0]["text"]) == ijro.MAX_TEXT and s["answers"][0]["type"] == "Ответ исполнителя"


def test_revoked_key_stops_working(admin):
    k = admin.post("/api/sync/keys", json={"name": "temp"}).json()["key"]
    anon = TestClient(app)
    assert anon.get("/api/sync/job", headers=bearer(k)).status_code == 200
    kid = [x for x in admin.get("/api/sync/keys").json()["items"] if x["name"] == "temp"][0]["id"]
    assert admin.delete(f"/api/sync/keys/{kid}").status_code == 200
    assert anon.get("/api/sync/job", headers=bearer(k)).status_code == 401
    assert admin.delete("/api/sync/keys/99999").status_code == 404


def test_card_template_is_validated(admin):
    assert admin.put("/api/sync/settings", json={"card_tpl": "https://evil.example/{id}"}).status_code == 400
    assert admin.put("/api/sync/settings", json={"card_tpl": "javascript:alert(1)"}).status_code == 400
    assert admin.put("/api/sync/settings", json={"card_tpl": "https://edo.ijro.uz/x/{section_path}"}).status_code == 400   # no {id}
    assert admin.put("/api/sync/settings", json={"card_tpl": "https://edo.ijro.uz/a/{section_path}/t/{id}"}).status_code == 200
    assert admin.put("/api/sync/settings", json={"card_tpl": ""}).status_code == 200


def test_apply_respects_info_and_unknown(admin):
    import sqlite3
    from app import db
    tid = admin.get("/api/tasks?q=SY0000").json()["items"][0]["id"]
    c = sqlite3.connect(db.DB_PATH)
    c.execute("UPDATE tasks SET status='info' WHERE id=?", (tid,)); c.commit(); c.close()
    assert admin.post("/api/sync/apply", json={"task_ids": [tid]}).json() == {"applied": 0, "skipped": 1}      # "for information" is never overwritten
    assert admin.post("/api/sync/apply", json={"task_ids": []}).status_code == 400
    assert admin.post("/api/sync/apply", json={"task_ids": ["1"]}).status_code == 400


def test_classification_table():
    def snap(**kw):
        base = {"found": 1, "site_status": 0, "is_done": 0, "repeatable": 0, "periods": "[]"}
        return {**base, **kw}
    assert ijro.classify(snap(site_status=20, is_done=1))["status"] == "done"
    assert ijro.classify(snap(site_status=21, is_done=1))["label"] == "Выполнена с опозданием"
    assert ijro.classify(snap(site_status=20, is_done=0))["status"] is None                                    # a status without is_done is not trusted
    assert ijro.classify(snap(site_status=2))["status"] == "progress" and ijro.classify(snap(site_status=0))["status"] == "todo"
    for st in (1, 3, 4, -1):
        r = ijro.classify(snap(site_status=st))
        assert r["status"] is None and not r["known"]
    import json
    from datetime import datetime, timezone
    DUES = [(2026, 3, 31), (2026, 6, 30), (2026, 9, 30), (2026, 12, 31)]
    ps = lambda *rs: json.dumps([{"order": i + 1, "recipient_status": r, "due_ms": int(datetime(*DUES[i], tzinfo=timezone.utc).timestamp() * 1000)} for i, r in enumerate(rs)])
    # periods due 2026-03-31, 2026-06-30, 2026-09-30, 2026-12-31 ...
    four = ps(20, 20, 20, 0)
    assert ijro.classify(snap(repeatable=1, periods=four), "2026-12-31")["status"] is None             # the period of our deadline is open
    assert ijro.classify(snap(repeatable=1, periods=four), "2026-09-30")["status"] == "done"            # ours is an earlier, finished period
    assert "Период 4 из 4" in ijro.classify(snap(repeatable=1, periods=four), "2026-12-31")["label"]
    assert ijro.classify(snap(repeatable=1, periods=ps(20, 20, 20, 20)))["status"] == "done"
    assert ijro.classify(snap(found=0))["status"] is None
