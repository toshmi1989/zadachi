"""Proposals for the closing date: learned from the specialist's earlier dates, refined by a language model when a key is set."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app import closing
from app.db import connect
from app.main import app
from test_app import xlsx

A_WORDS = "аҳолининг фоиз кўрсаткич даражаси ўртача мақсадли"          # an indicator: the specialist closes it on the 15th of the month of the term
B_WORDS = "семинар тренинг ўтказиш ташкил этиш амалий машғулот"        # an event: the end of the month before
C_WORDS = "дарҳол тезкор маълумот юбориш жавоб тайёрлаш"              # at once


def hist_rows():
    rows = []
    for i in range(12):
        rows.append([i + 1, "Қарор", f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\n{A_WORDS} вариант{i}ааа", "25.12.2026", "2026-12-15", "Hist Person", "Бажарилмаган", f"HA{i:04d}"])
    for i in range(12):
        rows.append([20 + i, "Қарор", f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\n{B_WORDS} вариант{i}ббб", "25.12.2026", "2026-11-27", "Hist Person", "Бажарилмаган", f"HB{i:04d}"])
    for i in range(10):
        rows.append([40 + i, "Қарор", f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\n{C_WORDS} вариант{i}ввв", "25.12.2026", "2026-11-17", "Hist Person", "Бажарилмаган", f"HC{i:04d}"])
    return rows


NEW = [[100, "Қарор", "ПҚ-9 \n 01.01.2026", f"1-банд\n{A_WORDS} янгиаа", "31.12.2026", None, "Hist Person", "Бажарилмаган", "NA0001"],
       [101, "Қарор", "ПҚ-9 \n 01.01.2026", f"2-банд\n{B_WORDS} янгибб", "31.12.2026", None, "Hist Person", "Бажарилмаган", "NB0001"],
       [102, "Қарор", "ПҚ-9 \n 01.01.2026", f"3-банд\n{C_WORDS} янгивв", "31.12.2026", None, "Hist Person", "Бажарилмаган", "NC0001"]]


class Fake(BaseHTTPRequestHandler):
    seen: list = []
    mode = {"status": 200, "answer": {}}

    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        out = json.dumps({"error": {"message": "bad key"}} if Fake.mode["status"] != 200 else {"choices": [{"message": {"content": json.dumps(Fake.mode["answer"])}}]}).encode()
        self.send_response(Fake.mode["status"]); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


@pytest.fixture(scope="module")
def srv():
    s = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/v1"
    s.shutdown()


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        yield c
        cleanup(["HA%", "HB%", "HC%", "NA%", "NB%", "NC%", "NR%", "AI%"], ["Hist Person"])      # the database is shared with the other test modules


def cleanup(code_likes, people):
    c = connect()
    for like in code_likes:
        c.execute("DELETE FROM tasks WHERE code LIKE ?", (like,))
    for n in people:
        c.execute("DELETE FROM users WHERE name=?", (n,))
    c.execute("UPDATE settings SET value='' WHERE key IN ('ai_key','ai_base_url')")
    c.execute("UPDATE settings SET value='0' WHERE key='ai_enabled'")
    c.commit()
    c.close()


def mine(admin, *prefixes):
    return [t["id"] for p in prefixes for t in admin.get(f"/api/tasks?q={p}&size=200").json()["items"]]


def task(admin, code):
    return admin.get(f"/api/tasks?q={code}").json()["items"][0]


def test_too_little_history_says_so_and_proposes_nothing(admin):
    admin.post("/api/import?dry=0", files={"file": ("n.xlsx", xlsx(NEW))})
    r = admin.post("/api/closing/suggest", json={"ids": mine(admin, "NA0001", "NB0001", "NC0001")}).json()
    assert r["proposed"] == 0 and "не меньше 20" in r["errors"][0]
    assert task(admin, "NA0001")["close_date"] is None


def test_the_template_follows_similar_earlier_tasks(admin):
    admin.post("/api/import?dry=0", files={"file": ("h.xlsx", xlsx(hist_rows()))})
    r = admin.post("/api/closing/suggest", json={"ai": False, "ids": mine(admin, "NA0001", "NB0001", "NC0001")}).json()
    assert r["proposed"] == 3 and r["by_history"] == 3 and r["by_ai"] == 0 and r["history"] >= 34
    a, b, c = task(admin, "NA0001"), task(admin, "NB0001"), task(admin, "NC0001")
    assert a["close_date"] == "2026-12-15" and b["close_date"] == "2026-11-27"                  # 15th of the month of the term; end of the month before
    assert "2026-11-16" < c["close_date"] <= "2026-11-19"                                        # "at once": today + the usual lead
    assert a["close_src"] == "rule" and "Похожие прежние задачи" in a["close_note"] and b["close_date"] < b["due"] if b["due"] else True


def test_a_proposal_is_marked_until_a_person_decides(admin):
    assert {x["code"] for x in admin.get("/api/tasks?closing=proposed").json()["items"]} >= {"NA0001", "NB0001", "NC0001"}
    t = task(admin, "NA0001")
    assert admin.post("/api/closing/confirm", json={"ids": [t["id"]]}).json() == {"confirmed": 1}
    assert task(admin, "NA0001")["close_src"] == "" and "NA0001" not in {x["code"] for x in admin.get("/api/tasks?closing=proposed").json()["items"]}
    u = task(admin, "NB0001")
    admin.patch(f"/api/tasks/{u['id']}", json={"close_date": "2026-11-30"})                       # a person sets his own date: the marker goes
    assert task(admin, "NB0001")["close_src"] == "" and task(admin, "NB0001")["close_date"] == "2026-11-30"
    ev = admin.get(f"/api/tasks/{t['id']}").json()["events"]
    assert ev[0]["field"] == "close_date" and ev[0]["who"] == "Автоматически"
    assert admin.post("/api/closing/suggest", json={"ids": mine(admin, "NA0001", "NB0001", "NC0001")}).json()["asked"] == 0   # nothing of these is left without a date


def test_what_the_history_alone_gets_right_is_measured(admin):
    m = closing.Model(connect())
    own = [x for x in m.h if x["code"].startswith("H")]
    ok = sum(1 for x in own if m.vote(x["text"], x["doc"], skip_code=x["code"])[0] == x["tmpl"])
    assert len(own) == 34 and ok / len(own) > 0.9                                                # clean clusters: the method must find them
    assert closing.evaluate(connect())["accuracy"] is not None


def test_dates_are_never_in_the_past_or_after_the_term():
    from datetime import date
    t0 = date(2026, 11, 16)
    assert closing.date_from("0:15", date(2026, 12, 25), t0, 2) == date(2026, 12, 15)
    assert closing.date_from("-1:27", date(2026, 12, 25), t0, 2) == date(2026, 11, 27)
    assert closing.date_from("-1:10", date(2026, 12, 25), t0, 2) == date(2026, 11, 18)            # already past: "at once"
    assert closing.date_from("0:31", date(2026, 2, 20), date(2026, 1, 5), 2) == date(2026, 2, 20)  # never after the term (and 31 February does not exist)
    assert closing.date_from("asap", date(2026, 11, 17), t0, 3) == date(2026, 11, 17)


# ---------------------------------------------------------------- the language model
def test_the_key_is_never_given_back_and_the_settings_are_checked(admin, srv):
    assert admin.put("/api/ai", json={"key": "short"}).status_code == 400
    assert admin.put("/api/ai", json={"base_url": "ftp://x"}).status_code == 400
    assert admin.put("/api/ai", json={"model": "gpt 4; drop"}).status_code == 400
    r = admin.put("/api/ai", json={"enabled": True, "key": "sk-test-1234567890abcdef", "model": "gpt-4o-mini", "base_url": srv}).json()
    assert r["key_set"] and r["key_tail"] == "…cdef" and "sk-test" not in json.dumps(r) and "sk-test" not in json.dumps(admin.get("/api/ai").json())
    assert admin.put("/api/ai", json={"model": "gpt-4.1-mini"}).json()["key_set"]                  # a change without a key keeps the key


def test_the_model_chooses_a_template_and_we_compute_the_date(admin, srv):
    admin.post("/api/import?dry=0", files={"file": ("n2.xlsx", xlsx([
        [200, "Қарор", "ПҚ-9 \n 01.01.2026", f"1-банд\n{A_WORDS} аиаии", "31.12.2026", None, "Hist Person", "Бажарилмаган", "AI0001"],
        [201, "Қарор", "ПҚ-9 \n 01.01.2026", f"2-банд\n{B_WORDS} ббббб", "31.12.2026", None, "Hist Person", "Бажарилмаган", "AI0002"],
        [202, "Қарор", "ПҚ-9 \n 01.01.2026", f"3-банд\n{B_WORDS} ввввв", "31.12.2026", None, "Hist Person", "Бажарилмаган", "AI0003"]]))})
    Fake.seen.clear()
    Fake.mode.update(status=200, answer={"items": [{"code": "AI0001", "template": "-1:27", "reason": "организационное мероприятие"},          # differs from the history (15th)
                                                    {"code": "AI0002", "template": "99:99", "reason": "выдуманный шаблон"},                        # not a template of the specialist: refused
                                                    {"code": "AI0003", "template": "0:15", "reason": "итоговый показатель", "date": "2020-01-01"}]})  # a date from the model is ignored
    r = admin.post("/api/closing/suggest", json={"ids": mine(admin, "AI0001", "AI0002", "AI0003")}).json()
    assert r["proposed"] == 3 and r["by_ai"] == 2 and r["by_history"] == 1 and not r["errors"]
    a1, a2, a3 = task(admin, "AI0001"), task(admin, "AI0002"), task(admin, "AI0003")
    assert (a1["close_date"], a1["close_src"]) == ("2026-11-27", "ai") and "организационное мероприятие" in a1["close_note"]
    assert (a2["close_date"], a2["close_src"]) == ("2026-11-27", "rule")                            # the answer of the history instead of the invented template
    assert (a3["close_date"], a3["close_src"]) == ("2026-12-15", "ai")                              # the date is ours, not the model's
    req = Fake.seen[0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer sk-test-1234567890abcdef"
    assert req["body"]["model"] == "gpt-4.1-mini" and req["body"]["response_format"] == {"type": "json_object"}
    user = json.loads(req["body"]["messages"][1]["content"])
    assert {t["id"] for t in user["templates"]} >= {"0:15", "-1:27"} and len(user["tasks"]) == 3
    assert user["tasks"][0]["examples"] and "template" in user["tasks"][0]["examples"][0]          # the model sees the earlier decisions


def test_a_failing_service_falls_back_to_the_history_and_never_shows_the_key(admin, srv):
    admin.post("/api/import?dry=0", files={"file": ("n3.xlsx", xlsx([[300, "Қарор", "ПҚ-9 \n 01.01.2026", f"1-банд\n{A_WORDS} фейлл", "31.12.2026", None, "Hist Person", "Бажарилмаган", "AI0010"]]))})
    Fake.mode.update(status=401)
    r = admin.post("/api/closing/suggest", json={"ids": mine(admin, "AI0010")}).json()
    assert r["proposed"] == 1 and r["by_history"] == 1 and "401" in r["errors"][0] and "sk-test" not in json.dumps(r)
    assert task(admin, "AI0010")["close_src"] == "rule"
    t = admin.post("/api/ai/test", json={}).json()
    assert t["ok"] is False and "sk-test" not in json.dumps(t)
    Fake.mode.update(status=200, answer={"ok": True})
    assert admin.post("/api/ai/test", json={}).json()["ok"] is True


def test_switched_off_the_model_is_not_asked(admin, srv):
    admin.put("/api/ai", json={"enabled": False})
    admin.post("/api/import?dry=0", files={"file": ("n4.xlsx", xlsx([[400, "Қарор", "ПҚ-9 \n 01.01.2026", f"1-банд\n{A_WORDS} оффф", "31.12.2026", None, "Hist Person", "Бажарилмаган", "AI0020"]]))})
    Fake.seen.clear()
    assert admin.post("/api/closing/suggest", json={"ids": mine(admin, "AI0020")}).json()["by_ai"] == 0 and Fake.seen == []
    admin.put("/api/ai", json={"clear_key": True})
    assert admin.get("/api/ai").json()["key_set"] is False


def test_only_the_administrator_touches_this(admin):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["name"] == "Hist Person"][0]
    pw = admin.post(f"/api/users/{uid['id']}/password", json={}).json()["password"]
    emp = TestClient(app)
    assert emp.post("/login", data={"login": uid["login"], "password": pw}, follow_redirects=False).status_code == 303
    for method, path, body in (("post", "/api/closing/suggest", {}), ("post", "/api/closing/confirm", {}), ("post", "/api/ai/test", {}), ("put", "/api/ai", {"enabled": True}),
                               ("put", "/api/import/aliases", {"map": {"x": None}}), ("post", "/api/import?dry=1", None)):
        r = getattr(emp, method)(path, json=body) if body is not None else emp.post(path)
        assert r.status_code == 403, (path, r.status_code)
    assert emp.get("/api/ai").status_code == 403
    anon = TestClient(app)
    assert anon.get("/api/ai").status_code == 401 and anon.post("/api/closing/confirm", json={}).status_code == 401


# ---------------------------------------------------------------- the window: not the official date, and enough time to get through
def _model_with(admin):
    admin.post("/api/import?dry=0", files={"file": ("h2.xlsx", xlsx(hist_rows()))})
    return closing.Model(connect())


def test_a_proposal_never_repeats_the_official_date_and_leaves_time_for_the_approval(admin):
    from datetime import date, timedelta
    m = _model_with(admin)
    t0 = date(2026, 11, 16)
    assert m.buffer == 10 and {15, 27} <= m.anchors                                            # learned from the history: the 10 days of the specialist's data
    m.anchors = {10, 15, 25, 27}                                                               # the days of the specialist's real list (the synthetic history has fewer)
    for tmpl in ("asap", "-1:27", "0:15", "0:25", "-1:10"):
        for due in ("2026-11-20", "2026-11-25", "2026-12-01", "2026-12-05", "2026-12-10", "2026-12-20", "2026-12-25", "2026-12-31", "2027-03-01"):
            d = date.fromisoformat(due)
            got, _ = closing.fit_date(m, tmpl, d, t0)
            assert t0 < got < d, (tmpl, due, got)                                                # never the official day, never in the past
            horizon = (d - t0).days
            if horizon >= 30:
                assert (d - got).days >= m.buffer, (tmpl, due, got)                              # a far term keeps the full buffer for Justice, Cabinet, Chamber
            else:
                assert (d - got).days >= 3, (tmpl, due, got)                                     # a near term keeps at least three days
    assert closing.fit_date(m, "0:15", date(2026, 12, 20), t0)[0] == date(2026, 12, 10)           # the 15th is too close to the 20th: the habitual day inside the window (the 10th)
    assert closing.fit_date(m, "0:15", date(2026, 12, 1), t0)[0] == date(2026, 11, 25)            # 1 December: the 25th, as the specialist did
    assert closing.fit_date(m, "0:15", date(2026, 12, 25), t0)[0] == date(2026, 12, 15)           # when it fits, the template stays as it is
    assert closing.fit_date(m, "asap", date(2026, 11, 17), t0)[0] == date(2026, 11, 17)            # a term tomorrow: nothing earlier is possible
    got, why = closing.fit_date(m, "0:15", date(2026, 11, 10), t0)                                 # the term has passed: today
    assert got == t0 and "наступил" in why


def test_the_stored_proposal_for_a_near_term_is_shorter_than_the_term(admin):
    admin.post("/api/import?dry=0", files={"file": ("near.xlsx", xlsx([
        [900, "Қарор", "ПҚ-9 \n 01.01.2026", f"1-банд\n{A_WORDS} яқинаа", "25.11.2026", None, "Hist Person", "Бажарилмаган", "NR0001"],
        [901, "Қарор", "ПҚ-9 \n 01.01.2026", f"2-банд\n{A_WORDS} яқинбб", "10.12.2026", None, "Hist Person", "Бажарилмаган", "NR0002"]]))})
    r = admin.post("/api/closing/suggest", json={"ai": False, "ids": mine(admin, "NR0001", "NR0002")}).json()
    assert r["proposed"] == 2
    a, b = task(admin, "NR0001"), task(admin, "NR0002")
    assert "2026-11-16" < a["close_date"] < "2026-11-25" and "2026-11-16" < b["close_date"] <= "2026-11-30"   # earlier than the term, not on it
    assert a["close_date"] != a["due"] and b["close_date"] != b["due"]


def test_a_recalculation_changes_only_the_unconfirmed_proposals(admin):
    ids = mine(admin, "NR0001", "NR0002")
    admin.post("/api/closing/confirm", json={"ids": [ids[0]]})
    admin.patch(f"/api/tasks/{ids[0]}", json={"close_date": "2026-11-19"})
    r = admin.post("/api/closing/suggest", json={"ai": False, "redo": True, "ids": ids}).json()
    assert r["asked"] == 1                                                                        # the one confirmed by a person is left alone
    assert task(admin, "NR0001")["close_date"] == "2026-11-19"


def test_the_honest_estimate_is_lower_than_the_one_with_the_group_visible(admin):
    ev = closing.evaluate(connect())
    assert ev["accuracy"] is not None and ev["accuracy"] <= ev["accuracy_with_siblings"] and ev["buffer_days"] >= 7
