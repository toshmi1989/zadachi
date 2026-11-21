"""Zadachi: task tracking with a dashboard. Single-page UI + JSON API; roles are enforced here, not in the browser."""
import io
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import openpyxl
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, backup, closing, importer, ijro, reminders, site_import, stats, tasks, telegram
from .db import STATUSES, audit, connect, init_db, now, setting, today, tx

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
MAX_UPLOAD = 40 * 1024 * 1024      # the one common list of the site (all statuses) is much larger than a list of one tab


@asynccontextmanager
async def lifespan(_app):
    init_db()
    if os.environ.get("ZADACHI_NO_BACKUP") != "1":
        backup.start()
    telegram.start()
    yield


app = FastAPI(title="Zadachi", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

OPEN_PATHS = ("/healthz", "/login", "/api/login-users", "/ijro-sync.user.js")
BEARER_PATHS = ("/api/sync/job", "/api/sync/ingest", "/api/sync/export", "/api/sync/export-plan", "/api/sync/finish")   # opened with a key of the platform (collector in a browser), not with a cookie
ADMIN_ONLY = re.compile(r"^/api/(users|units|import|settings|backup|audit|ai|closing|sync/(keys|review|apply|settings)|reminders/(settings|preview|run|log))(/|$)")
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
        if path in BEARER_PATHS:   # the collector: no cookie, no Origin check (a browser attack cannot carry this key)
            ip = client_ip(request)
            if auth.too_many_fails(ip):
                return JSONResponse({"error": "Слишком много неверных ключей. Подождите 15 минут."}, 429)
            c = connect()
            try:
                key = ijro.check_key(c, request.headers.get("authorization"))
                c.commit()
            finally:
                c.close()
            if not key:
                auth.record_fail(ip)
                return JSONResponse({"error": "Ключ синхронизации не подошёл или отозван"}, 401)
            request.state.key = key
            request.state.user = None
            resp = await call_next(request)
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            resp.headers["Cache-Control"] = "no-store"
            return resp
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


def login_page(error: str = "", status: int = 200, uid: str = "", login: str = ""):
    import html
    page = (LOGIN_HTML.replace("{{error}}", html.escape(error)).replace("{{uid}}", html.escape(uid if uid.isdigit() else ""))
            .replace("{{login}}", html.escape(login[:60])))
    return HTMLResponse(page, status, headers={"Cache-Control": "no-store"})


def pickable(c):
    """People shown on the sign-in page: active, with a password, not administrators (those type their login)."""
    return c.execute("SELECT id, name FROM users WHERE active=1 AND pw_set=1 AND role != 'admin' ORDER BY name").fetchall()


def login_for_uid(uid: str) -> str:
    if not uid.isdigit() or setting("login_list") != "1":
        return ""
    c = connect()
    try:
        if not any(r["id"] == int(uid) for r in pickable(c)):
            return ""
        return c.execute("SELECT login FROM users WHERE id=?", (int(uid),)).fetchone()["login"]
    finally:
        c.close()


@app.get("/api/login-users")
def api_login_users():
    """Public on purpose: the sign-in page lets people pick their name. Only ids and names, never logins; the administrator can switch it off."""
    if setting("login_list") != "1":
        return {"enabled": False, "items": []}
    c = connect()
    try:
        return {"enabled": True, "items": [{"id": r["id"], "name": r["name"]} for r in pickable(c)]}
    finally:
        c.close()


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return RedirectResponse("/", 303) if request.state.user else login_page()


@app.post("/login")
def login_post(request: Request, login: str = Form(""), password: str = Form(...), uid: str = Form("")):
    ip = client_ip(request)
    if auth.too_many_fails(ip):
        return login_page("Слишком много попыток. Подождите 15 минут.", 429, uid, login)
    if uid:  # a person picked from the list: the login is looked up on the server, the browser never sees it
        login = login_for_uid(uid)
    res = auth.login(login, password) if login else None
    if not res:
        auth.record_fail(ip)
        with tx() as c:
            audit(c, "login.fail", "user", None, {"login": login[:60], "picked": bool(uid)})
        return login_page("Неверный пароль." if uid else "Неверный логин или пароль.", 401, uid, login if not uid else "")
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
def api_dashboard(request: Request, by: str = "close"):
    c = connect()
    try:
        return stats.dashboard(c, tasks.norm_by(by, me(request)))
    finally:
        c.close()


def unit_list(c) -> list[dict]:
    """Active units in display order: a management, then its divisions."""
    rows = c.execute("SELECT id, num, name, parent_id FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    return [{"id": r["id"], "num": r["num"], "name": r["name"], "parent_id": r["parent_id"], "level": 1 if r["parent_id"] else 0} for r in rows]


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
        return {"people": people, "kinds": kinds, "docs": docs, "units": unit_list(c)}
    finally:
        c.close()


# ---------------------------------------------------------------- tasks

FILTER_KEYS = ("unit", "assignee", "status", "bucket", "kind", "doc", "q", "by", "sort", "dir", "date_from", "date_to", "stage", "closing", "term")


def filters(request: Request) -> dict:
    return {k: request.query_params.get(k, "") for k in FILTER_KEYS}


@app.get("/api/tasks")
def api_tasks(request: Request, page: int = 1, size: int = 50):
    scope = need_tasks(request)
    size = max(1, min(size, 200))
    c = connect()
    try:
        out = tasks.list_tasks(c, filters(request), me(request), scope == "own", limit=size, offset=(max(page, 1) - 1) * size) | {"page": max(page, 1), "size": size}
        for t in out["items"]:
            t["can_edit"] = me(request)["role"] == "admin" or t["assignee_id"] == me(request)["id"]
        ijro.brief(c, [t for t in out["items"] if t["can_edit"]], me(request)["role"] == "admin")
        return out
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
    admin = me(request)["role"] == "admin"
    head = ["№", "Код", "Тип", "Документ", "Пункт", "Содержание"] + (["Срок (официальный)"] if admin else []) + ["Дата закрытия", "Ответственный", "Статус", "Группа срока", "Дней до срока"]
    widths = [6, 10, 9, 18, 22, 70] + ([14] if admin else []) + [14, 30, 14, 16, 10]
    ws.append(head)
    for t in data["items"]:
        ws.append([t["num"] or None, t["code"], t["kind"], t["doc_no"], t["point"], t["text"]] + ([t["due"]] if admin else []) +
                  [t["close_date"], t["assignee_name"], STATUSES[t["status"]], tasks.BUCKETS.get(t["bucket"], STATUSES.get(t["bucket"], "")), t["days"]])
    for i, w in enumerate(widths):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i + 1)].width = w
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
        out = tasks.get_task(c, task_id, me(request), scope == "own", "due" if by == "due" else "close")
        out["can_edit"] = me(request)["role"] == "admin" or out["assignee_id"] == me(request)["id"]
        if out["can_edit"]:   # what the site says: for administrators and for the employee a task belongs to (not the official term)
            snap = c.execute("SELECT * FROM ijro_snapshots WHERE task_id=?", (task_id,)).fetchone()
            out["site"] = ijro.site_info(snap, out["status"], out["due"], me(request)["role"] == "admin") if snap else None
        return out
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


