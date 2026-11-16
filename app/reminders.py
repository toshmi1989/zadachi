"""Reminders: who gets what, when. Settings exist on two levels: the administrator sets the defaults for everyone
(time, weekdays, how many days ahead, how often to repeat overdue), each person may override days/overdue for themselves
or switch reminders off. One message per person per day (a digest), not one per task."""
import re
from datetime import date, datetime, timedelta

from . import auth, tasks, telegram
from .db import TZ, all_settings, connect, now, today as db_today
from .telegram import esc

ALLOWED_DAYS = range(0, 31)
OVERDUE_CHOICES = (0, 1, 2, 3, 7)
WINDOW_HOURS = 6          # a digest is still sent this long after the set time (the server may have been restarted)
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def parse_days(s) -> list[int]:
    if isinstance(s, (list, tuple)):
        vals = s
    else:
        vals = [x for x in str(s or "").split(",") if x.strip() != ""]
    out = sorted({int(x) for x in vals if str(x).strip().lstrip("-").isdigit() and int(x) in ALLOWED_DAYS}, reverse=True)
    return out


def global_cfg(c=None) -> dict:
    own = c is None
    c = c or connect()
    try:
        s = all_settings(c)
    finally:
        if own:
            c.close()
    hh, mm = (s["rem_time"].split(":") + ["0"])[:2]
    return {"enabled": s["rem_enabled"] == "1", "time": f"{int(hh):02d}:{int(mm):02d}",
            "weekdays": sorted({int(x) for x in s["rem_weekdays"].split(",") if x.strip().isdigit() and 1 <= int(x) <= 7}),
            "days": parse_days(s["rem_days"]), "overdue": int(s["rem_overdue"] or 0), "by": "due" if s["rem_by"] == "due" else "close",
            "admin": s["rem_admin"] == "1", "max": max(3, min(40, int(s["rem_max"] or 15))), "public_url": s["public_url"].rstrip("/")}


def validate_global(b: dict) -> dict:
    out = {}
    if "enabled" in b:
        out["rem_enabled"] = "1" if b["enabled"] else "0"
    if "time" in b:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(b["time"])):
            raise ValueError("Время в формате ЧЧ:ММ, например 09:00")
        out["rem_time"] = b["time"]
    if "weekdays" in b:
        w = sorted({int(x) for x in b["weekdays"] if str(x).isdigit() and 1 <= int(x) <= 7})
        if not w:
            raise ValueError("Выберите хотя бы один день недели")
        out["rem_weekdays"] = ",".join(map(str, w))
    if "days" in b:
        out["rem_days"] = ",".join(map(str, parse_days(b["days"])))
    if "overdue" in b:
        if int(b["overdue"]) not in OVERDUE_CHOICES:
            raise ValueError("Допустимо: не напоминать, каждый день, через день, раз в 3 дня, раз в неделю")
        out["rem_overdue"] = str(int(b["overdue"]))
    if "by" in b:
        if b["by"] not in ("close", "due"):
            raise ValueError("Срок считается по дате закрытия или по официальному сроку")
        out["rem_by"] = b["by"]
    if "admin" in b:
        out["rem_admin"] = "1" if b["admin"] else "0"
    if "max" in b:
        n = int(b["max"])
        if not 3 <= n <= 40:
            raise ValueError("В одном сообщении от 3 до 40 задач")
        out["rem_max"] = str(n)
    if "public_url" in b:
        u = str(b["public_url"]).strip().rstrip("/")
        if u and not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", u):
            raise ValueError("Адрес сайта: https://example.uz")
        out["public_url"] = u
    return out


def user_cfg(u, g: dict) -> dict:
    days = parse_days(u["remind_days"]) if u["remind_days"] != "" else g["days"]
    overdue = u["remind_overdue"] if u["remind_overdue"] is not None else g["overdue"]
    return {"remind": bool(u["remind"]), "days": days, "overdue": int(overdue), "notify_assign": bool(u["notify_assign"]),
            "custom_days": u["remind_days"] != "", "custom_overdue": u["remind_overdue"] is not None}


# ---------------------------------------------------------------- the digest

def _fmt(d: str) -> str:
    y, m, dd = d.split("-")
    return f"{dd}.{m}"


def _line(t, g) -> str:
    head = " · ".join(x for x in (t["doc_no"], t["point"]) if x)
    body = (t["text"] or "").replace("\n", " ").strip()
    body = body[:90] + "…" if len(body) > 90 else body
    return f"• <code>{esc(t['code'])}</code> {esc(head)} — {esc(body)} (до {_fmt(t['eff'])})"


def _plural(n, one, few, many):
    a, b = n % 10, n % 100
    return many if 10 < b < 20 else one if a == 1 else few if 1 < a < 5 else many


