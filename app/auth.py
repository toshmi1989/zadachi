"""Accounts: login + password, two roles.

admin — sees the dashboard and all tasks, edits tasks (assignee, status, closing date), manages users and imports
user  — sees the dashboard; the task list is read-only and the administrator decides how much of it (setting users_tasks)
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextvars import ContextVar

from .db import connect, now, tx

SESSION_DAYS = 30
ROLES = {"admin": "Администратор", "user": "Пользователь"}
CURRENT: ContextVar[dict | None] = ContextVar("current_user", default=None)
CURRENT_IP: ContextVar[str] = ContextVar("current_ip", default="")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


def generate_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes (l, 1, O, 0)
    return "".join(secrets.choice(alphabet) for _ in range(10))


def unusable_hash() -> str:
    """A hash nobody can log in with: a person imported from Excel has no password until the admin issues one."""
    return hash_password(secrets.token_urlsafe(24))


def ensure_admin(c: sqlite3.Connection) -> None:
    if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    password = os.environ.get("APP_PASSWORD")
    generated = not password
    if generated:
        password = generate_password()
    c.execute("INSERT INTO users(login, name, password_hash, role, created_at) VALUES ('admin', 'Администратор', ?, 'admin', ?)",
              (hash_password(password), now()))
    if generated:
        print(f'Создан администратор: логин "admin", пароль "{password}". Запишите его и смените на странице «Пользователи».', flush=True)


def short_name(name: str) -> str:
    parts = name.split()
    return f"{parts[0]} {parts[1][0]}." if len(parts) > 1 else name


def norm_name(s: str) -> str:
    s = (s or "").replace("‘", "'").replace("’", "'").replace("ʻ", "'").replace("ʼ", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s).strip().casefold()


def make_login(c: sqlite3.Connection, name: str) -> str:
    parts = [re.sub(r"[^a-z0-9]", "", p.casefold()) for p in name.split()]
    parts = [p for p in parts if p]
    base = (parts[0] + ("." + parts[1][0] if len(parts) > 1 else "")) if parts else "user"
    login, n = base, 1
    while c.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
        n += 1
        login = f"{base}{n}"
    return login


def _new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with tx() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
        c.execute(f"INSERT INTO sessions(token, user_id, expires_at) VALUES (?,?, datetime('now', '+{SESSION_DAYS} days'))", (token, user_id))
    return token


def login(login_name: str, password: str) -> dict | None:
    c = connect()
    u = c.execute("SELECT * FROM users WHERE login=? AND active=1", (login_name.strip(),)).fetchone()
    c.close()
    if not u or not verify_password(password, u["password_hash"]):
        return None
    return {"token": _new_session(u["id"]), "user_id": u["id"]}


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    c = connect()
    row = c.execute("""SELECT u.id, u.login, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id
                       WHERE s.token=? AND s.expires_at > datetime('now') AND u.active=1""", (token,)).fetchone()
    c.close()
    return dict(row) if row else None


def logout(token: str | None) -> None:
    if token:
        with tx() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))


MAX_FAILS, WINDOW = 10, 15 * 60
_fails: dict[str, list[float]] = {}


def too_many_fails(ip: str) -> bool:
    t = time.time()
    _fails[ip] = [x for x in _fails.get(ip, []) if t - x < WINDOW]
    return len(_fails[ip]) >= MAX_FAILS


def record_fail(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())


def clear_fails(ip: str) -> None:
    _fails.pop(ip, None)
