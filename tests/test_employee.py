"""An employee sees their own tasks and changes the status of them, nothing more."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from test_app import xlsx

ROWS = [[i + 1, "Қарор", f"ЭМ-{i} \n 01.01.2026", f"{i}-банд\nТекст {i}", "31.12.2026", "2026-12-01", who, "Бажарилмаган", f"EM000{i}"]
        for i, who in enumerate(["Employee Emil", "Employee Emil", "Other Olga", ""])]


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        assert c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))}).status_code == 200
        c.put("/api/settings", json={"users_tasks": "own"})        # other test modules share this database and change the setting
        yield c


def login_as(admin, login):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == login][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    c = TestClient(app)
    assert c.post("/login", data={"login": login, "password": pw}, follow_redirects=False).status_code == 303
    c.uid = uid
    return c


@pytest.fixture(scope="module")
def emil(admin):
    return login_as(admin, "employee.e")


def tid(client, code):
    return client.get(f"/api/tasks?q={code}").json()["items"][0]["id"]


def test_default_is_own_tasks_only(admin, emil):
    from app import db
    assert db.DEFAULT_SETTINGS["users_tasks"] == "own"                                         # the default for a new site (and applied once to an existing one)
    got = emil.get("/api/tasks?size=200&q=EM000").json()
    assert {t["code"] for t in got["items"]} == {"EM0000", "EM0001"} and all(t["can_edit"] for t in got["items"])
    other = tid(admin, "EM0002")
    assert emil.get(f"/api/tasks/{other}").status_code == 404                                  # somebody else's task does not exist for them
    assert emil.get("/api/tasks?assignee=0").json()["total"] == 0                              # nor can they ask for the unassigned ones
    assert "EM0002" not in emil.get("/api/tasks.xlsx?q=EM000").text


def test_employee_changes_the_status_of_own_task(admin, emil):
    t = tid(emil, "EM0000")
    r = emil.patch(f"/api/tasks/{t}", json={"status": "progress"})
    assert r.status_code == 200 and r.json()["status"] == "progress" and r.json()["changed"] and r.json()["can_edit"]
    r = emil.patch(f"/api/tasks/{t}", json={"status": "done"}).json()
    assert r["status"] == "done" and r["done_at"]
    ev = r["events"][0]
    assert ev["field"] == "status" and ev["new"] == "Выполнено" and ev["who"] == "Employee Emil"      # the history names who did it
    assert emil.patch(f"/api/tasks/{t}", json={"status": "todo"}).json()["done_at"] is None            # and it can be taken back
    assert emil.patch(f"/api/tasks/{t}", json={"status": "todo"}).json()["changed"] is False
    # the administrator sees it as an edited task: the next Excel import will not overwrite it
    assert admin.get(f"/api/tasks/{t}").json()["edited"] is True


def test_employee_cannot_do_anything_else(admin, emil):
    t = tid(emil, "EM0001")
    for body in ({"assignee_id": None}, {"close_date": "2026-12-31"}, {"status": "done", "assignee_id": emil.uid}, {"status": "done", "close_date": "2026-12-02"}):
        assert emil.patch(f"/api/tasks/{t}", json=body).status_code == 403, body
    assert emil.patch(f"/api/tasks/{t}", json={"status": "info"}).status_code == 403                  # "for information" is the administrator's decision
    assert emil.patch(f"/api/tasks/{t}", json={"status": "bogus"}).status_code == 403
    assert emil.patch(f"/api/tasks/{t}", json={}).status_code == 400
    assert admin.get(f"/api/tasks/{t}").json()["status"] == "todo"                                    # nothing of it got through
    assert emil.post("/api/tasks/bulk", json={"ids": [t], "status": "done"}).status_code == 403
    admin.patch(f"/api/tasks/{t}", json={"status": "info"})
    assert emil.patch(f"/api/tasks/{t}", json={"status": "done"}).status_code == 403                  # a task taken "for information" stays with the administrator
    admin.patch(f"/api/tasks/{t}", json={"status": "todo"})


def test_somebody_elses_task_is_out_of_reach(admin, emil):
    other, free = tid(admin, "EM0002"), tid(admin, "EM0003")
    for t in (other, free):
        assert emil.patch(f"/api/tasks/{t}", json={"status": "done"}).status_code == 404               # scope "own": it does not exist for them
    assert admin.get(f"/api/tasks/{other}").json()["status"] == "todo"
    admin.put("/api/settings", json={"users_tasks": "all"})                                           # they may read everything, still edit only their own
    try:
        assert emil.get(f"/api/tasks/{other}").status_code == 200
        r = emil.get(f"/api/tasks?q=EM000&size=200").json()["items"]
        assert {t["code"]: t["can_edit"] for t in r} == {"EM0000": True, "EM0001": True, "EM0002": False, "EM0003": False}
        assert emil.patch(f"/api/tasks/{other}", json={"status": "done"}).status_code == 403
        assert "site" not in emil.get(f"/api/tasks/{other}").json()
    finally:
        admin.put("/api/settings", json={"users_tasks": "own"})


def test_no_task_list_no_editing(admin, emil):
    t = tid(emil, "EM0000")
    admin.put("/api/settings", json={"users_tasks": "none"})
    try:
        assert emil.get("/api/tasks").status_code == 403
        assert emil.patch(f"/api/tasks/{t}", json={"status": "done"}).status_code == 403
    finally:
        admin.put("/api/settings", json={"users_tasks": "own"})


def test_administrator_is_unchanged(admin):
    t = tid(admin, "EM0003")
    assert admin.patch(f"/api/tasks/{t}", json={"status": "info", "close_date": "2026-12-05"}).status_code == 200
    assert admin.patch(f"/api/tasks/{t}", json={"status": "todo"}).status_code == 200


def test_the_history_and_the_audit_name_the_employee(admin, emil):
    t = tid(emil, "EM0000")
    emil.patch(f"/api/tasks/{t}", json={"status": "progress"})
    last = [a for a in admin.get("/api/audit").json()["items"] if a["action"] == "task.update"][0]
    assert last["who"] == "Employee Emil" and '"by_role": "user"' in last["details"]
