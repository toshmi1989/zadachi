"""Telegram linking and reminders, against a fake Telegram API."""
import sqlite3
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import db, reminders, telegram
from app.main import app
from fake_telegram import FAKE, TOKEN
from test_app import HEAD, xlsx

CHAT = 5550001
MON_9 = datetime(2026, 11, 16, 9, 5, tzinfo=db.TZ)    # Monday, five minutes after the default send time
ROWS = [  # today is 2026-11-16
    [1, "Қарор", "ПҚ-1 \n 01.01.2026", "1-банд\nПросроченная", "31.12.2026", "2026-11-10", "Sidorov Sidor", "Бажарилмаган", "TG0001"],
    [2, "Қарор", "ПҚ-1 \n 01.01.2026", "2-банд\nСегодня", "31.12.2026", "2026-11-16", "Sidorov Sidor", "Бажарилмаган", "TG0002"],
    [3, "Қарор", "ПҚ-1 \n 01.01.2026", "3-банд\nЧерез три дня", "31.12.2026", "2026-11-19", "Sidorov Sidor", "Бажарилмаган", "TG0003"],
    [4, "Қарор", "ПҚ-1 \n 01.01.2026", "4-банд\nЧерез пять дней", "31.12.2026", "2026-11-21", "Sidorov Sidor", "Бажарилмаган", "TG0004"],
    [5, "Қарор", "ПҚ-1 \n 01.01.2026", "5-банд\nЧерез семь дней", "31.12.2026", "2026-11-23", "Sidorov Sidor", "Бажарилмаган", "TG0005"],
    [6, "Қарор", "ПҚ-1 \n 01.01.2026", "6-банд\nВыполнена", "31.12.2026", "2026-11-10", "Sidorov Sidor", "Бажарилган", "TG0006"],
]


def sess(login, password):
    c = TestClient(app)
    c.__enter__()
    assert c.post("/login", data={"login": login, "password": password}, follow_redirects=False).status_code == 303
    return c


@pytest.fixture(scope="module")
def admin():
    with TestClient(app) as c:
        c.post("/login", data={"login": "admin", "password": "secret123"}, follow_redirects=False)
        r = c.post("/api/import?dry=0", files={"file": ("x.xlsx", xlsx(ROWS))})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture(scope="module")
def sidorov(admin):
    uid = [u for u in admin.get("/api/users").json()["items"] if u["login"] == "sidorov.s"][0]["id"]
    pw = admin.post(f"/api/users/{uid}/password", json={}).json()["password"]
    c = sess("sidorov.s", pw)
    c.uid = uid
    return c


def test_status_without_link_and_no_token_leak(admin):
    r = admin.get("/api/telegram")
    assert r.status_code == 200 and r.json()["configured"] and not r.json()["linked"] and r.json()["bot"] == "zadachi_test_bot"
    assert TOKEN not in r.text and TOKEN not in admin.get("/api/reminders/settings").text


def test_link_flow_and_commands(sidorov):
    link = sidorov.post("/api/telegram/link").json()
    assert link["url"] == f"https://t.me/zadachi_test_bot?start={link['code']}"
    FAKE.push(CHAT, "/start wrong-code")
    telegram.poll_once()
    assert "не найден" in FAKE.texts(CHAT)[-1] and not sidorov.get("/api/telegram").json()["linked"]
    FAKE.push(CHAT, f"/start {link['code']}", "sidor")
    telegram.poll_once()
    assert "Готово" in FAKE.texts(CHAT)[-1]
    st = sidorov.get("/api/telegram").json()
    assert st["linked"] and st["username"] == "sidor"
    FAKE.push(CHAT, f"/start {link['code']}")           # a code works once
    telegram.poll_once()
    assert "уже привязан" in FAKE.texts(CHAT)[-1] or "не найден" in FAKE.texts(CHAT)[-1]
    assert sidorov.post("/api/telegram/test").status_code == 200 and "Проверка связи" in FAKE.texts(CHAT)[-1]


