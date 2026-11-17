"""Synchronisation of task statuses with edo.ijro.uz.

How it works. The site is only reachable with the administrator's own sign-in (digital signature or OneID), so the
platform never talks to it. A small script in the administrator's browser reads the statuses and answers of our open
tasks while they are signed in there, and sends them here with a key that belongs to THIS platform. Nothing of the
ijro account (no session id, no password) ever reaches the server.

What arrives is only stored as a snapshot. A task changes when the administrator applies the proposal on the review
screen, and that goes into the task's history like any other edit."""
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timezone

from . import tasks
from .db import STATUSES, TZ, audit, now, setting, today

SECTIONS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ijro_sections.json"), encoding="utf-8"))
SECTION_BY_ID = {s["id"]: s for s in SECTIONS["sections"]}
EDO_API = "https://edo.ijro.uz/api"
# the tabs of the site that the export is taken for (their statuses are those the site itself sends): what is open and what is overdue.
# Closed tasks are not downloaded: the 8 MB of the president's list is 88% closed ones, and the open ones are checked task by task anyway.
# of the Cabinet's list only «Вазирлар маҳкамаси қарори (Янги)» is downloaded (the platform also drops the other kinds when a file is imported)
EXPORT_TYPES_ONLY = {"government": ["68d805f2c8d2f3123184e0f4"]}
EXPORT_TABS = [{"id": "in_progress", "statuses": [-1, 1, 0, 2, 3, 4]}, {"id": "overdue", "statuses": [10, 12, 11, 13, 14]}]
MAX_ITEMS = 200
MAX_TEXT = 600
MAX_ANSWERS = 30

# what the answers on the site mean (sender_type): the site's own table paTaskSenderType. The tens are the level: 1x executor, 2x Ministry of
# Justice, 3x Cabinet of Ministers, 4x Chamber of Accounts (the level is a reading of the pattern, the names are the site's).
T_ANSWER, T_AGREED, T_REMOVAL, T_REMOVED = 10, 25, 35, 45
T_DONE = {15, 45, 55, 105, 125}                                   # Nazoratdan yechildi: removed from control = done
T_REWORK = {19, 29, 33, 39, 59, 109, 129}                         # Qayta ishlashga yuborildi: back to the executor
T_RETAKEN = {18, 34, 38, 48, 58, 108, 128}                        # Qayta nazoratga olindi: taken under control again
T_INFO = {44, 54, 104, 49}                                        # 44.. Maʼlumot uchun qabul qilindi; 49 Qoʻshimcha maʼlumot uchun soʻrov: the task stays open, the term changes
ANSWER_TYPES = {10: "Ответ исполнителя", 20: "Согласовано (Kelishilgan)", 25: "Согласование подтверждено (Kelishish tasdiqlangan)",
                30: "Снятие с контроля согласовано (Nazoratdan olish kelishildi)", 40: "Снятие с контроля согласовано (Nazoratdan olish kelishildi)",
                35: "Снятие с контроля подтверждено (Nazoratdan olishni tasdiqlandi)", 44: "Принято к сведению (Maʼlumot uchun qabul qilindi)",
                54: "Принято к сведению (Maʼlumot uchun qabul qilindi)", 104: "Принято к сведению (Maʼlumot uchun qabul qilindi)",
                49: "Запрос дополнительной информации (Qoʻshimcha maʼlumot uchun soʻrov)", 124: "Рассматривается (Koʻrib chiqilmoqda)"}
for _c in T_DONE:
    ANSWER_TYPES[_c] = "Снято с контроля (Nazoratdan yechildi)"
for _c in T_REWORK:
    ANSWER_TYPES[_c] = "Отправлено на доработку (Qayta ishlashga yuborildi)"
for _c in T_RETAKEN:
    ANSWER_TYPES[_c] = "Снова взято на контроль (Qayta nazoratga olindi)"



