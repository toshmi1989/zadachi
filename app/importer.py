"""Import of the Excel export. Idempotent: a task is identified by its code ("Топшириқ коди"), so loading the
next export updates documents, texts and terms, and keeps what the administrator edited by hand."""
import io
import re
from datetime import date, datetime

import openpyxl

from . import auth, tasks
from .db import audit, now

HEADERS = {  # header text (casefolded, stripped) -> field
    "№": "num", "ҳужжат тури": "kind", "ҳужжат рақами ва санаси": "doc", "топшириқ мазмуни": "text",
    "топшириқ муддати": "due", "ёпиш муддати": "close", "масъул ҳодим": "who", "топшириқ ижроси": "status",
    "топшириқ коди": "code",
}
REQUIRED = ("kind", "doc", "text", "due", "who", "status", "code")


class ImportError_(Exception):
    pass


def parse_date(v) -> tuple[str | None, str | None]:
    """(iso, problem). Understands real dates, 25.12.2026 and the typo 14.112026; anything else is reported, not guessed."""
    if v in (None, ""):
        return None, None
    if isinstance(v, datetime):
        return v.date().isoformat(), None
    if isinstance(v, date):
        return v.isoformat(), None
    s = str(v).strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?", s)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat(), None
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s) or re.fullmatch(r"(\d{1,2})\.(\d{2})(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat(), None
        except ValueError:
            pass
    return None, f"не удалось прочитать дату «{s}»"


def parse_status(v: str) -> tuple[str, str]:
    lines = [x.strip() for x in str(v or "").splitlines() if x.strip()]
    head = (lines[0] if lines else "").casefold()
    tag = " ".join(lines[1:])
    if head.startswith("бажарилмаган"):
        return "todo", tag
    if head.startswith("бажарилган"):
        return "done", tag
    if head.startswith("маълумот учун"):
        return "info", tag
    return "todo", tag


def parse_doc(v: str) -> tuple[str, str | None]:
    lines = [x.strip() for x in str(v or "").splitlines() if x.strip()]
    no = lines[0] if lines else ""
    d, _ = parse_date(lines[1]) if len(lines) > 1 else (None, None)
    return no, d


def parse_text(v: str) -> tuple[str, str]:
    lines = [x.rstrip() for x in str(v or "").strip().splitlines()]
    if len(lines) > 1:
        return lines[0].strip(), "\n".join(lines[1:]).strip()
    return "", (lines[0] if lines else "")


def read(data: bytes) -> tuple[list[dict], list[str]]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:
        raise ImportError_("Файл не читается как Excel (.xlsx)")
    sheet = header = cols = None
    for ws in wb.worksheets:
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), 1):
            mapped = {HEADERS[str(c).strip().casefold()]: j for j, c in enumerate(row) if c is not None and str(c).strip().casefold() in HEADERS}
            if all(k in mapped for k in REQUIRED):
                sheet, header, cols = ws, i, mapped
                break
        if sheet:
            break
    if not sheet:
        raise ImportError_("Не нашёл таблицу задач: нужны колонки «Ҳужжат тури», «Топшириқ мазмуни», «Топшириқ муддати», "
                           "«Масъул ҳодим», «Топшириқ ижроси», «Топшириқ коди»")
    out, warnings = [], []
    for n, row in enumerate(sheet.iter_rows(min_row=header + 1, values_only=True), header + 1):
        def cell(k):
            j = cols.get(k)
            return row[j] if j is not None and j < len(row) else None
        code = str(cell("code") or "").strip()
        if not code:
            if any(c not in (None, "") for c in row):
                warnings.append(f"строка {n}: нет кода задачи, пропущена")
            continue
        due, p1 = parse_date(cell("due"))
        close, p2 = parse_date(cell("close"))
        for p, name in ((p1, "срок"), (p2, "дата закрытия")):
            if p:
                warnings.append(f"{code}: {name} — {p}; оставлено пустым, проверьте вручную")
        doc_no, doc_date = parse_doc(cell("doc"))
        point, text = parse_text(cell("text"))
        status, tag = parse_status(cell("status"))
        who = re.sub(r"\s+", " ", str(cell("who") or "")).strip()
        num = cell("num")
        out.append({"code": code, "seq": int(num) if isinstance(num, (int, float)) else 0, "kind": str(cell("kind") or "").strip(),
                    "doc_no": doc_no, "doc_date": doc_date, "point": point, "text": text, "due": due, "close_date": close,
                    "who": who, "status": status, "tag": tag})
    if not out:
        raise ImportError_("В таблице нет ни одной задачи с кодом")
    seen, dups = set(), []
    for r in out:
        if r["code"] in seen:
            dups.append(r["code"])
        seen.add(r["code"])
    if dups:
        warnings.append("повторяющиеся коды (берётся первая строка): " + ", ".join(sorted(set(dups))))
        first, out = set(), [r for r in out if not (r["code"] in first or first.add(r["code"]))]
    return out, warnings


