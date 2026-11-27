"""Tasks: listing with filters, deadline buckets, editing with a change history."""
import re
from datetime import date, timedelta

from . import auth
from .db import OPEN, STATUSES, now, setting, today, unit_tree_ids

BUCKETS = {
    "overdue": "Просрочено",
    "week": "Срок ≤ 7 дней",
    "month": "8–30 дней",
    "later": "Позже 30 дней",
    "nodate": "Без срока",
}
SORTS = {"unit": "un.name", "eff": "eff", "due": "t.due", "close": "t.close_date", "code": "t.code", "doc": "t.doc_no", "kind": "t.kind",
         "status": "t.status", "assignee": "a.name", "num": "t.seq"}


class TaskError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


def norm_by(by: str | None, user, grouping: bool = False) -> str:
    """Which date the numbers are built on. An administrator chooses: "close" (closing date, else the official term), "due" or "strict" (the closing date only, as the others see it).
    Everybody else gets "strict": the closing date only. The official term is not shown to them anywhere, so it also must not leak through a fallback, a sort order, an
    export or a reminder. One exception, for the dashboard and the lists it opens (grouping=True), when the administrator allows it (setting users_dashboard_by = "close"):
    "ucl" - the tasks are GROUPED (months, periods, the filters of the lists) by the closing date, else the official term, exactly as the administrator's dashboard, so the
    numbers agree; what is SHOWN is still the closing date only (the exact official date is never sent to them)."""
    if not user or user["role"] != "admin":
        return "ucl" if grouping and setting("users_dashboard_by") == "close" else "strict"
    return by if by in ("due", "strict") else "close"      # «strict» for an administrator: the numbers exactly as everybody else sees them


def eff_sql(by: str) -> str:
    """The date a task is judged by. "close": the planned closing date, else the official term; "due": the other way round."""
    if by == "strict":
        return "t.close_date"
    return "COALESCE(t.due, t.close_date)" if by == "due" else "COALESCE(t.close_date, t.due)"      # "close" and "ucl" (the grouping of an ordinary user)


def eff_value(row, by: str) -> str | None:
    due, close = row["due"], row["close_date"]
    if by in ("strict", "ucl"):
        return close                                         # what is shown to an ordinary user: the closing date only
    return (due or close) if by == "due" else (close or due)


def bucket_of(status: str, eff: str | None, t: date | None = None) -> str:
    """overdue | week | month | later | nodate for an open task; done | info otherwise."""
    if status not in OPEN:
        return status
    if not eff:
        return "nodate"
    t = t or today()
    d = date.fromisoformat(eff)
    if d < t:
        return "overdue"
    if d <= t + timedelta(days=7):
        return "week"
    if d <= t + timedelta(days=30):
        return "month"
    return "later"


def _bucket_where(bucket: str, e: str, params: dict) -> str:
    t = today()
    params.update(t0=t.isoformat(), t7=(t + timedelta(days=7)).isoformat(), t30=(t + timedelta(days=30)).isoformat())
    op = "t.status IN ('todo','progress')"
    return {
        "open": op,
        "overdue": f"{op} AND {e} < :t0",
        "week": f"{op} AND {e} >= :t0 AND {e} <= :t7",
        "month": f"{op} AND {e} > :t7 AND {e} <= :t30",
        "later": f"{op} AND {e} > :t30",
        "nodate": f"{op} AND {e} IS NULL",
        "done": "t.status='done'",
        "info": "t.status='info'",
    }.get(bucket, "")


