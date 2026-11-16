"""Consistent copies of the database through SQLite's backup API. Copies stay on the same disk: copy
/data/backups to another machine regularly, otherwise a lost server takes them along."""
import os
import sqlite3
import threading
import time
from datetime import datetime

from .db import DATA_DIR, DB_PATH, TZ, audit, tx

DIR = os.path.join(DATA_DIR, "backups")
PREFIX, HOURS, KEEP = "zadachi-", 6, 14


def _files() -> list[str]:
    return sorted(f for f in os.listdir(DIR) if f.startswith(PREFIX) and f.endswith(".db")) if os.path.isdir(DIR) else []


def make() -> str:
    os.makedirs(DIR, exist_ok=True)
    name = f"{PREFIX}{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}.db"
    path = os.path.join(DIR, name)
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(path, 0o600)
    for old in _files()[:-KEEP]:
        os.remove(os.path.join(DIR, old))
    return name


def verify_latest() -> dict:
    files = _files()
    if not files:
        return {"ok": False, "error": "Копий ещё нет"}
    try:
        c = sqlite3.connect(f"file:{os.path.join(DIR, files[-1])}?mode=ro", uri=True)
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        finally:
            c.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}
    return {"ok": ok, "file": files[-1], "tasks": n}


def _loop() -> None:
    while True:
        try:
            files = _files()
            if not files or time.time() - os.path.getmtime(os.path.join(DIR, files[-1])) >= HOURS * 3600:
                make()
        except Exception:  # a failed copy must not take the site down
            pass
        time.sleep(600)


def start() -> None:
    threading.Thread(target=_loop, daemon=True, name="backup").start()


def make_now() -> str:
    name = make()
    with tx() as c:
        audit(c, "backup.make", "backup", None, {"file": name})
    return name