def test_stranger_chat_is_refused():
    FAKE.push(999, "/my")
    telegram.poll_once()
    assert "не привязан" in FAKE.texts(999)[-1]


def test_digest_content_and_once_a_day(admin, sidorov):
    before = len(FAKE.texts(CHAT))
    res = [r for r in reminders.run_due(MON_9) if r["user_id"] == sidorov.uid]
    assert res and res[0]["status"] == "sent"
    msg = FAKE.texts(CHAT)[-1]
    assert len(FAKE.texts(CHAT)) == before + 1
    assert "TG0001" in msg and "TG0002" in msg and "TG0003" in msg and "TG0005" in msg   # overdue, today, in 3 days, in 7 days
    assert "TG0004" not in msg and "TG0006" not in msg                                  # 5 days is not in the rules; done is never listed
    assert "Просрочено" in msg and "Срок сегодня" in msg and "Срок через 3 дня" in msg
    reminders.run_due(MON_9)
    assert len(FAKE.texts(CHAT)) == before + 1                                          # no second digest the same day


def test_schedule_gate():
    g = reminders.global_cfg()
    assert reminders.due_now(g, MON_9)
    assert not reminders.due_now(g, datetime(2026, 11, 16, 8, 59, tzinfo=db.TZ))        # before the set time
    assert not reminders.due_now(g, datetime(2026, 11, 16, 16, 0, tzinfo=db.TZ))        # too late: the window is over
    assert not reminders.due_now(g, datetime(2026, 11, 21, 9, 5, tzinfo=db.TZ))         # Saturday is not in the default weekdays


def test_personal_settings_override_defaults(admin, sidorov):
    r = sidorov.put("/api/reminders/me", json={"days": [5], "overdue": 0}).json()
    assert r["mine"]["days"] == [5] and r["mine"]["overdue"] == 0 and r["mine"]["custom_days"]
    pv = {x["user_id"]: x for x in admin.get("/api/reminders/preview").json()["items"]}[sidorov.uid]
    assert pv["status"] == "would_send" and "TG0004" in pv["text"] and "TG0001" not in pv["text"] and "TG0003" not in pv["text"]
    assert sidorov.put("/api/reminders/me", json={"overdue": 5}).status_code == 400
    r = sidorov.put("/api/reminders/me", json={"days": None, "overdue": None}).json()
    assert r["mine"]["days"] == [7, 3, 1, 0] and not r["mine"]["custom_days"]


def test_overdue_repeat_interval(admin, sidorov):
    c = sqlite3.connect(db.DB_PATH)
    c.execute("DELETE FROM reminder_log WHERE user_id=?", (sidorov.uid,))
    c.execute("INSERT INTO reminder_log(user_id, day, kind, ok, count, overdue, created_at) VALUES (?,?,?,?,?,?,?)", (sidorov.uid, "2026-11-14", "digest", 1, 4, 1, "x"))
    c.commit(); c.close()
    sidorov.put("/api/reminders/me", json={"overdue": 3})                               # last reminded about overdue 2 days ago, repeat every 3
    pv = {x["user_id"]: x for x in admin.get("/api/reminders/preview").json()["items"]}[sidorov.uid]
    assert "TG0001" not in pv["text"] and "TG0002" in pv["text"]
    sidorov.put("/api/reminders/me", json={"overdue": 2})                               # every 2 days: it is time again
    pv = {x["user_id"]: x for x in admin.get("/api/reminders/preview").json()["items"]}[sidorov.uid]
    assert "TG0001" in pv["text"]
    sidorov.put("/api/reminders/me", json={"overdue": None})


def test_switch_off_by_user_and_by_bot(admin, sidorov):
    sidorov.put("/api/reminders/me", json={"remind": False})
    pv = {x["user_id"]: x for x in admin.get("/api/reminders/preview").json()["items"]}[sidorov.uid]
    assert pv["status"] == "off"
    FAKE.push(CHAT, "/start")
    telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["remind"] is True
    FAKE.push(CHAT, "/stop")
    telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["remind"] is False
    FAKE.push(CHAT, "/start")
    telegram.poll_once()
    FAKE.push(CHAT, "/my")
    telegram.poll_once()
    assert "TG0001" in FAKE.texts(CHAT)[-1]


