"""Numbers for the dashboard: three tables of departments (units).

  1. departments x months: how many tasks are done / not done in each month (the month of the term), and the percent done;
  2. departments x kinds of documents (Фармон, Қарор, Баён, ВМ, ПА): done / not done and the percent;
  3. departments x stages of the approval (Justice -> Cabinet -> Chamber of Accounts): where the open tasks are.

A task belongs to the department of its responsible person (a task nobody is responsible for, or a person without a department: «Без отдела»).
A management's numbers include its divisions. Tasks «К сведению» are counted apart: they are neither done nor open, so they are not in the percent.
Every number is a button on the page that opens the list of exactly those tasks, so the filters of the list must be able to say the same thing."""
from . import ijro
from .db import OPEN, today
from .tasks import eff_value

KIND_ORDER = ["Фармон", "Қарор", "Баён", "ВМ", "ПА"]      # the columns of the table of kinds, in this order (others seen in the data follow)
STAGE_COLS = [(k, label, hint) for k, label, hint in ijro.FUNNEL] + [
    ("other", "Другое", "Этап не распознан или задача не найдена на сайте"),
    ("unchecked", "Не проверялись", "Историю этапов ещё не читали (синхронизация читает только задачи, выбранные в настройках)")]


def _two() -> dict:
    """done, not done, and how many of the not done are past their term («over»: the term is before today by the chosen basis)."""
    return {"done": 0, "open": 0, "over": 0}


def _acc() -> dict:
    return {"months": {}, "nodate": _two(), "kinds": {}, "stages": {}, "sum": {"done": 0, "open": 0, "info": 0, "over": 0}}


def _add(a: dict, b: dict) -> dict:
    """a += b (a management takes its divisions' numbers)."""
    for ym, v in b["months"].items():
        t = a["months"].setdefault(ym, _two())
        t["done"] += v["done"]; t["open"] += v["open"]; t["over"] += v["over"]
    for k, v in b["kinds"].items():
        t = a["kinds"].setdefault(k, _two())
        t["done"] += v["done"]; t["open"] += v["open"]; t["over"] += v["over"]
    for k, n in b["stages"].items():
        a["stages"][k] = a["stages"].get(k, 0) + n
    for k in ("done", "open", "over"):
        a["nodate"][k] += b["nodate"][k]
    for k in ("done", "open", "info", "over"):
        a["sum"][k] += b["sum"][k]
    return a


def _copy(a: dict) -> dict:
    return _add(_acc(), a)


def dashboard(c, by: str = "close", period: str = "", scope: str = "main") -> dict:
    """period: "" (every task, also those without a term), "YYYY" (the terms of that year) or "YYYY-MM" (that month). `periods` always lists every month that has tasks,
    whatever the period is, so that the page can offer the years and the months."""
    by = by if by in ("due", "strict") else "close"
    period = period if period and len(period) in (4, 7) else ""
    units = c.execute("SELECT id, num, name, parent_id FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    ids = {u["id"] for u in units}
    today_s = today().isoformat()
    stage = ijro.stage_map(c)                                       # {task id: stage key} for the open tasks
    own: dict[int, dict] = {u["id"]: _acc() for u in units}
    own[0] = _acc()                                                  # «Без отдела»
    months: set[str] = set()
    every_month: set[str] = set()
    kinds_seen: list[str] = []
    no_term = 0
    for r in c.execute("""SELECT t.id, t.status, t.due, t.close_date, t.kind, u.unit_id FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id
                          WHERE t.status != 'gone' AND t.scope=?""", (scope,)).fetchall():
        a = own[r["unit_id"] if r["unit_id"] in ids else 0]
        st = r["status"]
        eff = eff_value(r, by)
        if eff:
            every_month.add(eff[:7])
        if period and not (eff and eff.startswith(period)):
            if not eff and st != "info":
                no_term += 1                               # a task without a term (e.g. just added by its code, waiting for the site's data) is in no period: the page says so
            continue                                       # not in the chosen year / month (a task without a term is in no period)
        if st == "info":
            a["sum"]["info"] += 1
            continue
        key = "open" if st in OPEN else "done"
        late = key == "open" and bool(eff) and eff < today_s              # not done and past its term (a task without a term is never past it)
        a["sum"][key] += 1
        a["sum"]["over"] += late
        if eff:
            months.add(eff[:7])
            m = a["months"].setdefault(eff[:7], _two())
            m[key] += 1; m["over"] += late
        else:
            a["nodate"][key] += 1
        kind = r["kind"] or "—"
        if kind not in KIND_ORDER and kind not in kinds_seen:
            kinds_seen.append(kind)
        k2 = a["kinds"].setdefault(kind, _two())
        k2[key] += 1; k2["over"] += late
        if key == "open":
            sk = stage.get(r["id"], "unchecked")
            a["stages"][sk] = a["stages"].get(sk, 0) + 1
    by_parent: dict[int, list[int]] = {}
    for u in units:
        if u["parent_id"] in ids:
            by_parent.setdefault(u["parent_id"], []).append(u["id"])
    rows, total = [], _acc()
    for u in units:
        agg = _copy(own[u["id"]])
        for child in by_parent.get(u["id"], []):                      # a management includes its divisions
            _add(agg, own[child])
        rows.append({"id": u["id"], "num": u["num"], "name": u["name"], "parent_id": u["parent_id"] if u["parent_id"] in ids else None,
                     "level": 1 if u["parent_id"] in ids else 0, **agg})
        if u["parent_id"] not in ids:
            _add(total, agg)
    none = _copy(own[0])
    _add(total, none)
    has_none = any(none["sum"].values())
    t = total["sum"]
    return {"today": today().isoformat(), "by": by, "period": period, "scope": scope, "no_term": no_term, "periods": sorted(every_month), "months": sorted(months), "kinds": KIND_ORDER + kinds_seen,
            "stages": [{"key": k, "label": label, "hint": hint} for k, label, hint in STAGE_COLS],
            "totals": {"done": t["done"], "open": t["open"], "over": t["over"], "info": t["info"], "total": t["done"] + t["open"] + t["info"]},
            "rows": rows, "none": {"id": 0, "num": "", "name": "Без отдела", "parent_id": None, "level": 0, **none} if has_none else None,
            "total": total}