USER_STATUSES = ("todo", "progress", "done")   # an employee cannot mark a task "for information": that is a decision of the administrator


@app.patch("/api/tasks/{task_id}")
async def api_task_update(request: Request, task_id: int):
    user = me(request)
    b = await _json(request)
    changes = {k: b[k] for k in EDITABLE if k in b}
    if not changes:
        bad("Нечего менять")
    if user["role"] != "admin":
        # an employee: only the status, only of their own task, only to a status they may set
        scope = need_tasks(request)
        c = connect()
        try:
            row = c.execute("SELECT assignee_id, status FROM tasks WHERE id=?", (task_id,)).fetchone()
        finally:
            c.close()
        if not row or (scope == "own" and row["assignee_id"] != user["id"]):
            bad("Задача не найдена", 404)
        if row["assignee_id"] != user["id"]:
            bad("Статус можно менять только у своих задач", 403)
        if set(changes) != {"status"}:
            bad("Сотрудник может менять только статус своей задачи", 403)
        if changes["status"] not in USER_STATUSES:
            bad("Этот статус ставит администратор", 403)
        if row["status"] == "info":
            bad("Задача принята к сведению: статус меняет администратор", 403)
    with tx() as c:
        before = c.execute("SELECT assignee_id FROM tasks WHERE id=?", (task_id,)).fetchone()
        changed = tasks.update_task(c, task_id, changes, user["id"])
        if changed:
            audit(c, "task.update", "task", task_id, changes | {"by_role": user["role"]})
        out = tasks.get_task(c, task_id, user, False)
        out["can_edit"] = True
        snap = c.execute("SELECT * FROM ijro_snapshots WHERE task_id=?", (task_id,)).fetchone()
        out["site"] = ijro.site_info(snap, out["status"], out["due"], user["role"] == "admin") if snap else None
    if user["role"] == "admin" and changed and before and out["assignee_id"] and out["assignee_id"] != before["assignee_id"] and out["assignee_id"] != user["id"]:
        reminders.notify_assigned([(task_id, out["assignee_id"])])
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
    n, assigned = 0, []
    with tx() as c:
        for i in ids:
            old = c.execute("SELECT assignee_id FROM tasks WHERE id=?", (i,)).fetchone()
            n += tasks.update_task(c, i, changes, me(request)["id"])
            new = c.execute("SELECT assignee_id FROM tasks WHERE id=?", (i,)).fetchone()
            if old and new and new["assignee_id"] and new["assignee_id"] != old["assignee_id"] and new["assignee_id"] != me(request)["id"]:
                assigned.append((i, new["assignee_id"]))
        audit(c, "task.bulk", "task", None, {"ids": len(ids), "changed": n, **changes})
    if assigned:
        reminders.notify_assigned(assigned)
    return {"changed": n, "total": len(ids)}


# ---------------------------------------------------------------- users

