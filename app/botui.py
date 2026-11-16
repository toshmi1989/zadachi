"""Buttons of the Telegram bot: a menu under the input field (reply keyboard) and inline buttons under messages.
Everything here is read-only for tasks; the only thing a person changes from the bot is their own reminder settings."""
from . import reminders
from .db import connect, today as db_today, tx

MENU = {"📋 Мои задачи": "all", "🔴 Просрочено": "overdue", "📅 Эта неделя": "week", "⚙️ Настройки": "settings", "📊 Сводка": "summary", "❓ Помощь": "help"}
COMMANDS = [("my", "Мои задачи"), ("overdue", "Просроченные"), ("week", "Сроки на неделю"), ("settings", "Настройки напоминаний"),
            ("help", "Помощь"), ("stop", "Выключить напоминания"), ("start", "Включить напоминания")]
DAY_BTNS = [14, 7, 5, 3, 2, 1, 0]
OVERDUE_BTNS = [(0, "Нет"), (1, "Каждый день"), (2, "Через день"), (3, "Раз в 3 дня"), (7, "Раз в неделю")]
WD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def main_keyboard(is_admin: bool) -> dict:
    rows = [[{"text": "📋 Мои задачи"}, {"text": "🔴 Просрочено"}], [{"text": "📅 Эта неделя"}, {"text": "⚙️ Настройки"}]]
    rows.append([{"text": "📊 Сводка"}, {"text": "❓ Помощь"}] if is_admin else [{"text": "❓ Помощь"}])
    return {"keyboard": rows, "resize_keyboard": True, "is_persistent": True}


def _site_row(g: dict, path: str, label: str) -> list:
    url = g["public_url"]
    # Telegram refuses non-https and local addresses in buttons, so such a site is simply left out of the keyboard
    if url.startswith("https://") and "localhost" not in url:
        return [[{"text": label, "url": url + path}]]
    return []


def nav_markup(g: dict, uid: int) -> dict:
    rows = [[{"text": "📋 Все", "callback_data": "v:all"}, {"text": "🔴 Просрочено", "callback_data": "v:overdue"}, {"text": "📅 Неделя", "callback_data": "v:week"}],
            [{"text": "⚙️ Настройки", "callback_data": "s:open"}]]
    return {"inline_keyboard": rows + _site_row(g, f"/#/tasks?assignee={uid}&status=open", "🌐 Открыть на сайте")}


def digest_markup(g: dict, uid: int) -> dict:
    rows = [[{"text": "📋 Мои задачи", "callback_data": "v:all"}, {"text": "⚙️ Настройки", "callback_data": "s:open"}]]
    return {"inline_keyboard": rows + _site_row(g, f"/#/tasks?assignee={uid}&status=open", "🌐 Открыть на сайте")}


def view(user_id: int, kind: str) -> tuple[str, dict]:
    c = connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        g = reminders.global_cfg(c)
        today = db_today()
        dg = reminders.build_digest(c, u, g, reminders.user_cfg(u, g), today, overdue_due=True, everything=True)
        if dg and kind == "overdue":
            dg["groups"] = {}
        elif dg and kind == "week":
            dg["overdue"] = []
        if not dg or not (dg["overdue"] or dg["groups"]):
            empty = {"overdue": "Просроченных задач нет. 👍", "week": "На ближайшие 7 дней сроков нет. 👍"}.get(kind, "Просроченных задач и сроков на ближайшую неделю нет. 👍")
            return empty, nav_markup(g, user_id)
        return reminders.render(u, dg, dict(g, max=30 if kind != "all" else g["max"]), today), nav_markup(g, user_id)
    finally:
        c.close()


def summary(user_id: int) -> tuple[str, dict]:
    c = connect()
    try:
        g = reminders.global_cfg(c)
        return reminders.admin_summary(c, g, db_today()) or "Просроченных задач и сроков на неделю нет. 👍", nav_markup(g, user_id)
    finally:
        c.close()


