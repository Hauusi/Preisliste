from backend.config import PROJECT_ROOT
from backend.excel.columns import detect_columns, load_synonyms, match_label, suggest_manufacturer
from backend.excel.reader import read_sheet
from tests.conftest import make_xlsx

SYN = load_synonyms(PROJECT_ROOT / "config")


def detect(tmp_path, rows, **kw):
    p = make_xlsx(tmp_path / "l.xlsx", rows, merged=kw.pop("merged", ()))
    return detect_columns(read_sheet(p), SYN, **kw), read_sheet(p)


def test_label_normalization():
    assert match_label("Art.-Nr.", SYN)[0] == ("article_number", 1.0)
    assert match_label("ARTIKEL NR", SYN)[0] == ("article_number", 1.0)
    assert match_label("Einkaufspreis netto", SYN)[0][0] == "supplier_price"
    assert match_label("Gültig ab", SYN)[0][0] == "valid_from"
    assert match_label("Hersteller-Art.-Nr.", SYN)[0] == ("article_number", 1.0)
    assert match_label("Foo", SYN) == []


def test_simple_layout(tmp_path):
    det, _ = detect(tmp_path, [
        ["Art.-Nr.", "Bezeichnung", "EK", "UVP"],
        ["A-1", "Schraube", "1,50", "2,99"],
        ["A-2", "Mutter", "0,20", "0,49"],
    ])
    assert det.header_row == 1
    assert det.mapping() == {"article_number": 0, "description": 1, "supplier_price": 2, "rrp": 3}
    assert det.decimal_separators[2] == ","


def test_header_not_in_first_row(tmp_path):
    det, _ = detect(tmp_path, [
        ["Firma Muster GmbH – Preisliste 2026"],
        [],
        ["Stand: 01.01.2026"],
        ["Artikelnummer", "Produktname", "Listenpreis", "Warengruppe"],
        ["100", "Teil", 12.5, "G1"],
    ])
    assert det.header_row == 4
    assert det.mapping() == {"article_number": 0, "description": 1, "list_price": 2, "category": 3}


def test_two_row_header_with_merged_group(tmp_path):
    det, _ = detect(tmp_path, [
        ["Artikel", None, "Preise", None],
        ["Nr.", "Bezeichnung", "EK", "Liste"],
        ["X1", "Teil", 1, 2],
    ], merged=["A1:B1", "C1:D1"])
    assert det.header_row == 2 and det.header_rows == 2
    m = det.mapping()
    assert m["article_number"] == 0
    assert m["supplier_price"] == 2
    assert m["list_price"] == 3


def test_heuristic_without_known_headers(tmp_path):
    det, _ = detect(tmp_path, [
        ["Code", "Text", "Betrag"],
        ["AB-100", "Teil eins", "12,50"],
        ["AB-101", "Teil zwei", "13,50"],
        ["AB-102", "Teil drei", "14,50"],
    ])
    m = det.mapping()
    assert m["article_number"] == 0
    assert m["list_price"] == 2
    srcs = {c.field: c.source for c in det.columns if c.field}
    assert srcs["article_number"] == "heuristik"


def test_duplicate_equal_match_is_not_assigned(tmp_path):
    det, _ = detect(tmp_path, [["Art.-Nr.", "EK", "EK"], ["1", 1, 2]])
    assert "supplier_price" not in det.mapping()
    assert any(c.note for c in det.columns)


def test_no_header_found(tmp_path):
    det, _ = detect(tmp_path, [[1, 2], [3, 4]])
    assert det.columns == [] and det.notes


def test_manual_header_override(tmp_path):
    det, _ = detect(tmp_path, [["Art.-Nr.", "EK"], ["Nr", "Preis"], ["1", 2]], header_row=2)
    assert det.header_row == 2


def test_manufacturer_suggestion(tmp_path):
    p = make_xlsx(tmp_path / "l.xlsx", [["ACME Werkzeuge Preisliste"], ["Art.-Nr.", "EK"], ["1", 2]])
    sheet = read_sheet(p)
    known = [(1, "ACME", ["Acme GmbH"]), (2, "Bosch", [])]
    assert suggest_manufacturer(known, "liste.xlsx", sheet, 2) == 1
    assert suggest_manufacturer(known, "bosch_acme.xlsx", sheet, 2) is None