# The way of an answer: entered -> Ministry of Justice -> Cabinet of Ministers -> Chamber of Accounts -> removed from control.
# The site stores NO stage: it is read from the answers. The answer that counts is the one with active=1, otherwise the newest:
# 10 -> with the Ministry of Justice, 25 -> with the Cabinet, 35 -> with the Chamber, 29/49 -> back to us, 45 -> removed from control (done).
STAGE_STEPS = [("sub", "Киритилди", "Ответ введён"), ("moj", "Адлия вазирлигида", "Согласование в Минюсте"), ("cab", "Вазирлар Маҳкамасида", "В Кабинете Министров"),
               ("chamber", "Ҳисоб палатасида", "В Счётной палате"), ("end", "Назоратдан ечилди", "Снята с контроля: выполнена")]
ACCEPTED_WORDS = ("қабул қилинди", "қабул килинди", "qabul qilindi", "принят")


NEUTRAL = {124}   # Koʻrib chiqilmoqda: "being reviewed" by the executor; it says nothing about where the task is


def current_answer(answers: list[dict]):
    """The answer that says where the task is now: the one the site marks active, else the newest. Answers of one day are ordered by their
    type (10, 25, 35, 45, 49 follow the way of the chain), so a day without a precise time does not mix them up."""
    real = [a for a in answers if a.get("sender_type") is not None and a["sender_type"] not in NEUTRAL]
    ordered = sorted(real, key=lambda a: (a.get("at_ms") or 0, a["sender_type"]))
    if not ordered:
        return None
    active = [a for a in ordered if a.get("active")]
    return (active or ordered)[-1]


def stage_of(snap, due: str | None = None, dates: bool = True) -> dict:
    """Where the task is on its way. {code, n (index in STAGE_STEPS, -1 = no answer yet), label, hint, attention, new_due}.
    code 'info': the Chamber of Accounts sent it back (accepted for information / asked for more): the task is NOT done and its term changes."""
    base = {"steps": [{"code": c, "label": l, "hint": h} for c, l, h in STAGE_STEPS], "new_due": None, "attention": False}
    if not snap["found"]:
        return base | {"code": "not_found", "n": None, "label": "Не найдена на сайте", "hint": ""}
    if snap["repeatable"] and json.loads(snap["periods"] or "[]"):
        return base | {"code": "periodic", "n": None, "label": "Периодическая задача", "hint": "Этапы считаются по каждому периоду отдельно"}
    answers = json.loads(snap["answers"] or "[]")
    cur = current_answer(answers)
    t = cur["sender_type"] if cur else None
    reviewing = bool(cur) and any(a.get("sender_type") in NEUTRAL and (a.get("at_ms") or 0) >= (cur.get("at_ms") or 0) for a in answers)
    extra = " Сейчас исполнитель рассматривает (Koʻrib chiqilmoqda)." if reviewing else ""
    done = classify(snap, due, dates=False)["status"] == "done"
    if done:
        return base | {"code": "removed", "n": 4, "label": "Назоратдан ечилди", "hint": "Снята с контроля: выполнена"}
    if t in T_DONE:   # the answer of removal is there, the status on the site has not followed yet
        return base | {"code": "removed_wait", "n": 4, "label": "Назоратдан ечилди", "hint": "Ответ о снятии получен, статус задачи на сайте ещё не обновился"}
    if t in T_INFO:
        nd = _day(snap["due_ms"])
        accepted = any(w in (cur.get("text") or "").lower() for w in ACCEPTED_WORDS)
        return base | {"code": "info", "n": 3, "label": "Маълумот учун қабул қилинди" if accepted else "Қўшимча маълумот сўрови",
                       "hint": "Счётная палата вернула задачу" + (": ответ принят к сведению" if accepted else " с запросом информации") + ". Задача НЕ выполнена, срок изменён." + extra,
                       "attention": True, "new_due": nd.isoformat() if nd and dates else None}
    if t in T_REWORK or t in T_RETAKEN:
        name = "Возврат на доработку" if t in T_REWORK else "Снова взята на контроль"
        return base | {"code": "returned", "n": 0, "label": name, "hint": "Нужны действия исполнителя." + extra, "attention": True}
    if t == T_REMOVAL:
        return base | {"code": "chamber", "n": 3, "label": "Ҳисоб палатасида", "hint": "Кабинет подтвердил снятие, решает Счётная палата"}
    if t == T_AGREED:
        return base | {"code": "cab", "n": 2, "label": "Вазирлар Маҳкамасида", "hint": "Минюст согласовал, дело в Кабинете Министров"}
    if t in (T_ANSWER, 20):
        return base | {"code": "moj", "n": 1, "label": "Адлия вазирлигида", "hint": "Ответ введён, идёт согласование в Минюсте"}
    if t is not None:   # a type we do not know: shown, not guessed
        return base | {"code": "chamber_other", "n": 3, "label": f"Ответ типа {t}", "hint": "Тип ответа не распознан: уточните на сайте", "attention": True}
    if snap["site_status"] == 2:
        return base | {"code": "answered", "n": 0, "label": "Киритилди", "hint": "Ответ введён; этап уточнится при следующей проверке (нет данных об ответах)"}
    return base | {"code": "none", "n": -1, "label": "Ответ не введён", "hint": "Исполнитель ещё не ответил"}


