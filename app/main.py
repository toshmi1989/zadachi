"""Zadachi: task tracking with a dashboard. Single-page UI + JSON API; roles are enforced here, not in the browser."""
import io
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import openpyxl
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, backup, importer, stats, tasks
from .db import STATUSES, audit, connect, init_db, now, setting, tx

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
MAX_UPLOAD = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(_app):
    init_db()
    if os.environ.get("ZADACHI_NO_BACKUP") != "1":
        backup.start()
    yield


app = FastAPI(title="Zadachi", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

OPEN_PATHS = ("/healthz", "/login")
ADMIN_ONLY = re.compile(r"^/api/(users|import|settings|backup|audit)(/|$)")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'self'; form-action 'self'",
}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() if fwd else (request.client.host if request.client else "")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    ip_token = auth.CURRENT_IP.set(client_ip(request))
    try:
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != "null":
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            if urlparse(origin).netloc != host:
                return JSONResponse({"error": "Запрос с чужого сайта отклонён"}, 403)
        user = auth.user_from_token(request.cookies.get("sid"))
        request.state.user = user
        resp = None
        if not user and path not in OPEN_PATHS and not path.startswith("/static/"):
            resp = JSONResponse({"error": "Требуется вход"}, 401) if path.startswith("/api/") else RedirectResponse("/login", 303)
        elif user and ADMIN_ONLY.match(path) and user["role"] != "admin":
            resp = JSONResponse({"error": "Раздел доступен только администратору"}, 403)
        if resp is None:
            token = auth.CURRENT.set(user)
            try:
                resp = await call_next(request)
            finally:
                auth.CURRENT.reset(token)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp
    finally:
        auth.CURRENT_IP.reset(ip_token)


@app.exception_handler(tasks.TaskError)
async def task_error(_r, exc: tasks.TaskError):
    return JSONResponse({"error": exc.message}, exc.status)


@app.exception_handler(HTTPException)
async def http_error(_r, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, exc.status_code)


def me(request: Request) -> dict:
    return request.state.user


def bad(message: str, status: int = 400):
    raise HTTPException(status, message)


# ---------------------------------------------------------------- pages and login

@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


LOGIN_HTML = open(os.path.join(STATIC, "login.html"), encoding="utf-8").read()


def login_page(error: str = "", status: int = 200):
    return HTMLResponse(LOGIN_HTML.replace("{{error}}", error), status, headers={"Cache-Control": "no-store"})


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return RedirectResponse("/", 303) if request.state.user else login_page()


