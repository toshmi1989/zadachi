"""Import of the raw export from edo.ijro.uz ("ТОПШИРИҚЛАР КЕСИМИДА": one row per task, executor and department).

What it does with it:
  * keeps only the rows of OUR departments (column «Бўлим номи» matched with the units of the structure; the names come in Latin and Cyrillic,
    so both sides are compared in one transliterated form). A row of an employee we already know is ours as well;
  * a task of the file may have several rows (several departments, periods): one row is chosen per code;
  * the status comes from the file (the site's «Топшириқ ҳолати»);
  * the dates of closing are not in the file: they are proposed afterwards (closing.py).
The result has the same shape as the old import (importer.apply stores it)."""
import difflib
import io
import re
from datetime import date

import openpyxl

from . import auth
from .importer import ImportError_, parse_date, parse_doc, parse_text

# Only the tasks whose main executor («Масъул ижрочи») is this ministry are taken: the export of the site also carries rows of other executors.
# Compared in the one transliterated form, so Latin / Cyrillic spelling and the apostrophes of the site do not matter.
EXECUTOR = "Соғлиқни сақлаш вазирлиги"

AUTO_MATCH = 0.90          # a department name this similar to a unit of ours is taken without asking
SUGGEST_MIN = 0.75

_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ", ["a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "x", "ts",
                                                             "ch", "sh", "sh", "", "i", "", "e", "yu", "ya", "o", "q", "g", "h"]))

# columns of the export by the beginning of the header (casefolded)
COLS = {"num": "№", "kind": "ҳужжат тури", "doc": "ҳужжат рақами ва санаси", "text": "топшириқ мазмуни", "due": "топшириқ муддати", "exec": "масъул ижрочи",
        "who": "масъул ҳодим", "dept": "бўлим номи", "code": "топшириқ коди", "state": "топшириқ ҳолати", "role": "топшириқ тури", "ext_n": "муддат узайтириш сони"}


def skeleton(s) -> str:
    """One comparable form for a name written in Latin or Cyrillic (ў → o, қ → q, ц → ts ...), without punctuation and repeated words."""
    s = "".join(_CYR.get(ch, ch) for ch in str(s or "").lower())
    s = re.sub(r"[ʻʼ’‘`']", "", s)
    out: list[str] = []
    for w in re.sub(r"[^a-z0-9]+", " ", s).split():
        if not out or out[-1] != w:
            out.append(w)
    return " ".join(out)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, skeleton(a), skeleton(b)).ratio()


def executor_ok(raw) -> bool:
    """True when the «Масъул ижрочи» cell is exactly our ministry (whole value, not a part of a longer name)."""
    return skeleton(raw) == skeleton(EXECUTOR)


def kind_of(raw: str) -> str:
    """The type of the document in our terms (Қарор, Фармон, Баён, ВМ, ПА)."""
    k = str(raw or "").strip()
    low = k.lower()
    if any(w in low for w in ("резолюци", "ёрдамчиси", "administratsiyasi", "администрацияси раҳбари", "администрацияси ҳужжат")):
        return "ПА"
    if any(w in low for w in ("вазирлар", "бош вазир", "сенат", "хавфсизлик кенгаши", "vazirlar")):
        return "ВМ"
    return k


# The list of the Cabinet of Ministers has many kinds of documents; only «Вазирлар маҳкамаси қарори (Янги)» is kept (the others are not tracked by the department).
# The values are what column B «Ҳужжат тури» holds for them; a kind that is not named here is taken as it is.
VM_NOT_KEPT = {" ".join(n.casefold().split()) for n in (
    "Бош вазир йўл хариталари", "Бош вазир рахбарлигидаги баёнлар", "Бош вазир раҳбарлигидаги баёнлар", "Бош вазир топшириқлари", "Вазирлар Маҳкамаси қарорлари",
    "Вазирлар Маҳкамаси Раёсат мажлиси баёнлари", "Вазирлар Маҳкамаси фармойишлари", "Қонунчилик палатаси қўмиталари топшириқлари", "Қонунчилик палатаси топшириқлари",
    "Сенат топшириқлари", "Ўзбекистон Республикаси Президенти Администрацияси раҳбари топшириқлари",
    "Ўзбекистон Республикаси Президенти Администрацияси раҳбари ўринбосарлари топшириқлари", "Ўзбекистон Республикаси Президенти Администрацияси ҳужжатлари",
    "Ўзбекистон Республикаси Президенти маслаҳатчилари топшириқлари", "Ўзбекистон Республикаси Президенти ҳузуридаги Хавфсизлик кенгаши топшириқлари")}


def not_kept_kind(raw) -> bool:
    return " ".join(str(raw or "").casefold().split()) in VM_NOT_KEPT


STATE = {"бажарилган": "done", "муддатидан кеч бажарилган": "done", "бажарилмасдан ёпилган": "info", "бажарилмоқда": "todo", "бажарилмаган": "todo"}


def is_site_export(data: bytes) -> bool:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=8, values_only=True):
                cells = [str(c).strip().casefold() for c in row if c is not None]
                if any(c.startswith(COLS["dept"]) for c in cells) and any(c.startswith(COLS["code"]) for c in cells):
                    return True
    except Exception:
        return False
    return False