def auto_apply(c, task_id: int) -> list[str]:
    """After a check: what is clear is applied without a review. Never lowers a status by itself, except one case the administrator named:
    the Chamber accepted the answer for information, so a task we had marked done is open again, with the new term.
    Returns what was done (for the log)."""
    r = c.execute("SELECT s.*, t.status AS our_status, t.due FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id WHERE s.task_id=?", (task_id,)).fetchone()
    if not r or r["our_status"] == "info" or not r["found"]:
        return []
    cl, st, done = classify(r, r["due"]), stage_of(r, r["due"]), []
    changes: dict = {}
    if cl["status"] == "done" and r["our_status"] != "done":
        changes["status"] = "done"
    elif cl["status"] == "progress" and r["our_status"] == "todo":
        changes["status"] = "progress"
    elif r["our_status"] == "todo" and cl.get("open") and st["code"] in ("moj", "cab", "chamber", "info", "returned", "chamber_other"):
        changes["status"] = "progress"
    if st["code"] == "info":
        if r["our_status"] == "done":
            changes["status"] = "progress"
        if st["new_due"] and st["new_due"] != r["due"]:
            changes["due"] = st["new_due"]
    if changes:
        tasks.update_task(c, task_id, changes, None)
        done = [f"{k}→{v}" for k, v in changes.items()]
    return done


FUNNEL = [("none", "Ответ не введён", "Исполнитель ещё не ответил"), ("moj", "Адлия вазирлигида", "Ответ введён, согласование в Минюсте"),
          ("cab", "Вазирлар Маҳкамасида", "В Кабинете Министров"), ("chamber", "Ҳисоб палатасида", "Ждёт решения Счётной палаты"),
          ("info", "Ҳисоб палатаси вернула", "Принято к сведению или запрос информации: НЕ выполнена, срок изменён"), ("returned", "Возврат / запрос", "Нужны действия исполнителя")]
_FUNNEL_OF = {"none": "none", "answered": "moj", "moj": "moj", "cab": "cab", "chamber": "chamber", "chamber_other": "chamber", "info": "info", "returned": "returned"}


def _open_stage_rows(c):
    return c.execute("""SELECT s.*, t.due, t.id AS tid FROM tasks t LEFT JOIN ijro_snapshots s ON s.task_id=t.id WHERE t.status IN ('todo','progress')""").fetchall()