@app.post("/login")
def login_post(request: Request, login: str = Form(...), password: str = Form(...)):
    ip = client_ip(request)
    if auth.too_many_fails(ip):
        return login_page("Слишком много попыток. Подождите 15 минут.", 429)
    res = auth.login(login, password)
    if not res:
        auth.record_fail(ip)
        with tx() as c:
            audit(c, "login.fail", "user", None, {"login": login[:60]})
        return login_page("Неверный логин или пароль.", 401)
    auth.clear_fails(ip)
    auth.CURRENT.set({"id": res["user_id"]})
    with tx() as c:
        audit(c, "login.ok", "user", res["user_id"], {})
    resp = RedirectResponse("/", 303)
    resp.set_cookie("sid", res["token"], httponly=True, samesite="lax", max_age=auth.SESSION_DAYS * 86400,
                    secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return resp


@app.post("/logout")
def logout(request: Request):
    auth.logout(request.cookies.get("sid"))
    resp = RedirectResponse("/login", 303)
    resp.delete_cookie("sid")
    return resp


# ---------------------------------------------------------------- who am I, what may I see

def task_scope(user: dict) -> str:
    """all | own | none: what this user may see in the task list. The administrator always sees everything."""
    if user["role"] == "admin":
        return "all"
    s = setting("users_tasks")
    return s if s in ("all", "own", "none") else "all"


def need_tasks(request: Request) -> str:
    scope = task_scope(me(request))
    if scope == "none":
        bad("Список задач для вашей роли отключён администратором", 403)
    return scope


@app.get("/api/me")
def api_me(request: Request):
    u = me(request)
    return {"id": u["id"], "login": u["login"], "name": u["name"], "short": auth.short_name(u["name"]), "role": u["role"],
            "role_label": auth.ROLES[u["role"]], "tasks": task_scope(u), "statuses": STATUSES, "buckets": tasks.BUCKETS}


@app.get("/api/dashboard")
def api_dashboard(by: str = "close"):
    c = connect()
    try:
        return stats.dashboard(c, by)
    finally:
        c.close()


@app.get("/api/meta")
def api_meta(request: Request):
    """Lists for filters: people, document kinds and documents."""
    need_tasks(request)
    c = connect()
    try:
        people = [{"id": u["id"], "name": u["name"], "short": auth.short_name(u["name"])}
                  for u in c.execute("SELECT id, name FROM users WHERE active=1 ORDER BY name")]
        kinds = [r[0] for r in c.execute("SELECT DISTINCT kind FROM tasks ORDER BY kind")]
        docs = [{"doc": r["doc_no"], "kind": r["kind"], "n": r["n"]} for r in
                c.execute("SELECT doc_no, kind, COUNT(*) n FROM tasks GROUP BY doc_no, kind ORDER BY n DESC, doc_no")]
        return {"people": people, "kinds": kinds, "docs": docs}
    finally:
        c.close()


# ---------------------------------------------------------------- tasks

FILTER_KEYS = ("assignee", "status", "bucket", "kind", "doc", "q", "by", "sort", "dir", "date_from", "date_to")


def filters(request: Request) -> dict:
    return {k: request.query_params.get(k, "") for k in FILTER_KEYS}


@app.get("/api/tasks")
def api_tasks(request: Request, page: int = 1, size: int = 50):
    scope = need_tasks(request)
    size = max(1, min(size, 200))
    c = connect()
    try:
        return tasks.list_tasks(c, filters(request), me(request), scope == "own", limit=size, offset=(max(page, 1) - 1) * size) | {"page": max(page, 1), "size": size}
    finally:
        c.close()


@app.get("/api/tasks.xlsx")
def api_tasks_xlsx(request: Request):
    scope = need_tasks(request)
    c = connect()
    try:
        data = tasks.list_tasks(c, filters(request), me(request), scope == "own", limit=None)
    finally:
        c.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Задачи"
    ws.append(["№", "Код", "Тип", "Документ", "Пункт", "Содержание", "Срок (официальный)", "Дата закрытия", "Ответственный", "Статус", "Группа срока", "Дней до срока"])
    for t in data["items"]:
        ws.append([t["num"] or None, t["code"], t["kind"], t["doc_no"], t["point"], t["text"], t["due"], t["close_date"], t["assignee_name"],
                   STATUSES[t["status"]], tasks.BUCKETS.get(t["bucket"], STATUSES.get(t["bucket"], "")), t["days"]])
    for col, w in zip("ABCDEFGHIJKL", (6, 10, 9, 18, 22, 70, 14, 14, 30, 14, 16, 10)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="zadachi.xlsx"'})


@app.get("/api/tasks/{task_id}")
def api_task(request: Request, task_id: int, by: str = "close"):
    scope = need_tasks(request)
    c = connect()
    try:
        return tasks.get_task(c, task_id, me(request), scope == "own", "due" if by == "due" else "close")
    finally:
        c.close()


async def _json(request: Request) -> dict:
    try:
        b = await request.json()
    except ValueError:
        bad("Ожидался JSON")
    if not isinstance(b, dict):
        bad("Ожидался объект JSON")
    return b


EDITABLE = ("assignee_id", "status", "close_date")


@app.patch("/api/tasks/{task_id}")
async def api_task_update(request: Request, task_id: int):
    if me(request)["role"] != "admin":
        bad("Задачи редактирует администратор", 403)
    b = await _json(request)
    changes = {k: b[k] for k in EDITABLE if k in b}
    if not changes:
        bad("Нечего менять")
    with tx() as c:
        changed = tasks.update_task(c, task_id, changes, me(request)["id"])
        if changed:
            audit(c, "task.update", "task", task_id, changes)
        out = tasks.get_task(c, task_id, me(request), False)
    return out | {"changed": changed}


@app.post("/api/tasks/bulk")
async def api_task_bulk(request: Request):
    if me(request)["role"] != "admin":
        bad("Задачи редактирует администратор", 403)
    b = await _json(request)
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or not all(isinstance(i, int) for i in ids):
        bad("Выберите от 1 до 1000 задач")
    changes = {k: b[k] for k in EDITABLE if k in b}
    if not changes:
        bad("Нечего менять")
    n = 0
    with tx() as c:
        for i in ids:
            n += tasks.update_task(c, i, changes, me(request)["id"])
        audit(c, "task.bulk", "task", None, {"ids": len(ids), "changed": n, **changes})
    return {"changed": n, "total": len(ids)}


# ---------------------------------------------------------------- users

def user_row(r) -> dict:
    return {"id": r["id"], "login": r["login"], "name": r["name"], "short": auth.short_name(r["name"]), "role": r["role"],
            "active": bool(r["active"]), "excel_name": r["excel_name"], "tasks": r["n"], "open": r["o"]}


USERS_SQL = """SELECT u.*, (SELECT COUNT(*) FROM tasks WHERE assignee_id=u.id) n,
               (SELECT COUNT(*) FROM tasks WHERE assignee_id=u.id AND status IN ('todo','progress')) o FROM users u"""


def relink(c, uid: int, *names: str) -> int:
    """Tasks that came from Excel with this person's name but had nobody to attach to."""
    keys = {auth.norm_name(n) for n in names if n}
    n = 0
    for r in c.execute("SELECT id, assignee_raw FROM tasks WHERE assignee_id IS NULL AND assignee_raw != ''").fetchall():
        if auth.norm_name(r["assignee_raw"]) in keys:
            c.execute("UPDATE tasks SET assignee_id=? WHERE id=?", (uid, r["id"]))
            n += 1
    return n


@app.get("/api/users")
def api_users():
    c = connect()
    try:
        return {"items": [user_row(r) for r in c.execute(USERS_SQL + " ORDER BY u.role, u.name")]}
    finally:
        c.close()


@app.post("/api/users")
async def api_user_create(request: Request):
    b = await _json(request)
    login = str(b.get("login") or "").strip().lower()
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()
    role = b.get("role") or "user"
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        bad("Логин: 3–40 символов, латиница, цифры, точка, дефис, подчёркивание")
    if not name:
        bad("Укажите имя")
    if role not in auth.ROLES:
        bad("Неизвестная роль")
    password = str(b.get("password") or "")
    generated = not password
    if generated:
        password = auth.generate_password()
    elif len(password) < 8:
        bad("Пароль не короче 8 символов")
    try:
        with tx() as c:
            cur = c.execute("INSERT INTO users(login, name, password_hash, role, excel_name, created_at) VALUES (?,?,?,?,?,?)",
                            (login, name, auth.hash_password(password), role, str(b.get("excel_name") or "").strip(), now()))
            linked = relink(c, cur.lastrowid, name, b.get("excel_name") or "")
            audit(c, "user.create", "user", cur.lastrowid, {"login": login, "role": role, "linked_tasks": linked})
    except sqlite3.IntegrityError:
        bad("Такой логин уже есть")
    return {"id": cur.lastrowid, "password": password if generated else None, "linked_tasks": linked}


@app.patch("/api/users/{uid}")
async def api_user_update(request: Request, uid: int):
    b = await _json(request)
    with tx() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            bad("Пользователь не найден", 404)
        name = re.sub(r"\s+", " ", str(b.get("name", u["name"]))).strip() or u["name"]
        role = b.get("role", u["role"])
        active = int(bool(b.get("active", u["active"])))
        excel = str(b.get("excel_name", u["excel_name"])).strip()
        if role not in auth.ROLES:
            bad("Неизвестная роль")
        if uid == me(request)["id"] and (role != "admin" or not active):
            bad("Нельзя отключить или понизить самого себя")
        if u["role"] == "admin" and (role != "admin" or not active) and c.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id != ?", (uid,)).fetchone()[0] == 0:
            bad("Должен остаться хотя бы один активный администратор")
        c.execute("UPDATE users SET name=?, role=?, active=?, excel_name=? WHERE id=?", (name, role, active, excel, uid))
        if not active:
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        linked = relink(c, uid, name, excel)
        audit(c, "user.update", "user", uid, {"role": role, "active": bool(active)})
    return {"ok": True, "linked_tasks": linked}


@app.post("/api/users/{uid}/password")
async def api_user_password(request: Request, uid: int):
    b = await _json(request)
    password = str(b.get("password") or "")
    generated = not password
    if generated:
        password = auth.generate_password()
    elif len(password) < 8:
        bad("Пароль не короче 8 символов")
    with tx() as c:
        if not c.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(password), uid)).rowcount:
            bad("Пользователь не найден", 404)
        if uid != me(request)["id"]:  # other devices of this person are logged out, the admin keeps their own session
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        audit(c, "user.password", "user", uid, {})
    return {"password": password if generated else None}