def _read_rows(data: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    for ws in wb.worksheets:
        header = cols = None
        rows_iter = ws.iter_rows(values_only=True)
        out = []
        for i, row in enumerate(rows_iter, 1):
            if header is None:
                names = [str(c).strip().casefold() if c is not None else "" for c in row]
                m = {k: next((j for j, n in enumerate(names) if n.startswith(v)), None) for k, v in COLS.items()}
                if m["code"] is not None and m["dept"] is not None and m["due"] is not None:
                    header, cols = i, m
                continue
            get = lambda k: (row[cols[k]] if cols.get(k) is not None and cols[k] < len(row) else None)
            code = str(get("code") or "").strip()
            if not code:
                continue
            out.append({"code": code, "kind": get("kind"), "doc": get("doc"), "text": get("text"), "due": get("due"), "who": re.sub(r"\s+", " ", str(get("who") or "")).strip(),
                        "dept": re.sub(r"\s+", " ", str(get("dept") or "")).strip(), "state": str(get("state") or "").strip(), "role": str(get("role") or "").strip(),
                        "exec": str(get("exec") or "").strip(), "ext": str(get("ext_n") or "").strip(), "n": i})
        if header:
            if cols.get("exec") is None:       # without the column the filter would drop everything: say so instead
                raise ImportError_("В выгрузке нет колонки «Масъул ижрочи»: по ней отбираются задачи Соғлиқни сақлаш вазирлиги")
            return out
    raise ImportError_("Не нашёл таблицу выгрузки с сайта (нужны колонки «Бўлим номи», «Топшириқ коди», «Топшириқ муддати»)")


def load_aliases(c) -> dict:
    """{skeleton of a department name: unit_id, or None for 'not ours'} as the administrator has confirmed it."""
    return {r["alias_key"]: r["unit_id"] for r in c.execute("SELECT alias_key, unit_id FROM unit_aliases")}


def suggest_unit(c, name: str, units=None) -> tuple[int | None, float]:
    units = units or c.execute("SELECT id, name FROM units WHERE active=1").fetchall()
    best = max(((similarity(name, u["name"]), u["id"]) for u in units), default=(0.0, None))
    return (best[1], best[0])


def read(c, data: bytes, due_from: str | None, due_to: str | None, ours_out: set | None = None) -> tuple[list[dict], list[str], dict]:
    """(rows in the shape of importer.apply, warnings, report). due_from/due_to: only the terms of this window are taken (ISO dates, both ends included)."""
    raw = _read_rows(data)
    aliases = load_aliases(c)
    units = c.execute("SELECT id, name FROM units WHERE active=1").fetchall()
    unit_name = {u["id"]: u["name"] for u in units}
    known = {}   # employees of ours (name -> unit of the user): their rows are ours even when the department name is not matched
    who_is = {}  # the same names -> the user
    for u in c.execute("SELECT id, name, excel_name, unit_id FROM users WHERE active=1"):
        for nm in (u["name"], u["excel_name"]):
            if nm:
                who_is[auth.norm_name(nm)] = u
                if u["unit_id"] is not None:
                    known[auth.norm_name(nm)] = u["unit_id"]
    depts: dict[str, dict] = {}
    chosen: dict[str, dict] = {}
    skipped = {"window": 0, "not_ours": 0, "coexec": 0, "executor": 0}
    warnings: list[str] = []
    all_codes = {r["code"] for r in raw}
    for r in raw:
        key = skeleton(r["dept"])
        d = depts.setdefault(key, {"name": r["dept"], "rows": 0, "tasks": set(), "people": {}, "unit_id": None, "how": "", "suggest": None, "score": 0.0})
        d["rows"] += 1
        d["tasks"].add(r["code"])
        d["people"][r["who"]] = d["people"].get(r["who"], 0) + 1
    for key, d in depts.items():                         # which department is ours
        if key in aliases:
            d["unit_id"], d["how"] = aliases[key], "confirmed"
        else:
            uid, score = suggest_unit(c, d["name"], units)
            d["score"] = round(score, 2)
            if uid and score >= AUTO_MATCH:
                d["unit_id"], d["how"] = uid, "auto"
            elif uid and score >= SUGGEST_MIN:
                d["suggest"] = uid
        if d["unit_id"] is None:                          # a department unknown to us, but with employees of ours in it: suggested from them
            votes: dict[int, int] = {}
            for who, n in d["people"].items():
                uid = known.get(auth.norm_name(who))
                if uid:
                    votes[uid] = votes.get(uid, 0) + n
            if votes:
                d["suggest"] = max(votes, key=votes.get)
                d["how"] = "people"
    lo = parse_date(due_from)[0] if due_from else None
    hi = parse_date(due_to)[0] if due_to else None
    owner = {r["code"]: r["assignee_raw"] for r in c.execute("SELECT code, assignee_raw FROM tasks WHERE assignee_raw != ''")}
    cand: dict[str, list[dict]] = {}
    for r in raw:
        if not_kept_kind(r["kind"]):                                # a kind of document of the Cabinet's list that is not kept
            skipped["doc_type"] = skipped.get("doc_type", 0) + 1
            continue
        if not executor_ok(r["exec"]):                              # the main executor is another body: not ours, whatever the department says
            skipped["executor"] += 1
            continue
        if r["role"].strip().casefold().startswith("ҳамижрочи"):     # a co-executor's task: deliberately not taken (the department does not keep them)
            skipped["coexec"] += 1
            continue
        d = depts[skeleton(r["dept"])]
        uid = d["unit_id"] or (known.get(auth.norm_name(r["who"])) if r["who"] else None)
        if uid is None:
            skipped["not_ours"] += 1
            continue
        if ours_out is not None:
            ours_out.add(r["code"])                                  # ours by department, role and kind, whatever the term is
        due, prob = parse_date(r["due"])
        if prob or not due:
            warnings.append(f"{r['code']}: срок — {prob or 'пусто'}; строка пропущена")
            continue
        if (lo and due < lo) or (hi and due > hi):
            skipped["window"] += 1
            continue
        cand.setdefault(r["code"], []).append(dict(r, _due=due, _unit=uid))
    rows = []
    for code, lst in cand.items():
        mine = auth.norm_name(owner.get(code, ""))
        lst.sort(key=lambda x: (auth.norm_name(x["who"]) != mine, x["role"] != "Асосий", x["_due"]))   # the person who already has the task, then the main executor, then the earliest term
        r = lst[0]
        if len({x["who"] for x in lst}) > 1:
            warnings.append(f"{code}: несколько ответственных в наших отделах ({', '.join(sorted({x['who'] for x in lst}))}); взят {r['who']}")
        doc_no, doc_date = parse_doc(r["doc"])
        point, text = parse_text(r["text"])
        text = re.sub(r"\s*\n\s*Механизм:\s*-\s*$", "", text).rstrip()                # the site adds an empty "Механизм: -" and blank lines

        st = STATE.get(r["state"].strip().casefold(), "todo")
        rows.append({"code": code, "seq": 0, "kind": kind_of(r["kind"]), "doc_no": doc_no, "doc_date": doc_date, "point": point, "text": text, "due": r["_due"], "close_date": None,
                     "who": r["who"], "status": st, "tag": "", "unit_id": r["_unit"], "department": r["dept"], "ext": r["ext"]})
    votes: dict[tuple, int] = {}            # which unit the export puts a person in, and where he is now
    for r in rows:
        u = who_is.get(auth.norm_name(r["who"])) if r["who"] else None
        if u is not None and r["unit_id"] is not None:
            votes[(u["id"], r["unit_id"])] = votes.get((u["id"], r["unit_id"]), 0) + 1
    moves = []
    for uid in {k[0] for k in votes}:
        wanted = max((k for k in votes if k[0] == uid), key=lambda k: votes[k])[1]
        u = next(x for x in who_is.values() if x["id"] == uid)
        if u["unit_id"] is not None and u["unit_id"] != wanted:
            moves.append({"user_id": uid, "name": u["name"], "now": unit_name.get(u["unit_id"], "?"), "wanted_id": wanted, "wanted": unit_name.get(wanted, "?"), "tasks": votes[(uid, wanted)]})
    report = {"people_moves": sorted(moves, key=lambda m: -m["tasks"]), "file_rows": len(raw), "file_tasks": len(all_codes), "skipped": skipped, "tasks": len(rows),
              "departments": sorted(({"key": k, "name": d["name"], "rows": d["rows"], "tasks": len(d["tasks"]), "unit_id": d["unit_id"], "unit": unit_name.get(d["unit_id"], ""),
                                      "how": d["how"], "suggest": d["suggest"], "suggest_name": unit_name.get(d["suggest"], ""), "score": d["score"],
                                      "people": sorted(d["people"], key=lambda n: -d["people"][n])[:3]} for k, d in depts.items()), key=lambda x: (x["unit_id"] is None, -x["rows"])),
              "units": [{"id": u["id"], "name": u["name"]} for u in units]}
    return rows, warnings, report


def absent(c, data_codes: set[str], due_from: str | None, due_to: str | None) -> list[dict]:
    """Open tasks of ours with a term in the window that the file does not contain at all: probably closed on the site (nothing is changed by this)."""
    q = "SELECT code, doc_no, point, due FROM tasks WHERE status IN ('todo','progress')"
    args: list = []
    if due_from:
        q += " AND due >= ?"; args.append(due_from)
    if due_to:
        q += " AND due <= ?"; args.append(due_to)
    return [dict(r) for r in c.execute(q, args) if r["code"] not in data_codes]


def save_aliases(c, mapping: dict[str, int | None]) -> int:
    n = 0
    for key, uid in mapping.items():
        if not key:
            continue
        c.execute("INSERT INTO unit_aliases(alias_key, unit_id) VALUES (?,?) ON CONFLICT(alias_key) DO UPDATE SET unit_id=excluded.unit_id", (key, uid))
        n += 1
    return n