def funnel(c) -> dict:
    """How many open tasks are at each stage (for the dashboard). Tasks never checked on the site are counted apart."""
    counts = {k: 0 for k, _, _ in FUNNEL}
    unchecked = other = 0
    for r in _open_stage_rows(c):
        if r["task_id"] is None:
            unchecked += 1
            continue
        k = _FUNNEL_OF.get(stage_of(r, r["due"], dates=False)["code"])
        if k:
            counts[k] += 1
        else:
            other += 1
    return {"steps": [{"code": k, "label": l, "hint": h, "count": counts[k]} for k, l, h in FUNNEL], "unchecked": unchecked, "other": other,
            "attention": counts["info"] + counts["returned"]}


def stage_ids(c, key: str) -> list[int]:
    """Ids of the open tasks at a stage of the funnel ('unchecked' = never read from the site)."""
    out = []
    for r in _open_stage_rows(c):
        if r["task_id"] is None:
            if key == "unchecked":
                out.append(r["tid"])
        elif _FUNNEL_OF.get(stage_of(r, r["due"], dates=False)["code"]) == key:
            out.append(r["tid"])
    return out


# ---------------------------------------------------------------- keys of this platform

def new_key(c, name: str, user_id: int) -> str:
    key = "zk_" + secrets.token_urlsafe(32)
    c.execute("INSERT INTO sync_keys(name, key_hash, created_by, created_at) VALUES (?,?,?,?)",
              (name.strip()[:60] or "Ключ", hashlib.sha256(key.encode()).hexdigest(), user_id, now()))
    return key


def check_key(c, header: str | None):
    """The row of a valid, not revoked key, or None. Only a hash is stored, so a copy of the database does not open anything."""
    if not header or not header.lower().startswith("bearer "):
        return None
    key = header[7:].strip()
    if not key.startswith("zk_") or len(key) > 100:
        return None
    h = hashlib.sha256(key.encode()).hexdigest()
    row = c.execute("SELECT * FROM sync_keys WHERE key_hash=? AND revoked=0", (h,)).fetchone()
    if row and hmac.compare_digest(row["key_hash"], h):
        c.execute("UPDATE sync_keys SET last_used=? WHERE id=?", (now(), row["id"]))
        return row
    return None


# ---------------------------------------------------------------- what to check

RESUME_HOURS = 6


def job(c, key_id: int, resume: bool = False) -> dict:
    """The tasks the collector must look up: everything still open. The section order for each follows the document kind.
    With resume, what was checked in the last hours is skipped: the run goes on where an interrupted one stopped."""
    sql = "SELECT id, code, kind FROM tasks WHERE status IN ('todo','progress')"
    args: list = []
    if resume:
        from datetime import timedelta
        sql += " AND id NOT IN (SELECT task_id FROM ijro_snapshots WHERE checked_at >= ?)"
        args.append((datetime.now(TZ) - timedelta(hours=RESUME_HOURS)).strftime("%Y-%m-%d %H:%M:%S"))
    rows = c.execute(sql + " ORDER BY seq, id", args).fetchall()
    by_kind = {k: s["id"] for s in SECTIONS["sections"] for k in s["kinds"]}
    cur = c.execute("INSERT INTO sync_runs(key_id, started_at, expected) VALUES (?,?,?)", (key_id, now(), len(rows)))
    return {"run_id": cur.lastrowid, "api_tasks": SECTIONS["api_tasks"], "sections": SECTIONS["sections"],
            "items": [{"code": r["code"], "section": by_kind.get(r["kind"], "")} for r in rows]}


# ---------------------------------------------------------------- mapping of the site's status to ours

def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date() if ms else None


def current_period(periods: list[dict], due: str | None):
    """The period that our task row stands for: the one with the same deadline as the official term in the Excel row; otherwise the
    first unfinished period that is not in the past; otherwise the last one."""
    if due:
        want = date.fromisoformat(due)
        for p in periods:
            if _day(p.get("due_ms")) == want:
                return p
    t = today()
    for p in periods:
        d = _day(p.get("due_ms"))
        if p.get("recipient_status") != 20 and d and d >= t:
            return p
    return periods[-1]