@app.post("/api/me/password")
async def api_my_password(request: Request):
    b = await _json(request)
    u = me(request)
    c = connect()
    try:
        row = c.execute("SELECT password_hash FROM users WHERE id=?", (u["id"],)).fetchone()
    finally:
        c.close()
    if not auth.verify_password(str(b.get("old") or ""), row["password_hash"]):
        bad("Текущий пароль неверен")
    new = str(b.get("new") or "")
    if len(new) < 8:
        bad("Новый пароль не короче 8 символов")
    with tx() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(new), u["id"]))
        audit(c, "password.change", "user", u["id"], {})
    return {"ok": True}


# ---------------------------------------------------------------- import, settings, backup, audit

@app.post("/api/import")
async def api_import(request: Request, file: UploadFile = File(...), dry: int = 1):
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        bad("Файл больше 15 МБ")
    try:
        rows, warnings = importer.read(data)
    except importer.ImportError_ as e:
        bad(str(e))
    with tx() as c:
        summary = importer.apply(c, rows, warnings, file.filename or "export.xlsx", me(request)["id"], bool(dry))
    return summary


@app.get("/api/import/history")
def api_import_history():
    import json
    c = connect()
    try:
        return {"items": [{"filename": r["filename"], "created_at": r["created_at"], "by": r["who"], "summary": json.loads(r["summary"])}
                          for r in c.execute("""SELECT i.*, u.name AS who FROM imports i LEFT JOIN users u ON u.id=i.user_id
                                                ORDER BY i.id DESC LIMIT 10""")]}
    finally:
        c.close()


@app.get("/api/settings")
def api_settings():
    return {"users_tasks": setting("users_tasks"), "backup": {"files": len(backup._files()), "latest": backup.verify_latest()}}


@app.put("/api/settings")
async def api_settings_put(request: Request):
    b = await _json(request)
    v = b.get("users_tasks")
    if v not in ("all", "own", "none"):
        bad("Допустимо: all, own, none")
    with tx() as c:
        c.execute("INSERT INTO settings(key, value) VALUES ('users_tasks', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (v,))
        audit(c, "settings.update", "settings", None, {"users_tasks": v})
    return {"ok": True}


@app.post("/api/backup")
def api_backup():
    return {"file": backup.make_now()}


@app.get("/api/audit")
def api_audit(limit: int = 100):
    c = connect()
    try:
        return {"items": [dict(r) for r in c.execute(
            """SELECT a.id, a.action, a.entity, a.entity_id, a.details, a.ip, a.created_at, u.name AS who
               FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?""", (max(1, min(limit, 500)),))]}
    finally:
        c.close()
