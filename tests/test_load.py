"""Belastungstest 50.000 Zeilen. Ausführen mit: pytest -m slow -s"""

import resource
import time

import openpyxl
import pytest
from sqlalchemy import func, select

from backend.database.engine import session_scope
from backend.excel.importer import ImportConfig, run_import
from backend.excel.reader import read_sheet
from backend.models.entities import Article, ArticlePrice, Manufacturer, PriceList, User

ROWS = 50_000


@pytest.mark.slow
def test_import_50000_rows(app, tmp_path):
    path = tmp_path / "gross.xlsx"
    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Preise")
    ws.append(["Art.-Nr.", "Bezeichnung", "Warengruppe", "EK", "UVP"])
    for i in range(ROWS):
        ws.append([f"ART-{i:06d}", f"Artikel Nummer {i}", f"G{i % 50}", f"{i % 1000 + 1},{i % 100:02d}", (i % 500) + 0.99])
    wb.save(path)

    t0 = time.perf_counter()
    sheet = read_sheet(path)
    t_read = time.perf_counter() - t0
    with session_scope() as db:
        admin = db.scalar(select(User))
        m = Manufacturer(name="Last", aliases=[])
        db.add(m)
        pl = PriceList(name="g", source_file="g.xlsx", stored_file="g.xlsx", file_sha256="0" * 64, uploaded_by=admin.id)
        db.add(pl)
        db.flush()
        t1 = time.perf_counter()
        summary = run_import(db, pl.id, sheet, ImportConfig(
            header_row=1, mapping={"article_number": 0, "description": 1, "category": 2, "supplier_price": 3, "rrp": 4},
            manufacturer_id=m.id, default_currency="EUR", decimal_separators={3: ","}))
        t_import = time.perf_counter() - t1
    with session_scope() as db:
        assert db.scalar(select(func.count(Article.id))) == ROWS
        assert db.scalar(select(func.count(ArticlePrice.id))) == 2 * ROWS
    assert summary["status"]["OK"] == ROWS
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"\n50.000 Zeilen: Lesen {t_read:.1f}s, Import {t_import:.1f}s, Spitzen-RAM {peak_mb:.0f} MB")