OPEN_SITE = {-1, 1, 3, 4}   # statuses of the tab "Bajarilmoqda" besides 0 (no answer) and 2 (answered)


def classify(snap, due: str | None = None, dates: bool = True) -> dict:
    """What the site says, in our terms. Conservative: an unknown status never changes anything. A periodic task has one general
    status for all its periods (it stays 'in work' until the last one), so it is judged by the period of our deadline.
    Returns {status: our status or None, label, note, known}."""
    if not snap["found"]:
        return {"status": None, "label": "Не найдена на сайте", "note": "Код не найден ни в одном из трёх разделов", "known": False}
    st = snap["site_status"]
    periods = json.loads(snap["periods"] or "[]")
    if snap["repeatable"] and periods:
        cur = current_period(periods, due)
        n, k = len(periods), (cur.get("order") or periods.index(cur) + 1)
        when = _day(cur.get("due_ms"))
        tail = f" (срок {when.strftime('%d.%m.%Y')})" if when and dates else ""   # the date of a period is the official term: only administrators see it
        if all(p.get("recipient_status") == 20 for p in periods):
            return {"status": "done", "label": "Выполнена (все периоды)", "note": f"Периодов: {n}", "known": True}
        if cur.get("recipient_status") == 20:
            return {"status": "done", "label": f"Период {k} из {n} выполнен{tail}", "note": "Периодическая задача: считается по периоду вашего срока", "known": True}
        done = sum(1 for p in periods if p.get("recipient_status") == 20)
        return {"status": None, "label": f"Период {k} из {n} не выполнен{tail}", "note": f"Периодическая задача, выполнено периодов: {done} из {n}. Общий статус на сайте остаётся «в работе»", "known": True}
    if snap["is_done"] and st in (20, 21):
        late = st == 21
        return {"status": "done", "label": "Выполнена с опозданием" if late else "Выполнена в срок", "note": "", "known": True}
    if st == 2:
        return {"status": "progress", "label": "Ответ дан, идёт согласование", "note": "", "known": True, "open": True}
    if st == 0:
        return {"status": "todo", "label": "В работе, ответа нет", "note": "", "known": True, "open": True}
    note = "Задача лежит на вкладке «Выполнено» сайта, но смысл статуса 31 не определён: статус у нас не меняется" if st == 31 else "Смысл этого значения ещё не определён: статус не меняется"
    if st in OPEN_SITE:   # on the "Bajarilmoqda" tab of the site, only the meaning of the number is unknown: the task is open
        return {"status": None, "label": f"В работе на сайте (статус {st})", "note": f"Статус {st} лежит на вкладке «В работе» сайта; его смысл не определён, поэтому статус у нас не меняется. Этап — по ответам ниже", "known": True, "open": True}
    return {"status": None, "label": f"Неизвестный статус на сайте ({st})", "note": note, "known": False}


def card_link(snap, c=None) -> str:
    """Address of the task on the site. With the card template set (Settings) it is exact; without it, the list of the section."""
    sec = SECTION_BY_ID.get(snap["section"])
    if not sec:
        return ""
    tpl = setting("ijro_card_tpl").strip()
    if tpl and snap["recipient_id"]:
        return tpl.replace("{section_path}", sec["path"]).replace("{id}", str(snap["recipient_id"])).replace("{task_id}", str(snap["task_ref"] or ""))
    return f"https://edo.ijro.uz/assignments/{sec['path']}/current-user/main/tasks/in_progress"


