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
from datetime import date, datetime, timedelta, timezone

from . import tasks
from .db import STATUSES, TZ, audit, now, setting, today

SECTIONS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ijro_sections.json"), encoding="utf-8"))
SECTION_BY_ID = {s["id"]: s for s in SECTIONS["sections"]}
EDO_API = "https://edo.ijro.uz/api"
# the tabs of the site that the export is taken for (their statuses are those the site itself sends): what is open and what is overdue.
# The Bajarilgan tab brings the closed ones: they are heavy (the president's list is ~8 MB, up to a minute on the site) but give the status of every task of the window at once.
# of the Cabinet's list only «Вазирлар маҳкамаси қарори (Янги)» is downloaded (the platform also drops the other kinds when a file is imported)
EXPORT_TYPES_ONLY = {"government": ["68d805f2c8d2f3123184e0f4"]}
EXPORT_TABS = [{"id": "in_progress", "statuses": [-1, 1, 0, 2, 3, 4], "open": True}, {"id": "overdue", "statuses": [10, 12, 11, 13, 14], "open": True},
               {"id": "done", "statuses": [20, 21, 31], "open": False}]   # Bajarilgan: done, done late, closed without execution
MAX_ITEMS = 200
MAX_TEXT = 600
MAX_ANSWERS = 30
MAX_ORG = 120          # the name of the body that gave an answer

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


_DAYS = {"t": 0.0, "v": 30}


def history_days() -> int:
    """How many days back the answers of the site count (the setting; 0 = the whole history). Read at most once in a few seconds: a list of tasks asks it for every row."""
    import time
    if time.time() - _DAYS["t"] > 3:
        v = setting("history_days")
        _DAYS.update(t=time.time(), v=int(v) if str(v).isdigit() else 30)
    return _DAYS["v"]


def reset_history_days() -> None:
    _DAYS["t"] = 0.0


def window_ms() -> int | None:
    """The oldest moment an answer may have to count (the start of the day `history_days` days ago, UTC), or None for the whole history."""
    d = history_days()
    return int(datetime.combine(today() - timedelta(days=d), datetime.min.time(), timezone.utc).timestamp() * 1000) if d else None


def live_answers(snap) -> tuple[list[dict], int]:
    """(the answers inside the window, how many the site has). An answer without a date is kept: nothing says it is old."""
    allv = json.loads(snap["answers"] or "[]")
    cut = window_ms()
    keep = [a for a in allv if cut is None or not a.get("at_ms") or a["at_ms"] >= cut]
    total = snap["answers_total"] if "answers_total" in snap.keys() else 0
    return keep, max(len(allv), total or 0)


def _opt(snap, key):
    """A field of a snapshot that older rows (and the tests' dictionaries) may not have."""
    return snap[key] if key in snap.keys() else None


def _local_day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TZ).date().isoformat()


def term_changed_after(snap, answer_ms: int) -> bool:
    """The Chamber of Accounts accepted the answer for information at `answer_ms`. Was the term of the task changed (extended) AFTER that?
    Then the task has been dealt with: a new term is in place, nothing waits for us. What the site gives (checked on its real cards): the card's flag «due_date_changed» is true
    for EVERY task whose term was ever changed, so it cannot tell one task from another; the `updated_time` of the LIST row is moved by every answer (34 ms after it);
    the `updated_time` of the TASK in its card moves only when the task itself is changed (its term extended): for the tasks that really got a new term it is days after
    the Chamber's answer, for the tasks that did not it is months before it. The Excel list has a date of the extension too («Муддат узайтириш санаси»). In this order:
      the extension date of the Excel list: on or after the day of the answer -> yes, earlier -> no;
      the card says the term was never changed -> no;
      the task itself was changed on the site (the card's updated_time), or the card's modification date, later than a minute after the answer -> yes;
      the change that the synchronisation saw after the answer; the list row changed more than 5 minutes after the answer (old data without the card's time) -> yes;
      nothing of this: the task stays «Палата вернула» (a task is not taken out of the list that waits for us on a guess)."""
    ext = _opt(snap, "ext_date")
    if ext:
        return ext >= _local_day(answer_ms)
    if _opt(snap, "due_changed") == 0:
        return False
    tupd, mod = _opt(snap, "task_updated_ms"), _opt(snap, "due_mod_ms")
    if (tupd and tupd > answer_ms + 60 * 1000) or (mod and mod > answer_ms + 60 * 1000):
        return True
    seen, upd = _opt(snap, "term_seen_ms"), _opt(snap, "updated_ms")
    if seen and seen > answer_ms:
        return True
    return bool(upd and upd > answer_ms + 5 * 60 * 1000)


def term_evidence(snap, answer_ms: int) -> str:
    """What the platform knows about the term of a task that the Chamber returned, in words (for the administrator): to see at once why it is where it is."""
    fd = lambda iso: iso[8:10] + "." + iso[5:7] + "." + iso[:4]
    ft = lambda ms: datetime.fromtimestamp(ms / 1000, TZ).strftime("%d.%m.%Y %H:%M")
    ext, mod, seen, upd, tupd = _opt(snap, "ext_date"), _opt(snap, "due_mod_ms"), _opt(snap, "term_seen_ms"), _opt(snap, "updated_ms"), _opt(snap, "task_updated_ms")
    parts = [f"ответ Палаты: {ft(answer_ms)}",
             f"дата продления срока в списке сайта: {fd(ext)}" if ext else "даты продления срока в списке сайта нет (загрузите свежий список Excel)",
             f"дата изменения срока в карточке: {ft(mod)}" if mod else "",
             f"задача (карточка) изменена на сайте: {ft(tupd)}" if tupd else ("карточка задачи ещё не читалась скриптом 1.8.4" if not upd else ""),
             f"запись в списке изменена: {ft(upd)}" if upd else "",
             {1: "карточка сайта: срок задачи менялся когда-то (флаг не говорит когда)", 0: "карточка сайта: срок задачи не менялся"}.get(_opt(snap, "due_changed"), ""),
             f"синхронизация увидела новый срок: {ft(seen)}" if seen else ""]
    return "; ".join(x for x in parts if x)


