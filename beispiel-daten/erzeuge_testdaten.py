"""Erzeugt realistische Testlisten für fiktive Hersteller (deterministisch, gleiche Ausgabe bei jedem Lauf).

Pro Hersteller: unsere EK/VK-Liste (Vorjahr, Nummern mit unserem Kürzel) und die neue Liste des Herstellers
(Nummern ohne unser Kürzel, eigenes Layout). Szenarien:
- Raphi LED (RA): EK-Liste mit Titelzeilen, Preiserhöhungen, fehlende/neue Artikel, eine geänderte Nummer,
  zusätzlich eine Teilliste (Preiserhöhung Arbeitsscheinwerfer).
- Nordlicht Signaltechnik (NS): Hersteller liefert UVP, Händlerrabatt 35 %, ein Preis "auf Anfrage".
- Svensk Ljus AB (SL): Liste in SEK, englische Überschriften, Kurs 0,095.

Aufruf: python beispiel-daten/erzeuge_testdaten.py
"""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

OUT = Path(__file__).resolve().parent
CENT = Decimal("0.01")
FONT = "Arial"


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def write(path: Path, sheet: str, header: list[str], rows: list[list], title: list[str] | None = None,
          money_cols: tuple[int, ...] = ()) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for line in title or []:
        ws.append([line])
        ws.cell(ws.max_row, 1).font = Font(name=FONT, bold=True, size=13 if ws.max_row == 1 else 10)
    if title:
        ws.append([])
    ws.append(header)
    hr = ws.max_row
    for c in ws[hr]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in row])
        for i, c in enumerate(ws[ws.max_row]):
            c.font = Font(name=FONT)
            if i in money_cols and isinstance(c.value, float):
                c.number_format = "#,##0.00"
    for i, w in enumerate([18, 42, 14, 14, 14], start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(hr + 1, 1)
    wb.save(path)


# ---------- Raphi LED (RA) ----------

def raphi() -> None:
    src = openpyxl.load_workbook(OUT / "RaphiLED_Preisliste_2026.xlsx", data_only=True)["Preisliste 2026"]
    ours = [(r[0], r[1], Decimal(str(r[2]))) for r in src.iter_rows(min_row=2, values_only=True)]
    rnd = random.Random(27)
    missing = {"RARK20", "RAZB3"}           # beim Hersteller entfallen
    big = {"RALEUCHTBALKEN3", "RAAS300", "RABL3"}  # +15 % -> Prüfung
    renamed = {"RAAS500": "AS500-B"}         # Hersteller hat die Nummer geändert
    rows = []
    for nr, desc, ek in ours:
        if nr in missing:
            continue
        factor = Decimal("1.15") if nr in big else Decimal(rnd.choice(["1.03", "1.04", "1.05", "1.02", "1.00"]))
        number = renamed.get(nr, nr[2:])    # Hersteller kennt unser Kürzel nicht
        rows.append([number, desc, money(ek * factor)])
    rows += [["LED6", "LED-Modul 48V 20W (NEU 2027)", Decimal("88.40")],
             ["AS600", "Arbeitsscheinwerfer 8000 lm (NEU 2027)", Decimal("214.00")],
             ["ZB6", "Montagewinkel Aluminium (NEU 2027)", Decimal("6.90")]]
    write(OUT / "RaphiLED_Herstellerliste_2027.xlsx", "Preise 2027", ["Art.-Nr.", "Bezeichnung", "Ihr EK netto"],
          rows, title=["Raphi LED GmbH – Händlerpreisliste 2027", "Gültig ab 01.01.2027 · alle Preise netto in EUR"],
          money_cols=(2,))
    # Preiserhöhung unterm Jahr: nur Arbeitsscheinwerfer +6 %
    part = [[nr[2:], desc, money(ek * Decimal("1.06"))] for nr, desc, ek in ours if nr.startswith("RAAS")
            and nr != "RAAS500"]
    write(OUT / "RaphiLED_Preiserhoehung_Arbeitsscheinwerfer.xlsx", "Preiserhöhung",
          ["Artikelnummer", "Bezeichnung", "EK neu"], part,
          title=["Raphi LED – Preiserhöhung Serie Arbeitsscheinwerfer", "gültig ab 01.07.2027"], money_cols=(2,))


# ---------- Nordlicht Signaltechnik (NS): UVP-Liste ----------

NS_ITEMS = [
    ("10100", "Signalsäule 2-stufig rot/grün"), ("10101", "Signalsäule 3-stufig rot/gelb/grün"),
    ("10102", "Signalsäule 4-stufig mit Summer"), ("10200", "Blitzleuchte Xenon rot"),
    ("10201", "Blitzleuchte LED orange"), ("10300", "Sirene 105 dB"), ("10301", "Sirene mit Blitz 110 dB"),
    ("10400", "Ampel 2-flammig LED"), ("10401", "Ampel 3-flammig LED"), ("10500", "Hupe 24V Industrie"),
    ("10600", "Warnleuchte Ex-geschützt"), ("10601", "Warnleuchte IP69K"), ("10700", "Rundumleuchte Spiegel"),
    ("10800", "Signalgeber Mehrton"), ("10900", "Montagesockel Signalsäule"), ("10901", "Wandhalter Signalsäule"),
    ("11000", "Steuerung Ampel Zeitrelais"), ("11100", "Ersatzglocke rot"), ("11101", "Ersatzglocke grün"),
    ("11200", "Kabel 5 m M12"),
]


def nordlicht() -> None:
    rnd = random.Random(11)
    ours_rows, new_rows = [], []
    for nr, desc in NS_ITEMS:
        uvp_old = money(Decimal(rnd.randint(1500, 90000)) / 100)
        ek_old = money(uvp_old * Decimal("0.65"))     # 35 % Händlerrabatt
        vk_old = money(ek_old * Decimal("1.8"))
        ours_rows.append([f"NS{nr}", desc, ek_old, vk_old])
        uvp_new = money(uvp_old * Decimal(rnd.choice(["1.04", "1.05", "1.06"])))
        new_rows.append([nr, desc, uvp_new])
    new_rows[7][2] = "auf Anfrage"                     # kein Preis -> Fehler, alter Preis bleibt
    write(OUT / "Nordlicht_unsere_Liste_2026.xlsx", "Nordlicht", ["Artikelnummer", "Bezeichnung", "EK", "VK"],
          ours_rows, money_cols=(2, 3))
    write(OUT / "Nordlicht_UVP_2027.xlsx", "UVP 2027", ["Artikel", "Beschreibung", "UVP"], new_rows,
          title=["Nordlicht Signaltechnik – Unverbindliche Preisempfehlung 2027"], money_cols=(2,))


# ---------- Svensk Ljus AB (SL): Liste in SEK ----------

SL_ITEMS = [
    ("FL-100", "Floodlight 1000 lm"), ("FL-200", "Floodlight 2000 lm"), ("FL-400", "Floodlight 4000 lm"),
    ("WL-10", "Work light compact"), ("WL-20", "Work light wide"), ("BL-1", "Beacon amber magnetic"),
    ("BL-2", "Beacon amber bolt"), ("LB-30", "Light bar 30 cm"), ("LB-60", "Light bar 60 cm"),
    ("LB-90", "Light bar 90 cm"), ("RL-1", "Reversing light"), ("IL-1", "Interior light 300 mm"),
]


def svensk() -> None:
    rnd = random.Random(5)
    ours_rows, new_rows = [], []
    for nr, desc in SL_ITEMS:
        sek_old = Decimal(rnd.randint(300, 9000))
        ek_old = money(sek_old * Decimal("0.095"))
        ours_rows.append([f"SL{nr}", desc, ek_old, money(ek_old * Decimal("2.4"))])
        new_rows.append([nr, desc, money(sek_old * Decimal(rnd.choice(["1.02", "1.03", "1.04"])))])
    write(OUT / "SvenskLjus_unsere_Liste_2026.xlsx", "Svensk Ljus", ["Artikelnummer", "Bezeichnung", "EK", "VK"],
          ours_rows, money_cols=(2, 3))
    write(OUT / "SvenskLjus_Pricelist_2027_SEK.xlsx", "Pricelist", ["Item no.", "Description", "Net price SEK"],
          new_rows, title=["Svensk Ljus AB – Dealer price list 2027", "All prices in SEK, excl. VAT"],
          money_cols=(2,))


if __name__ == "__main__":
    raphi()
    nordlicht()
    svensk()
    print("Testdaten erzeugt in", OUT)
