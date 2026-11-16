"""Tasks: listing with filters, deadline buckets, editing with a change history."""
import re
from datetime import date, timedelta

from . import auth
from .db import OPEN, STATUSES, now, today, unit_tree_ids

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


def norm_by(by: str | None, user) -> str:
    """Which date the numbers are built on. An administrator chooses: "close" (closing date, else the official term) or "due".
    Everybody else always gets "strict": the closing date only. The official term is not shown to them anywhere, so it also
    must not leak through a fallback, a sort order, an export or a reminder."""
    if not user or user["role"] != "admin":
        return "strict"
    return "due" if by == "due" else "close"


def eff_sql(by: str) -> str:
    """The date a task is judged by. "close": the planned closing date, else the official term; "due": the other way round."""
    if by == "strict":
        return "t.close_date"
    return "COALESCE(t.due, t.close_date)" if by == "due" else "COALESCE(t.close_date, t.due)"


def eff_value(row, by: str) -> str | None:
    due, close = row["due"], row["close_date"]
    if by == "strict":
        return close
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
    s = f.get("status") or ""
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
        clauses.append("a.unit_id IS NULL")
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
        "id": r["id"], "code": r["code"], "num": r["seq"], "kind": r["kind"], "doc_no": r["doc_no"], "doc_date": r["doc_date"],
        "point": r["point"], "text": r["text"], "due": None if by == "strict" else r["due"], "close_date": r["close_date"], "eff": eff,
        "days": (date.fromisoformat(eff) - t).days if eff else None,
        "status": r["status"], "tag": r["tag"], "bucket": bucket_of(r["status"], eff, t),
        "assignee_id": r["assignee_id"], "assignee": auth.short_name(r["a_name"]) if r["a_name"] else "",
        "assignee_name": r["a_name"] or "", "unit_id": r["a_unit"], "unit": r["unit_name"] or "", "assignee_raw": r["assignee_raw"], "done_at": r["done_at"], "edited": bool(r["edited"]),
        "updated_at": r["updated_at"],
    }


SELECT = """SELECT t.*, a.name AS a_name, a.unit_id AS a_unit, un.name AS unit_name, {e} AS eff FROM tasks t
    LEFT JOIN users a ON a.id = t.assignee_id LEFT JOIN units un ON un.id = a.unit_id"""


def list_tasks(c, f: dict, user: dict, own_only: bool, *, limit: int | None = 50, offset: int = 0) -> dict:
    by = norm_by(f.get("by"), user)
    if f.get("stage"):
        from . import ijro
        f = dict(f, _stage_ids=ijro.stage_ids(c, str(f["stage"])))
    if str(f.get("unit") or "").isdigit() and f["unit"] != "0":
        f = dict(f, _unit_ids=unit_tree_ids(c, int(f["unit"])))
    where, p = _where(f, by, user, own_only)
    key = f.get("sort") if f.get("sort") in SORTS else "eff"
    if by == "strict" and key == "due":
        key = "eff"  # sorting by the official term would reveal its order
    direction = "DESC" if f.get("dir") == "desc" else "ASC"
    col = "eff" if key == "eff" else SORTS[key]
    nulls = f"({col} IS NULL) ASC"  # empty values always go last
    order = f"ORDER BY {nulls}, {col} {direction}, eff ASC, t.seq ASC, t.id ASC"
    sql = SELECT.format(e=eff_sql(by)) + where
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
        """SELECT e.field, e.old, e.new, e.created_at, COALESCE(u.name, 'Автоматически (ijro)') AS who FROM task_events e
           LEFT JOIN users u ON u.id = e.user_id WHERE e.task_id=? AND (? OR e.field != 'due') ORDER BY e.id DESC LIMIT 100""", (task_id, user["role"] == "admin"))]   # the official term is not for employees: neither its changes
    return out


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


def update_task(c, task_id: int, changes: dict, user_id: int) -> bool:
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
        if field == "status":
            c.execute("UPDATE tasks SET done_at=? WHERE id=?", (now() if value == "done" else None, task_id))
    if changed:
        c.execute("UPDATE tasks SET edited=1, updated_at=? WHERE id=?", (now(), task_id))
    return changed