def build_digest(c, u, g: dict, cfg: dict, today: date, *, overdue_due: bool, everything: bool = False) -> dict | None:
    """What this person should hear today: overdue (if it is time to repeat), term today, terms in N days.
    everything=True is the /my command: overdue plus the next 7 days regardless of the rules."""
    rows = c.execute(tasks.SELECT.format(e=tasks.eff_sql(g["by"])) + " WHERE t.assignee_id=? AND t.status IN ('todo','progress')", (u["id"],)).fetchall()
    items = [tasks.row_out(r, g["by"]) for r in rows]
    overdue, groups = [], {}
    wanted = set(range(0, 8)) if everything else set(cfg["days"])
    for t in items:
        if t["days"] is None:
            continue
        if t["days"] < 0:
            overdue.append(t)
        elif t["days"] in wanted:
            groups.setdefault(t["days"], []).append(t)
    if not (overdue_due or everything):
        overdue = []
    if not overdue and not groups:
        return None
    overdue.sort(key=lambda t: t["eff"])
    return {"overdue": overdue, "groups": dict(sorted(groups.items())), "count": len(overdue) + sum(map(len, groups.values()))}


def _when(n: int, d: date) -> str:
    if n == 0:
        return "Срок сегодня"
    if n == 1:
        return "Срок завтра"
    return f"Срок через {n} {_plural(n, 'день', 'дня', 'дней')} ({d.day:02d}.{d.month:02d})"


def render(u, dg: dict, g: dict, today: date, *, intro: bool = True) -> str:
    out = []
    if intro:
        out.append(f"<b>Задачи на контроле</b> · {today.day} {MONTHS[today.month - 1]}\nЗдравствуйте, {esc(auth.short_name(u['name']))}.")
    budget = g["max"]

    def block(title, lst):
        nonlocal budget
        if not lst:
            return
        take = lst[:max(budget, 0)] if budget > 0 else []
        text = f"\n{title}: <b>{len(lst)}</b>\n" + "\n".join(_line(t, g) for t in take)
        if len(lst) > len(take):
            text += f"\nи ещё {len(lst) - len(take)}…"
        budget -= len(take)
        out.append(text)

    block("🔴 Просрочено", dg["overdue"])
    for n, lst in dg["groups"].items():
        block(("🟠 " if n <= 1 else "🟡 ") + _when(n, today + timedelta(days=n)), lst)
    if g["public_url"]:
        out.append(f"\n<a href=\"{esc(g['public_url'])}/#/tasks?assignee={u['id']}&amp;status=open\">Открыть мои задачи</a>")
    return "\n".join(out)


def my_now(user_id: int) -> str:
    """The /my command: my open tasks right now, ignoring schedule and rules."""
    c = connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        g = global_cfg(c)
        today = db_today()
        dg = build_digest(c, u, g, user_cfg(u, g), today, overdue_due=True, everything=True)
        return render(u, dg, g, today) if dg else "Просроченных задач и сроков на ближайшую неделю нет. 👍"
    finally:
        c.close()


def admin_summary(c, g: dict, today: date) -> str | None:
    rows = c.execute(tasks.SELECT.format(e=tasks.eff_sql(g["by"])) + " WHERE t.status IN ('todo','progress')").fetchall()
    per, tot_over, tot_week = {}, 0, 0
    for r in rows:
        t = tasks.row_out(r, g["by"])
        if t["days"] is None:
            continue
        key = t["assignee"] or "Не назначен"
        d = per.setdefault(key, [0, 0])
        if t["days"] < 0:
            d[0] += 1
            tot_over += 1
        elif t["days"] <= 7:
            d[1] += 1
            tot_week += 1
    if not tot_over and not tot_week:
        return None
    lines = [f"<b>Сводка по задачам</b> · {today.day} {MONTHS[today.month - 1]}",
             f"🔴 Просрочено: <b>{tot_over}</b>\n🟠 Срок ≤ 7 дней: <b>{tot_week}</b>", ""]
    for name, (o, w) in sorted(per.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:12]:
        if o or w:
            lines.append(f"• {esc(name)}: просрочено {o}, скоро {w}")
    if g["public_url"]:
        lines.append(f"\n<a href=\"{esc(g['public_url'])}/#/dashboard\">Открыть дашборд</a>")
    return "\n".join(lines)


# ---------------------------------------------------------------- scheduling

def due_now(g: dict, at: datetime) -> bool:
    if not g["enabled"] or at.isoweekday() not in g["weekdays"]:
        return False
    hh, mm = map(int, g["time"].split(":"))
    start = at.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return start <= at <= start + timedelta(hours=WINDOW_HOURS)


def _last_overdue_day(c, uid: int) -> date | None:
    r = c.execute("SELECT MAX(day) d FROM reminder_log WHERE user_id=? AND kind='digest' AND overdue=1 AND ok=1", (uid,)).fetchone()
    return date.fromisoformat(r["d"]) if r and r["d"] else None


