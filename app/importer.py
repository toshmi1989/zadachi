"""Import of the Excel export. Idempotent: a task is identified by its code ("Топшириқ коди"), so loading the
next export updates documents, texts and terms, and keeps what the administrator edited by hand."""
import io
import re
from datetime import date, datetime

import openpyxl

from . import auth
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


def apply_status(c, rows: list[dict], warnings: list[str], filename: str, user_id: int | None, dry: bool) -> dict:
    """The ordinary import: ONLY the statuses of tasks that are already in the base. A task that is not in the base is counted, never created;
    texts, terms, responsible people are not touched; what the administrator edited by hand stays as it is."""
    existing = {r["code"]: r for r in c.execute("SELECT id, code, status, edited FROM tasks")}
    updated = same = kept = missing = 0
    t = now()
    for r in rows:
        cur = existing.get(r["code"])
        if cur is None:
            missing += 1
            continue
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
    summary = {"rows": len(rows), "created": 0, "updated": updated, "unchanged": same, "kept_manual": kept, "missing": missing,
               "new_people": [], "warnings": warnings, "dry": dry, "mode": "status"}
    if not dry:
        import json
        c.execute("INSERT INTO imports(user_id, filename, summary, created_at) VALUES (?,?,?,?)", (user_id, filename[:200], json.dumps(summary, ensure_ascii=False), t))
        audit(c, "import.status", "tasks", None, {"file": filename[:200], "updated": updated, "missing": missing})
    return summary


def absent_open(c, present: set) -> list[dict]:
    """Open tasks of the base whose code is not in the loaded file (the base is loaded as a whole, so they are no longer on the site's list)."""
    return [dict(r) for r in c.execute("SELECT id, code, doc_no, point, substr(text, 1, 120) AS text, due FROM tasks WHERE status IN ('todo','progress') ORDER BY code")
            if r["code"] not in present]


def apply(c, rows: list[dict], warnings: list[str], filename: str, user_id: int | None, dry: bool, mode: str = "base", overwrite: bool = False) -> dict:
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
    new_people, created, updated, same, kept, overwritten = [], 0, 0, 0, 0, 0
    existing = {r["code"]: r for r in c.execute("SELECT * FROM tasks")}
    t = now()
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
        cur_row = existing.get(r["code"])
        if cur_row is None:
            created += 1
            if not dry:
                c.execute("""INSERT INTO tasks(code, seq, kind, doc_no, doc_date, point, text, due, close_date, assignee_id, assignee_raw,
                             status, tag, done_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (r["code"], r["seq"], r["kind"], r["doc_no"], r["doc_date"], r["point"], r["text"], r["due"], r["close_date"],
                           uid, r["who"], r["status"], r["tag"], t if r["status"] == "done" else None, t, t))
            continue
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
        diff = {k: v for k, v in fields.items() if cur_row[k] != v}
        if not diff:
            same += 1
            continue
        if cur_row["edited"] and overwrite and diff.keys() & {"status", "assignee_id", "close_date"}:
            overwritten += 1                      # something the administrator had set by hand is replaced by the file ...
            diff["edited"] = 0                    # ... and the task is the file's again (no longer "edited by hand")
        updated += 1
        if not dry:
            if "status" in diff:
                diff["done_at"] = t if diff["status"] == "done" else None
            diff["updated_at"] = t
            c.execute(f"UPDATE tasks SET {', '.join(k + '=?' for k in diff)} WHERE id=?", (*diff.values(), cur_row["id"]))
    summary = {"rows": len(rows), "created": created, "updated": updated, "unchanged": same, "kept_manual": kept, "overwritten": overwritten,
               "new_people": new_people, "warnings": warnings, "dry": dry, "mode": "base"}
    if not dry:
        import json
        c.execute("INSERT INTO imports(user_id, filename, summary, created_at) VALUES (?,?,?,?)",
                  (user_id, filename[:200], json.dumps(summary, ensure_ascii=False), t))
        audit(c, "import", "tasks", None, {"file": filename[:200], "created": created, "updated": updated, "people": len(new_people)})
    return summary