def test_assignment_notice(admin, sidorov):
    tid = admin.get("/api/tasks?q=TG0004").json()["items"][0]["id"]
    admin.patch(f"/api/tasks/{tid}", json={"assignee_id": None})
    n = len(FAKE.texts(CHAT))
    admin.patch(f"/api/tasks/{tid}", json={"assignee_id": sidorov.uid})
    for _ in range(40):
        if len(FAKE.texts(CHAT)) > n:
            break
        time.sleep(0.05)
    assert "Вам назначена задача" in FAKE.texts(CHAT)[-1] and "TG0004" in FAKE.texts(CHAT)[-1]
    sidorov.put("/api/reminders/me", json={"notify_assign": False})
    admin.patch(f"/api/tasks/{tid}", json={"assignee_id": None})
    n = len(FAKE.texts(CHAT))
    admin.patch(f"/api/tasks/{tid}", json={"assignee_id": sidorov.uid})
    time.sleep(0.4)
    assert len(FAKE.texts(CHAT)) == n                                                   # the person switched assignment notices off


def test_global_settings_validation_and_permissions(admin, sidorov):
    assert sidorov.get("/api/reminders/settings").status_code == 403
    assert sidorov.put("/api/reminders/settings", json={"time": "10:00"}).status_code == 403
    assert sidorov.get("/api/reminders/preview").status_code == 403
    assert sidorov.post("/api/reminders/run").status_code == 403
    assert admin.put("/api/reminders/settings", json={"time": "25:00"}).status_code == 400
    assert admin.put("/api/reminders/settings", json={"weekdays": []}).status_code == 400
    assert admin.put("/api/reminders/settings", json={"public_url": "javascript:alert(1)"}).status_code == 400
    ok = admin.put("/api/reminders/settings", json={"time": "08:30", "weekdays": [1, 2, 3, 4, 5, 6], "days": [14, 2], "overdue": 7, "public_url": "https://t.example.uz/"}).json()
    assert ok["time"] == "08:30" and ok["days"] == [14, 2] and ok["overdue"] == 7 and ok["public_url"] == "https://t.example.uz"
    assert reminders.due_now(reminders.global_cfg(), datetime(2026, 11, 21, 8, 31, tzinfo=db.TZ))   # Saturday now counts
    admin.put("/api/reminders/settings", json={"time": "09:00", "weekdays": [1, 2, 3, 4, 5], "days": [7, 3, 1, 0], "overdue": 1, "enabled": False})
    assert reminders.run_due(MON_9) == []                                               # switched off for everyone
    admin.put("/api/reminders/settings", json={"enabled": True})


def test_blocked_bot_unlinks(admin, sidorov):
    FAKE.fail_next = (403, "Forbidden: bot was blocked by the user")
    ok, err = telegram.send(str(CHAT), "x")
    assert not ok and "заблокировал" in err
    assert not sidorov.get("/api/telegram").json()["linked"]