def user_row(r) -> dict:
    return {"id": r["id"], "login": r["login"], "name": r["name"], "short": auth.short_name(r["name"]), "role": r["role"],
            "active": bool(r["active"]), "excel_name": r["excel_name"], "tasks": r["n"], "open": r["o"],
            "unit_id": r["unit_id"], "unit": r["unit_name"] or "", "pw_set": bool(r["pw_set"]),
            "tg_linked": bool(r["tg_chat_id"]), "tg_username": r["tg_username"], "remind": bool(r["remind"])}


USERS_SQL = """SELECT u.*, (SELECT name FROM units WHERE id=u.unit_id) unit_name, (SELECT COUNT(*) FROM tasks WHERE assignee_id=u.id AND status != 'gone') n,
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


def check_unit(c, v):
    """None for "no department", else the id of an active unit."""
    if v in (None, "", 0, "0"):
        return None
    if not str(v).isdigit() or not c.execute("SELECT 1 FROM units WHERE id=? AND active=1", (int(v),)).fetchone():
        bad("Такого отдела нет")
    return int(v)


@app.get("/api/users")
def api_users():
    c = connect()
    try:
        return {"items": [user_row(r) for r in c.execute(USERS_SQL + " ORDER BY u.role, u.name")], "units": unit_list(c)}
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
            unit = check_unit(c, b.get("unit_id"))
            cur = c.execute("INSERT INTO users(login, name, password_hash, role, excel_name, created_at, pw_set, unit_id) VALUES (?,?,?,?,?,?,1,?)",
                            (login, name, auth.hash_password(password), role, str(b.get("excel_name") or "").strip(), now(), unit))
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
        unit = check_unit(c, b["unit_id"]) if "unit_id" in b else u["unit_id"]
        c.execute("UPDATE users SET name=?, role=?, active=?, excel_name=?, unit_id=? WHERE id=?", (name, role, active, excel, unit, uid))
        if not active:
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        linked = relink(c, uid, name, excel)
        audit(c, "user.update", "user", uid, {"role": role, "active": bool(active), "unit_id": unit})
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
        if not c.execute("UPDATE users SET password_hash=?, pw_set=1 WHERE id=?", (auth.hash_password(password), uid)).rowcount:
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
        c.execute("UPDATE users SET password_hash=?, pw_set=1 WHERE id=?", (auth.hash_password(new), u["id"]))
        audit(c, "password.change", "user", u["id"], {})
    return {"ok": True}


# ---------------------------------------------------------------- import, settings, backup, audit

def ai_on() -> bool:
    return setting("ai_enabled") == "1"


def import_files(datas: list[bytes], filename: str, user_id: int, dry: bool, due_from: str | None, due_to: str | None, ai: bool, suggest: bool = True,
                 ours_out: set | None = None, mode: str = "base", overwrite: bool = False, replace: bool = False, confirm: bool = False, strict: bool = True) -> dict:
    """One import, shared by the screen (files picked by the administrator) and the collector (the list the site's own button makes).
    The files are ONE base (a list per section): they are read together and judged together.
    mode "base": the base load (new tasks are created, fields updated, a window of terms applies). mode "status": only the statuses of tasks already in the
    base (no window: a status is needed whatever the term is).
    overwrite: the file wins over what the administrator edited by hand. replace: the open tasks that are NOT in the loaded base are taken off the dashboard
    («Нет на сайте»; nothing is deleted, they come back if a later base has them). More than a quarter of the open tasks needs `confirm`."""
    status = mode == "status"
    if not strict:
        due_from = due_to = None                       # the files are selected by the person: no window of terms either
    sites = [site_import.is_site_export(d) for d in datas]
    if any(sites) and not all(sites):
        bad("Нельзя загружать вместе выгрузки с сайта и обработанный список: загрузите их по отдельности")
    site = bool(sites) and all(sites)
    report = None
    present = ours_out if ours_out is not None else set()
    try:
        if site:
            raw_all = [r for d in datas for r in site_import._read_rows(d)]
            with tx() as c:
                rows, warnings, report = site_import.read_rows(c, raw_all, None if status else due_from, None if status else due_to, present, strict)
                if not status:
                    report["absent"] = site_import.absent(c, {r["code"] for r in raw_all}, due_from, due_to)[:200]
        else:
            if len(datas) > 1:
                bad("Обработанный список загружается одним файлом")
            rows, warnings = importer.read(datas[0])
            present.update(r["code"] for r in rows)
    except importer.ImportError_ as e:
        bad(str(e))
    gone: list[dict] = []
    open_total = 0
    if replace and not status:
        with tx() as c:
            present |= {r["code"] for r in rows}
            gone = importer.absent_open(c, present)
            open_total = c.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('todo','progress')").fetchone()[0]
        limit = max(10, open_total // 4)
        if not dry and len(gone) > limit and not confirm:
            bad(f"Из базы уйдёт {len(gone)} из {open_total} открытых задач (больше четверти): проверьте файлы (загружены ли все разделы?) и подтвердите снятие")
    with tx() as c:
        summary = importer.apply(c, rows, warnings, filename or "export.xlsx", user_id, dry, mode="status" if status else "base", overwrite=overwrite)
    if replace and not status:
        summary["absent_tasks"] = {"count": len(gone), "open": open_total, "needs_confirm": len(gone) > max(10, open_total // 4), "sample": gone[:50]}
        if not dry and gone:
            with tx() as c:
                summary["absent_tasks"]["taken_off"] = ijro.archive(c, [g["id"] for g in gone])
                audit(c, "import.replace", "tasks", None, {"taken_off": summary["absent_tasks"]["taken_off"], "file": (filename or "")[:200]})
    if report is not None:
        summary["site"] = report
    if site and not dry and ai and suggest and not status:
        summary["closing"] = closing.suggest()
    return summary


def import_file(data: bytes, filename: str, user_id: int, dry: bool, due_from: str | None, due_to: str | None, ai: bool, suggest: bool = True, ours_out: set | None = None,
                mode: str = "base") -> dict:
    return import_files([data], filename, user_id, dry, due_from, due_to, ai, suggest, ours_out, mode)


@app.post("/api/import")
async def api_import(request: Request, file: list[UploadFile] = File(...), dry: int = 1, due_from: str = "", due_to: str = "", ai: int = 1, mode: str = "base",
                     overwrite: int = 0, replace: int = 0, confirm: int = 0, select: str = "ours"):
    """The base load: the lists of the site (one per section, they are read together) or the old processed list. Only our departments, a window of terms,
    the closing dates are proposed. overwrite=1: the file wins over hand edits. replace=1: open tasks that are not in the loaded base leave the dashboard.
    mode=status: only the statuses of tasks that are already in the base."""
    if mode not in ("base", "status"):
        bad("mode: base или status")
    if select not in ("ours", "none"):
        bad("select: ours или none")
    if not file or len(file) > 10:
        bad("Нужно от 1 до 10 файлов")
    datas, total = [], 0
    for f in file:
        d = await f.read(MAX_UPLOAD + 1)
        total += len(d)
        if len(d) > MAX_UPLOAD or total > MAX_UPLOAD * 2:
            bad(f"Файл больше {MAX_UPLOAD // (1024 * 1024)} МБ")
        datas.append(d)
    name = ", ".join((f.filename or "export.xlsx") for f in file)[:200]
    return import_files(datas, name, me(request)["id"], bool(dry), due_from or None, due_to or None, bool(ai), mode=mode, overwrite=bool(overwrite), replace=bool(replace),
                        confirm=bool(confirm), strict=select == "ours")


@app.get("/api/sync/export-plan")
def api_sync_export_plan():
    """What the collector downloads with the site's «Hisobot» button: for each of the three lists the open and the overdue tasks (the two tabs of the site)."""
    return {**ijro.export_plan(),
            "urls": {"export": ijro.SECTIONS["api_tasks"] + "/report/list-by-recipient-export", "presigned": ijro.EDO_API + "/v2/files/presigned-url/download"}}


@app.post("/api/sync/export")
async def api_sync_export(request: Request, source: str = "", last: int = 0, run: str = ""):
    """The Excel export of one of the three lists of the site, sent by the collector (the file is what the site's own «Hisobot» button gives).
    Imported at once with the default window (the last 30 days and the next 60 of terms) and the remembered department mapping;
    departments that are not mapped yet are only reported (they are mapped once, on the import screen). `last=1` on the final file of a run:
    then the closing dates are proposed for the new tasks (once per run, not once per file)."""
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        bad(f"Файл больше {MAX_UPLOAD // (1024 * 1024)} МБ", 413)
    if not data or not site_import.is_site_export(data):
        bad("Это не выгрузка «Топшириқлар кесимида» сайта")
    from datetime import timedelta
    t = today()
    ours: set = set()
    mode = "base" if setting("sync_apply") == "base" else "status"        # Settings: only the statuses of tasks in the base, or new tasks as well
    day = lambda key, sign: (t + timedelta(days=sign * int(setting(key)))).isoformat() if setting(key).strip().isdigit() else None    # empty = no limit
    out = import_file(data, f"sync:{source or 'export'}.xlsx", request.state.key["created_by"], False, day("base_back", -1), day("base_fwd", 1),
                      ai_on(), suggest=bool(last) and mode == "base", ours_out=ours, mode=mode)
    if re.fullmatch(r"[0-9a-fA-F-]{8,64}", run or ""):
        with tx() as c:
            ijro.record_export(c, run, ours)
    site = out.get("site", {})
    return {"source": source, "mode": mode, "rows": out["rows"], "created": out["created"], "updated": out["updated"], "unchanged": out["unchanged"], "missing": out.get("missing", 0),
            "unmapped": [d["name"] for d in site.get("departments", []) if not d.get("unit_id") and d.get("how") != "confirmed"][:30], "skipped": site.get("skipped", {}),
            "closing": out.get("closing")}


@app.put("/api/import/aliases")
async def api_import_aliases(request: Request):
    """Which unit of ours a department name of the site stands for ({key: unit id}; null = not ours). Remembered for the next files."""
    b = await _json(request)
    m = b.get("map")
    if not isinstance(m, dict) or not m:
        bad("Нечего сохранять")
    with tx() as c:
        ids = {r["id"] for r in c.execute("SELECT id FROM units")}
        clean = {}
        for k, v in m.items():
            if not isinstance(k, str) or len(k) > 300:
                bad("Неверное название отдела")
            if v is not None and v not in ids:
                bad("Такого отдела у нас нет")
            clean[k] = v
        n = site_import.save_aliases(c, clean)
        audit(c, "import.aliases", "units", None, {"count": n})
    return {"saved": n}


@app.post("/api/import/add-units")
async def api_import_add_units(request: Request):
    """Adds the departments of a loaded file that are not in the structure of the department (the names are taken as they are written in the file; they go to the end of the
    top level without a number and can be renamed, moved into a management or hidden on the Settings page). A name that already matches a unit of the structure is skipped."""
    b = await _json(request)
    names = b.get("names")
    if not isinstance(names, list) or not names or len(names) > 100 or not all(isinstance(n, str) and n.strip() for n in names):
        bad("names: от 1 до 100 названий отделов")
    made = []
    with tx() as c:
        units = c.execute("SELECT id, name FROM units WHERE active=1").fetchall()
        for raw in names:
            name = re.sub(r"\s+", " ", raw).strip()[:300]
            if site_import.suggest_unit(c, name, units)[1] >= site_import.AUTO_MATCH or any(site_import.skeleton(u["name"]) == site_import.skeleton(name) for u in units):
                continue
            last = c.execute("SELECT MAX(sort) FROM units").fetchone()[0]
            cur = c.execute("INSERT INTO units(num, name, parent_id, sort) VALUES ('', ?, NULL, ?)", (name, (last or 0) + 1))
            units = list(units) + [{"id": cur.lastrowid, "name": name}]
            made.append(name)
        if made:
            audit(c, "unit.create_from_import", "unit", None, {"count": len(made)})
    return {"created": len(made), "skipped": len(names) - len(made)}


@app.put("/api/import/people-units")
async def api_import_people_units(request: Request):
    """Moves employees to the unit the export puts them in (the administrator ticks whom)."""
    b = await _json(request)
    moves = b.get("moves")
    if not isinstance(moves, list) or not moves or not all(isinstance(m, dict) and isinstance(m.get("user_id"), int) and isinstance(m.get("unit_id"), int) for m in moves):
        bad("moves: список {user_id, unit_id}")
    with tx() as c:
        n = 0
        for m in moves:
            if not c.execute("SELECT 1 FROM users WHERE id=?", (m["user_id"],)).fetchone() or not c.execute("SELECT 1 FROM units WHERE id=?", (m["unit_id"],)).fetchone():
                bad("Сотрудник или отдел не найден", 404)
            n += c.execute("UPDATE users SET unit_id=? WHERE id=?", (m["unit_id"], m["user_id"])).rowcount
        audit(c, "import.people_units", "users", None, {"moved": n})
    return {"moved": n}


@app.get("/api/ai")
def api_ai():
    c = connect()
    try:
        ev = closing.evaluate(c)
    finally:
        c.close()
    return closing.settings_view() | {"history": ev}


@app.put("/api/ai")
async def api_ai_put(request: Request):
    b = await _json(request)
    try:
        closing.save_settings(b)
    except ValueError as e:
        bad(str(e))
    return closing.settings_view()


@app.post("/api/ai/test")
def api_ai_test():
    try:
        return {"ok": True, "message": closing.ai_test()}
    except closing.AiError as e:
        return {"ok": False, "message": str(e)}


@app.post("/api/closing/suggest")
async def api_closing_suggest(request: Request):
    b = await _json(request)
    ids = b.get("ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        bad("ids: список чисел")
    return closing.suggest(ids or None, redo=bool(b.get("redo")), use_ai=b.get("ai") is not False)


@app.post("/api/closing/confirm")
async def api_closing_confirm(request: Request):
    b = await _json(request)
    ids = b.get("ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        bad("ids: список чисел")
    return {"confirmed": closing.confirm(ids or None)}


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
    return {"users_tasks": setting("users_tasks"), "login_list": setting("login_list") == "1",
            "sync": {"groups": ijro.SYNC_GROUPS, "fields": ijro.sync_settings_view(), "auto_apply": setting("ijro_auto_apply") == "1", "auto_archive": setting("ijro_auto_archive") == "1"},
            "backup": {"files": len(backup._files()), "latest": backup.verify_latest()}}


@app.put("/api/settings")
async def api_settings_put(request: Request):
    b = await _json(request)
    values = {}
    if "users_tasks" in b:
        if b["users_tasks"] not in ("all", "own", "none"):
            bad("Допустимо: all, own, none")
        values["users_tasks"] = b["users_tasks"]
    if "login_list" in b:
        values["login_list"] = "1" if b["login_list"] else "0"
    if "sync" in b:
        if not isinstance(b["sync"], dict) or not b["sync"]:
            bad("sync: объект {настройка: значение}")
        try:
            values.update(ijro.check_sync_settings(b["sync"]))
        except ValueError as e:
            bad(str(e))
    if not values:
        bad("Нечего менять")
    with tx() as c:
        from .db import put_settings
        put_settings(c, values)
        audit(c, "settings.update", "settings", None, values)
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


# ---------------------------------------------------------------- Telegram and reminders

def _tg_state(uid: int) -> dict:
    c = connect()
    try:
        u = c.execute("SELECT tg_chat_id, tg_username, tg_code_exp FROM users WHERE id=?", (uid,)).fetchone()
    finally:
        c.close()
    return {"configured": telegram.configured(), "bot": telegram.bot_username() if telegram.configured() else "", "linked": bool(u["tg_chat_id"]),
            "username": u["tg_username"], "error": setting("tg_error") if telegram.configured() else "",
            "running": bool(setting("tg_seen")) and telegram.configured()}


@app.get("/api/telegram")
def api_telegram(request: Request):
    return _tg_state(me(request)["id"])


@app.post("/api/telegram/link")
def api_telegram_link(request: Request):
    if not telegram.configured():
        bad("Бот не подключён: администратору нужно указать TELEGRAM_BOT_TOKEN в .env на сервере")
    res = telegram.new_link_code(me(request)["id"])
    if not res["url"]:
        bad("Не удалось связаться с Telegram. Проверьте токен бота и доступ сервера к api.telegram.org")
    return res


@app.post("/api/telegram/unlink")
def api_telegram_unlink(request: Request):
    with tx() as c:
        c.execute("UPDATE users SET tg_chat_id='', tg_username='', tg_code='', tg_code_exp='' WHERE id=?", (me(request)["id"],))
        audit(c, "telegram.unlink", "user", me(request)["id"], {"by": "site"})
    return {"ok": True}


@app.post("/api/telegram/test")
def api_telegram_test(request: Request):
    c = connect()
    try:
        u = c.execute("SELECT tg_chat_id FROM users WHERE id=?", (me(request)["id"],)).fetchone()
    finally:
        c.close()
    if not u["tg_chat_id"]:
        bad("Сначала привяжите Telegram")
    ok, err = telegram.send(u["tg_chat_id"], "✅ <b>Проверка связи</b>\nНапоминания о задачах будут приходить сюда.")
    if not ok:
        bad("Не отправилось: " + err, 502)
    return {"ok": True}


def _my_reminders(uid: int) -> dict:
    c = connect()
    try:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        g = reminders.global_cfg(c)
    finally:
        c.close()
    return {"mine": reminders.user_cfg(u, g), "defaults": {k: g[k] for k in ("enabled", "time", "weekdays", "days", "overdue", "by")}}


@app.get("/api/reminders/me")
def api_reminders_me(request: Request):
    return _my_reminders(me(request)["id"])


@app.put("/api/reminders/me")
async def api_reminders_me_put(request: Request):
    b = await _json(request)
    sets, vals = [], []
    if "remind" in b:
        sets.append("remind=?"); vals.append(int(bool(b["remind"])))
    if "notify_assign" in b:
        sets.append("notify_assign=?"); vals.append(int(bool(b["notify_assign"])))
    if "days" in b:   # null = "like everyone"
        sets.append("remind_days=?"); vals.append("" if b["days"] is None else ",".join(map(str, reminders.parse_days(b["days"]))))
    if "overdue" in b:
        if b["overdue"] is not None and b["overdue"] not in reminders.OVERDUE_CHOICES:
            bad("Недопустимая частота напоминаний о просрочке")
        sets.append("remind_overdue=?"); vals.append(b["overdue"])
    if sets:
        with tx() as c:
            c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*vals, me(request)["id"]))
    return _my_reminders(me(request)["id"])


@app.get("/api/reminders/settings")
def api_reminders_settings():
    return reminders.global_cfg()


@app.put("/api/reminders/settings")
async def api_reminders_settings_put(request: Request):
    b = await _json(request)
    try:
        values = reminders.validate_global(b)
    except (ValueError, TypeError) as e:
        bad(str(e) or "Неверное значение")
    with tx() as c:
        from .db import put_settings
        put_settings(c, values)
        audit(c, "settings.reminders", "settings", None, values)
    return reminders.global_cfg()


@app.get("/api/reminders/preview")
def api_reminders_preview():
    return {"items": reminders.run_due(dry=True, force=True), "config": reminders.global_cfg()}


@app.post("/api/reminders/run")
def api_reminders_run(request: Request):
    res = reminders.run_due(force=True)
    with tx() as c:
        audit(c, "reminders.run", "reminders", None, {"sent": sum(1 for r in res if r["status"] == "sent")})
    return {"items": [{k: v for k, v in r.items() if k != "text"} for r in res]}


@app.get("/api/reminders/log")
def api_reminders_log():
    c = connect()
    try:
        return {"items": [dict(r) for r in c.execute("""SELECT l.day, l.kind, l.ok, l.count, l.detail, l.created_at, u.name FROM reminder_log l
                                                       JOIN users u ON u.id=l.user_id WHERE l.detail != 'nothing to send' ORDER BY l.id DESC LIMIT 30""")]}
    finally:
        c.close()


# ---------------------------------------------------------------- structure of the department

ROMAN = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def roman(n: int) -> str:
    out = ""
    for v, r in ROMAN:
        while n >= v:
            out, n = out + r, n - v
    return out


def unit_out(c) -> list[dict]:
    rows = c.execute("""SELECT un.*, (SELECT COUNT(*) FROM users WHERE unit_id=un.id AND active=1) people FROM units un ORDER BY sort, id""").fetchall()
    return [{"id": r["id"], "num": r["num"], "name": r["name"], "parent_id": r["parent_id"], "active": bool(r["active"]), "people": r["people"],
             "level": 1 if r["parent_id"] else 0} for r in rows]


@app.get("/api/units")
def api_units():
    c = connect()
    try:
        return {"items": unit_out(c)}
    finally:
        c.close()


@app.post("/api/units")
async def api_unit_create(request: Request):
    b = await _json(request)
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()
    if not name or len(name) > 300:
        bad("Укажите название (до 300 знаков)")
    with tx() as c:
        parent = b.get("parent_id")
        if parent:
            p = c.execute("SELECT parent_id FROM units WHERE id=?", (parent,)).fetchone()
            if not p or p["parent_id"]:
                bad("Отдел можно создать только внутри управления")
        sibs = c.execute("SELECT COUNT(*) FROM units WHERE parent_id IS ?", (parent or None,)).fetchone()[0]
        num = str(b.get("num") or "").strip() or (str(sibs + 1) if parent else roman(sibs + 1))
        # a new management goes to the end of the top level, a new division to the end of its management
        if parent:
            last = c.execute("SELECT MAX(sort) FROM units WHERE id=? OR parent_id=?", (parent, parent)).fetchone()[0]
        else:
            last = c.execute("SELECT MAX(sort) FROM units").fetchone()[0]
        sort = (last or 0) + 1
        c.execute("UPDATE units SET sort = sort + 1 WHERE sort >= ?", (sort,))
        cur = c.execute("INSERT INTO units(num, name, parent_id, sort) VALUES (?,?,?,?)", (num[:12], name, parent or None, sort))
        audit(c, "unit.create", "unit", cur.lastrowid, {"name": name})
    return {"id": cur.lastrowid}


@app.patch("/api/units/{unit_id}")
async def api_unit_update(request: Request, unit_id: int):
    b = await _json(request)
    with tx() as c:
        u = c.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
        if not u:
            bad("Отдел не найден", 404)
        name = re.sub(r"\s+", " ", str(b.get("name", u["name"]))).strip() or u["name"]
        num = str(b.get("num", u["num"])).strip()[:12]
        active = int(bool(b.get("active", u["active"])))
        if not active and c.execute("SELECT 1 FROM users WHERE active=1 AND unit_id IN (SELECT id FROM units WHERE id=? OR parent_id=?)", (unit_id, unit_id)).fetchone():
            bad("В отделе есть сотрудники: сначала переведите их в другой отдел")
        c.execute("UPDATE units SET name=?, num=?, active=? WHERE id=?", (name, num, active, unit_id))
        if not active:  # hiding a management hides its divisions with it
            c.execute("UPDATE units SET active=0 WHERE parent_id=?", (unit_id,))
        audit(c, "unit.update", "unit", unit_id, {"name": name, "active": bool(active)})
    return {"ok": True}


@app.delete("/api/units/{unit_id}")
def api_unit_delete(unit_id: int):
    with tx() as c:
        if c.execute("SELECT 1 FROM users WHERE unit_id=?", (unit_id,)).fetchone() or c.execute("SELECT 1 FROM units WHERE parent_id=?", (unit_id,)).fetchone():
            bad("Нельзя удалить: в отделе есть сотрудники или вложенные отделы. Можно скрыть.")
        if not c.execute("DELETE FROM units WHERE id=?", (unit_id,)).rowcount:
            bad("Отдел не найден", 404)
        audit(c, "unit.delete", "unit", unit_id, {})
    return {"ok": True}


# ---------------------------------------------------------------- synchronisation with edo.ijro.uz

@app.get("/ijro-sync.user.js")
def ijro_script(request: Request):
    """The collector for the administrator's browser (Tampermonkey). It holds no secret: the key is typed in once, in the browser."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    origin = f"{proto}://{host}"
    text = open(os.path.join(STATIC, "ijro-sync.user.js"), encoding="utf-8").read().replace("{{ORIGIN}}", origin).replace("{{HOST}}", host.split(":")[0])
    return Response(text, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/api/sync/job")
def api_sync_job(request: Request, resume: int = 0):
    c = connect()
    try:
        out = ijro.job(c, request.state.key["id"], bool(resume))
        c.commit()
        return out
    finally:
        c.close()


@app.post("/api/sync/ingest")
async def api_sync_ingest(request: Request):
    raw = await request.body()
    if len(raw) > 2_000_000:
        bad("Слишком большой пакет", 413)
    try:
        body = json.loads(raw)
    except ValueError:
        bad("Ожидался JSON")
    if not isinstance(body, dict):
        bad("Ожидался объект JSON")
    with tx() as c:
        try:
            out = ijro.ingest(c, request.state.key, body)
        except ValueError as e:
            bad(str(e))
    return out


@app.post("/api/sync/finish")
async def api_sync_finish(request: Request):
    """The collector finished a run: the tasks that the site no longer lists as ours are found (and, within the limit, taken off the dashboard)."""
    b = await _json(request)
    run = str(b.get("run") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", run):
        bad("Неверный номер запуска")
    with tx() as c:
        return ijro.finish_run(c, run, bool(b.get("complete")))


@app.get("/api/sync/stale")
def api_sync_stale():
    c = connect()
    try:
        return {"items": ijro.stale_list(c), "auto_archive": setting("ijro_auto_archive") == "1"}
    finally:
        c.close()


@app.post("/api/sync/archive")
async def api_sync_archive(request: Request):
    """The administrator takes the proposed tasks off the dashboard (all of them, or the ticked ones)."""
    b = await _json(request)
    with tx() as c:
        ids = b.get("task_ids")
        if ids is None:
            ids = [r["task_id"] for r in c.execute("SELECT task_id FROM site_stale")]
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            bad("task_ids: список номеров задач")
        allowed = {r["task_id"] for r in c.execute("SELECT task_id FROM site_stale")}
        return {"archived": ijro.archive(c, [i for i in ids if i in allowed])}      # only what the last run proposed


@app.get("/api/sync/keys")
def api_sync_keys():
    c = connect()
    try:
        return {"items": [{"id": r["id"], "name": r["name"], "created_at": r["created_at"], "last_used": r["last_used"], "revoked": bool(r["revoked"])}
                          for r in c.execute("SELECT * FROM sync_keys ORDER BY id DESC")]}
    finally:
        c.close()


@app.post("/api/sync/keys")
async def api_sync_key_create(request: Request):
    b = await _json(request)
    with tx() as c:
        key = ijro.new_key(c, str(b.get("name") or ""), me(request)["id"])
        audit(c, "sync.key_create", "sync", None, {"name": str(b.get("name") or "")[:60]})
    return {"key": key}   # shown once: only a hash stays here


@app.delete("/api/sync/keys/{key_id}")
def api_sync_key_revoke(key_id: int):
    with tx() as c:
        if not c.execute("UPDATE sync_keys SET revoked=1 WHERE id=?", (key_id,)).rowcount:
            bad("Ключ не найден", 404)
        audit(c, "sync.key_revoke", "sync", key_id, {})
    return {"ok": True}


@app.get("/api/sync/review")
def api_sync_review():
    c = connect()
    try:
        out = ijro.review(c)
        out["card_tpl"] = setting("ijro_card_tpl")
        out["auto_apply"] = setting("ijro_auto_apply") == "1"
        out["auto_archive"] = setting("ijro_auto_archive") == "1"
        out["stale"] = c.execute("SELECT COUNT(*) FROM site_stale").fetchone()[0]
        return out
    finally:
        c.close()


@app.put("/api/sync/settings")
async def api_sync_settings(request: Request):
    b = await _json(request)
    if ("auto_apply" in b or "auto_archive" in b) and "card_tpl" not in b:      # only the switches of the automatic application and the automatic archive
        with tx() as c:
            from .db import put_settings
            if "auto_apply" in b:
                put_settings(c, {"ijro_auto_apply": "1" if b["auto_apply"] else "0"})
            if "auto_archive" in b:
                put_settings(c, {"ijro_auto_archive": "1" if b["auto_archive"] else "0"})
            audit(c, "sync.settings", "sync", None, {k: bool(b[k]) for k in ("auto_apply", "auto_archive") if k in b})
        return {"ok": True}
    tpl = str(b.get("card_tpl") or "").strip()
    if tpl and not re.fullmatch(r"https://edo\.ijro\.uz/[^\s]*", tpl):
        bad("Адрес должен начинаться с https://edo.ijro.uz/ и без пробелов")
    if tpl and "{id}" not in tpl and "{task_id}" not in tpl:
        bad("В адресе нужна метка {id} (или {task_id}): на её место подставится номер задачи на сайте")
    with tx() as c:
        from .db import put_settings
        put_settings(c, {"ijro_card_tpl": tpl})
        audit(c, "sync.settings", "sync", None, {"card_tpl": tpl})
    return {"ok": True}


@app.post("/api/sync/detect-template")
async def api_sync_detect(request: Request):
    b = await _json(request)
    c = connect()
    try:
        try:
            return ijro.detect_template(c, str(b.get("url") or ""))
        except ValueError as e:
            bad(str(e))
    finally:
        c.close()


@app.post("/api/sync/apply")
async def api_sync_apply(request: Request):
    b = await _json(request)
    ids = b.get("task_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 1000 or not all(isinstance(i, int) for i in ids):
        bad("Выберите от 1 до 1000 задач")
    with tx() as c:
        return ijro.apply(c, ids, me(request)["id"])
