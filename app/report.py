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


def collect(c, month: str, by: str) -> dict:
    """{rows: [...], total, none, groups}: month "YYYY-MM", or "" for every month (and the tasks without a term)."""
    units = c.execute("SELECT id, num, name, parent_id FROM units WHERE active=1 ORDER BY sort, id").fetchall()
    ids = {u["id"] for u in units}
    stage = ijro.stage_map(c)
    own = {u["id"]: _acc() for u in units}
    own[0] = _acc()
    for r in c.execute("""SELECT t.id, t.status, t.due, t.close_date, t.kind, u.unit_id FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id
                          WHERE t.status NOT IN ('gone', 'info')""").fetchall():
        if month and (eff_value(r, by) or "")[:7] != month:
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


def title_text(month: str) -> str:
    when = f" {month[:4]} йил {MONTHS_UZ[int(month[5:7]) - 1]} ойига белгиланган" if month else ""
    return f"Соғлиқни сақлаш вазирлигида{when} ijro.gov.uz тизимидаги топшириқларининг бажарилиши"


def build_xlsx(data: dict, month: str, stamp: str) -> bytes:
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
    ws.cell(1, 1, title_text(month)).font = font(bold=True, size=14)
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
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def last_updates(c) -> dict:
    """When the data was last brought: the synchronisation with the site (the last read of a task) and the load of the base. 'YYYY-MM-DD HH:MM:SS' or ''."""
    sync = c.execute("SELECT MAX(checked_at) FROM ijro_snapshots").fetchone()[0] or ""
    base = c.execute("SELECT MAX(created_at) FROM imports").fetchone()[0] or ""
    return {"sync": sync, "base": base}
