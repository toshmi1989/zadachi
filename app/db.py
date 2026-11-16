"""SQLite: users, sessions, tasks, change history, import log, audit. One file, easy to back up."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "zadachi.db")
TZ = timezone(timedelta(hours=5))  # Uzbekistan has no daylight saving time

# The department's structure as given by the customer: (number, name, parent number). Seeded once; editable on the Settings page.
UNITS_SEED = [
    ("I", "Тиббий хизматлар бошқармаси", None),
    ("1", "Туман (шаҳар) стационар тиббий хизматлари бўлими", "I"),
    ("2", "Ихтисослашган тиббий хизматлар бўлими", "I"),
    ("3", "Тез тиббий ёрдам бўлими", "I"),
    ("4", "Экологик дипломатия ва тиббий туризмни ривожлантириш бўлими", "I"),
    ("II", "Бирламчи тиббий-санитария ёрдамини ташкиллаштириш бошқармаси", None),
    ("III", "Оналик ва болаликни муҳофаза қилиш бошқармаси", None),
    ("1", "Оналик ва репродуктив саломатликни муҳофаза қилиш бўлими", "III"),
    ("2", "Болалар саломатлиги бўлими", "III"),
    ("IV", "Фармацевтика маҳсулотлари сиёсати бошқармаси", None),
    ("V", "Тиббий реабилитация, паллиатив ёрдам ва ижтимоий ҳимояга муҳтож аҳолига тиббий хизматлар кўрсатишни мувофиқлаштириш бошқармаси", None),
    ("VI", "Ташхислаш хизмати бўлими", None),
]
STATUSES = {"todo": "Не выполнено", "progress": "В работе", "done": "Выполнено", "info": "К сведению"}
OPEN = ("todo", "progress")


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def today() -> date:
    """Today in Tashkent. ZADACHI_TODAY=YYYY-MM-DD pins the date (tests, demos)."""
    pinned = os.environ.get("ZADACHI_TODAY")
    return date.fromisoformat(pinned) if pinned else datetime.now(TZ).date()


TABLES = """
-- Structure of the department: managements (top level, roman numerals) and divisions inside them.
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY,
    num TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES units(id),
    sort INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    excel_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    tg_chat_id TEXT NOT NULL DEFAULT '',
    tg_username TEXT NOT NULL DEFAULT '',
    tg_code TEXT NOT NULL DEFAULT '',
    tg_code_exp TEXT NOT NULL DEFAULT '',
    remind INTEGER NOT NULL DEFAULT 1,
    remind_days TEXT NOT NULL DEFAULT '',
    remind_overdue INTEGER,
    notify_assign INTEGER NOT NULL DEFAULT 1,
    pw_set INTEGER NOT NULL DEFAULT 0,
    unit_id INTEGER REFERENCES units(id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    seq INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT '',
    doc_no TEXT NOT NULL DEFAULT '',
    doc_date TEXT,
    point TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    due TEXT,
    close_date TEXT,
    assignee_id INTEGER REFERENCES users(id),
    assignee_raw TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    tag TEXT NOT NULL DEFAULT '',
    done_at TEXT,
    edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    field TEXT NOT NULL,
    old TEXT NOT NULL DEFAULT '',
    new TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    filename TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- What the bot sent and when. One digest per person per day is guaranteed by the unique index below.
CREATE TABLE IF NOT EXISTS reminder_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    count INTEGER NOT NULL DEFAULT 0,
    overdue INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    details TEXT NOT NULL DEFAULT '{}',
    ip TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_reminder_daily ON reminder_log(user_id, day, kind) WHERE kind IN ('digest','admin');
CREATE INDEX IF NOT EXISTS idx_users_tg ON users(tg_chat_id);
CREATE INDEX IF NOT EXISTS idx_users_unit ON users(unit_id);
CREATE INDEX IF NOT EXISTS idx_units_parent ON units(parent_id);
"""
# The change history and the audit log are append-only, enforced by the database itself.
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON task_events BEGIN SELECT RAISE(ABORT, 'История изменений неизменяема'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'Журнал неизменяем'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'Журнал неизменяем'); END;
"""

DEFAULT_SETTINGS = {
    "users_tasks": "all",         # what role "user" may see: all tasks (read-only) | own | none
    "rem_enabled": "1",           # Telegram reminders on/off for everyone
    "rem_time": "09:00",          # Tashkent time of the daily digest
    "rem_weekdays": "1,2,3,4,5",  # ISO weekdays the digest is sent on
    "rem_days": "7,3,1,0",        # warn this many days before the term (0 = on the day)
    "rem_overdue": "1",           # repeat overdue tasks every N days (0 = never)
    "rem_by": "close",            # which term the reminders use: close | due
    "rem_admin": "1",             # summary for administrators
    "login_list": "1",            # show the list of employees on the sign-in page
    "rem_max": "15",              # tasks listed in one message
    "public_url": "",             # site address for links in messages
}
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN tg_chat_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN tg_username TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN tg_code TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN tg_code_exp TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN remind INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN remind_days TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN remind_overdue INTEGER",
    "ALTER TABLE users ADD COLUMN notify_assign INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE users ADD COLUMN pw_set INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN unit_id INTEGER REFERENCES units(id)",
]
# pw_set = somebody has issued this person a password (people created by the Excel import have none yet)
BACKFILL_PW_SET = """UPDATE users SET pw_set=1 WHERE role='admin'
    OR id IN (SELECT user_id FROM audit WHERE action='login.ok' AND user_id IS NOT NULL)
    OR id IN (SELECT entity_id FROM audit WHERE action IN ('user.password','user.create') AND entity_id IS NOT NULL)"""


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