def _ts(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M") if ms else ""


def answers_out(snap) -> list[dict]:
    out = []
    for a in json.loads(snap["answers"] or "[]"):
        out.append({"type": ANSWER_TYPES.get(a.get("sender_type"), f"Тип {a.get('sender_type')}"), "sender_type": a.get("sender_type"),
                    "state": a.get("state"), "at": _ts(a.get("at_ms")), "text": "" if snap["is_secret"] else a.get("text", ""),
                    "active": bool(a.get("active"))})
    return out


def shown(snap, due: str | None, dates: bool = True) -> tuple[dict, dict, str, str]:
    """(classification, stage, label, note) as they are shown. The site's number 2 stays after an answer, after a return (29) and after the
    Chamber's request (49) alike, so the number alone says "the answer is being approved" also when the task is back with us. Then the stage speaks."""
    cl, st = classify(snap, due, dates=dates), stage_of(snap, due, dates=dates)
    label, note = cl["label"], cl["note"]
    if cl["status"] == "progress" and st["code"] in ("info", "returned", "chamber_other"):
        label = {"info": "Вернулась от Счётной палаты — ждёт вашего ответа", "returned": "Вернулась к вам — ждёт вашего ответа", "chamber_other": "Ответ Счётной палаты: проверьте на сайте"}[st["code"]]
        note = st["hint"]
    return cl, st, label, note


def site_info(snap, our_status: str, due: str | None = None, admin: bool = True) -> dict:
    """The block 'С ijro.uz' of a task card: for administrators, and for the employee a task is assigned to (without the official term)."""
    cl, st, label, note = shown(snap, due, dates=admin)
    diff = bool(cl["status"] and cl["status"] != our_status and our_status != "info")
    return {"found": bool(snap["found"]), "section": snap["section"], "section_name": (SECTION_BY_ID.get(snap["section"]) or {}).get("name", ""),
            "label": label, "note": note, "known": cl["known"], "proposed": cl["status"],
            "proposed_label": STATUSES.get(cl["status"], "") if cl["status"] else "", "diff": diff,
            "site_open_we_done": bool(snap["found"] and cl["known"] and (cl["status"] in ("todo", "progress") or cl.get("open")) and our_status == "done"),
            "checked_at": snap["checked_at"], "link": card_link(snap), "exact_link": bool(setting("ijro_card_tpl").strip() and snap["recipient_id"]),
            "secret": bool(snap["is_secret"]), "answers": answers_out(snap), "late": snap["site_status"] == 21,
            "stage": {k: v for k, v in st.items() if k != "new_due" or admin}}


# ---------------------------------------------------------------- receiving

def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and -2**53 < v < 2**53 else None


def ingest(c, key_row, body: dict) -> dict:
    """Validates and stores a batch. Anything that is not a plain, small value is rejected, not repaired."""
    items = body.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise ValueError(f"Нужен список от 1 до {MAX_ITEMS} задач")
    run_id = _int(body.get("run_id"))
    codes = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM tasks")}
    stored = found = 0
    touched: list[int] = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("code"), str) or it["code"] not in codes:
            continue   # a code we do not have is ignored: the collector can never create tasks
        sec = it.get("section") if it.get("section") in SECTION_BY_ID else ""
        is_found = bool(it.get("found")) and bool(sec)
        periods = []
        for p in ((it.get("periods") or []) if is_found else [])[:20]:
            if isinstance(p, dict):
                periods.append({"order": _int(p.get("order")), "status": _int(p.get("status")), "recipient_status": _int(p.get("recipient_status")), "due_ms": _int(p.get("due_ms"))})
        answers = []
        secret = bool(it.get("is_secret"))
        for a in ((it.get("answers") or []) if is_found else [])[-MAX_ANSWERS:]:
            if isinstance(a, dict) and _int(a.get("sender_type")) is not None:   # an answer without a type means nothing: skipped
                text = a.get("text") if isinstance(a.get("text"), str) else ""
                answers.append({"sender_type": _int(a.get("sender_type")), "state": _int(a.get("state")), "at_ms": _int(a.get("at_ms")),
                                "active": bool(a.get("active")), "text": "" if secret else text[:MAX_TEXT]})
        rid = it.get("recipient_id")
        rid = str(rid)[:64] if isinstance(rid, (str, int)) and not isinstance(rid, bool) else ""
        ref = it.get("task_ref")
        ref = str(ref)[:64] if isinstance(ref, (str, int)) and not isinstance(ref, bool) else ""
        c.execute("""INSERT INTO ijro_snapshots(task_id, found, section, recipient_id, task_ref, site_status, is_done, overdue, repeatable, due_ms, done_ms,
                                                periods, is_secret, answers, checked_at, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(task_id) DO UPDATE SET found=excluded.found, section=excluded.section, recipient_id=excluded.recipient_id, task_ref=excluded.task_ref,
                       site_status=excluded.site_status, is_done=excluded.is_done, overdue=excluded.overdue, repeatable=excluded.repeatable,
                       due_ms=excluded.due_ms, done_ms=excluded.done_ms, periods=excluded.periods, is_secret=excluded.is_secret,
                       answers=CASE WHEN excluded.found=1 AND ? THEN excluded.answers ELSE ijro_snapshots.answers END,
                       checked_at=excluded.checked_at, run_id=excluded.run_id""",
                  (codes[it["code"]], int(is_found), sec if is_found else "", rid if is_found else "", ref if is_found else "", _int(it.get("status")) if is_found else None,
                   int(bool(it.get("is_done"))), None if it.get("overdue") is None else int(bool(it.get("overdue"))), int(bool(it.get("repeatable"))),
                   _int(it.get("due_ms")), _int(it.get("done_ms")), json.dumps(periods), int(secret), json.dumps(answers, ensure_ascii=False), now(), run_id,
                   int(bool(it.get("answers_loaded")))))
        stored += 1
        touched.append(codes[it["code"]])
        found += is_found
    auto = 0
    if setting("ijro_auto_apply") == "1":
        for tid in touched:
            if auto_apply(c, tid):
                auto += 1
        if auto:
            audit(c, "ijro.auto_apply", "task", None, {"tasks": auto, "run": run_id})
    if run_id:
        c.execute("UPDATE sync_runs SET received=received+?, found=found+?, finished_at=? WHERE id=? AND key_id=?", (stored, found, now(), run_id, key_row["id"]))
    return {"stored": stored, "found": found, "auto_applied": auto}