def _where(f: dict, by: str, user: dict | None, own_only: bool) -> tuple[str, dict]:
    e = eff_sql(by)
    clauses, p = [], {}
    if own_only and user:
        clauses.append("t.assignee_id = :own")
        p["own"] = user["id"]
    a = str(f.get("assignee") or "")
    if a == "0":
        clauses.append("t.assignee_id IS NULL")
    elif a.isdigit():
        clauses.append("t.assignee_id = :assignee")
        p["assignee"] = int(a)
    grp = f.get("scope") or "main"                  # the group of the tasks: the groups have their own lists as they have their own dashboards
    if grp in ("main", "co", "vm"):
        clauses.append("t.scope = :grp")
        p["grp"] = grp
    s = f.get("status") or ""
    if s != "gone":
        clauses.append("t.status != 'gone'")        # tasks the site no longer lists as ours are off the lists, unless asked for
    if s == "open":
        clauses.append("t.status IN ('todo','progress')")
    elif s in STATUSES:
        clauses.append("t.status = :status")
        p["status"] = s
    b = f.get("bucket") or ""
    if b:
        w = _bucket_where(b, e, p)
        if not w:
            raise TaskError("Неизвестная группа сроков")
        clauses.append(w)
    if f.get("kind"):
        clauses.append("t.kind = :kind")
        p["kind"] = f["kind"]
    u = str(f.get("unit") or "")
    if u == "0":
        clauses.append("(a.unit_id IS NULL OR a.unit_id NOT IN (SELECT id FROM units WHERE active=1))")     # «Без отдела»: nobody's department, or a hidden one
    elif u.isdigit():
        ids = f.get("_unit_ids") or [int(u)]
        clauses.append(f"a.unit_id IN ({','.join(str(int(i)) for i in ids)})")
    if f.get("doc"):
        clauses.append("t.doc_no = :doc")
        p["doc"] = f["doc"]
    if f.get("date_from"):
        clauses.append(f"{e} >= :dfrom")
        p["dfrom"] = f["date_from"]
    if f.get("date_to"):
        clauses.append(f"{e} <= :dto")
        p["dto"] = f["date_to"]
    if f.get("term") == "none":
        clauses.append(f"{e} IS NULL")                                     # tasks without any term (whatever their status): the «Без срока» column of the dashboard
    if f.get("closing") == "proposed":
        clauses.append("t.close_src != ''")
    if "_stage_ids" in f:
        ids = [int(i) for i in f["_stage_ids"]]
        clauses.append(f"t.id IN ({','.join(map(str, ids))})" if ids else "1=0")
    q = (f.get("q") or "").strip()
    if q:
        clauses.append("(t.code LIKE :q OR t.text LIKE :q OR t.doc_no LIKE :q OR t.point LIKE :q)")
        p["q"] = f"%{q}%"
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", p


def row_out(r, by: str) -> dict:
    eff = eff_value(r, by)
    t = today()
    return {
        "id": r["id"], "code": r["site_code"] or r["code"], "num": r["seq"], "kind": r["kind"], "doc_no": r["doc_no"], "doc_date": r["doc_date"],
        "point": r["point"], "text": r["text"], "due": None if by in ("strict", "ucl") else r["due"], "close_date": r["close_date"], "eff": eff,
        "close_src": r["close_src"], "close_note": r["close_note"],
        "days": (date.fromisoformat(eff) - t).days if eff else None,
        "status": r["status"], "tag": r["tag"], "bucket": bucket_of(r["status"], eff, t),
        "assignee_id": r["assignee_id"], "assignee": auth.short_name(r["a_name"]) if r["a_name"] else "",
        "assignee_name": r["a_name"] or "", "unit_id": r["a_unit"], "unit": r["unit_name"] or "", "assignee_raw": r["assignee_raw"], "done_at": r["done_at"], "edited": bool(r["edited"]), "manual": bool(r["manual"]), "by_code": r["manual"] == 2, "status_manual": bool(r["status_manual"]), "pending": r["manual"] == 2 and not r["text"],
        "updated_at": r["updated_at"],
    }


SELECT = """SELECT t.*, a.name AS a_name, a.unit_id AS a_unit, un.name AS unit_name, {e} AS eff FROM tasks t
    LEFT JOIN users a ON a.id = t.assignee_id LEFT JOIN units un ON un.id = a.unit_id"""


