"""The summary table of the execution of tasks of our department, in the format of the ministry's table (title, the total line, the groups
«ПРЕЗИДЕНТ ТОПШИРИҚЛАРИ / АДМИНИСТРАЦИЯ РАҲБАРИ ТОПШИРИҚЛАРИ / ВАЗИРЛАР МАҲКАМАСИ ҚАРОРЛАРИ»), as an Excel file.

The numbers are those of the dashboard: a task belongs to the unit of its responsible person (none: «Без отдела»), a management includes its divisions,
«К сведению» and the tasks taken off the dashboard are not counted, the month is the month of the term (the same date as the dashboard is built on)."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties

from . import ijro
from .db import OPEN
from .tasks import eff_value

MONTHS_UZ = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
GROUPS = [("ПРЕЗИДЕНТ ТОПШИРИҚЛАРИ", ("Фармон", "Қарор", "Баён")), ("АДМИНИСТРАЦИЯ РАҲБАРИ ТОПШИРИҚЛАРИ", ("ПА",)), ("ВАЗИРЛАР МАҲКАМАСИ ҚАРОРЛАРИ", ("ВМ",))]
OTHER = "БОШҚА ҲУЖЖАТЛАР"


def _acc() -> dict:
    return {"done": 0, "open": 0, "info": 0, "g": {}}


def _plus(a: dict, b: dict) -> dict:
    for k in ("done", "open", "info"):
        a[k] += b[k]
    for g, v in b["g"].items():
        t = a["g"].setdefault(g, {"done": 0, "open": 0})
        t["done"] += v["done"]
        t["open"] += v["open"]
    return a


def group_of(kind: str) -> str:
    for name, kinds in GROUPS:
        if kind in kinds:
            return name
    return OTHER


def collect(c, month: str, by: str, scope: str = "main") -> dict:
    """{rows: [...], total, none, groups}: month "YYYY-MM", or "" for every month (and the tasks without a term)."""
    units = c.execute("SELECT id, num, name, parent_id FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    ids = {u["id"] for u in units}
    stage = ijro.stage_map(c)
    own = {u["id"]: _acc() for u in units}
    own[0] = _acc()
    for r in c.execute("""SELECT t.id, t.status, t.due, t.close_date, t.kind, u.unit_id FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id
                          WHERE t.status NOT IN ('gone', 'info') AND t.scope=?""", (scope,)).fetchall():
        if month and not (eff_value(r, by) or "").startswith(month):
            continue
        a = own[r["unit_id"] if r["unit_id"] in ids else 0]
        key = "open" if r["status"] in OPEN else "done"
        a[key] += 1
        g = a["g"].setdefault(group_of(r["kind"] or ""), {"done": 0, "open": 0})
        g[key] += 1
        if key == "open" and stage.get(r["id"]) == "info":
            a["info"] += 1                       # the Chamber of Accounts accepted the answer for information: the task stays open
    kids: dict[int, list[int]] = {}
    for u in units:
        if u["parent_id"] in ids:
            kids.setdefault(u["parent_id"], []).append(u["id"])
    rows, total = [], _acc()
    for u in units:
        agg = _plus(_acc(), own[u["id"]])
        for k in kids.get(u["id"], []):
            _plus(agg, own[k])
        level = 1 if u["parent_id"] in ids else 0
        if not level:
            _plus(total, agg)
        rows.append({"num": (u["num"] + ".") if (u["num"] and not level) else u["num"], "name": u["name"], "level": level, **agg})
    none = _plus(_acc(), own[0])
    _plus(total, none)
    rows = [r for r in rows if r["done"] + r["open"]]                        # a unit without tasks in this month is not shown
    if none["done"] + none["open"]:
        rows.append({"num": "", "name": "Бўлинма кўрсатилмаган (Без отдела)", "level": 0, **none})
    seen = {g for r in rows for g in r["g"]} | set(total["g"])
    groups = [g for g, _ in GROUPS] + ([OTHER] if OTHER in seen else [])
    return {"rows": rows, "total": total, "groups": groups}


def asof_text(stamp: str) -> str:
    """'2026-11-23 09:13:05' -> '2026 йил 23 ноябрь 09:13 ҳолатига'."""
    y, m, d = int(stamp[:4]), int(stamp[5:7]), int(stamp[8:10])
    return f"{y} йил {d} {MONTHS_UZ[m - 1]} {stamp[11:16]} ҳолатига"


def title_text(month: str, scope: str = "main") -> str:
    when = (f" {month[:4]} йил {MONTHS_UZ[int(month[5:7]) - 1]} ойига белгиланган" if len(month) == 7 else f" {month[:4]} йилга белгиланган") if month else ""
    grp = {"co": " (Ҳамижрочи)", "vm": " (ВМ топшириқлари)"}.get(scope, "")
    return f"Соғлиқни сақлаш вазирлигида{when} ijro.gov.uz тизимидаги топшириқларининг бажарилиши{grp}"


def build_xlsx(data: dict, month: str, stamp: str, tdata: dict | None = None, admin: bool = False, scope: str = "main") -> bytes:
    groups, rows, total = data["groups"], data["rows"], data["total"]
    ncol = 7 + 3 * len(groups)
    wb = Workbook()
    ws = wb.active
    ws.title = "ТАҲЛИЛИ"
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    font = lambda **k: Font(name="Calibri", size=k.pop("size", 11), **k)
    grey, yellow, green = (PatternFill("solid", fgColor=x) for x in ("F2F2F2", "FFF2CC", "E2EFDA"))
    pct = lambda d, o: round(100 * d / (d + o), 1) if d + o else 0

    def merge(r1, c1, r2, c2, value, **kw):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
        cell = ws.cell(r1, c1, value)
        cell.alignment = kw.get("align", center)
        cell.font = kw.get("font", font(bold=True))
        for rr in range(r1, r2 + 1):
            for cc in range(c1, c2 + 1):
                ws.cell(rr, cc).border = box
                if kw.get("fill"):
                    ws.cell(rr, cc).fill = kw["fill"]
        return cell

    # the title and the date
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws.cell(1, 1, title_text(month, scope)).font = font(bold=True, size=14)
    ws.cell(1, 1).alignment = center
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
    ws.cell(2, 1, "ТАҲЛИЛИ").font = font(bold=True, size=14)
    ws.cell(2, 1).alignment = center
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=ncol)
    ws.cell(3, 1, asof_text(stamp)).font = font(italic=True, color="C00000", size=10)
    ws.cell(3, 1).alignment = Alignment(horizontal="right")
    # the head of the table (rows 5-7)
    merge(5, 1, 7, 1, "№", fill=grey)
    merge(5, 2, 7, 2, "Таркибий бўлинмалар\n(департамент, бошқарма, бўлим)", fill=grey)
    merge(5, 3, 5, 7, "ЖАМИ\nНазоратга олинган топшириқлар", fill=grey)
    merge(5, 8, 5, ncol, "Шу жумладан,", fill=grey)
    merge(6, 3, 7, 3, "ЖАМИ", fill=grey)
    merge(6, 4, 6, 5, "Бажарилди", fill=grey)
    ws.cell(7, 4, "Сони"), ws.cell(7, 5, "Фоиз (%)")
    merge(6, 6, 7, 6, "Тизимда қолган топшириқ", fill=grey)
    merge(6, 7, 7, 7, "Маълумот учун қабул қилинган", fill=grey)
    for i, g in enumerate(groups):
        c0 = 8 + 3 * i
        gd = total["g"].get(g, {"done": 0, "open": 0})
        merge(6, c0, 6, c0 + 2, g, fill=grey)
        for j, label in enumerate(("ЖАМИ", f"Бажарилди ({pct(gd['done'], gd['open']):.1f}%)".replace(".", ","), "Қолдиқ")):
            ws.cell(7, c0 + j, label)
    for cc in range(1, ncol + 1):
        for rr in (5, 6, 7):
            cell = ws.cell(rr, cc)
            cell.border, cell.fill = box, grey
            if cell.alignment.horizontal is None:
                cell.alignment = center
            cell.font = font(bold=True, size=10)
    # the lines
    def put(r, row, kind):
        d, o = row["done"], row["open"]
        share = pct(d, o) if kind == "total" else round(pct(d, o))      # the total line has one decimal (22,5), the others are whole percents
        vals = [row.get("num", ""), row["name"], d + o, d or None, share, o or None, row["info"] or None]
        for g in groups:
            gd = row["g"].get(g, {"done": 0, "open": 0})
            vals += [(gd["done"] + gd["open"]) or None, gd["done"] or None, gd["open"] or None]
        for cc, v in enumerate(vals, 1):
            cell = ws.cell(r, cc, v)
            cell.border = box
            cell.alignment = left if cc == 2 else center
            cell.font = font(bold=kind in ("total", "mgmt"))
            if kind == "total":
                cell.fill = yellow
            elif kind == "mgmt":
                cell.fill = green
        ws.cell(r, 5).number_format = "0.0" if kind == "total" else "0"
    r = 8
    put(r, {"num": "Департамент бўйича жами:", "name": "", **total}, "total")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    ws.cell(r, 1).alignment = center
    for row in rows:
        r += 1
        put(r, row, "kid" if row["level"] else "mgmt")
    # widths, printing
    widths = [6, 52, 11, 10, 9, 13, 14] + [11, 12, 10] * len(groups)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = ws.row_dimensions[2].height = 22
    ws.row_dimensions[7].height = 34
    ws.freeze_panes = "C8"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    ws.print_title_rows = "5:7"
    if tdata is not None:
        add_task_sheets(wb, tdata, admin)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def last_updates(c) -> dict:
    """When the data was last brought: the synchronisation with the site (the last read of a task) and the load of the base. 'YYYY-MM-DD HH:MM:SS' or ''."""
    sync = c.execute("SELECT MAX(checked_at) FROM ijro_snapshots").fetchone()[0] or ""
    base = c.execute("SELECT MAX(created_at) FROM imports").fetchone()[0] or ""
    return {"sync": sync, "base": base}


# ---------------------------------------------------------------- the tasks themselves (further sheets of the file)

STAGE_RU = {"none": "Ответ не введён", "moj": "Минюст (Адлия)", "cab": "Кабинет Министров", "chamber": "Счётная палата", "info": "Палата вернула (принято к сведению)",
            "returned": "Возврат / запрос", "other": "Другое", "unchecked": "Не проверялись"}
STAGE_ORDER = ["none", "moj", "cab", "chamber", "info", "returned", "other", "unchecked", "done"]
STATUS_RU = {"todo": "Не выполнено", "progress": "В работе", "done": "Выполнено"}


def collect_tasks(c, month: str, by: str, scope: str = "main") -> dict:
    """The tasks that stand behind the summary numbers (the same selection: a period by the same date, «К сведению» and the tasks taken off the dashboard are not there),
    each with its department (management / division), its stage and its terms, and the order of the departments of the structure."""
    units = c.execute("SELECT id, num, name, parent_id FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    ids = {u["id"]: u for u in units}
    stage = ijro.stage_map(c)
    out = []      # a long text is cut to 400 characters: the whole one is in the task
    for r in c.execute("""SELECT t.id, t.code, t.site_code, t.kind, t.doc_no, t.doc_date, t.point, t.text, t.due, t.close_date, t.status, a.name AS who, a.unit_id AS unit_id
                          FROM tasks t LEFT JOIN users a ON a.id = t.assignee_id WHERE t.status NOT IN ('gone', 'info') AND t.scope=?""", (scope,)):
        eff = eff_value(r, by)
        if month and not (eff or "").startswith(month):
            continue
        u = ids.get(r["unit_id"])
        mgmt = ids.get(u["parent_id"]) if u and u["parent_id"] in ids else u
        done = r["status"] not in OPEN
        out.append({"code": r["site_code"] or r["code"], "kind": r["kind"] or "", "doc": (r["doc_no"] or "") + (f" от {r['doc_date'][8:10]}.{r['doc_date'][5:7]}.{r['doc_date'][:4]}" if r["doc_date"] else ""),
                    "point": r["point"] or "", "text": " ".join((r["text"] or "").split())[:400] + ("…" if len(" ".join((r["text"] or "").split())) > 400 else ""), "who": r["who"] or "", "close": r["close_date"] or "", "due": r["due"] or "", "eff": eff or "",
                    "status": STATUS_RU.get(r["status"], r["status"]), "stage_key": "done" if done else stage.get(r["id"], "unchecked"),
                    "stage": "Выполнено" if done else STAGE_RU.get(stage.get(r["id"], "unchecked"), "Другое"),
                    "mgmt": mgmt["id"] if mgmt else 0, "unit": u["id"] if u else 0})
    return {"tasks": out, "units": [dict(u) for u in units]}


def _fdate(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else ""


def add_task_sheets(wb, tdata: dict, admin: bool) -> None:
    from openpyxl.worksheet.properties import Outline
    tasks, units = tdata["tasks"], {u["id"]: u for u in tdata["units"]}
    heads = ["№", "Код", "Вид", "Документ", "Пункт", "Текст задачи", "Ответственный", "Месяц срока", "Срок исполнения (дата закрытия)"] + (["Официальный срок"] if admin else []) + ["Статус", "Этап согласования", "Отдел"]
    widths = [5, 11, 9, 24, 10, 70, 24, 11, 14] + ([14] if admin else []) + [13, 24, 36]
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")
    green, band, head = (PatternFill("solid", fgColor=x) for x in ("E2EFDA", "F2F2F2", "D9E1F2"))

    def unit_label(uid: int) -> str:
        u = units.get(uid)
        if not u:
            return "Без отдела"
        par = units.get(u["parent_id"]) if u["parent_id"] in units else None
        mine = (u["num"] + ". " if u["num"] else "") + u["name"]
        return ((par["num"] + ". " if par and par["num"] else "") + par["name"] + " / " + mine) if par else mine

    def setup(ws, title: str):
        ws.append([title])
        ws["A1"].font = Font(name="Calibri", size=13, bold=True)
        ws.append([])
        ws.append(heads)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
            cell = ws.cell(3, i)
            cell.font, cell.fill, cell.border = Font(name="Calibri", bold=True, size=10), head, box
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[3].height = 32
        ws.freeze_panes = "C4"
        ws.sheet_properties.outlinePr = Outline(summaryBelow=False)          # the plus/minus of a group sits on its heading line
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.print_title_rows = "3:3"

    def group_line(ws, text: str, fill, level: int = 0):
        r = ws.max_row + 1
        ws.cell(r, 1, text)
        for cc in range(1, len(heads) + 1):
            ws.cell(r, cc).fill, ws.cell(r, cc).border = fill, box
        ws.cell(r, 1).font = Font(name="Calibri", bold=True, size=11 if level == 0 else 10)
        ws.cell(r, 1).alignment = Alignment(horizontal="left", vertical="center", indent=level)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(heads))
        ws.row_dimensions[r].height = 20 if level == 0 else 17

    def task_line(ws, n: int, t: dict, level: int):
        vals = [n, t["code"], t["kind"], t["doc"], t["point"], t["text"], t["who"], t["eff"][:7] if t["eff"] else "", _fdate(t["close"])] + ([_fdate(t["due"])] if admin else []) \
            + [t["status"], t["stage"], unit_label(t["unit"])]
        r = ws.max_row + 1
        for cc, v in enumerate(vals, 1):
            cell = ws.cell(r, cc, v)
            cell.alignment, cell.border, cell.font = wrap, box, Font(name="Calibri", size=10)
        ws.cell(r, 1).alignment = Alignment(horizontal="center", vertical="top")
        ws.row_dimensions[r].outlineLevel = level

    def key(t):
        return (t["eff"] or "9999", t["code"])

    def counts(ts):
        d = sum(1 for t in ts if t["stage_key"] == "done")
        return f"задач: {len(ts)} · выполнено: {d} · не выполнено: {len(ts) - d}"

    # ---- 1. by departments: a management, its divisions, the tasks of each
    ws = wb.create_sheet("Задачи по отделам")
    setup(ws, "Задачи по отделам (управление → отдел): значок «–» слева сворачивает группу")
    by_m: dict[int, list] = {}
    for t in tasks:
        by_m.setdefault(t["mgmt"], []).append(t)
    n = 0
    order = [u["id"] for u in tdata["units"] if u["parent_id"] not in units] + [0]
    for mid in order:
        group = by_m.get(mid)
        if not group:
            continue
        mname = "Без отдела (ответственный без отдела или не назначен)" if mid == 0 else ((units[mid]["num"] + ". " if units[mid]["num"] else "") + units[mid]["name"])
        group_line(ws, f"{mname} — {counts(group)}", green)
        own = [t for t in group if t["unit"] == mid]
        if own:
            for t in sorted(own, key=key):
                n += 1; task_line(ws, n, t, 1)
        for kid in [u["id"] for u in tdata["units"] if u["parent_id"] == mid]:
            sub = [t for t in group if t["unit"] == kid]
            if sub:
                group_line(ws, f"{unit_label(kid).split(' / ')[-1]} — {counts(sub)}", band, 1)
                for t in sorted(sub, key=key):
                    n += 1; task_line(ws, n, t, 2)
    # ---- 2. by stages: a stage, the departments in it, the tasks
    ws = wb.create_sheet("Задачи по этапам")
    setup(ws, "Задачи по этапам согласования (этап → управление → задачи): не выполненные идут по пути ответа, выполненные в конце")
    n = 0
    for sk in STAGE_ORDER:
        group = [t for t in tasks if t["stage_key"] == sk]
        if not group:
            continue
        group_line(ws, f"{'Выполнено' if sk == 'done' else STAGE_RU[sk]} — {len(group)}", green)
        for mid in order:
            sub = [t for t in group if t["mgmt"] == mid]
            if not sub:
                continue
            group_line(ws, f"{'Без отдела' if mid == 0 else ((units[mid]['num'] + '. ' if units[mid]['num'] else '') + units[mid]['name'])} — {len(sub)}", band, 1)
            for t in sorted(sub, key=lambda t: (unit_label(t["unit"]),) + key(t)):
                n += 1; task_line(ws, n, t, 2)
    # ---- 3. the flat list: for filtering and searching
    ws = wb.create_sheet("Все задачи")
    setup(ws, "Все задачи списком (фильтры в заголовках колонок: отдел, этап, статус, месяц)")
    for i, t in enumerate(sorted(tasks, key=lambda t: (order.index(t["mgmt"]) if t["mgmt"] in order else 99, unit_label(t["unit"])) + key(t)), 1):
        task_line(ws, i, t, 0)
    ws.auto_filter.ref = f"A3:{get_column_letter(len(heads))}{max(ws.max_row, 3)}"