# ---------------------------------------------------------------- review and apply

def review(c) -> dict:
    rows = c.execute("""SELECT s.*, t.code, t.due, t.status AS our_status, t.text, t.kind, t.doc_no, t.point, t.assignee_id, a.name AS assignee
                        FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id LEFT JOIN users a ON a.id=t.assignee_id ORDER BY t.seq, t.id""").fetchall()
    items, counts = [], {"checked": len(rows), "found": 0, "not_found": 0, "unknown": 0, "to_done": 0, "to_progress": 0, "to_todo": 0, "site_open_we_done": 0, "same": 0}
    for r in rows:
        cl, _st, site_label, site_note = shown(r, r["due"])
        counts["found"] += bool(r["found"])
        if not r["found"]:
            counts["not_found"] += 1
        elif not cl["known"]:
            counts["unknown"] += 1
        kind = ""
        if cl["status"] and r["our_status"] != "info" and cl["status"] != r["our_status"]:
            kind = "to_" + cl["status"]
            counts[kind] += 1
        elif r["found"] and cl["known"] and (cl["status"] in ("todo", "progress") or cl.get("open")) and r["our_status"] == "done":
            kind = "site_open_we_done"
            counts[kind] += 1
        elif r["found"] and cl["known"]:
            counts["same"] += 1
        if kind or not r["found"] or not cl["known"]:
            items.append({"task_id": r["task_id"], "code": r["code"], "kind": r["kind"], "doc_no": r["doc_no"], "point": r["point"], "text": (r["text"] or "")[:160],
                          "assignee": r["assignee"] or "", "our_status": r["our_status"], "site_label": site_label, "note": site_note,
                          "proposed": cl["status"], "change": kind or ("not_found" if not r["found"] else "unknown"), "checked_at": r["checked_at"],
                          "link": card_link(r), "exact_link": bool(setting("ijro_card_tpl").strip() and r["recipient_id"])})
    runs = [dict(x) for x in c.execute("""SELECT r.*, k.name AS key_name FROM sync_runs r LEFT JOIN sync_keys k ON k.id=r.key_id ORDER BY r.id DESC LIMIT 8""")]
    open_total = c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('todo','progress')").fetchone()[0]
    return {"counts": counts, "items": items, "runs": runs, "open_total": open_total}