def list_tasks(c, f: dict, user: dict, own_only: bool, *, limit: int | None = 50, offset: int = 0) -> dict:
    by = norm_by(f.get("by"), user, grouping=True)
    if f.get("stage"):
        from . import ijro
        f = dict(f, _stage_ids=ijro.stage_ids(c, str(f["stage"])))
    if str(f.get("unit") or "").isdigit() and f["unit"] != "0":
        f = dict(f, _unit_ids=unit_tree_ids(c, int(f["unit"])))
    where, p = _where(f, by, user, own_only)
    key = f.get("sort") if f.get("sort") in SORTS else "eff"
    if by in ("strict", "ucl") and key == "due":
        key = "eff"  # sorting by the official term would reveal its order
    direction = "DESC" if f.get("dir") == "desc" else "ASC"
    col = "eff" if key == "eff" else SORTS[key]
    nulls = f"({col} IS NULL) ASC"  # empty values always go last
    order = f"ORDER BY {nulls}, {col} {direction}, eff ASC, t.seq ASC, t.id ASC"
    sql = SELECT.format(e=eff_sql("strict" if by == "ucl" else by)) + where        # the shown (and sorted) date of an ordinary user is the closing date only
    total = c.execute(f"SELECT COUNT(*) FROM tasks t LEFT JOIN users a ON a.id=t.assignee_id{where}", p).fetchone()[0]
    sql += f" {order}" + (f" LIMIT {int(limit)} OFFSET {int(offset)}" if limit else "")
    rows = c.execute(sql, p).fetchall()
    return {"total": total, "items": [row_out(r, by) for r in rows], "by": by}


def get_task(c, task_id: int, user: dict, own_only: bool, by: str = "close") -> dict:
    by = norm_by(by, user)
    r = c.execute(SELECT.format(e=eff_sql(by)) + " WHERE t.id=?", (task_id,)).fetchone()
    if not r or (own_only and r["assignee_id"] != user["id"]):
        raise TaskError("Задача не найдена", 404)
    out = row_out(r, by)
    out["events"] = [dict(e) for e in c.execute(
        """SELECT e.field, e.old, e.new, e.created_at, COALESCE(u.name, 'Автоматически') AS who FROM task_events e
           LEFT JOIN users u ON u.id = e.user_id WHERE e.task_id=? AND (? OR e.field NOT IN ('due', 'term')) ORDER BY e.id DESC LIMIT 100""", (task_id, user["role"] == "admin"))]   # the official term is not for employees: neither its changes
    return out