def stage_of(snap, due: str | None = None, dates: bool = True) -> dict:
    """Where the task is on its way. {code, n (index in STAGE_STEPS, -1 = no answer yet), label, hint, attention, new_due}.
    code 'info': the Chamber of Accounts sent it back (accepted for information / asked for more): the task is NOT done and its term changes."""
    base = {"steps": [{"code": c, "label": l, "hint": h} for c, l, h in STAGE_STEPS], "new_due": None, "attention": False}
    if not snap["found"]:
        return base | {"code": "not_found", "n": None, "label": "Не найдена на сайте", "hint": ""}
    periods = json.loads(snap["periods"] or "[]")
    periodic = bool(snap["repeatable"] and periods)
    scope_all = json.loads(snap["answers"] or "[]")          # everything stored; the answers older than the window do not count for the stage
    cut = window_ms()
    answers = [a for a in scope_all if cut is None or not a.get("at_ms") or a["at_ms"] >= cut]
    if periodic:
        # A periodic task has one list of answers for all its periods; each answer carries the term of its period ("pd"). The stage is read from the answers of
        # the period that our deadline stands for. A period that is done is simply done (the site's own status of the period says so).
        if classify(snap, due, dates=False)["status"] == "done":
            return base | {"code": "removed", "n": 4, "label": "Назоратдан ечилди", "hint": "Период выполнен, снят с контроля"}
        want = _day((current_period(periods, due) or {}).get("due_ms"))
        if want is None or not any(a.get("pd") for a in answers):
            # the answers do not say which period they belong to (read by an older collector): no stage is claimed, none is guessed
            return base | {"code": "period_unknown", "n": -1, "label": "Этап периода уточняется",
                           "hint": "Периодическая задача: этап берётся из ответов именно этого периода. Он появится после обновления скрипта и новой проверки задачи"}
        scope_all = [a for a in scope_all if a.get("pd") and _day(a["pd"]) == want]
        answers = [a for a in answers if a.get("pd") and _day(a["pd"]) == want]
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
        nd = None if periodic else _day(snap["due_ms"])
        accepted = any(w in (cur.get("text") or "").lower() for w in ACCEPTED_WORDS)
        ev = term_evidence(snap, cur.get("at_ms") or 0) if dates and cur.get("at_ms") else ""
        if term_changed_after(snap, cur.get("at_ms") or 0):       # the new term was set after the answer: the task is not waiting for an answer of ours any more
            return base | {"evidence": ev, "code": "info_term", "n": 3, "label": "Срок изменён после ответа Палаты",
                           "hint": "Счётная палата приняла ответ к сведению, затем срок задачи на сайте был изменён. Задача НЕ выполнена, но ответа от нас сейчас не ждут.",
                           "attention": False, "new_due": nd.isoformat() if nd and dates else None}
        return base | {"evidence": ev, "code": "info", "n": 3, "label": "Маълумот учун қабул қилинди" if accepted else "Қўшимча маълумот сўрови",
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
    site_total = (snap["answers_total"] if "answers_total" in snap.keys() else 0) or 0
    if not answers and (scope_all or (site_total and not periodic)):   # the site has answers, but none in the last days: the stage is not guessed from an old one
        return base | {"code": "quiet", "n": -1, "label": f"Нет ответов за последние {history_days()} дн.",
                       "hint": f"Последний ответ на сайте старше {history_days()} дней (всего ответов: {max(len(scope_all), site_total)}): этап по такой истории не определяется. Откройте задачу на сайте."}
    if snap["site_status"] == 2 and not periodic:           # for a periodic task the general status says nothing about this period
        return base | {"code": "answered", "n": 0, "label": "Киритилди", "hint": "Ответ введён; этап уточнится при следующей проверке (нет данных об ответах)"}
    return base | {"code": "none", "n": -1, "label": "Ответ не введён", "hint": "Исполнитель ещё не ответил"}


def auto_apply(c, task_id: int) -> list[str]:
    """After a check: what is clear is applied without a review. Never lowers a status by itself, except one case the administrator named:
    the Chamber accepted the answer for information, so a task we had marked done is open again, with the new term.
    Returns what was done (for the log)."""
    r = c.execute("SELECT s.*, t.status AS our_status, t.due, t.status_manual FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id WHERE s.task_id=?", (task_id,)).fetchone()
    if not r or r["our_status"] == "info" or not r["found"] or r["status_manual"]:
        return []                           # a status that a person set stays as it is: the site does not change it
    cl, st, done = classify(r, r["due"]), stage_of(r, r["due"]), []
    changes: dict = {}
    if cl["status"] == "done" and r["our_status"] != "done":
        changes["status"] = "done"
    elif cl["status"] == "progress" and r["our_status"] == "todo":
        changes["status"] = "progress"
    elif r["our_status"] == "todo" and cl.get("open") and st["code"] in ("moj", "cab", "chamber", "info", "returned", "chamber_other"):
        changes["status"] = "progress"
    if st["code"] in ("info", "info_term"):
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


def _open_stage_rows(c, month: str = "", by: str = "close"):
    q = """SELECT s.*, t.due, t.id AS tid FROM tasks t LEFT JOIN ijro_snapshots s ON s.task_id=t.id WHERE t.status IN ('todo','progress')"""
    args: tuple = ()
    if month:                                                    # only the tasks whose term (the date the dashboard is built on) falls in this month
        q += f" AND substr({tasks.eff_sql(by)}, 1, 7) = ?"
        args = (month,)
    return c.execute(q, args).fetchall()


def funnel(c, month: str = "", by: str = "close") -> dict:
    """How many open tasks are at each stage (for the dashboard). Tasks never checked on the site are counted apart."""
    counts = {k: 0 for k, _, _ in FUNNEL}
    unchecked = other = 0
    for r in _open_stage_rows(c, month, by):
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


def stage_map(c) -> dict[int, str]:
    """{id of an open task: its stage on the way of the answer}: one of the keys of FUNNEL, 'unchecked' (never read from the site) or 'other' (a stage that is not on the way:
    not found on the site, not recognised ...). The dashboard counts by it, and the list filter ?stage= selects by it, so the two always agree."""
    out: dict[int, str] = {}
    for r in _open_stage_rows(c):
        out[r["tid"]] = "unchecked" if r["task_id"] is None else (_FUNNEL_OF.get(stage_of(r, r["due"], dates=False)["code"]) or "other")
    return out


def stage_ids(c, key: str) -> list[int]:
    """Ids of the open tasks at a stage of the funnel ('unchecked' = never read from the site, 'other' = not on the way)."""
    return [tid for tid, k in stage_map(c).items() if k == key]


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


# ---------------------------------------------------------------- the settings of the import and the synchronisation (shown with explanations on the Settings page)

SYNC_GROUPS = [
    {"id": "base", "title": "Загрузка базы задач (страница «Импорт»)",
     "help": "Каждая загрузка — это база. Выберите на странице «Импорт» файлы Excel с сайта (можно сразу несколько, например по одному на раздел): они читаются вместе и "
             "перезаписывают то, что есть на сервере."},
    {"id": "history", "title": "Синхронизация этапов (кнопка «Синхронизировать» в скрипте)",
     "help": "Скрипт только читает с сайта историю этапов (ответы Адлии, Кабинета, Счётной палаты) и записывает её к задачам, которые уже есть в базе. Новых задач он не создаёт, "
             "а задачи и их статусы приходят из загруженной базы. Здесь выбирается, у каких задач историю читать."},
    {"id": "lists", "title": "Скачивание списков скриптом (по умолчанию выключено)",
     "help": "Дополнительная возможность, нужна только если в скрипте включена кнопка «Скачивать списки: вкл»: скрипт сам приносит списки с сайта вместо ручной загрузки "
             "базы. Для обычной работы (база загружается вручную) эти два пункта не нужны."},
]
SYNC_FIELDS = [
    {"key": "base_f_dept", "group": "base", "title": "Брать только отделы нашей структуры", "kind": "switch",
     "help": "Берутся строки тех отделов, которые есть в структуре департамента или которые вы сопоставили с ней на странице «Импорт». Решение по каждому отделу файла вы принимаете там же, в таблице "
             "«Отделы в выгрузке»: «не наш отдел» значит не загружать. Строки сотрудников, которые у нас уже есть, берутся в любом случае. Выключите, чтобы брать все строки: "
             "задачи отделов вне структуры попадут в строку «Без отдела»."},
    {"key": "base_f_exec", "group": "base", "title": "Брать только исполнителя «Соғлиқни сақлаш вазирлиги»", "kind": "switch",
     "help": "Берутся строки, где в колонке «Масъул ижрочи» стоит Соғлиқни сақлаш вазирлиги. Строки с «-» (роль «Тенг кучли») и других органов отбрасываются. "
             "По умолчанию выключено: файлы вы отбираете сами. Включите, если в них остаются чужие исполнители."},
    {"key": "base_f_kind", "group": "base", "title": "Отбрасывать соисполнителей и лишние виды документов", "kind": "switch",
     "help": "Не берутся строки соисполнителей (роль «Ҳамижрочи») и виды документов Кабинета министров, кроме «Қарор (Янги)». Нужно для сырых списков с сайта; для отобранных файлов обычно выключено."},
    {"key": "base_f_window", "group": "base", "title": "Брать только сроки в окне", "kind": "switch",
     "help": "Берутся только задачи, срок которых попадает в окно ниже (дней назад и вперёд от сегодня). Для файлов за один месяц не нужно: выключено по умолчанию."},
    {"key": "base_manual", "group": "base", "title": "Ваши ручные правки при загрузке базы", "kind": "choice", "options": [
        ("overwrite", "База перезаписывает (по умолчанию)",
         "Статус и ответственный (а также дата закрытия, если она есть в файле) возвращаются к значениям из файла, даже если вы меняли их вручную. Перед загрузкой страница «Импорт» "
         "показывает, сколько ваших правок будет перезаписано. Дата закрытия, которой нет в файле, не стирается."),
        ("keep", "Правки сохраняются",
         "Задачи, которые вы правили вручную (статус, ответственный, дата закрытия), загрузка не трогает: обновляются только их тексты и сроки из файла.")]},
    {"key": "base_absent", "group": "base", "title": "Задачи, которых нет в загруженной базе (выбор по умолчанию)", "kind": "choice", "options": [
        ("gone", "Снимаются с дашборда (по умолчанию)",
         "Задачи, которых нет в загруженных файлах (в том числе выполненные), получают статус «Нет на сайте» и пропадают с дашборда и из списков, так что в базе остаётся только то, что в файлах. "
         "Ничего не удаляется: история остаётся, задача вернётся, если появится в следующей базе. Задачи, добавленные вручную, не трогаются. Если уходит больше четверти задач, нужно подтверждение: "
         "так платформа защищается от неполной загрузки (например, выбран один раздел из трёх)."),
        ("keep", "Остаются как есть (добавление к существующим)", "Задачи, которых нет в файле, не трогаются: файлы только добавляют и обновляют. Удобно для загрузки других месяцев поверх уже загруженных. Выбор можно сменить при каждой загрузке на странице «Импорт».")]},
    {"key": "sync_source", "group": "lists", "title": "Что скачивает скрипт синхронизации", "kind": "choice", "options": [
        ("lists", "Три общих списка (по умолчанию)",
         "По одному списку на раздел: Президент, Администрация Президента, Кабинет Министров (только «Қарор (Янги)»). В каждом сразу все статусы (Бажарилмоқда, Бажарилган, "
         "Муддати ўтган): статус задачи берётся из колонки «Топшириқ ҳолати», вкладки не нужны. 3 файла вместо девяти: быстрее и меньше шансов на обрыв. "
         "Файлы крупнее, потому что в них и выполненные задачи, сайт может готовить их до минуты."),
        ("tabs", "По разделам и вкладкам: 9 файлов",
         "Прежний способ: три раздела × три вкладки («в работе», «просрочено», «выполнено»). Каждый файл меньше. Выберите его, если общие списки не скачиваются или обрываются.")]},
    {"key": "sync_apply", "group": "lists", "title": "Что делает скачанный скриптом список", "kind": "choice", "options": [
        ("status", "Только обновляет статусы (по умолчанию)",
         "Обновляются статусы задач, которые УЖЕ есть в базе. Новые задачи не создаются, тексты, сроки и ответственные не меняются, задачи с вашими правками не трогаются. "
         "Строки, которых нет в базе, только считаются (в итоге синхронизации и на странице «Импорт»). Новые задачи добавляйте через «Импорт базы задач»."),
        ("base", "Обновляет статусы и добавляет новые задачи",
         "Как «Импорт базы задач»: новые задачи создаются (с сотрудниками без пароля), у существующих обновляются тексты, документ и срок. Берутся сроки в окне ниже. "
         "Удобно, если задачи приходят постоянно и вы не хотите загружать базу вручную.")]},
    {"key": "base_back", "group": "base", "title": "Окно сроков: дней назад", "kind": "days",
     "help": "Действует, когда включено «Брать только сроки в окне», и при скачивании списков скриптом: в базу берутся задачи, срок которых не раньше, чем столько дней назад. "
             "Пусто — без ограничения. По умолчанию 30. То же окно подставляется в поля дат на странице «Импорт», там его можно изменить для одной загрузки."},
    {"key": "base_fwd", "group": "base", "title": "Окно сроков: дней вперёд", "kind": "days",
     "help": "…и не позже, чем через столько дней. Пусто — без ограничения. По умолчанию 60."},
    {"key": "history_scope", "group": "history", "title": "У каких задач читать историю этапов", "kind": "choice", "options": [
        ("all", "Все невыполненные задачи базы (по умолчанию)",
         "Проверяются все задачи базы со статусом «Не выполнено» и «В работе». Основной режим: база загружается заново каждый раз и содержит только нужный период, поэтому отдельный отбор по "
         "месяцу не нужен. Время проверки растёт с числом задач: примерно 250 задач за несколько минут."),
        ("month", "Только срок в текущем месяце",
         "История читается только у задач, срок которых приходится на текущий месяц. Подойдёт, если в базе много месяцев и нужны только текущие. Внимание: если база за следующий месяц, "
         "а сегодня ещё этот, под «текущий месяц» попадёт лишь часть задач (или ни одной). Задачи без срока в этот режим не попадают."),
        ("month_overdue", "Текущий месяц и просроченные прошлых",
         "Текущий месяц плюс все ещё не выполненные задачи с более ранним сроком: чтобы не потерять давно просроченное, пока оно не закрыто."),
        ("month_next", "Текущий и следующий месяц", "Удобно в конце месяца: следующий уже в работе, а этапы нужны заранее.")]},
    {"key": "history_days", "group": "history", "title": "За какой срок читать и хранить ответы сайта", "kind": "choice", "options": [
        ("30", "Последний месяц (по умолчанию)", "Читаются и хранятся только ответы за последние 30 дней: в карточке задачи видна свежая история, этап определяется по ней. "
         "Если последний ответ на сайте старше, задача получает пометку «Нет ответов за последние 30 дн.» (этап не угадывается по старому ответу), а на дашборде попадает в «Другое»."),
        ("90", "Три месяца", "Для задач, которые долго идут по цепочке согласования. История длиннее, этапов определяется больше."),
        ("0", "Вся история", "Читается и хранится всё, что есть на сайте (до 30 последних ответов). Этап считается по самому свежему ответу, каким бы старым он ни был.")]},
    {"key": "history_groups", "group": "history", "title": "Какие группы задач проверять синхронизацией", "kind": "choice", "options": [
        ("all", "Все группы (по умолчанию)", "Этапы читаются у задач всех трёх групп: Асосий ижрочи, Ҳамижрочи и ВМ топшириқлари. Тогда вкладка «По этапам согласования» работает в каждой группе. Проверка занимает дольше, чем только по основным."),
        ("main", "Только Асосий ижрочи", "Читаются только основные задачи. Для групп Ҳамижрочи и ВМ топшириқлари этапы не читаются: на их дашбордах в «По этапам согласования» задачи будут в колонке «Не проверялись».")]},
    {"key": "sync_parallel", "group": "history", "title": "Сколько задач читать одновременно", "kind": "choice", "options": [
        ("1", "По одной", "Самый бережный режим: сайт нагружается минимально, но проверка 250 задач занимает около 5 минут."),
        ("2", "По две", "Вдвое быстрее, чем по одной."),
        ("3", "По три (по умолчанию)", "Хорошее соотношение: около 250 задач за 1,5–2 минуты. Если сайт начнёт отвечать ошибками, скрипт сам замедлится."),
        ("4", "По четыре", "Быстрее, но чаще упирается в ограничения сайта."),
        ("5", "По пять", "Самый быстрый режим. Выбирайте, только если сайт не жалуется.")]},
    {"key": "history_date", "group": "history", "title": "Какой срок решает, в каком месяце задача", "kind": "choice", "options": [
        ("close", "Дата закрытия, иначе официальный срок (по умолчанию)", "Как на дашборде по умолчанию: ваша внутренняя дата закрытия, а если её нет, то официальный срок."),
        ("due", "Официальный срок, иначе дата закрытия", "Срок из поручения («Топшириқ муддати»); дата закрытия подставляется, только если срока нет.")]},
    {"key": "history_statuses", "group": "history", "title": "Статусы задач, у которых читать историю", "kind": "choice", "options": [
        ("open", "Только невыполненные (по умолчанию)",
         "У задач «Выполнено» и «К сведению» история не читается: их статус берётся из выгрузки, этапы им не нужны. Самое быстрое."),
        ("all", "И у выполненных", "Читать историю и у завершённых задач. Нужно редко (например, чтобы увидеть, кто и когда снял с контроля), но проверка заметно дольше.")]},
]
SYNC_KEYS = {f["key"]: f for f in SYNC_FIELDS}


def sync_settings_view() -> list[dict]:
    """The fields of the Settings block with their current values and the explanations."""
    out = []
    for f in SYNC_FIELDS:
        d = {"key": f["key"], "group": f["group"], "title": f["title"], "kind": f["kind"], "value": setting(f["key"])}
        if f["kind"] == "choice":
            d["options"] = [{"value": v, "label": lbl, "help": h} for v, lbl, h in f["options"]]
        else:
            d["help"] = f["help"]            # a switch ("1" / "0") or a number of days
        out.append(d)
    return out


def check_sync_settings(values: dict) -> dict:
    """Validates {key: value} of the block; returns what to store. ValueError with a message for the person otherwise."""
    clean = {}
    for k, v in values.items():
        f = SYNC_KEYS.get(k)
        if not f:
            raise ValueError("Неизвестная настройка: " + str(k))
        if f["kind"] == "choice":
            if v not in [o[0] for o in f["options"]]:
                raise ValueError(f"«{f['title']}»: допустимо " + ", ".join(o[0] for o in f["options"]))
            clean[k] = v
        elif f["kind"] == "switch":
            if v not in ("0", "1", 0, 1, True, False):
                raise ValueError(f"«{f['title']}»: допустимо 0 или 1")
            clean[k] = "1" if v in ("1", 1, True) else "0"
        else:
            v = "" if v is None else str(v).strip()
            if v != "" and not (v.isdigit() and int(v) <= 3660):
                raise ValueError(f"«{f['title']}»: число дней от 0 до 3660 или пусто (без ограничения)")
            clean[k] = v
    return clean


def history_filter() -> tuple[str, list]:
    """The part of the query that says WHOSE history (answers, stages) is read, by the settings: which statuses of ours, and which month of the term.
    A task without any term is outside every month scope (there is nothing to put it in)."""
    sts = ("todo", "progress", "done", "info") if setting("history_statuses") == "all" else ("todo", "progress")
    sql, args = f" AND t.manual IN (0, 2) AND t.status IN ({','.join('?' * len(sts))})", list(sts)          # a task added by hand (manual=1) is not on the site: nothing to read; one added by its code (manual=2) is read like any other
    if setting("history_groups") == "main":
        sql += " AND t.scope='main'"
    scope = setting("history_scope")
    if scope in ("month", "month_next", "month_overdue"):
        eff = tasks.eff_sql("due" if setting("history_date") == "due" else "close")
        ym = today().isoformat()[:7]
        if scope == "month":
            sql += f" AND substr({eff}, 1, 7) = ?"
            args.append(ym)
        elif scope == "month_next":
            nxt = f"{int(ym[:4]) + (ym[5:] == '12')}-{(int(ym[5:]) % 12) + 1:02d}"
            sql += f" AND substr({eff}, 1, 7) IN (?, ?)"
            args += [ym, nxt]
        else:     # this month and everything earlier that is still open
            sql += f" AND ({eff} IS NOT NULL AND substr({eff}, 1, 7) <= ?)"
            args.append(ym)
    return sql, args


CLAIM_MINUTES = 5          # a task that somebody else has taken is left to them for this long (then it is free again: that one may have closed the tab)
SHARE_MINUTES = 10         # a task that somebody else has read this recently is not read again


def _ago(minutes: int) -> str:
    from datetime import timedelta
    return (datetime.now(TZ) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def claim(c, key_id: int, run_id: int, codes: list) -> dict:
    """Several people may run the synchronisation at the same time. Before reading a few tasks the collector asks which of them it may take:
    those that another key has taken in the last minutes or has read in the last minutes are left to the other. {granted: [...], taken: [...]}."""
    codes = [x for x in codes if isinstance(x, str)][:100]
    if not codes:
        return {"granted": [], "taken": []}
    ids = {}
    for r in c.execute(f"SELECT id, COALESCE(NULLIF(site_code, ''), code) AS code FROM tasks WHERE COALESCE(NULLIF(site_code, ''), code) IN ({','.join('?' * len(codes))}) ORDER BY id", codes):
        ids.setdefault(r["code"], r["id"])
    granted, taken = [], []
    busy = {r["task_id"] for r in c.execute("SELECT task_id FROM sync_claims WHERE key_id IS NOT ? AND claimed_at >= ?", (key_id, _ago(CLAIM_MINUTES)))}
    fresh = {r["task_id"] for r in c.execute("""SELECT s.task_id FROM ijro_snapshots s LEFT JOIN sync_runs r ON r.id=s.run_id
                                                WHERE s.checked_at >= ? AND r.key_id IS NOT NULL AND r.key_id IS NOT ?""", (_ago(SHARE_MINUTES), key_id))}
    for code in codes:
        tid = ids.get(code)
        if tid is None or tid in busy or tid in fresh:
            taken.append(code)
            continue
        c.execute("INSERT INTO sync_claims(task_id, run_id, key_id, claimed_at) VALUES (?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET run_id=excluded.run_id, key_id=excluded.key_id, claimed_at=excluded.claimed_at",
                  (tid, run_id, key_id, now()))
        granted.append(code)
    return {"granted": granted, "taken": taken}


def job(c, key_id: int, resume: bool = False) -> dict:
    """The tasks the collector must look up. Which ones is a setting (history_scope / history_statuses / history_date): by default the open tasks whose
    term is in the current month. The section order for each follows the document kind.
    With resume, what was checked in the last hours is skipped: the run goes on where an interrupted one stopped."""
    cond, args = history_filter()
    sql = "SELECT t.id, COALESCE(NULLIF(t.site_code, ''), t.code) AS code, t.kind, t.scope FROM tasks t WHERE t.status_manual=0" + cond      # a task whose status a person set is not checked
    if resume:
        from datetime import timedelta
        sql += " AND t.id NOT IN (SELECT task_id FROM ijro_snapshots WHERE checked_at >= ?)"
        args.append((datetime.now(TZ) - timedelta(hours=RESUME_HOURS)).strftime("%Y-%m-%d %H:%M:%S"))
    rows, seen_codes = [], set()
    for r in c.execute(sql + " ORDER BY t.seq, t.id", args).fetchall():      # the periods of a periodic task are one task on the site: it is read once, the result goes to all its periods
        if r["code"] not in seen_codes:
            seen_codes.add(r["code"])
            rows.append(r)
    cond0, args0 = history_filter()
    outside = c.execute("SELECT COUNT(*) FROM tasks t WHERE t.manual IN (0, 2) AND t.status_manual=0 AND t.status IN ('todo','progress') AND t.id NOT IN (SELECT t.id FROM tasks t WHERE 1=1" + cond0 + ")", args0).fetchone()[0]
    by_kind = {k: s["id"] for s in SECTIONS["sections"] for k in s["kinds"]}
    cur = c.execute("INSERT INTO sync_runs(key_id, started_at, expected) VALUES (?,?,?)", (key_id, now(), len(rows)))
    return {"run_id": cur.lastrowid, "outside_scope": outside, "scope": setting("history_scope"), "api_tasks": SECTIONS["api_tasks"], "sections": SECTIONS["sections"],
            "manual_locked": c.execute("SELECT COUNT(*) FROM tasks t WHERE t.status_manual=1 AND t.manual IN (0, 2) AND t.status IN ('todo','progress','done')").fetchone()[0],
            "parallel": max(1, min(5, int(setting("sync_parallel") or 3))), "answers_days": history_days(), "items": [{"code": r["code"], "section": "government" if r["scope"] == "vm" else by_kind.get(r["kind"], "")} for r in rows]}


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


def cabinet_removed(snap) -> bool:
    """A document of the CABINET OF MINISTERS (its list on the site): its way ends with the Cabinet. The answer «Nazoratdan olishni tasdiqlandi» (35) of the Cabinet is the last
    one in the history: the task is removed from control, i.e. done. (For the President's documents the way goes on to the Chamber of Accounts, so there it is only a step.)"""
    if _opt(snap, "section") != "government" or not snap["found"]:
        return False
    cur = current_answer(live_answers(snap)[0])
    return bool(cur) and cur["sender_type"] == T_REMOVAL


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
        return {"status": None, "label": f"Период {k} из {n} не выполнен{tail}", "note": f"Периодическая задача, выполнено периодов: {done} из {n}. Общий статус на сайте остаётся «в работе»", "known": True, "open": True}
    if cabinet_removed(snap):
        return {"status": "done", "label": "Снято с контроля Кабинетом Министров", "known": True,
                "note": "Для документов Кабинета Министров подтверждение снятия с контроля (Nazoratdan olishni tasdiqlandi) последнее: Счётная палата не участвует, задача выполнена."}
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
    """The answers as the card shows them: the NEWEST first, each with the body that gave it (Ҳисоб палатаси, Вазирлар Маҳкамаси, Адлия вазирлиги, the executor ...)."""
    out = []
    for a in live_answers(snap)[0]:
        out.append({"type": ANSWER_TYPES.get(a.get("sender_type"), f"Тип {a.get('sender_type')}"), "sender_type": a.get("sender_type"),
                    "state": a.get("state"), "at": _ts(a.get("at_ms")), "text": "" if snap["is_secret"] else a.get("text", ""),
                    "active": bool(a.get("active")), "org": "" if snap["is_secret"] else (a.get("org") or "")})
    out.reverse()          # stored oldest -> newest (the collector sorts by time; the order of the site is kept for equal times)
    return out


def shown(snap, due: str | None, dates: bool = True) -> tuple[dict, dict, str, str]:
    """(classification, stage, label, note) as they are shown. The site's number 2 stays after an answer, after a return (29) and after the
    Chamber's request (49) alike, so the number alone says "the answer is being approved" also when the task is back with us. Then the stage speaks."""
    cl, st = classify(snap, due, dates=dates), stage_of(snap, due, dates=dates)
    label, note = cl["label"], cl["note"]
    if st["code"] == "info_term":
        label, note = "Срок изменён после ответа Палаты", st["hint"]
    elif cl["status"] == "progress" and st["code"] in ("info", "returned", "chamber_other"):
        label = {"info": "Вернулась от Счётной палаты — ждёт вашего ответа", "returned": "Вернулась к вам — ждёт вашего ответа", "chamber_other": "Ответ Счётной палаты: проверьте на сайте"}[st["code"]]
        note = st["hint"]
    return cl, st, label, note


def site_info(snap, our_status: str, due: str | None = None, admin: bool = True, locked: bool = False) -> dict:
    """The block 'С ijro.uz' of a task card: for administrators, and for the employee a task is assigned to (without the official term)."""
    cl, st, label, note = shown(snap, due, dates=admin)
    diff = bool(cl["status"] and cl["status"] != our_status and our_status != "info") and not locked
    return {"found": bool(snap["found"]), "section": snap["section"], "section_name": (SECTION_BY_ID.get(snap["section"]) or {}).get("name", ""),
            "label": label, "note": note, "known": cl["known"], "proposed": cl["status"],
            "proposed_label": STATUSES.get(cl["status"], "") if cl["status"] else "", "diff": diff,
            "site_open_we_done": bool(snap["found"] and cl["known"] and (cl["status"] in ("todo", "progress") or cl.get("open")) and our_status == "done") and not locked, "locked": locked,
            "checked_at": snap["checked_at"], "link": card_link(snap), "exact_link": bool(setting("ijro_card_tpl").strip() and snap["recipient_id"]),
            "secret": bool(snap["is_secret"]), "answers": answers_out(snap), "answers_total": live_answers(snap)[1], "answers_days": history_days(), "late": snap["site_status"] == 21,
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
    by_site: dict[str, list[int]] = {}
    for r in c.execute("SELECT id, COALESCE(NULLIF(site_code, ''), code) AS code FROM tasks ORDER BY id"):
        by_site.setdefault(r["code"], []).append(r["id"])
    stored = found = 0
    touched: list[int] = []
    expanded = [(tid, it) for it in items if isinstance(it, dict) and isinstance(it.get("code"), str) for tid in by_site.get(it["code"], [])]   # a code we do not have is ignored: the collector can never create tasks; the periods of a periodic task are all one code
    term_split = 0
    for tid, it in list(expanded):                           # the official term of an ordinary open task moved to another month since the last check: see tasks.split_term
        new_ms = _int(it.get("due_ms"))
        if not (it.get("found") and it.get("section") in SECTION_BY_ID and not it.get("repeatable") and new_ms):
            continue
        prev = c.execute("SELECT due_ms, repeatable FROM ijro_snapshots WHERE task_id=?", (tid,)).fetchone()
        if not prev or not prev["due_ms"] or prev["repeatable"]:
            continue
        d_old, d_new = _day(prev["due_ms"]).isoformat(), _day(new_ms).isoformat()
        row = c.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()
        if d_old[:7] != d_new[:7] and row and row["due"] and row["due"][:7] != d_new[:7]:
            new_id = tasks.split_term(c, tid, d_new)
            if new_id:
                term_split += 1
                if new_id not in [x for x, _ in expanded]:
                    expanded.append((new_id, it))
    for tid, it in expanded:
        sec = it.get("section") if it.get("section") in SECTION_BY_ID else ""
        is_found = bool(it.get("found")) and bool(sec)
        periods = []
        for p in ((it.get("periods") or []) if is_found else [])[:20]:
            if isinstance(p, dict):
                periods.append({"order": _int(p.get("order")), "status": _int(p.get("status")), "recipient_status": _int(p.get("recipient_status")), "due_ms": _int(p.get("due_ms"))})
        answers = []
        secret = bool(it.get("is_secret"))
        raw_answers = ((it.get("answers") or []) if is_found else [])[-MAX_ANSWERS:]
        cut = window_ms()
        total = max(len(raw_answers), _int(it.get("answers_total")) or 0)
        for a in raw_answers:
            if cut is not None and _int(a.get("at_ms") if isinstance(a, dict) else None) and a["at_ms"] < cut:
                continue                  # older than the window: not kept
            if isinstance(a, dict) and _int(a.get("sender_type")) is not None:   # an answer without a type means nothing: skipped
                text = a.get("text") if isinstance(a.get("text"), str) else ""
                org = a.get("org") if isinstance(a.get("org"), str) else ""
                answers.append({"sender_type": _int(a.get("sender_type")), "state": _int(a.get("state")), "at_ms": _int(a.get("at_ms")),
                                "active": bool(a.get("active")), "text": "" if secret else text[:MAX_TEXT],
                                "org": "" if secret else " ".join(org.split())[:MAX_ORG], "pd": _int(a.get("pd"))})
        rid = it.get("recipient_id")
        rid = str(rid)[:64] if isinstance(rid, (str, int)) and not isinstance(rid, bool) else ""
        ref = it.get("task_ref")
        ref = str(ref)[:64] if isinstance(ref, (str, int)) and not isinstance(ref, bool) else ""
        old_row = c.execute("SELECT due_ms, answers FROM ijro_snapshots WHERE task_id=?", (tid,)).fetchone()
        seen_ms = None
        if old_row and is_found and old_row["due_ms"] and _int(it.get("due_ms")) and _day(old_row["due_ms"]) != _day(_int(it.get("due_ms"))):
            prev = current_answer(json.loads(old_row["answers"] or "[]"))
            if prev and prev.get("sender_type") in T_INFO:      # the Chamber's answer was already known, and now the term is different
                seen_ms = int(datetime.now(TZ).timestamp() * 1000)
        upd_ms = _int(it.get("updated_ms"))
        mod_ms = _int(it.get("due_mod_ms"))
        tupd_ms = _int(it.get("task_updated_ms"))
        dch = it.get("due_changed")
        dch = None if dch is None or not isinstance(dch, bool) else int(dch)
        c.execute("""INSERT INTO ijro_snapshots(task_id, found, section, recipient_id, task_ref, site_status, is_done, overdue, repeatable, due_ms, done_ms,
                                                periods, is_secret, answers, checked_at, run_id, answers_total, updated_ms, due_changed, term_seen_ms, due_mod_ms, task_updated_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(task_id) DO UPDATE SET found=excluded.found, section=excluded.section, recipient_id=excluded.recipient_id, task_ref=excluded.task_ref,
                       site_status=excluded.site_status, is_done=excluded.is_done, overdue=excluded.overdue, repeatable=excluded.repeatable,
                       due_ms=excluded.due_ms, done_ms=excluded.done_ms, periods=excluded.periods, is_secret=excluded.is_secret,
                       answers=CASE WHEN excluded.found=1 AND ? THEN excluded.answers ELSE ijro_snapshots.answers END,
                       checked_at=excluded.checked_at, run_id=excluded.run_id,
                       answers_total=CASE WHEN excluded.found=1 AND ? THEN excluded.answers_total ELSE ijro_snapshots.answers_total END,
                       updated_ms=CASE WHEN excluded.found=1 THEN excluded.updated_ms ELSE ijro_snapshots.updated_ms END,
                       due_changed=CASE WHEN excluded.found=1 THEN excluded.due_changed ELSE ijro_snapshots.due_changed END,
                       due_mod_ms=CASE WHEN excluded.found=1 THEN excluded.due_mod_ms ELSE ijro_snapshots.due_mod_ms END,
                       task_updated_ms=CASE WHEN excluded.found=1 AND excluded.task_updated_ms IS NOT NULL THEN excluded.task_updated_ms ELSE ijro_snapshots.task_updated_ms END,
                       term_seen_ms=COALESCE(excluded.term_seen_ms, ijro_snapshots.term_seen_ms)""",
                  (tid, int(is_found), sec if is_found else "", rid if is_found else "", ref if is_found else "", _int(it.get("status")) if is_found else None,
                   int(bool(it.get("is_done"))), None if it.get("overdue") is None else int(bool(it.get("overdue"))), int(bool(it.get("repeatable"))),
                   _int(it.get("due_ms")), _int(it.get("done_ms")), json.dumps(periods), int(secret), json.dumps(answers, ensure_ascii=False), now(), run_id, total, upd_ms if is_found else None, dch if is_found else None, seen_ms, mod_ms if is_found else None, tupd_ms if is_found else None,
                   int(bool(it.get("answers_loaded"))), int(bool(it.get("answers_loaded")))))
        c.execute("UPDATE ijro_snapshots SET ext_date=(SELECT ext_date FROM tasks WHERE id=?) WHERE task_id=?", (tid, tid))
        stored += 1
        touched.append(tid)
        found += is_found
    auto, moved = 0, {"done": 0, "progress": 0, "due": 0}
    if setting("ijro_auto_apply") == "1":
        for tid in touched:
            did = auto_apply(c, tid)
            if did:
                auto += 1
                for d in did:
                    if d == "status→done":
                        moved["done"] += 1
                    elif d == "status→progress":
                        moved["progress"] += 1
                    elif d.startswith("due"):
                        moved["due"] += 1
        if auto:
            audit(c, "ijro.auto_apply", "task", None, {"tasks": auto, "run": run_id})
    if run_id:
        c.execute("UPDATE sync_runs SET received=received+?, found=found+?, finished_at=? WHERE id=? AND key_id=?", (stored, found, now(), run_id, key_row["id"]))
    return {"stored": stored, "found": found, "auto_applied": auto, "moved": moved, "term_split": term_split}


# ---------------------------------------------------------------- tasks added by their code: the rest is filled from the site's list

CODE_RE = __import__("re").compile(r"^[A-Z]{2,4}\d{3,6}$")


def pending_codes(c) -> list[str]:
    """Tasks that were added by the code only and wait for their data (text, document, term, the responsible person): the collector brings it from the site's list."""
    return [r["code"] for r in c.execute("SELECT code FROM tasks WHERE manual=2 AND text='' ORDER BY id")]


def fill_pending(c, data: bytes, filename: str, user_id: int | None) -> dict:
    """The site's Excel list (the same file as an import) is searched for the codes that wait for their data; the rows found fill those tasks, exactly as an import
    would (kind, document, point, text, term, the responsible person and their department, the status). Nothing else in the file is touched."""
    from . import importer, site_import
    want = set(pending_codes(c))
    if not want:
        return {"filled": 0, "pending": []}
    raw = [r for r in site_import._read_rows(data) if str(r["code"]).upper() in want]
    if not raw:
        return {"filled": 0, "pending": sorted(want)}
    for r in raw:
        r["code"] = str(r["code"]).upper()
    rows, warnings, _report = site_import.read_rows(c, raw, None, None, None, False, False, False)      # no filters: these codes were asked for by a person
    by_scope: dict[str, list] = {}
    for r in rows:                                          # each row says which group it is (main, co-executor, the Cabinet's other kinds): the waiting task joins that group
        by_scope.setdefault(r.get("scope") or "main", []).append(r)
    for sc, rs in by_scope.items():
        codes = [r["code"] for r in rs]
        c.execute(f"UPDATE tasks SET scope=? WHERE manual=2 AND text='' AND code IN ({','.join('?' * len(codes))})", [sc, *codes])
        importer.apply(c, rs, warnings, filename or "fill.xlsx", user_id, False, mode="base", overwrite=True, scope=sc)
    left = pending_codes(c)
    return {"filled": len(want) - len(left), "pending": left}


# ---------------------------------------------------------------- tasks the site no longer lists as ours

SITE_OPEN_STATUSES = {st for t in EXPORT_TABS if t["open"] for st in t["statuses"]}      # the states in which a task counts as open on the site
EXPORT_FILES = len(SECTIONS["sections"]) * len(EXPORT_TABS)      # the files of a run in the "tabs" mode (3 lists x 3 tabs)


def export_plan() -> dict:
    """What the collector downloads, by the setting «sync_source»:
    lists - THREE files: one common list per section (president, president's administration, cabinet), each with every status at once (the site's
            «Barcha topshiriqlar» tab). The status of a task is in the file («Топшириқ ҳолати»), so the tabs are not needed;
    tabs  - nine files: three lists x three tabs («в работе», «просрочено», «выполнено»), the earlier way."""
    sections = [{"id": x["id"], "type_ids": EXPORT_TYPES_ONLY.get(x["id"], x["type_ids"])} for x in SECTIONS["sections"]]
    if setting("sync_source") == "tabs":
        return {"mode": "tabs", "sections": sections, "tabs": EXPORT_TABS}
    return {"mode": "lists", "sections": sections, "tabs": [{"id": "all", "statuses": []}]}


def export_files() -> int:
    p = export_plan()
    return len(p["sections"]) * len(p["tabs"])


def record_export(c, run: str, codes) -> None:
    """One export file of a run arrived: the codes it listed as ours (department, role, kind; whatever the term)."""
    t = now()
    c.execute("DELETE FROM export_seen WHERE run IN (SELECT run FROM export_runs WHERE created_at < ?)", ((datetime.now(TZ) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),))
    c.execute("DELETE FROM export_runs WHERE created_at < ?", ((datetime.now(TZ) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),))
    c.execute("INSERT INTO export_runs(run, files, created_at) VALUES (?,0,?) ON CONFLICT(run) DO NOTHING", (run, t))
    c.execute("UPDATE export_runs SET files=files+1 WHERE run=?", (run,))
    c.executemany("INSERT OR IGNORE INTO export_seen(run, code) VALUES (?,?)", [(run, x) for x in codes])


def finish_run(c, run: str, complete: bool) -> dict:
    """After the whole run (exports, then the check of every open task). Finds the open tasks that the site does not list as ours any more and that
    the check of THIS run found open on the site. Nothing is judged unless every export file arrived and the run was complete: a half run proves nothing.
    Up to a quarter of the open tasks go off the dashboard at once; more than that waits for the administrator."""
    r = c.execute("SELECT files, created_at FROM export_runs WHERE run=?", (run,)).fetchone()
    if not r:
        return {"judged": False, "why": "Файлы выгрузок этого запуска не получены"}
    if r["files"] < export_files() or not complete:
        return {"judged": False, "why": f"Запуск неполный (файлов {r['files']} из {export_files()}{'' if complete else ', проверка статусов не завершена'}): задачи не трогаю"}
    rows = c.execute("""SELECT t.id, t.code, s.site_status, s.found, s.checked_at FROM tasks t LEFT JOIN ijro_snapshots s ON s.task_id=t.id
                        WHERE t.status IN ('todo','progress') AND t.manual=0 AND COALESCE(NULLIF(t.site_code, ''), t.code) NOT IN (SELECT code FROM export_seen WHERE run=?)""", (run,)).fetchall()
    stale, unsure = [], 0
    for x in rows:
        site_open = x["found"] and x["checked_at"] and x["checked_at"] >= r["created_at"] and x["site_status"] in SITE_OPEN_STATUSES
        if site_open:
            stale.append(x["id"])
        else:
            unsure += 1       # not checked in this run, not found, or closed / in a state the exported tabs do not cover: left alone
    c.execute("DELETE FROM site_stale")
    t = now()
    c.executemany("INSERT INTO site_stale(task_id, run, reason, found_at) VALUES (?,?,?,?)",
                  [(i, run, "Сайт не относит задачу к нашим выгрузкам (другой вид документа, не наш отдел или соисполнитель)", t) for i in stale])
    open_total = c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('todo','progress')").fetchone()[0]
    out = {"judged": True, "stale": len(stale), "unsure": unsure, "open": open_total, "archived": 0, "waiting": 0}
    if not stale:
        return out
    if setting("ijro_auto_archive") == "1" and len(stale) <= max(10, open_total // 4):
        out["archived"] = archive(c, stale)
    else:
        out["waiting"] = len(stale)
    return out


def archive(c, ids: list[int]) -> int:
    """Takes tasks off the dashboard (status «Нет на сайте»). Nothing is deleted: the history stays, and a task listed again comes back by itself."""
    n, t = 0, now()
    for i in ids:
        r = c.execute("SELECT status FROM tasks WHERE id=? AND status != 'gone'", (i,)).fetchone()
        if not r:
            continue
        c.execute("INSERT INTO task_events(task_id, user_id, field, old, new, created_at) VALUES (?,?,?,?,?,?)", (i, None, "status", STATUSES.get(r["status"], r["status"]), STATUSES["gone"], t))
        c.execute("UPDATE tasks SET status='gone', updated_at=? WHERE id=?", (t, i))
        c.execute("DELETE FROM site_stale WHERE task_id=?", (i,))
        n += 1
    if n:
        audit(c, "ijro.archive", "task", None, {"tasks": n})
    return n


def stale_list(c) -> list[dict]:
    return [dict(r) for r in c.execute("""SELECT t.id, t.code, t.kind, t.doc_no, t.point, substr(t.text,1,160) AS text, t.due, a.name AS assignee, x.found_at FROM site_stale x
                                          JOIN tasks t ON t.id=x.task_id LEFT JOIN users a ON a.id=t.assignee_id WHERE t.status IN ('todo','progress') ORDER BY t.kind, t.code""")]


# ---------------------------------------------------------------- review and apply

def review(c) -> dict:
    rows = c.execute("""SELECT s.*, t.code, t.due, t.status AS our_status, t.text, t.kind, t.doc_no, t.point, t.assignee_id, a.name AS assignee
                        FROM ijro_snapshots s JOIN tasks t ON t.id=s.task_id LEFT JOIN users a ON a.id=t.assignee_id WHERE t.status_manual=0 ORDER BY t.seq, t.id""").fetchall()
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
        tasks.update_task(c, tid, {"status": cl["status"]}, user_id, lock=False)      # the site's own status taken over: not a manual choice
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
        info = site_info(r, t["status"], t["due"], admin, t.get("status_manual", False))
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