def settings_view(user_id: int) -> tuple[str, dict]:
    c = connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        g = reminders.global_cfg(c)
    finally:
        c.close()
    cfg = reminders.user_cfg(u, g)
    days = ", ".join(("в день срока" if n == 0 else f"за {n}") for n in sorted(cfg["days"], reverse=True)) or "не предупреждать"
    over = dict(OVERDUE_BTNS).get(cfg["overdue"], str(cfg["overdue"])).lower()
    wd = ", ".join(WD[d - 1] for d in g["weekdays"])
    text = ("<b>⚙️ Настройки напоминаний</b>\n\n"
            f"Напоминания: <b>{'включены' if cfg['remind'] else 'выключены'}</b>\n"
            f"О сроке: <b>{days}</b>{'' if cfg['custom_days'] else ' (как у всех)'}\n"
            f"О просроченных: <b>{over}</b>{'' if cfg['custom_overdue'] else ' (как у всех)'}\n"
            f"О новых назначениях: <b>{'да' if cfg['notify_assign'] else 'нет'}</b>\n\n"
            f"Сводка приходит: {wd} в {g['time']}{'' if g['enabled'] else ' — сейчас администратор отключил напоминания для всех'}.")
    days_set = set(cfg["days"])
    chip = lambda n: {"text": ("✅ " if n in days_set else "") + ("в день" if n == 0 else f"{n} дн."), "callback_data": f"s:d:{n}"}
    ov = lambda n, lab: {"text": ("● " if cfg["overdue"] == n else "") + lab, "callback_data": f"s:o:{n}"}
    rows = [[{"text": "🔔 Напоминания: вкл ✅" if cfg["remind"] else "🔕 Напоминания: выкл", "callback_data": "s:on"}],
            [chip(n) for n in DAY_BTNS[:4]], [chip(n) for n in DAY_BTNS[4:]],
            [ov(*OVERDUE_BTNS[0]), ov(*OVERDUE_BTNS[1]), ov(*OVERDUE_BTNS[2])], [ov(*OVERDUE_BTNS[3]), ov(*OVERDUE_BTNS[4])],
            [{"text": "📌 Назначения: " + ("да ✅" if cfg["notify_assign"] else "нет"), "callback_data": "s:asg"}, {"text": "↩️ Как у всех", "callback_data": "s:reset"}],
            [{"text": "⬅️ К задачам", "callback_data": "v:all"}]]
    return text, {"inline_keyboard": rows}


def apply(user_id: int, data: str) -> None:
    """Callback data s:on | s:asg | s:d:N | s:o:N | s:reset — changes only this person's own settings."""
    c = connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        g = reminders.global_cfg(c)
    finally:
        c.close()
    cfg = reminders.user_cfg(u, g)
    parts = data.split(":")
    with tx() as c:
        if data == "s:on":
            c.execute("UPDATE users SET remind=? WHERE id=?", (0 if cfg["remind"] else 1, user_id))
        elif data == "s:asg":
            c.execute("UPDATE users SET notify_assign=? WHERE id=?", (0 if cfg["notify_assign"] else 1, user_id))
        elif data == "s:reset":
            c.execute("UPDATE users SET remind_days='', remind_overdue=NULL WHERE id=?", (user_id,))
        elif len(parts) == 3 and parts[1] == "d" and parts[2].isdigit() and int(parts[2]) in DAY_BTNS:
            days = set(cfg["days"]) ^ {int(parts[2])}
            c.execute("UPDATE users SET remind_days=? WHERE id=?", (",".join(map(str, sorted(days, reverse=True))), user_id))
        elif len(parts) == 3 and parts[1] == "o" and parts[2].isdigit() and int(parts[2]) in dict(OVERDUE_BTNS):
            c.execute("UPDATE users SET remind_overdue=? WHERE id=?", (int(parts[2]), user_id))