def split_term(c, task_id: int, new_due: str) -> int | None:
    """The official term of an open task moved to another month (it was November, now it is December). Then
      - the task of the OLD month is done (nothing is left to do for that month: the term has moved on); it is locked, so it is not checked against the site again;
      - a NEW task with the same code stands for the NEW month: it carries the work that is still open (the same status, the same people and texts, no closing date yet).
    So November counts it as done and December as not done. Only for an open task whose term moves to another month. Returns the id of the task of the new month
    (an existing task of that code in that month is used as it is), or None when nothing was moved."""
    old = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not old or old["status"] not in OPEN or old["manual"] or not old["due"] or not new_due or old["due"][:7] == new_due[:7]:
        return None
    base = old["site_code"] or old["code"]
    twin = c.execute("SELECT id FROM tasks WHERE COALESCE(NULLIF(site_code, ''), code) = ? AND scope = ? AND substr(due, 1, 7) = ? AND id != ? AND status != 'gone'",
                     (base, old["scope"], new_due[:7], task_id)).fetchone()
    if twin:
        new_id = twin["id"]
    else:
        code, n = f"{base}#{new_due}", 2
        while c.execute("SELECT 1 FROM tasks WHERE code=?", (code,)).fetchone():
            code, n = f"{base}#{new_due}-{n}", n + 1
        t = now()
        new_id = c.execute("""INSERT INTO tasks(code, site_code, scope, seq, kind, doc_no, doc_date, point, text, due, close_date, assignee_id, assignee_raw, status, tag, ext_date, ext_n,
                                                created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (code, base, old["scope"], old["seq"], old["kind"], old["doc_no"], old["doc_date"], old["point"], old["text"], new_due, None, old["assignee_id"],
                            old["assignee_raw"], old["status"], old["tag"], old["ext_date"], old["ext_n"], t, t)).lastrowid
        cols = ", ".join(r["name"] for r in c.execute("PRAGMA table_info(ijro_snapshots)") if r["name"] != "task_id")
        c.execute(f"INSERT INTO ijro_snapshots(task_id, {cols}) SELECT ?, {cols} FROM ijro_snapshots WHERE task_id=?", (new_id, task_id))   # what was read from the site belongs to both
        c.execute("INSERT INTO task_events(task_id, user_id, field, old, new, created_at) VALUES (?,?,?,?,?,?)",
                  (new_id, None, "term", old["due"], f"{new_due} (перенос срока: запись создана)", t))
    update_task(c, task_id, {"status": "done"}, None, lock=True)                # the old month is done, and the site does not reopen it
    c.execute("INSERT INTO task_events(task_id, user_id, field, old, new, created_at) VALUES (?,?,?,?,?,?)",
              (task_id, None, "term", old["due"], f"{new_due} (срок перенесён на другой месяц: этот месяц закрыт)", now()))
    return new_id


def _date_or_none(v) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise TaskError("Дата должна быть в формате ГГГГ-ММ-ДД")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise TaskError("Такой даты не существует")
    return v


def _label(c, field: str, value) -> str:
    if value is None or value == "":
        return ""
    if field == "assignee_id":
        r = c.execute("SELECT name FROM users WHERE id=?", (value,)).fetchone()
        return r["name"] if r else str(value)
    if field == "status":
        return STATUSES.get(value, str(value))
    return str(value)


def update_task(c, task_id: int, changes: dict, user_id: int, lock: bool | None = None) -> bool:
    """Admin edit: assignee, status, closing date. Every real change is written to the history. True when anything changed."""
    r = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not r:
        raise TaskError("Задача не найдена", 404)
    new = {}
    if "assignee_id" in changes:
        a = changes["assignee_id"]
        if a in (None, "", 0):
            new["assignee_id"] = None
        else:
            u = c.execute("SELECT id FROM users WHERE id=? AND active=1", (a,)).fetchone()
            if not u:
                raise TaskError("Такого сотрудника нет или он отключён")
            new["assignee_id"] = u["id"]
    if "status" in changes:
        if changes["status"] not in STATUSES:
            raise TaskError("Неизвестный статус")
        new["status"] = changes["status"]
    if "close_date" in changes:
        new["close_date"] = _date_or_none(changes["close_date"])
    if "due" in changes:
        new["due"] = _date_or_none(changes["due"])
    changed = False
    for field, value in new.items():
        if r[field] == value:
            continue
        c.execute("INSERT INTO task_events(task_id, user_id, field, old, new, created_at) VALUES (?,?,?,?,?,?)",
                  (task_id, user_id, field, _label(c, field, r[field]), _label(c, field, value), now()))
        c.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))
        changed = True
        if field == "close_date":
            c.execute("UPDATE tasks SET close_src='', close_note='' WHERE id=?", (task_id,))   # a person decided: no longer a proposal
        if field == "status":
            c.execute("UPDATE tasks SET done_at=? WHERE id=?", (now() if value == "done" else None, task_id))
            if (user_id is not None) if lock is None else lock:       # a person set the status: the task is no longer checked against the site (until they say so)
                c.execute("UPDATE tasks SET status_manual=1 WHERE id=?", (task_id,))
    if changed:
        c.execute("UPDATE tasks SET edited=1, updated_at=? WHERE id=?", (now(), task_id))
    return changed
