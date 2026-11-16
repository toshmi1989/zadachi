"""Numbers for the dashboard: who has how many tasks, and how the terms are distributed."""
from datetime import date, timedelta

from . import auth
from .db import OPEN, today
from .tasks import BUCKETS, bucket_of, eff_value

COLS = ("overdue", "week", "month", "later", "nodate")
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _fmt(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def _blank() -> dict:
    return {**{k: 0 for k in COLS}, "done": 0, "info": 0, "total": 0, "open": 0}


def _finish(d: dict) -> dict:
    d["pct_done"] = round(100 * d["done"] / (d["total"] - d["info"])) if d["total"] - d["info"] > 0 else 0
    d["pct_overdue"] = round(100 * d["overdue"] / d["open"]) if d["open"] else 0
    return d


def dashboard(c, by: str = "close") -> dict:
    by = "due" if by == "due" else "close"
    t = today()
    rows = c.execute("SELECT id, assignee_id, status, due, close_date, kind, doc_no, code, point, text, done_at FROM tasks").fetchall()
    users = {u["id"]: u for u in c.execute("SELECT id, name, active, role FROM users")}
    total, per = _blank(), {}
    kinds, docs, open_rows, windows = {}, {}, [], [0] * 8
    closed_14d = 0
    horizon = t - timedelta(days=14)
    for r in rows:
        eff = eff_value(r, by)
        b = bucket_of(r["status"], eff, t)
        pid = r["assignee_id"] or 0
        for acc in (total, per.setdefault(pid, _blank()), kinds.setdefault(r["kind"], _blank()), docs.setdefault(r["doc_no"], _blank())):
            acc["total"] += 1
            acc[b] += 1
            if r["status"] in OPEN:
                acc["open"] += 1
        if r["status"] in OPEN:
            open_rows.append((eff or "9999-12-31", r["code"], r, eff))
            if eff and b != "overdue":
                i = (date.fromisoformat(eff) - t).days // 7
                if i < 8:
                    windows[i] += 1
        if r["status"] == "done" and r["done_at"] and r["done_at"][:10] >= horizon.isoformat():
            closed_14d += 1
    people = []
    for pid, d in per.items():
        u = users.get(pid)
        name = u["name"] if u else "Не назначен"
        if u and not u["active"] and d["total"] == 0:
            continue
        people.append({"id": pid, "name": name, "short": auth.short_name(name) if u else name, **_finish(d)})
    for u in users.values():  # active employees with no tasks are still shown: "nobody gave them anything" is information too
        if u["role"] == "user" and u["active"] and u["id"] not in per:
            people.append({"id": u["id"], "name": u["name"], "short": auth.short_name(u["name"]), **_finish(_blank())})
    people.sort(key=lambda p: (-p["open"], -p["overdue"], p["name"]))
    timeline = [{"key": "overdue", "label": "Просрочено", "count": total["overdue"], "to": (t - timedelta(days=1)).isoformat()}]
    last = max([i for i, n in enumerate(windows) if n] + [3])  # no empty weeks at the tail
    for i, n in enumerate(windows[: last + 1]):
        a, b = t + timedelta(days=7 * i), t + timedelta(days=7 * i + 6)
        timeline.append({"key": f"w{i}", "label": f"{_fmt(a)} – {_fmt(b)}" if i else f"Сегодня – {_fmt(b)}", "count": n,
                         "from": a.isoformat(), "to": b.isoformat()})
    later_from = t + timedelta(days=56)
    later = sum(1 for _, _, r, e in open_rows if e and e >= later_from.isoformat())
    if later:
        timeline.append({"key": "later", "label": f"После {_fmt(later_from - timedelta(days=1))}", "count": later, "from": later_from.isoformat()})
    if total["nodate"]:
        timeline.append({"key": "nodate", "label": "Без срока", "count": total["nodate"], "bucket": "nodate"})
    open_rows.sort(key=lambda x: (x[0], x[1]))
    upcoming = []
    for _, _, r, e in open_rows[:8]:
        a = users.get(r["assignee_id"])
        upcoming.append({"id": r["id"], "code": r["code"], "doc_no": r["doc_no"], "point": r["point"], "eff": e,
                         "days": (date.fromisoformat(e) - t).days if e else None,
                         "text": (r["text"] or "").split("\n")[0][:140], "assignee": auth.short_name(a["name"]) if a else "Не назначен"})
    doc_list = sorted(({"doc": k, **_finish(v)} for k, v in docs.items()), key=lambda x: (-x["open"], x["doc"]))[:10]
    return {
        "today": t.isoformat(), "by": by, "totals": _finish(total), "closed_14d": closed_14d, "people": people,
        "timeline": timeline, "kinds": sorted(({"kind": k, **_finish(v)} for k, v in kinds.items()), key=lambda x: -x["total"]),
        "docs": doc_list, "upcoming": upcoming, "bucket_labels": BUCKETS,
    }
