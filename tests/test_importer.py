from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.database.engine import session_scope
from backend.excel.importer import ImportConfig, normalize_article_number, run_import
from backend.excel.reader import read_sheet
from backend.models.entities import Article, ArticlePrice, ImportMessage, Manufacturer, PriceList, User
from tests.conftest import make_xlsx, strip_formula_cache

D = Decimal


@pytest.fixture
def db(app):
    with session_scope() as s:
        yield s


def new_list(db) -> PriceList:
    admin = db.scalar(select(User).where(User.username == "admin"))
    m = db.scalar(select(Manufacturer).where(Manufacturer.name == "ACME"))
    if m is None:
        m = Manufacturer(name="ACME", aliases=[])
        db.add(m)
    pl = PriceList(name="t", source_file="t.xlsx", stored_file="t.xlsx", file_sha256="0" * 64, uploaded_by=admin.id)
    db.add(pl)
    db.flush()
    return pl, m


def do_import(db, tmp_path, rows, mapping, currency="EUR", seps=None, **kw):
    pl, m = new_list(db)
    sheet = read_sheet(make_xlsx(tmp_path / "x.xlsx", rows))
    if kw.get("strip"):
        strip_formula_cache(tmp_path / "x.xlsx")
        sheet = read_sheet(tmp_path / "x.xlsx")
    cfg = ImportConfig(header_row=kw.get("header_row", 1), mapping=mapping,
                       manufacturer_id=None if "manufacturer" in mapping else m.id,
                       default_currency=currency, decimal_separators=seps or {})
    summary = run_import(db, pl.id, sheet, cfg)
    db.flush()
    arts = db.scalars(select(Article).where(Article.price_list_id == pl.id).order_by(Article.source_row)).all()
    msgs = db.scalars(select(ImportMessage).where(ImportMessage.price_list_id == pl.id)).all()
    return summary, arts, msgs


def codes(msgs):
    return sorted(m.code for m in msgs)


def test_normalize_article_number():
    assert normalize_article_number("ab-12.3 4/5_6") == "AB123456"
    assert normalize_article_number("00123") == "00123"  # führende Nullen bleiben (F2 offen)


def test_basic_import_with_decimal_prices(db, tmp_path):
    summary, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "Bezeichnung", "EK", "UVP"],
        ["A-1", "Schraube", "1.234,56 €", 2.99],
        ["A-2", "Mutter", "0,20", "0,49"],
    ], {"article_number": 0, "description": 1, "supplier_price": 2, "rrp": 3})
    assert summary["articles"] == 2 and summary["prices"] == 4
    assert [a.status for a in arts] == ["OK", "OK"]
    prices = {(p.price_type, p.amount) for p in arts[0].prices}
    assert prices == {("EK", D("1234.56")), ("UVP", D("2.99"))}
    assert all(isinstance(p.amount, Decimal) for p in arts[0].prices)
    assert arts[0].article_number_normalized == "A1"
    assert msgs == []


def test_missing_and_invalid_values(db, tmp_path):
    summary, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "EK"],
        [None, "1,00"],
        ["B", None],
        ["C", "auf Anfrage"],
        ["D", "-5,00"],
        ["E", "0"],
        ["F", "12,00 JPY"],
    ], {"article_number": 0, "supplier_price": 1})
    by_row = {a.source_row: a.status for a in arts}
    assert by_row == {2: "FEHLER", 3: "FEHLER", 4: "FEHLER", 5: "FEHLER", 6: "WARNUNG", 7: "FEHLER"}
    assert codes(msgs) == sorted(["ARTIKELNUMMER_FEHLT", "PREIS_FEHLT", "KEIN_BETRAG", "PREIS_NEGATIV",
                                  "PREIS_NULL", "WAEHRUNG_UNBEKANNT"])


def test_unknown_currency_without_default_is_error(db, tmp_path):
    _, arts, msgs = do_import(db, tmp_path, [["Art.-Nr.", "EK"], ["A", "1,00"], ["B", "2,00 €"]],
                              {"article_number": 0, "supplier_price": 1}, currency=None)
    assert [a.status for a in arts] == ["FEHLER", "OK"]
    assert codes(msgs) == ["WAEHRUNG_FEHLT"]


