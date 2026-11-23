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
    ("VII", "Даволаш-профилактика ёрдамини ташкиллаштириш департаменти", None),
]
# the department the first structure lacked: added once to a database that already has units
UNITS_EXTRA = UNITS_SEED[-1:]
# departments that were added by mistake (they are not part of the structure): removed once, unless somebody works in them
UNITS_NOT_OURS = ["Стандартлар ва клиник қўлланмаларни ишлаб чиқиш ва жорий қилиш бошқармаси", "Иккинчи бўлим"]
STATUSES = {"todo": "Не выполнено", "progress": "В работе", "done": "Выполнено", "info": "К сведению", "gone": "Нет на сайте"}   # "gone": taken off the dashboard because the site no longer lists it as ours; comes back by itself if it reappears
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
-- the names of departments in the export of the site (Latin or Cyrillic, in one comparable form) and the unit of ours they stand for; unit_id NULL = not ours
CREATE TABLE IF NOT EXISTS unit_aliases (
    alias_key TEXT PRIMARY KEY,
    unit_id INTEGER REFERENCES units(id)
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
-- Synchronisation with edo.ijro.uz. The collector runs in an administrator's own browser (where they are signed in) and
-- sends what it read here. The key below is a key to THIS platform; nothing of the ijro account is ever stored.
CREATE TABLE IF NOT EXISTS sync_keys (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    key_hash TEXT NOT NULL UNIQUE,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    last_used TEXT NOT NULL DEFAULT '',
    revoked INTEGER NOT NULL DEFAULT 0
);
-- the export files of one synchronisation run (the run is a token made by the collector): which tasks they listed, and how many files arrived
CREATE TABLE IF NOT EXISTS export_runs (run TEXT PRIMARY KEY, files INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS export_seen (run TEXT NOT NULL, code TEXT NOT NULL, PRIMARY KEY (run, code));
-- open tasks that the site no longer lists as ours (waiting for the administrator's decision when there are many)
CREATE TABLE IF NOT EXISTS site_stale (task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, run TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', found_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    key_id INTEGER REFERENCES sync_keys(id),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    expected INTEGER NOT NULL DEFAULT 0,
    received INTEGER NOT NULL DEFAULT 0,
    found INTEGER NOT NULL DEFAULT 0
);
-- who is reading which task right now: several people may press «Синхронизировать» at once, and every task is read by one of them, not by all
CREATE TABLE IF NOT EXISTS sync_claims (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    run_id INTEGER NOT NULL,
    key_id INTEGER,
    claimed_at TEXT NOT NULL
);
-- The last thing read from the site about a task. It never changes the task by itself: the administrator applies it.
CREATE TABLE IF NOT EXISTS ijro_snapshots (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    found INTEGER NOT NULL DEFAULT 0,
    section TEXT NOT NULL DEFAULT '',
    recipient_id TEXT NOT NULL DEFAULT '',
    task_ref TEXT NOT NULL DEFAULT '',
    site_status INTEGER,
    is_done INTEGER NOT NULL DEFAULT 0,
    overdue INTEGER,
    repeatable INTEGER NOT NULL DEFAULT 0,
    due_ms INTEGER,
    done_ms INTEGER,
    periods TEXT NOT NULL DEFAULT '[]',
    is_secret INTEGER NOT NULL DEFAULT 0,
    answers TEXT NOT NULL DEFAULT '[]',
    checked_at TEXT NOT NULL,
    run_id INTEGER
);
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
    "users_tasks": "own",         # what role "user" may see: only own tasks (default) | all tasks (read-only, own ones editable) | none
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
    "ai_enabled": "0",            # the language model chooses the closing-date template (the key and the model are in the settings)
    "ai_key": "",
    "ai_model": "gpt-4o-mini",
    "ai_base_url": "",
    "ijro_auto_archive": "1",     # take tasks the site no longer lists as ours off the dashboard after a complete synchronisation (up to a quarter of the open ones; more waits for a confirmation)
    "ijro_auto_apply": "1",       # apply clear changes from the site automatically after each synchronisation
    "base_f_dept": "1",           # a loaded file: take only the departments that are in the structure (the person decides on the import page which are ours)
    "base_f_exec": "0",           # ... only the rows whose main executor is the ministry
    "base_f_kind": "0",           # ... no co-executors, of the cabinet's list only the kept kind
    "base_f_window": "0",         # ... only the terms inside the window (base_back / base_fwd)
    "base_manual": "overwrite",   # the loaded base vs what the administrator edited by hand: overwrite (the file wins) | keep (hand edits stay)
    "base_absent": "gone",        # open tasks that are not in the loaded base: gone (taken off the dashboard, «Нет на сайте») | keep (stay as they are)
    "sync_source": "lists",       # what the collector downloads: lists (3 files: one list per section with every status) | tabs (3 lists x 3 tabs = 9 files)
    "sync_apply": "status",       # what a downloaded list does: status (only updates the statuses of tasks already in the base) | base (also adds new tasks and updates the fields)
    "base_back": "30",            # a list that adds tasks takes terms from this many days back (empty = no limit) ...
    "base_fwd": "60",             # ... to this many days ahead (empty = no limit)
    "sync_parallel": "3",         # how many tasks the collector reads at the same time (1-5)
    "history_days": "30",         # how far back the answers of the site are read and kept: 30 (the last month) | 90 | 0 (the whole history)
    "history_scope": "all",       # whose answers (the stage history) are read: all (every not-done task of the base) | month | month_overdue | month_next
    "history_date": "close",      # the term that decides the month of a task for that: close (closing date, else official) | due (official, else closing)
    "history_statuses": "open",   # open (only not-done tasks) | all (done ones too)
    "ijro_card_tpl": "",          # address of a task card on edo.ijro.uz: {section_path} and {id} are substituted
}
MIGRATIONS = [
    "ALTER TABLE tasks ADD COLUMN close_src TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE tasks ADD COLUMN close_note TEXT NOT NULL DEFAULT ''",
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
    "ALTER TABLE ijro_snapshots ADD COLUMN task_ref TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE ijro_snapshots ADD COLUMN answers_total INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE ijro_snapshots ADD COLUMN updated_ms INTEGER",          # the time the site last changed the task itself (not an answer): a term moved after the Chamber's answer shows here
    "ALTER TABLE ijro_snapshots ADD COLUMN due_changed INTEGER",         # the card's own flag «term changed» (NULL = the site did not say)
    "ALTER TABLE ijro_snapshots ADD COLUMN term_seen_ms INTEGER",        # when the synchronisation saw the term change after it had already seen the Chamber's answer
    "ALTER TABLE ijro_snapshots ADD COLUMN task_updated_ms INTEGER",     # when the TASK itself (the card, not the list row that every answer moves) was last changed on the site
    "ALTER TABLE ijro_snapshots ADD COLUMN due_mod_ms INTEGER",          # the card's own «modification_date» (when the term was modified), if the site gives one
    "ALTER TABLE ijro_snapshots ADD COLUMN ext_date TEXT",               # «Муддат узайтириш санаси» of the Excel list: the date the term was extended (a copy of tasks.ext_date)
    "ALTER TABLE tasks ADD COLUMN ext_date TEXT",
    "ALTER TABLE tasks ADD COLUMN ext_n INTEGER",
    "ALTER TABLE tasks ADD COLUMN site_code TEXT NOT NULL DEFAULT ''",        # the code of the site when the task is one PERIOD of a periodic task (code is then «КОД#срок»); empty = code
    "ALTER TABLE tasks ADD COLUMN status_manual INTEGER NOT NULL DEFAULT 0",    # a person set the status by hand: the task is no longer checked against the site
    "ALTER TABLE tasks ADD COLUMN manual INTEGER NOT NULL DEFAULT 0",       # 1 = a task added by hand: a loaded base never takes it off the dashboard
]
# pw_set = somebody has issued this person a password (people created by the Excel import have none yet)
BACKFILL_PW_SET = """UPDATE users SET pw_set=1 WHERE role='admin'
    OR id IN (SELECT user_id FROM audit WHERE action='login.ok' AND user_id IS NOT NULL)
    OR id IN (SELECT entity_id FROM audit WHERE action IN ('user.password','user.create') AND entity_id IS NOT NULL)"""


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=20000")
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
        add_missing_units(c)
        remove_wrong_units(c)
        if not c.execute("SELECT 1 FROM settings WHERE key='status_manual_backfill'").fetchone():      # once: tasks whose status a person has already changed are not checked against the site
            c.execute("UPDATE tasks SET status_manual=1 WHERE id IN (SELECT task_id FROM task_events WHERE field='status' AND user_id IS NOT NULL)")
            c.execute("INSERT INTO settings(key, value) VALUES ('status_manual_backfill', '1')")
        if not c.execute("SELECT 1 FROM settings WHERE key='own_default_applied'").fetchone():   # once: employees see only their own tasks
            put_settings(c, {"users_tasks": "own", "own_default_applied": "1"})
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


ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


def add_missing_units(c) -> None:
    """Once: the structure of the customer has three more departments than the first one (the department itself, standards, the second section).
    Added to a database that already has units, unless a unit with that name is already there (compared in Latin and Cyrillic alike). A flag keeps
    a department that was deleted on purpose from coming back."""
    if c.execute("SELECT 1 FROM settings WHERE key='units_extra_1'").fetchone():
        return
    from .site_import import similarity
    have = c.execute("SELECT num, name, parent_id FROM units").fetchall()
    if have:
        used = {r["num"] for r in have if r["parent_id"] is None}
        sort = (c.execute("SELECT COALESCE(MAX(sort), 0) FROM units").fetchone()[0] or 0) + 1
        for num, name, _ in UNITS_EXTRA:
            if any(similarity(name, r["name"]) >= 0.9 for r in have):
                continue
            free = num if num not in used else next((x for x in ROMAN if x not in used), num)
            c.execute("INSERT INTO units(num, name, parent_id, sort) VALUES (?,?,NULL,?)", (free, name, sort))
            used.add(free)
            sort += 1
    c.execute("INSERT INTO settings(key, value) VALUES ('units_extra_1', '1') ON CONFLICT(key) DO NOTHING")


def remove_wrong_units(c) -> None:
    """Once: two departments (Standards, the Second section) were added to the structure by mistake; they are deleted again when nobody is in them."""
    if c.execute("SELECT 1 FROM settings WHERE key='units_wrong_removed'").fetchone():
        return
    from .site_import import similarity
    for u in c.execute("SELECT id, name FROM units").fetchall():
        if any(similarity(u["name"], bad) >= 0.9 for bad in UNITS_NOT_OURS):
            busy = c.execute("SELECT 1 FROM users WHERE unit_id=?", (u["id"],)).fetchone() or c.execute("SELECT 1 FROM units WHERE parent_id=?", (u["id"],)).fetchone()
            if not busy:
                c.execute("DELETE FROM unit_aliases WHERE unit_id=?", (u["id"],))
                c.execute("DELETE FROM units WHERE id=?", (u["id"],))
    c.execute("INSERT INTO settings(key, value) VALUES ('units_wrong_removed', '1') ON CONFLICT(key) DO NOTHING")


def unit_tree_ids(c, unit_id: int) -> list[int]:
    """The unit and everything inside it (a management includes its divisions)."""
    ids = [unit_id]
    for r in c.execute("SELECT id FROM units WHERE parent_id=? AND active=1", (unit_id,)):      # a hidden division is not in the management any more (its people are «Без отдела»)
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