def _same_words(a, b) -> bool:
    flat = lambda s: re.sub(r"\s+", " ", re.sub(r"(-банд)+", "-банд", s or "")).strip()
    return flat(a) == flat(b)


def _days_apart(a: str | None, b: str | None) -> int:
    from datetime import date as _d
    try:
        return abs((_d.fromisoformat(a) - _d.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return 10 ** 6


def _periods_of(c) -> dict[int, set]:
    """{task id: the terms (ISO dates) of all the periods of a periodic task} as the synchronisation read them from the site."""
    import json
    from datetime import datetime, timezone
    out: dict[int, set] = {}
    for r in c.execute("SELECT task_id, periods FROM ijro_snapshots WHERE repeatable=1 AND periods != '[]'"):
        try:
            ps = json.loads(r["periods"])
        except ValueError:
            continue
        out[r["task_id"]] = {datetime.fromtimestamp(p["due_ms"] / 1000, timezone.utc).date().isoformat() for p in ps if isinstance(p, dict) and p.get("due_ms")}
    return out


class Matcher:
    """Which task of ours a row of the site's file is. A task is a CODE at a TERM: a periodic task has a row for every period, each with its own term, and each period is
    its own task on the dashboard (its month, its status). A row is
      the task with the same code and the same term, if there is one;
      an extension of the task (the file says the term was extended: «Муддат узайтириш сони» is a number): the nearest term of that code;
      another PERIOD when the code is periodic (the file has several terms of the code, or the code already has several tasks, or the site's own list of the periods
        has this term): a new task «КОД#срок», shown with the site's code;
      otherwise the same task with a new term (the term of an ordinary task moved)."""
    def __init__(self, c, scope: str | None = None):
        self.c = c
        self.scope = scope
        self.by_site: dict[str, list] = {}
        for t in c.execute("SELECT * FROM tasks"):
            if scope is None or t["scope"] == scope:        # a load of one group only ever meets the tasks of that group
                self.by_site.setdefault(t["site_code"] or t["code"], []).append(dict(t))
        self.periods = _periods_of(c)
        self.taken = {r["code"] for r in c.execute("SELECT code FROM tasks")}

    def find(self, r: dict):
        sibs = self.by_site.get(r["code"], [])
        for t in sibs:
            if t["due"] == r["due"]:
                return t
        if not sibs:
            return None
        if (r.get("ext_n") or 0) > 0:
            return min(sibs, key=lambda t: _days_apart(t["due"], r["due"]))
        if r.get("occ", 1) > 1 or len(sibs) > 1 or any(r["due"] in self.periods.get(t["id"], ()) for t in sibs):
            return None
        return sibs[0]

    def new_code(self, r: dict) -> str:
        sibs = self.by_site.get(r["code"], [])
        code = r["code"] if not sibs else f"{r['code']}#{r['due']}"
        if code in self.taken and self.scope:                 # the same code is already a task of another group: it gets a code of its own
            code = f"{code}~{self.scope}"
        n = 2
        while code in self.taken:
            code, n = f"{r['code']}#{r['due']}-{n}", n + 1
        self.taken.add(code)
        return code

    def add(self, t: dict) -> None:
        self.by_site.setdefault(t["site_code"] or t["code"], []).append(t)


def store_ext(c, pairs: list) -> None:
    """The extension date of the site's list («Муддат узайтириш санаси») and the number of extensions: kept on the task and copied to what was read from the site,
    because the Chamber's «accepted for information» answer only means «waiting for us» until the term is extended after it. pairs: [(task id, row)]."""
    for tid, r in pairs:
        if tid is None or "unit_id" not in r:
            continue                      # only the raw export of the site has these columns
        c.execute("UPDATE tasks SET ext_date=?, ext_n=? WHERE id=?", (r.get("ext_date"), r.get("ext_n"), tid))
        c.execute("UPDATE ijro_snapshots SET ext_date=? WHERE task_id=?", (r.get("ext_date"), tid))


def apply_status(c, rows: list[dict], warnings: list[str], filename: str, user_id: int | None, dry: bool) -> dict:
    """The ordinary import: ONLY the statuses of tasks that are already in the base. A task that is not in the base is counted, never created;
    texts, terms, responsible people are not touched; what the administrator edited by hand stays as it is."""
    m = Matcher(c)                           # the statuses of the site's list go to the task whatever its group
    updated = same = kept = missing = 0
    t = now()
    ext_pairs = []
    for r in rows:
        cur = m.find(r)
        if cur is None:                          # not in the base (another period of a periodic task is not created here either)
            missing += 1
            continue
        ext_pairs.append((cur["id"], r))
        raw = "unit_id" in r                     # a raw export of the site (its "in progress" never lowers our status)
        if cur["status"] == "gone" and raw:      # the site lists it as ours again: back on the dashboard
            new = r["status"]
        elif cur["edited"]:
            kept += 1
            continue
        elif raw and r["status"] == "todo" and cur["status"] in ("todo", "progress"):
            same += 1
            continue
        else:
            new = r["status"]
        if new == cur["status"]:
            same += 1
            continue
        updated += 1
        if not dry:
            c.execute("UPDATE tasks SET status=?, done_at=?, updated_at=? WHERE id=?", (new, t if new == "done" else None, t, cur["id"]))
    if not dry:
        store_ext(c, ext_pairs)
    summary = {"rows": len(rows), "created": 0, "updated": updated, "unchanged": same, "kept_manual": kept, "missing": missing,
               "new_people": [], "warnings": warnings, "dry": dry, "mode": "status"}
    if not dry:
        import json
        c.execute("INSERT INTO imports(user_id, filename, summary, created_at) VALUES (?,?,?,?)", (user_id, filename[:200], json.dumps(summary, ensure_ascii=False), t))
        audit(c, "import.status", "tasks", None, {"file": filename[:200], "updated": updated, "missing": missing})
    return summary


def absent_tasks(c, present: set, scope: str = "main") -> list[dict]:
    """The tasks of the base whose code is not in the loaded file, whatever their status: the base is loaded as a whole, so what is not in it is no longer in the base.
    A task added by hand is not in any file and is never one of them."""
    return [dict(r) for r in c.execute("SELECT id, code, site_code, status, doc_no, point, substr(text, 1, 120) AS text, due FROM tasks WHERE status != 'gone' AND manual=0 AND scope=? ORDER BY code", (scope,))
            if (r["site_code"] or r["code"]) not in present]


def apply(c, rows: list[dict], warnings: list[str], filename: str, user_id: int | None, dry: bool, mode: str = "base", overwrite: bool = False, scope: str = "main") -> dict:
    """mode "base": the base load (new tasks are created, fields are updated). mode "status": only the statuses, see apply_status.
    overwrite: the file wins over what the administrator edited by hand (the status and the responsible person, and the closing date when the file has one);
    otherwise a task with hand edits keeps them."""
    if mode == "status":
        return apply_status(c, rows, warnings, filename, user_id, dry)
    users = {}
    for u in c.execute("SELECT id, name, excel_name FROM users"):
        users[auth.norm_name(u["name"])] = u["id"]
        if u["excel_name"]:
            users[auth.norm_name(u["excel_name"])] = u["id"]
    new_people, created, updated, same, kept, overwritten, term_moved = [], 0, 0, 0, 0, 0, 0
    m = Matcher(c, scope)
    t = now()
    ext_pairs = []
    for r in rows:
        key = auth.norm_name(r["who"])
        uid = users.get(key) if key else None
        if key and uid is None:
            if r["who"] not in [p["name"] for p in new_people]:
                new_people.append({"name": r["who"], "login": None})
            if not dry:
                login = auth.make_login(c, r["who"])
                cur = c.execute("INSERT INTO users(login, name, password_hash, role, excel_name, created_at, unit_id) VALUES (?,?,?,?,?,?,?)",
                                (login, r["who"], auth.unusable_hash(), "user", r["who"], t, r.get("unit_id")))
                users[key] = uid = cur.lastrowid
                new_people[-1]["login"] = login
        if uid and r.get("unit_id") and not dry:   # the department of the export tells where a person without a unit of ours belongs
            c.execute("UPDATE users SET unit_id=? WHERE id=? AND unit_id IS NULL", (r["unit_id"], uid))
        cur_row = m.find(r)
        if cur_row is None:
            created += 1
            code = m.new_code(r)
            new_id = None
            if not dry:
                cur = c.execute("""INSERT INTO tasks(code, site_code, scope, seq, kind, doc_no, doc_date, point, text, due, close_date, assignee_id, assignee_raw,
                             status, tag, done_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (code, r["code"], scope, r["seq"], r["kind"], r["doc_no"], r["doc_date"], r["point"], r["text"], r["due"], r["close_date"],
                           uid, r["who"], r["status"], r["tag"], t if r["status"] == "done" else None, t, t))
                new_id = cur.lastrowid
            m.add({"id": new_id, "code": code, "site_code": r["code"], "due": r["due"], "status": r["status"], "edited": 0, "close_src": "", "manual": 0})
            ext_pairs.append((new_id, r))
            continue
        if "unit_id" in r and r["due"] and cur_row["due"] and r["due"][:7] != cur_row["due"][:7] and cur_row["status"] in ("todo", "progress") and not cur_row["manual"]:
            term_moved += 1                                  # the site moved the term of an open task to another month: the old month is done, the new month carries the work
            if not dry:
                new_id = tasks.split_term(c, cur_row["id"], r["due"])
                if new_id:
                    cur_row["status"] = "done"
                    cur_row = dict(c.execute("SELECT * FROM tasks WHERE id=?", (new_id,)).fetchone())
                    m.add(cur_row)
        ext_pairs.append((cur_row["id"], r))
        fields = {"seq": r["seq"], "kind": r["kind"], "doc_no": r["doc_no"], "doc_date": r["doc_date"], "point": r["point"],
                  "text": r["text"], "due": r["due"], "assignee_raw": r["who"], "tag": r["tag"]}
        if "unit_id" in r:
            fields.pop("seq"), fields.pop("tag")       # the raw export knows neither the number of the specialist's list nor his notes
            for k in ("text", "point"):                 # the same words written with other blank lines or "-банд-банд" are not a change
                if _same_words(cur_row[k], r[k]):
                    fields.pop(k)
        if cur_row["status"] == "gone" and "unit_id" in r:
            fields.update(status=r["status"], assignee_id=uid)          # the site lists it as ours again: back on the dashboard
        elif cur_row["edited"] and not overwrite:
            kept += 1  # the administrator already worked on this task: the file does not overwrite assignee, status, closing date
        elif "unit_id" in r:
            # the raw export of the site: it has no closing date (never erased) and says "in progress" for everything open (never lowers our status)
            fields.update(assignee_id=uid)
            if r["status"] != "todo" or cur_row["status"] not in ("todo", "progress"):
                fields.update(status=r["status"])
        else:
            fields.update(close_date=r["close_date"], assignee_id=uid, status=r["status"])
        if overwrite and "unit_id" in r and cur_row["close_src"]:
            fields.update(close_date=None, close_src="", close_note="")       # a closing date that is only a proposal (nobody confirmed it) goes with the old base; a confirmed one stays
        diff = {k: v for k, v in fields.items() if cur_row[k] != v}
        if not diff:
            same += 1
            continue
        if cur_row["edited"] and overwrite and diff.keys() & {"status", "assignee_id", "close_date"}:
            overwritten += 1                      # something the administrator had set by hand is replaced by the file ...
            diff["edited"] = 0                    # ... and the task is the file's again (no longer "edited by hand")
            diff["status_manual"] = 0             # ... and checked against the site again
        updated += 1
        if not dry:
            if "status" in diff:
                diff["done_at"] = t if diff["status"] == "done" else None
            diff["updated_at"] = t
            c.execute(f"UPDATE tasks SET {', '.join(k + '=?' for k in diff)} WHERE id=?", (*diff.values(), cur_row["id"]))
    if not dry:
        store_ext(c, ext_pairs)
    summary = {"scope": scope, "rows": len(rows), "created": created, "updated": updated, "unchanged": same, "kept_manual": kept, "overwritten": overwritten, "term_moved": term_moved,
               "new_people": new_people, "warnings": warnings, "dry": dry, "mode": "base"}
    if not dry:
        import json
        c.execute("INSERT INTO imports(user_id, filename, summary, created_at) VALUES (?,?,?,?)",
                  (user_id, filename[:200], json.dumps(summary, ensure_ascii=False), t))
        audit(c, "import", "tasks", None, {"file": filename[:200], "created": created, "updated": updated, "people": len(new_people)})
    return summary