def test_ambiguous_number_is_unclear_unless_column_separator_given(db, tmp_path):
    rows = [["Art.-Nr.", "EK"], ["A", "1.234"]]
    _, arts, _ = do_import(db, tmp_path, rows, {"article_number": 0, "supplier_price": 1})
    assert arts[0].status == "UNKLAR"
    _, arts, _ = do_import(db, tmp_path, rows, {"article_number": 0, "supplier_price": 1}, seps={1: ","})
    assert arts[0].status == "OK" and arts[0].prices[0].amount == D("1234")


def test_duplicates_are_warned_not_overwritten(db, tmp_path):
    summary, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "EK"], ["A-1", "1,00"], ["a 1", "2,00"], ["B", "3,00"],
    ], {"article_number": 0, "supplier_price": 1})
    assert len(arts) == 3
    assert [a.status for a in arts] == ["WARNUNG", "WARNUNG", "OK"]
    assert codes(msgs) == ["DOPPELT", "DOPPELT"]


def test_tier_prices_merge_into_one_article(db, tmp_path):
    summary, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "Staffel", "EK"], ["A", 1, "10,00"], ["A", 10, "9,00"], ["A", 100, "8,00"],
    ], {"article_number": 0, "quantity": 1, "supplier_price": 2})
    assert len(arts) == 1
    tiers = sorted((p.min_quantity, p.amount) for p in arts[0].prices)
    assert tiers == [(D(1), D("10.00")), (D(10), D("9.00")), (D(100), D("8.00"))]
    assert msgs == []


def test_same_quantity_twice_is_duplicate(db, tmp_path):
    _, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "Staffel", "EK"], ["A", 1, "10,00"], ["A", 1, "9,00"],
    ], {"article_number": 0, "quantity": 1, "supplier_price": 2})
    assert len(arts) == 2 and codes(msgs) == ["DOPPELT", "DOPPELT"]


def test_empty_and_section_rows(db, tmp_path):
    summary, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "Bezeichnung", "EK"], [None, None, None], [None, "Kapitel 2", None], ["A", "x", 1],
    ], {"article_number": 0, "description": 1, "supplier_price": 2})
    assert len(arts) == 1 and summary["empty_rows"] == 1
    assert codes(msgs) == ["ZEILE_UEBERSPRUNGEN"]


def test_formula_without_cache_warns(db, tmp_path):
    _, arts, msgs = do_import(db, tmp_path, [["Art.-Nr.", "EK"], ["A", "=1+1"]],
                              {"article_number": 0, "supplier_price": 1}, strip=True)
    assert "FORMEL_OHNE_WERT" in codes(msgs)
    assert arts[0].status == "FEHLER"  # ohne Wert kein Preis


def test_manufacturer_column_creates_and_reuses(db, tmp_path):
    summary, arts, _ = do_import(db, tmp_path, [
        ["Hersteller", "Art.-Nr.", "EK"], ["acme", "1", 1], ["Neu AG", "2", 2], ["", "3", 3],
    ], {"manufacturer": 0, "article_number": 1, "supplier_price": 2})
    acme = db.scalar(select(Manufacturer).where(Manufacturer.name == "ACME"))
    assert arts[0].manufacturer_id == acme.id
    assert summary["manufacturers_created"] == ["Neu AG"]
    assert arts[2].status == "FEHLER"


def test_discount_and_currency_column(db, tmp_path):
    _, arts, msgs = do_import(db, tmp_path, [
        ["Art.-Nr.", "Listenpreis", "Rabatt", "Währung"],
        ["A", "100,00", "15 %", "EUR"], ["B", "100,00", "150", "CHF"], ["C", "5,00 €", "", "USD"],
    ], {"article_number": 0, "list_price": 1, "discount": 2, "currency": 3}, currency=None)
    assert arts[0].prices[0].discount_percent == D(15)
    assert arts[1].status == "FEHLER"  # Rabatt > 100
    assert arts[2].status == "FEHLER"  # Währungswiderspruch
    assert set(codes(msgs)) == {"RABATT_UNGUELTIG", "WAEHRUNG_WIDERSPRUCH"}


def test_mapping_validation(db, tmp_path):
    pl, m = new_list(db)
    sheet = read_sheet(make_xlsx(tmp_path / "x.xlsx", [["a"]]))
    with pytest.raises(ValueError):
        run_import(db, pl.id, sheet, ImportConfig(1, {"supplier_price": 0}, m.id, "EUR"))
    with pytest.raises(ValueError):
        run_import(db, pl.id, sheet, ImportConfig(1, {"article_number": 0}, m.id, "EUR"))