@contextmanager
def tx():
    c = connect()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    from . import auth

    with tx() as c:
        c.executescript(TABLES)
        for stmt in MIGRATIONS:
            try:
                c.execute(stmt)
                if "pw_set" in stmt:
                    c.execute(BACKFILL_PW_SET)  # column just added to an existing database: work out who already has a password
            except sqlite3.OperationalError as e:  # "duplicate column name": already there
                if "duplicate column" not in str(e):
                    raise
        c.executescript(INDEXES)
        c.executescript(TRIGGERS)
        seed_units(c)
        auth.ensure_admin(c)


def seed_units(c) -> None:
    """First start only (a flag, so a department that deleted everything is not refilled on the next restart)."""
    if c.execute("SELECT 1 FROM settings WHERE key='units_seeded'").fetchone() or c.execute("SELECT 1 FROM units LIMIT 1").fetchone():
        return
    top = {}
    for i, (num, name, parent) in enumerate(UNITS_SEED):
        cur = c.execute("INSERT INTO units(num, name, parent_id, sort) VALUES (?,?,?,?)", (num, name, top.get(parent) if parent else None, i))
        if parent is None:
            top[num] = cur.lastrowid
    c.execute("INSERT INTO settings(key, value) VALUES ('units_seeded', '1')")


def unit_tree_ids(c, unit_id: int) -> list[int]:
    """The unit and everything inside it (a management includes its divisions)."""
    ids = [unit_id]
    for r in c.execute("SELECT id FROM units WHERE parent_id=?", (unit_id,)):
        ids.append(r["id"])
    return ids


def setting(key: str) -> str:
    c = connect()
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    finally:
        c.close()
    return r["value"] if r else DEFAULT_SETTINGS.get(key, "")


def all_settings(c) -> dict:
    out = dict(DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in c.execute("SELECT key, value FROM settings") if r["key"] in DEFAULT_SETTINGS})
    return out


def put_settings(c, values: dict) -> None:
    for k, v in values.items():
        c.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def audit(c: sqlite3.Connection, action: str, entity: str = "", entity_id: int | None = None, details: dict | None = None) -> None:
    from . import auth

    user = auth.CURRENT.get()
    c.execute("INSERT INTO audit(user_id, action, entity, entity_id, details, ip, created_at) VALUES (?,?,?,?,?,?,?)",
              (user["id"] if user else None, action, entity, entity_id,
               json.dumps(details or {}, ensure_ascii=False), auth.CURRENT_IP.get(), now()))
