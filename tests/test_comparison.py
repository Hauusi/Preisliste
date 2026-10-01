from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.calculations.engine import RuleDefinition
from backend.comparison.service import decide, percent_change, run_comparison
from backend.database.engine import session_scope
from backend.models.entities import (
    Article, ArticlePrice, Comparison, ComparisonItem, Manufacturer, PriceList, User,
)
from backend.services.rules import create_rule, current_version

D = Decimal


@pytest.fixture
def db(app):
    with session_scope() as s:
        yield s


def make_list(db, articles, mfr):
    admin = db.scalar(select(User).where(User.username == "admin"))
    pl = PriceList(name="l", source_file="l.xlsx", stored_file="l.xlsx", file_sha256="0" * 64,
                   uploaded_by=admin.id, status="IMPORTIERT")
    db.add(pl)
    db.flush()
    for i, a in enumerate(articles):
        from backend.excel.importer import normalize_article_number
        art = Article(price_list_id=pl.id, source_row=i + 2, article_number=a["nr"],
                      article_number_normalized=normalize_article_number(a["nr"]) if a["nr"] else None,
                      manufacturer_id=mfr.id, description=a.get("desc"), category=a.get("cat"), status="OK")
        db.add(art)
        db.flush()
        for p in a.get("prices", []):
            db.add(ArticlePrice(article_id=art.id, price_type=p[0], amount=D(p[1]), currency=p[2] if len(p) > 2 else "EUR",
                                min_quantity=D(p[3]) if len(p) > 3 and p[3] is not None else None))
    db.flush()
    return pl


def compare(db, old, new, price_type="LISTE", rule_version_id=None, mfr=None):
    admin = db.scalar(select(User).where(User.username == "admin"))
    cmp = Comparison(old_price_list_id=old.id, new_price_list_id=new.id, price_type=price_type,
                     rule_version_id=rule_version_id, quantity=D(1), created_by=admin.id,
                     manufacturer_id=mfr.id if mfr else None)
    db.add(cmp)
    db.flush()
    run_comparison(db, cmp)
    db.flush()
    items = db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id)).all()
    return cmp, {i.article_number: i for i in items}, items


def test_percent_change():
    assert percent_change(D("100"), D("104.50")) == D("4.50")
    assert percent_change(D("3"), D("4")) == D("33.33")
    assert percent_change(D("3"), D("2")) == D("-33.33")


def test_statuses(db):
    m = Manufacturer(name="M", aliases=[])
    db.add(m)
    db.flush()
    old = make_list(db, [
        {"nr": "SAME", "desc": "a", "prices": [("LISTE", "10.00")]},
        {"nr": "UP", "desc": "b", "prices": [("LISTE", "10.00")]},
        {"nr": "DOWN", "desc": "c", "prices": [("LISTE", "10.00")]},
        {"nr": "CHG", "desc": "alt", "prices": [("LISTE", "10.00")]},
        {"nr": "GONE", "desc": "e", "prices": [("LISTE", "1.00")]},
        {"nr": "CUR", "desc": "f", "prices": [("LISTE", "1.00", "CHF")]},
        {"nr": "ZERO", "desc": "g", "prices": [("LISTE", "0")]},
        {"nr": "NOPRICE", "desc": "h", "prices": [("EK", "1")]},
    ], m)
    new = make_list(db, [
        {"nr": "SAME", "desc": "a", "prices": [("LISTE", "10.00")]},
        {"nr": "UP", "desc": "b", "prices": [("LISTE", "10.50")]},
        {"nr": "DOWN", "desc": "c", "prices": [("LISTE", "9.00")]},
        {"nr": "CHG", "desc": "neu", "prices": [("LISTE", "10.00")]},
        {"nr": "NEW", "desc": "x", "prices": [("LISTE", "5.00")]},
        {"nr": "CUR", "desc": "f", "prices": [("LISTE", "1.00", "EUR")]},
        {"nr": "ZERO", "desc": "g", "prices": [("LISTE", "1")]},
        {"nr": "NOPRICE", "desc": "h", "prices": [("LISTE", "1")]},
    ], m)
    cmp, by, items = compare(db, old, new)
    st = {k: v.status for k, v in by.items()}
    assert st == {"SAME": "UNVERAENDERT", "UP": "PREIS_ERHOEHT", "DOWN": "PREIS_GESENKT", "CHG": "ARTIKEL_GEAENDERT",
                  "GONE": "ENTFALLENER_ARTIKEL", "NEW": "NEUER_ARTIKEL", "CUR": "FEHLER", "ZERO": "FEHLER",
                  "NOPRICE": "FEHLER"}
    assert by["UP"].difference == D("0.50") and by["UP"].difference_percent == D("5.00")
    assert by["DOWN"].difference_percent == D("-10.00")
    assert by["CHG"].changed_fields == ["Bezeichnung"]
    assert by["ZERO"].difference == D("1") and by["ZERO"].difference_percent is None
    s = cmp.summary
    assert s["analysiert"] == 9 and s["PREIS_ERHOEHT"] == 1 and s["FEHLER"] == 3