def apply(c, task_ids: list[int], user_id: int) -> dict:
    """Applies the proposals for the given tasks. A proposal that is no longer valid (the task changed meanwhile) is skipped."""
    applied, skipped = 0, 0
    for tid in task_ids:
        r = c.execute("SELECT s.*, t.status AS our_status, t.due FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id WHERE s.task_id=?", (tid,)).fetchone()
        if not r:
            skipped += 1
            continue
        cl = classify(r, r["due"])
        if not cl["status"] or r["our_status"] == "info" or cl["status"] == r["our_status"]:
            skipped += 1
            continue
        tasks.update_task(c, tid, {"status": cl["status"]}, user_id)
        applied += 1
    audit(c, "ijro.apply", "task", None, {"applied": applied, "skipped": skipped})
    return {"applied": applied, "skipped": skipped}


def brief(c, items: list[dict], admin: bool = True) -> None:
    """Adds a short 'site' note to the rows of the task list: the link and whether the site disagrees. An employee gets it for their own tasks only."""
    if not items:
        return
    ids = [t["id"] for t in items]
    snaps = {r["task_id"]: r for r in c.execute(f"SELECT * FROM ijro_snapshots WHERE task_id IN ({','.join('?' * len(ids))})", ids)}
    for t in items:
        r = snaps.get(t["id"])
        if not r:
            t["site"] = None
            continue
        info = site_info(r, t["status"], t["due"], admin)
        t["site"] = {"found": info["found"], "label": info["label"], "diff": info["diff"], "link": info["link"], "exact": info["exact_link"],
                     "stage": {"code": info["stage"]["code"], "n": info["stage"]["n"], "label": info["stage"]["label"], "attention": info["stage"]["attention"]},
                     "site_open_we_done": info["site_open_we_done"], "checked_at": info["checked_at"]}


HEX24 = __import__("re").compile(r"[0-9a-f]{24}", __import__("re").I)


def detect_template(c, url: str) -> dict:
    """The address of an opened task card on the site tells where the number of the task sits: find a number we have read from the
    site (the id of the task for us, or the id of the task itself) inside it and turn the address into a template."""
    import re
    from urllib.parse import urlparse
    u = urlparse(url.strip())
    if u.scheme != "https" or u.netloc != "edo.ijro.uz" or " " in url:
        raise ValueError("Нужен адрес со страницы edo.ijro.uz (https://edo.ijro.uz/...)")
    snaps = {}
    for r in c.execute("SELECT s.recipient_id, s.task_ref, s.section, t.code FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id WHERE s.found=1"):
        if r["recipient_id"]:
            snaps.setdefault(r["recipient_id"].lower(), ("{id}", r))
        if r["task_ref"]:
            snaps.setdefault(r["task_ref"].lower(), ("{task_id}", r))
    for m in HEX24.finditer(url):
        hit = snaps.get(m.group(0).lower())
        if hit:
            mark, r = hit
            tpl = url[:m.start()] + mark + url[m.end():]
            for sec in SECTIONS["sections"]:
                tpl = tpl.replace("/" + sec["path"] + "/", "/{section_path}/")
            return {"template": tpl, "code": r["code"], "section": r["section"], "mark": mark}
    if HEX24.search(url):
        raise ValueError("В адресе есть номер, но он не совпал ни с одной прочитанной задачей. Откройте карточку задачи из списка, которую уже проверяла синхронизация, и вставьте её адрес.")
    raise ValueError("В адресе нет номера задачи. Откройте карточку задачи (не список) и скопируйте адрес из строки браузера.")
