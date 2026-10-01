import zipfile

import openpyxl.xml
import pytest

from backend.excel.reader import ExcelRejected, check_file, read_sheet
from tests.conftest import make_xlsx, strip_formula_cache

LIMIT = 300 * 1024 * 1024


def test_defusedxml_active():
    assert openpyxl.xml.DEFUSEDXML


def test_valid_xlsx_passes(tmp_path):
    p = make_xlsx(tmp_path / "a.xlsx", [["Art.-Nr.", "Preis"], ["A1", 1]])
    check_file(p, "a.xlsx", LIMIT, 5000)


@pytest.mark.parametrize("name", ["liste.xls", "liste.xlsm", "liste.xlsb", "liste.csv"])
def test_rejected_extensions(tmp_path, name):
    p = make_xlsx(tmp_path / "a.xlsx", [["x"]])
    with pytest.raises(ExcelRejected):
        check_file(p, name, LIMIT, 5000)


def test_ole_file_renamed_to_xlsx_rejected(tmp_path):
    p = tmp_path / "alt.xlsx"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)
    with pytest.raises(ExcelRejected, match=".xls"):
        check_file(p, "alt.xlsx", LIMIT, 5000)


def test_macro_content_in_xlsx_rejected(tmp_path):
    p = make_xlsx(tmp_path / "m.xlsx", [["x"]])
    with zipfile.ZipFile(p, "a") as zf:
        zf.writestr("xl/vbaProject.bin", b"fake")
    with pytest.raises(ExcelRejected, match="Makros"):
        check_file(p, "m.xlsx", LIMIT, 5000)


def test_broken_file_rejected(tmp_path):
    p = tmp_path / "kaputt.xlsx"
    p.write_bytes(b"PK\x03\x04" + b"kaputt" * 50)
    with pytest.raises(ExcelRejected):
        check_file(p, "kaputt.xlsx", LIMIT, 5000)


def test_random_bytes_rejected(tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"hallo welt")
    with pytest.raises(ExcelRejected):
        check_file(p, "x.xlsx", LIMIT, 5000)


def test_zip_bomb_rejected(tmp_path):
    p = make_xlsx(tmp_path / "b.xlsx", [["x"]])
    with zipfile.ZipFile(p, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/media/gross.bin", b"\0" * (5 * 1024 * 1024))
    with pytest.raises(ExcelRejected, match="zu groß"):
        check_file(p, "b.xlsx", 2 * 1024 * 1024, 5000)


def test_formula_values_are_not_evaluated_and_missing_cache_detected(tmp_path):
    p = make_xlsx(tmp_path / "f.xlsx", [["Art.-Nr.", "Preis"], ["A1", "=1+1"], ["A2", '=HYPERLINK("http://x")']])
    strip_formula_cache(p)
    sheet = read_sheet(p)
    # Formeln werden nie als Code behandelt: ohne gespeicherten Wert kommt None
    assert sheet.rows[1][1] is None
    assert (2, 2) in sheet.formula_without_cache
    assert (3, 2) in sheet.formula_without_cache


def test_formula_text_is_kept_as_text(tmp_path):
    # Ein Text, der wie eine Formel aussieht, bleibt Text
    p = make_xlsx(tmp_path / "t.xlsx", [["Bezeichnung"], ["x"]])
    import openpyxl
    wb = openpyxl.load_workbook(p)
    wb.active["A2"].value = "=cmd|' /C calc'!A0"
    wb.active["A2"].data_type = "s"
    wb.save(p)
    sheet = read_sheet(p)
    assert sheet.rows[1][0] == "=cmd|' /C calc'!A0"


def test_merged_cells_and_multiple_sheets(tmp_path):
    p = make_xlsx(tmp_path / "m.xlsx", [["Preise 2026", None], ["Art.-Nr.", "EK"]], merged=["A1:B1"],
                  extra_sheets={"Zweites": [["x"]]})
    sheet = read_sheet(p, "Preise")
    assert (1, 1, 1, 2) in sheet.merged
    assert read_sheet(p, "Zweites").rows == [["x"]]
    with pytest.raises(ExcelRejected):
        read_sheet(p, "gibtsnicht")