def test_link_requires_token_and_unlink(sidorov, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert sidorov.post("/api/telegram/link").status_code == 400
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert sidorov.post("/api/telegram/unlink").status_code == 200


# ---------------------------------------------------------------- buttons

def flat(markup):
    rows = markup.get("inline_keyboard") or markup.get("keyboard") or []
    return [b for row in rows for b in row]


def test_buttons_menu_and_navigation(admin, sidorov):
    link = sidorov.post("/api/telegram/link").json()
    FAKE.push(CHAT + 1, f"/start {link['code']}", "sidor2")
    telegram.poll_once()
    chat = CHAT + 1
    kb = FAKE.last_markup(chat)
    labels = [b["text"] for b in flat(kb)]
    assert "📋 Мои задачи" in labels and "⚙️ Настройки" in labels and "📊 Сводка" not in labels   # the summary button is for administrators
    assert kb["is_persistent"] and kb["resize_keyboard"]
    FAKE.push(chat, "🔴 Просрочено"); telegram.poll_once()
    assert "TG0001" in FAKE.texts(chat)[-1] and "TG0003" not in FAKE.texts(chat)[-1]
    assert {b.get("callback_data") for b in flat(FAKE.last_markup(chat))} >= {"v:all", "v:overdue", "v:week", "s:open"}
    FAKE.push(chat, "📅 Эта неделя"); telegram.poll_once()
    assert "TG0003" in FAKE.texts(chat)[-1] and "TG0001" not in FAKE.texts(chat)[-1]
    FAKE.push_callback(chat, "v:all", 77); telegram.poll_once()             # inline button edits the message in place
    e = FAKE.edits[-1]
    assert e["message_id"] == 77 and "TG0001" in e["text"] and "TG0003" in e["text"]
    assert FAKE.answers[-1]["callback_query_id"].startswith("cb")


def test_buttons_settings_change_only_own_rules(admin, sidorov):
    chat = CHAT + 1
    sidorov.put("/api/reminders/me", json={"remind": True, "notify_assign": True, "days": None, "overdue": None})
    FAKE.push(chat, "⚙️ Настройки"); telegram.poll_once()
    assert "Настройки напоминаний" in FAKE.texts(chat)[-1] and "как у всех" in FAKE.texts(chat)[-1]
    FAKE.push_callback(chat, "s:d:5"); telegram.poll_once()                  # add "5 days before" to the effective list 7,3,1,0
    mine = sidorov.get("/api/reminders/me").json()["mine"]
    assert mine["days"] == [7, 5, 3, 1, 0] and mine["custom_days"]
    assert "✅ 5 дн." in str(FAKE.edits[-1]["reply_markup"])
    FAKE.push_callback(chat, "s:d:7"); telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["days"] == [5, 3, 1, 0]
    FAKE.push_callback(chat, "s:o:3"); telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["overdue"] == 3
    FAKE.push_callback(chat, "s:asg"); telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["notify_assign"] is False
    FAKE.push_callback(chat, "s:on"); telegram.poll_once()
    assert sidorov.get("/api/reminders/me").json()["mine"]["remind"] is False
    FAKE.push_callback(chat, "s:on"); FAKE.push_callback(chat, "s:asg"); FAKE.push_callback(chat, "s:reset"); telegram.poll_once()
    m = sidorov.get("/api/reminders/me").json()["mine"]
    assert m["remind"] and m["notify_assign"] and not m["custom_days"] and not m["custom_overdue"]
    FAKE.push_callback(chat, "s:d:99"); FAKE.push_callback(chat, "s:o:99"); FAKE.push_callback(chat, "s:nonsense"); telegram.poll_once()   # junk is ignored
    assert not sidorov.get("/api/reminders/me").json()["mine"]["custom_days"]


def test_buttons_stranger_and_digest_markup(admin, sidorov):
    FAKE.push_callback(31337, "s:on"); telegram.poll_once()
    assert FAKE.answers[-1].get("text") == "Telegram не привязан к аккаунту" and not FAKE.edits[-1]["chat_id"] == 31337
    admin.put("/api/reminders/settings", json={"public_url": "https://z.example.uz"})
    reminders.run_due(MON_9, force=True)
    mk = FAKE.last_markup(CHAT + 1)
    urls = [b.get("url") for b in flat(mk) if b.get("url")]
    assert urls == ["https://z.example.uz/#/tasks?assignee=%d&status=open" % sidorov.uid]
    admin.put("/api/reminders/settings", json={"public_url": "http://localhost:8766"})
    reminders.run_due(MON_9, force=True)
    assert not [b for b in flat(FAKE.last_markup(CHAT + 1)) if b.get("url")]               # Telegram would reject a local address


def test_unlink_removes_keyboard():
    FAKE.push(CHAT + 1, "/unlink"); telegram.poll_once()
    assert FAKE.last_markup(CHAT + 1) == {"remove_keyboard": True}