def run_due(at: datetime | None = None, *, force: bool = False, dry: bool = False) -> list[dict]:
    """Send today's digests to everyone who is due. force: ignore time/weekday and the once-a-day guard (manual run).
    dry: send nothing, only report what would go out. Returns one record per person."""
    at = at or datetime.now(TZ)
    today = db_today()  # equals the date of `at` in production; the tests pin it
    c = connect()
    results = []
    try:
        g = global_cfg(c)
        if not force and not dry and not due_now(g, at):
            return []
        if not g["enabled"] and not (force or dry):
            return []
        users = c.execute("SELECT * FROM users WHERE active=1 ORDER BY name").fetchall()
        for u in users:
            cfg = user_cfg(u, g)
            rec = {"user_id": u["id"], "name": u["name"], "role": u["role"], "linked": bool(u["tg_chat_id"]), "remind": cfg["remind"],
                   "status": "", "reason": "", "overdue": 0, "soon": 0, "text": ""}
            results.append(rec)
            if not u["tg_chat_id"]:
                rec.update(status="no_telegram", reason="Telegram не привязан")
                continue
            if not cfg["remind"]:
                rec.update(status="off", reason="напоминания выключены")
                continue
            done = c.execute("SELECT 1 FROM reminder_log WHERE user_id=? AND day=? AND kind='digest' AND ok=1", (u["id"], today.isoformat())).fetchone()
            if done and not (force or dry):
                rec.update(status="already", reason="сегодня уже отправлено")
                continue
            fails = c.execute("SELECT COUNT(*) FROM reminder_log WHERE user_id=? AND day=? AND kind='error'", (u["id"], today.isoformat())).fetchone()[0]
            if fails >= 3 and not (force or dry):
                rec.update(status="error", reason="3 неудачные отправки сегодня, повтор завтра")
                continue
            last = _last_overdue_day(c, u["id"])
            overdue_due = cfg["overdue"] > 0 and (last is None or (today - last).days >= cfg["overdue"])
            dg = build_digest(c, u, g, cfg, today, overdue_due=overdue_due)
            parts = []
            if dg:
                rec.update(overdue=len(dg["overdue"]), soon=dg["count"] - len(dg["overdue"]), text=render(u, dg, g, today))
                parts.append(rec["text"])
            adm = admin_summary(c, g, today) if (u["role"] == "admin" and g["admin"]) else None
            if adm:
                rec["text"] = (rec["text"] + "\n\n" if rec["text"] else "") + adm
            if not rec["text"]:
                rec.update(status="nothing", reason="нет задач под правила")
                if not dry and not force:
                    c.execute("INSERT OR IGNORE INTO reminder_log(user_id, day, kind, ok, count, overdue, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
                              (u["id"], today.isoformat(), "digest", 1, 0, 0, "nothing to send", now()))
                    c.commit()
                continue
            if dry:
                rec["status"] = "would_send"
                continue
            from . import botui
            ok, err = telegram.send(u["tg_chat_id"], rec["text"], markup=botui.digest_markup(g, u["id"]))
            rec.update(status="sent" if ok else "error", reason=err)
            kind = "digest" if ok and not force else ("manual" if ok else "error")
            c.execute("INSERT OR IGNORE INTO reminder_log(user_id, day, kind, ok, count, overdue, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (u["id"], today.isoformat(), kind, int(ok), (dg["count"] if dg else 0), 1 if dg and dg["overdue"] else 0, err, now()))
            c.commit()
    finally:
        c.close()
    return results


def notify_assigned(pairs: list[tuple[int, int]]) -> None:
    """After the administrator assigns tasks: pairs of (task_id, new_user_id). One message per person."""
    by_user: dict[int, list[int]] = {}
    for tid, uid in pairs:
        by_user.setdefault(uid, []).append(tid)
    c = connect()
    try:
        g = global_cfg(c)
        for uid, tids in by_user.items():
            u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
            if not u or not u["tg_chat_id"] or not u["notify_assign"] or not u["remind"] or not g["enabled"]:
                continue
            rows = c.execute(tasks.SELECT.format(e=tasks.eff_sql(g["by"])) + f" WHERE t.id IN ({','.join('?' * len(tids))})", tids).fetchall()
            ts = [tasks.row_out(r, g["by"]) for r in rows]
            text = f"📌 <b>Вам назначено {'задач' if len(ts) > 4 else 'задача'}: {len(ts)}</b>\n" if len(ts) > 1 else "📌 <b>Вам назначена задача</b>\n"
            text += "\n".join(_line(t, g) if t["eff"] else f"• <code>{esc(t['code'])}</code> {esc((t['text'] or '')[:90])}" for t in ts[:5])
            if len(ts) > 5:
                text += f"\nи ещё {len(ts) - 5}…"
            if g["public_url"]:
                text += f"\n<a href=\"{esc(g['public_url'])}/#/tasks?assignee={uid}&amp;status=open\">Открыть мои задачи</a>"
            from . import botui
            telegram.send_async(u["tg_chat_id"], text, botui.digest_markup(g, uid))
    finally:
        c.close()