def test_tiers_compared_individually(db):
    m = Manufacturer(name="T", aliases=[])
    db.add(m)
    db.flush()
    old = make_list(db, [{"nr": "A", "prices": [("LISTE", "10", "EUR", 1), ("LISTE", "9", "EUR", 10)]}], m)
    new = make_list(db, [{"nr": "A", "prices": [("LISTE", "11", "EUR", 1), ("LISTE", "8", "EUR", 100)]}], m)
    _, _, items = compare(db, old, new)
    st = sorted((i.min_quantity, i.status) for i in items)
    assert st == [(D(1), "PREIS_ERHOEHT"), (D(10), "NICHT_EINDEUTIG"), (D(100), "NICHT_EINDEUTIG")]


def test_calculated_price_comparison(db):
    m = Manufacturer(name="K", aliases=[])
    db.add(m)
    db.flush()
    admin = db.scalar(select(User).where(User.username == "admin"))
    rule = create_rule(db, "R", None, RuleDefinition.model_validate(
        {"steps": [{"type": "discount", "percent": "15", "base": "start"},
                   {"type": "surcharge", "percent": "4", "base": "current"}]}), admin)
    rv = current_version(db, rule)
    old = make_list(db, [{"nr": "A", "prices": [("LISTE", "100.00")]}], m)
    new = make_list(db, [{"nr": "A", "prices": [("LISTE", "110.00")]}], m)
    _, by, _ = compare(db, old, new, "KALKULIERT", rv.id)
    assert by["A"].old_amount == D("88.40")
    assert by["A"].new_amount == D("97.24")  # 110 - 16,50 = 93,50 + 3,74


def test_unclear_then_confirm_and_reject(db):
    m = Manufacturer(name="U", aliases=[])
    db.add(m)
    db.flush()
    old = make_list(db, [{"nr": "ABC-1000", "desc": "Schraube M6", "prices": [("LISTE", "1")]}], m)
    new = make_list(db, [{"nr": "ABC-1001", "desc": "Schraube M6", "prices": [("LISTE", "2")]}], m)
    cmp, by, items = compare(db, old, new)
    assert [i.status for i in items] == ["NICHT_EINDEUTIG"]
    item = items[0]
    admin = db.scalar(select(User).where(User.username == "admin"))
    decide(db, cmp, item, item.candidates[0]["old_id"], admin.id)
    items = db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id)).all()
    assert [(i.status, i.match_method) for i in items] == [("PREIS_ERHOEHT", "BESTAETIGT")]
    # Bestätigung wird in neuen Vergleichen wiederverwendet
    _, _, items2 = compare(db, old, new)
    assert items2[0].match_method == "BESTAETIGT"


def test_reject_makes_new_and_gone(db):
    m = Manufacturer(name="R", aliases=[])
    db.add(m)
    db.flush()
    old = make_list(db, [{"nr": "ABC-1000", "desc": "Schraube M6", "prices": [("LISTE", "1")]}], m)
    new = make_list(db, [{"nr": "ABC-1001", "desc": "Schraube M6", "prices": [("LISTE", "2")]}], m)
    cmp, _, items = compare(db, old, new)
    admin = db.scalar(select(User).where(User.username == "admin"))
    decide(db, cmp, items[0], None, admin.id)
    items = db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp.id)).all()
    assert sorted(i.status for i in items) == ["ENTFALLENER_ARTIKEL", "NEUER_ARTIKEL"]


def test_duplicate_cannot_be_decided(db):
    m = Manufacturer(name="D", aliases=[])
    db.add(m)
    db.flush()
    old = make_list(db, [{"nr": "A", "prices": [("LISTE", "1")]}, {"nr": "A", "prices": [("LISTE", "2")]}], m)
    new = make_list(db, [{"nr": "A", "prices": [("LISTE", "1")]}], m)
    cmp, _, items = compare(db, old, new)
    assert items[0].status == "NICHT_EINDEUTIG" and items[0].match_method == "DOPPELT"
    admin = db.scalar(select(User).where(User.username == "admin"))
    with pytest.raises(ValueError):
        decide(db, cmp, items[0], items[0].candidates[0]["old_id"], admin.id)


def test_rule_versions_immutable(db):
    from sqlalchemy.exc import DatabaseError
    admin = db.scalar(select(User).where(User.username == "admin"))
    rule = create_rule(db, "R", None, RuleDefinition.model_validate({"steps": [{"type": "fixed", "amount": "1"}]}), admin)
    rv = current_version(db, rule)
    rv.comment = "geändert"
    with pytest.raises(DatabaseError, match="unveraenderlich"):
        db.flush()
    db.rollback()
