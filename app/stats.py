"""Numbers for the dashboard: who has how many tasks, and how the terms are distributed."""
from datetime import date, timedelta

from . import auth
from .db import OPEN, today
from .tasks import BUCKETS, bucket_of, eff_value

COLS = ("overdue", "week", "month", "later", "nodate")
KIND_ORDER = ["Фармон", "Қарор", "Баён", "ВМ", "ПА"]   # columns of the department matrix: the kinds of documents, in this order
NUM_KEYS = (*COLS, "done", "info", "total", "open")
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
    by = by if by in ("due", "strict") else "close"
    t = today()
    rows = c.execute("""SELECT t.id, t.assignee_id, t.status, t.due, t.close_date, t.kind, t.doc_no, t.code, t.point, t.text, t.done_at, u.unit_id
                        FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id WHERE t.status != 'gone'""").fetchall()
    users = {u["id"]: u for u in c.execute("SELECT id, name, active, role FROM users")}
    unit_cells: dict[tuple[int, str], dict] = {}
    per_month: dict[int, dict[str, dict]] = {}   # person -> "YYYY-MM" -> how many tasks fall on days 1-10 / 11-15 / 16-20 / 21-end
    months_seen: set[str] = set()
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
        if eff:
            ym, day = eff[:7], int(eff[8:10])
            m = per_month.setdefault(pid, {}).setdefault(ym, {"d10": 0, "d15": 0, "d20": 0, "d31": 0, "total": 0, "done": 0})
            m["d10" if day <= 10 else "d15" if day <= 15 else "d20" if day <= 20 else "d31"] += 1
            m["total"] += 1
            m["done"] += r["status"] == "done"
            months_seen.add(ym)
        uacc = unit_cells.setdefault((r["unit_id"] or 0, r["kind"]), _blank())
        uacc["total"] += 1
        uacc[b] += 1
        if r["status"] in OPEN:
            uacc["open"] += 1
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
        people.append({"id": pid, "name": name, "short": auth.short_name(name) if u else name, **_finish(d), "months": per_month.get(pid, {})})
    for u in users.values():  # active employees with no tasks are still shown: "nobody gave them anything" is information too
        if u["role"] == "user" and u["active"] and u["id"] not in per:
            people.append({"id": u["id"], "name": u["name"], "short": auth.short_name(u["name"]), **_finish(_blank()), "months": {}})
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
        "units": _units(c, unit_cells, kinds), "months": sorted(months_seen), "today": t.isoformat(), "by": by, "totals": _finish(total), "closed_14d": closed_14d, "people": people,
        "timeline": timeline, "kinds": sorted(({"kind": k, **_finish(v)} for k, v in kinds.items()), key=lambda x: -x["total"]),
        "docs": doc_list, "upcoming": upcoming, "bucket_labels": BUCKETS, "stages": _stages(c),
    }


def _stages(c) -> dict:
    from . import ijro
    return ijro.funnel(c)


def _add(a: dict, b: dict) -> dict:
    for k in NUM_KEYS:
        a[k] = a.get(k, 0) + b.get(k, 0)
    return a


def _units(c, cells: dict, kinds_seen: dict) -> dict:
    """The matrix "department structure x kind of document". A management's numbers include its divisions;
    people without a department (and unassigned tasks) are shown as a separate row so that the total still adds up."""
    cols = KIND_ORDER + [k for k in kinds_seen if k and k not in KIND_ORDER]
    units = c.execute("SELECT * FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    by_id = {u["id"]: u for u in units}

    def row(uid: int, **meta) -> dict:
        per = {k: dict(cells.get((uid, k), _blank())) for k in cols}
        return {**meta, "id": uid, "cells": per, "sum": {}}

    out = []
    for u in units:
        r = row(u["id"], num=u["num"], name=u["name"], parent_id=u["parent_id"] if u["parent_id"] in by_id else None, level=0 if not u["parent_id"] else 1)
        out.append(r)
    index = {r["id"]: r for r in out}
    for r in out:                      # a division adds itself to its management
        if r["parent_id"]:
            for k in cols:
                _add(index[r["parent_id"]]["cells"][k], r["cells"][k])
    none = row(0, num="", name="Без отдела", parent_id=None, level=0)
    total_cells = {k: _blank() for k in cols}
    for r in out:
        if not r["parent_id"]:
            for k in cols:
                _add(total_cells[k], r["cells"][k])
    for k in cols:
        _add(total_cells[k], none["cells"][k])
    for r in out + [none]:
        s = _blank()
        for k in cols:
            _add(s, r["cells"][k])
        r["sum"] = _finish(s)
    tot = _blank()
    for k in cols:
        _add(tot, total_cells[k])
    result = {"columns": cols, "rows": out, "none": none if none["sum"]["total"] else None,
              "total": {"cells": total_cells, "sum": _finish(tot)}}
    return result
