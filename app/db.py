"""SQLite: users, sessions, tasks, change history, import log, audit. One file, easy to back up."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "zadachi.db")
TZ = timezone(timedelta(hours=5))  # Uzbekistan has no daylight saving time

STATUSES = {"todo": "Не выполнено", "progress": "В работе", "done": "Выполнено", "info": "К сведению"}
OPEN = ("todo", "progress")


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def today() -> date:
    """Today in Tashkent. ZADACHI_TODAY=YYYY-MM-DD pins the date (tests, demos)."""
    pinned = os.environ.get("ZADACHI_TODAY")
    return date.fromisoformat(pinned) if pinned else datetime.now(TZ).date()


TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    excel_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
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
"""
# The change history and the audit log are append-only, enforced by the database itself.
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON task_events BEGIN SELECT RAISE(ABORT, 'История изменений неизменяема'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'Журнал неизменяем'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'Журнал неизменяем'); END;
"""

DEFAULT_SETTINGS = {"users_tasks": "all"}  # what role "user" may see: all tasks (read-only) | own | none


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
        c.executescript(INDEXES)
        c.executescript(TRIGGERS)
        auth.ensure_admin(c)


def setting(key: str) -> str:
    c = connect()
    try:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    finally:
        c.close()
    return r["value"] if r else DEFAULT_SETTINGS.get(key, "")


def audit(c: sqlite3.Connection, action: str, entity: str = "", entity_id: int | None = None, details: dict | None = None) -> None:
    from . import auth

    user = auth.CURRENT.get()
    c.execute("INSERT INTO audit(user_id, action, entity, entity_id, details, ip, created_at) VALUES (?,?,?,?,?,?,?)",
              (user["id"] if user else None, action, entity, entity_id,
               json.dumps(details or {}, ensure_ascii=False), auth.CURRENT_IP.get(), now()))
