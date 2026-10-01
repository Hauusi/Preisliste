"""Belastungstest 50.000 Zeilen. Ausführen mit: pytest -m slow -s"""

import resource
import time

import openpyxl
import pytest
from sqlalchemy import func, insert, select

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


@pytest.mark.slow
def test_compare_10000_articles(app):
    from decimal import Decimal

    from backend.comparison.service import run_comparison
    from backend.excel.importer import normalize_article_number
    from backend.models.entities import Comparison

    n = 10_000
    with session_scope() as db:
        admin = db.scalar(select(User))
        m = Manufacturer(name="V", aliases=[])
        db.add(m)
        db.flush()
        ids = {}
        for side in ("alt", "neu"):
            pl = PriceList(name=side, source_file="x", stored_file="x", file_sha256="0" * 64, uploaded_by=admin.id,
                           status="IMPORTIERT")
            db.add(pl)
            db.flush()
            ids[side] = pl.id
            arts, prices = [], []
            base = 1_000_000 if side == "alt" else 2_000_000
            for i in range(n):
                nr = f"ART-{i:06d}" if side == "alt" or i % 50 else f"ART-{i:06d}X"  # 2 % geänderte Nummern
                arts.append({"id": base + i, "price_list_id": pl.id, "source_row": i + 2, "article_number": nr,
                             "article_number_normalized": normalize_article_number(nr), "manufacturer_id": m.id,
                             "description": f"Artikel {i}", "status": "OK"})
                prices.append({"id": base + i, "article_id": base + i, "price_type": "LISTE",
                               "amount": Decimal(10 + (i % 7 if side == "neu" else 0)), "currency": "EUR"})
            db.execute(insert(Article), arts)
            db.execute(insert(ArticlePrice), prices)
        cmp = Comparison(old_price_list_id=ids["alt"], new_price_list_id=ids["neu"], price_type="LISTE",
                         quantity=Decimal(1), created_by=admin.id)
        db.add(cmp)
        db.flush()
        t0 = time.perf_counter()
        summary = run_comparison(db, cmp)
        took = time.perf_counter() - t0
    assert summary["NICHT_EINDEUTIG"] == n // 50
    print(f"\nVergleich 10.000 Artikel: {took:.1f}s, {summary}")
