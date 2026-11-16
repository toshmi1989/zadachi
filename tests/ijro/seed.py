"""Seeds a throw-away database for the collector test: run with DATA_DIR pointing to an empty folder."""
import io
import sys

import openpyxl

sys.path.insert(0, "tests")
from app import db, importer

HEAD = ["№", "Ҳужжат тури", "Ҳужжат рақами ва санаси", "Топшириқ мазмуни", "Топшириқ муддати", "Ёпиш муддати", "Масъул ҳодим", "Топшириқ ижроси", "Топшириқ коди"]
ROWS = [("XPG5469", "Қарор", "Бажарилмаган"), ("OJN6944", "ПА", "Бажарилмаган"), ("VMK3541", "ВМ", "Бажарилмаган"), ("REP0001", "Қарор", "Бажарилмаган"), ("REP0002", "Қарор", "Бажарилмаган"),
        ("UNK0001", "Қарор", "Бажарилмаган"), ("NOF0001", "Қарор", "Бажарилмаган"), ("SEC0001", "Фармон", "Бажарилмаган"), ("DON0001", "Қарор", "Бажарилган")]
db.init_db()
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["x"]); ws.append([]); ws.append(HEAD)
for i, (code, kind, st) in enumerate(ROWS):
    ws.append([i + 1, kind, f"ПҚ-{i} \n 01.01.2026", f"{i}-банд\nТекст {code}", "31.12.2026", "2026-12-01", "Test Person", st, code])
b = io.BytesIO(); wb.save(b)
rows, w = importer.read(b.getvalue())
with db.tx() as c:
    importer.apply(c, rows, w, "seed.xlsx", None, False)
print("seeded", len(ROWS))
