"""Telegram bot: linking an account, commands, sending messages. Standard library only.

The token is a secret: it lives only in the environment (TELEGRAM_BOT_TOKEN in .env on the server), never in
the database and never in a response. The bot works by long polling, so the server needs no public endpoint.
Two uvicorn workers share one container: a file lock makes sure only one of them polls and sends on schedule."""
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from . import auth
from .db import DATA_DIR, TZ, audit, connect, now, put_settings, setting, tx

API = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
CODE_MINUTES = 15
_lock_file = None


def token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def configured() -> bool:
    return bool(token())


class TgError(Exception):
    def __init__(self, code: int, description: str, retry_after: int = 0):
        super().__init__(description)
        self.code, self.description, self.retry_after = code, description, retry_after


def api(method: str, payload: dict | None = None, timeout: int = 15):
    """One Bot API call. Error text never contains the token (the URL does, so it is cut out of it)."""
    url = f"{API}/bot{token()}/{method}"
    req = urllib.request.Request(url, json.dumps(payload or {}).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            body = {}
        raise TgError(e.code, body.get("description", f"HTTP {e.code}"), (body.get("parameters") or {}).get("retry_after", 0)) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TgError(0, "нет связи с Telegram: " + str(getattr(e, "reason", e)).replace(token(), "***")) from None
    if not data.get("ok"):
        raise TgError(data.get("error_code", 0), data.get("description", "ошибка Telegram"))
    return data["result"]


def bot_username() -> str:
    u = setting("tg_bot")
    if u or not configured():
        return u
    try:
        u = api("getMe").get("username", "")
        with tx() as c:
            put_settings(c, {"tg_bot": u})
    except TgError:
        return ""
    return u


def esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def send(chat_id: str, text: str, *, silent: bool = False) -> tuple[bool, str]:
    """(ok, error). A user who blocked the bot is unlinked, so nothing is sent into the void every morning."""
    for attempt in (1, 2):
        try:
            api("sendMessage", {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True,
                                "disable_notification": silent})
            return True, ""
        except TgError as e:
            if e.code == 429 and attempt == 1:
                time.sleep(min(e.retry_after or 2, 20))
                continue
            if e.code in (400, 403) and ("blocked" in e.description or "chat not found" in e.description or "deactivated" in e.description):
                with tx() as c:
                    c.execute("UPDATE users SET tg_chat_id='', tg_username='' WHERE tg_chat_id=?", (str(chat_id),))
                return False, "пользователь заблокировал бота — привязка снята"
            return False, e.description
    return False, "не удалось отправить"


def send_async(chat_id: str, text: str) -> None:
    threading.Thread(target=send, args=(chat_id, text), daemon=True).start()


# ---------------------------------------------------------------- linking

def new_link_code(user_id: int) -> dict:
    code = secrets.token_urlsafe(8)
    exp = (datetime.now(TZ) + timedelta(minutes=CODE_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    with tx() as c:
        c.execute("UPDATE users SET tg_code=?, tg_code_exp=? WHERE id=?", (code, exp, user_id))
    bot = bot_username()
    return {"code": code, "expires": exp, "url": f"https://t.me/{bot}?start={code}" if bot else "", "bot": bot, "minutes": CODE_MINUTES}


def link(code: str, chat_id: str, username: str) -> str:
    with tx() as c:
        u = c.execute("SELECT * FROM users WHERE tg_code=? AND tg_code!='' AND tg_code_exp > ? AND active=1", (code, now())).fetchone()
        if not u:
            return "Код не найден или истёк. Откройте на сайте раздел «Напоминания» и нажмите «Привязать Telegram» ещё раз."
        other = c.execute("SELECT name FROM users WHERE tg_chat_id=? AND id != ?", (chat_id, u["id"])).fetchone()
        if other:
            return "Этот Telegram уже привязан к другому пользователю. Сначала отвяжите его командой /unlink в этом чате."
        c.execute("UPDATE users SET tg_chat_id=?, tg_username=?, tg_code='', tg_code_exp='', remind=1 WHERE id=?", (chat_id, username, u["id"]))
        audit(c, "telegram.link", "user", u["id"], {})
    return (f"Готово, {esc(auth.short_name(u['name']))}. Напоминания включены.\n\n"
            "Команды: /my — мои задачи сейчас, /stop — выключить, /start — включить, /unlink — отвязать, /help.")


HELP = ("<b>Команды</b>\n/my — мои задачи: просрочено и ближайшие сроки\n/stop — выключить напоминания\n"
        "/start — включить обратно\n/unlink — отвязать этот Telegram\n\n"
        "Что и когда приходит, настраивается на сайте, раздел «Напоминания».")


def handle_update(u: dict) -> None:
    from . import reminders

    msg = u.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or not msg.get("text"):
        return
    chat_id, text = str(chat["id"]), msg["text"].strip()
    uname = (msg.get("from") or {}).get("username", "")
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    c = connect()
    try:
        me = c.execute("SELECT * FROM users WHERE tg_chat_id=? AND active=1", (chat_id,)).fetchone()
    finally:
        c.close()
    reply = ""
    if cmd == "/start" and len(parts) == 2:
        reply = link(parts[1].strip(), chat_id, uname)
    elif cmd == "/start":
        if me:
            with tx() as c:
                c.execute("UPDATE users SET remind=1 WHERE id=?", (me["id"],))
            reply = "Напоминания включены."
        else:
            reply = "Здравствуйте! Чтобы привязать Telegram, откройте на сайте раздел «Напоминания» и нажмите «Привязать Telegram»."
    elif not me:
        reply = "Этот Telegram не привязан к аккаунту. Откройте на сайте раздел «Напоминания» и нажмите «Привязать Telegram»."
    elif cmd == "/stop":
        with tx() as c:
            c.execute("UPDATE users SET remind=0 WHERE id=?", (me["id"],))
        reply = "Напоминания выключены. Включить обратно: /start"
    elif cmd == "/unlink":
        with tx() as c:
            c.execute("UPDATE users SET tg_chat_id='', tg_username='' WHERE id=?", (me["id"],))
            audit(c, "telegram.unlink", "user", me["id"], {"by": "bot"})
        reply = "Telegram отвязан."
    elif cmd in ("/my", "/tasks"):
        reply = reminders.my_now(me["id"])
    else:
        reply = HELP
    if reply:
        send(chat_id, reply)


def poll_once(timeout: int = 0) -> int:
    """One getUpdates round; returns the number of updates handled. The offset is kept in the database."""
    offset = int(setting("tg_offset") or 0)
    updates = api("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}, timeout=timeout + 10)
    for u in updates:
        try:
            handle_update(u)
        except Exception:  # one bad message must not stop the bot
            pass
        offset = u["update_id"] + 1
        with tx() as c:
            put_settings(c, {"tg_offset": offset})
    return len(updates)


def _status(error: str = "") -> None:
    with tx() as c:
        put_settings(c, {"tg_error": error, "tg_seen": now()})


def _poll_loop() -> None:
    bot_username()
    while True:
        try:
            poll_once(25)
            _status("")
        except TgError as e:
            _status("токен используется другим приложением (конфликт getUpdates): нужен отдельный бот" if e.code == 409 else e.description)
            time.sleep(30 if e.code == 409 else 10)
        except Exception:
            time.sleep(10)


def _schedule_loop() -> None:
    from . import reminders

    while True:
        try:
            reminders.run_due()
        except Exception:
            pass
        time.sleep(30)


def start() -> None:
    """Called by every worker; only the one that gets the lock runs the bot."""
    global _lock_file
    if not configured() or os.environ.get("ZADACHI_NO_TELEGRAM") == "1":
        return
    try:
        import fcntl
        os.makedirs(DATA_DIR, exist_ok=True)
        _lock_file = open(os.path.join(DATA_DIR, "telegram.lock"), "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        _lock_file = None
        return
    threading.Thread(target=_poll_loop, daemon=True, name="tg-poll").start()
    threading.Thread(target=_schedule_loop, daemon=True, name="tg-schedule").start()
