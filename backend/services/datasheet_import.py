"""Hersteller-Datenblatt (PDF) einlesen und den Datenblatt-Baukasten im Braun-&-Braun-Layout vorbefüllen.

Ablauf: Text seitenweise im Layout-Modus lesen (Spalten bleiben als Abstände erhalten), Abschnitte an Überschriften
in Großbuchstaben erkennen, daraus Titel, Beschreibung, Technische Daten und Artikelnummern ableiten; eingebettete
Bilder als Produktbild, Maßzeichnung oder Anwendungsfoto einordnen. Alles ist ein Vorschlag: der Baukasten bleibt
voll bearbeitbar. Die lokale KI (falls aktiv) formuliert nur den Beschreibungstext; Zahlen und Nummern kommen nie
von der KI, sondern direkt aus der Datei.
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from backend.config import Settings
from backend.excel.importer import normalize_article_number
from backend.services import datasheets as ds
from backend.services.image_cutout import product_png

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 20
MAX_SPEC_ROWS_AUTO = 3  # weitere Daten zusätzlich zu den B&B-Standardzeilen; der Rest steht im Bericht

HEADING_SPEC = re.compile(r"TECHNISCHE\s+DATEN|TECHNICAL\s+DATA|SPEZIFIKATION|SPECIFICATION|KENNDATEN|DATENBLATT", re.I)
HEADING_ARTICLES = re.compile(r"ARTIKEL|BESTELL|ORDER|TYPEN|VARIANTEN|AUSF[ÜU]HRUNGEN|PART\s*NO|^MODELS?$", re.I)
# Englische Abschnittsüberschriften in normaler Schreibweise („Models“, „Flash Patterns“)
HEADING_EN = re.compile(r"^(models?|technical data|technical specifications?|specifications?|features|key features|"
                        r"dimensions|flash patterns?|ordering information|accessories|applications?|description)$", re.I)
HEADING_TEXT = re.compile(r"ANWENDUNG|BESCHREIBUNG|PRODUKT|VORTEIL|EIGENSCHAFT|DESCRIPTION|FEATURE|ALLGEMEIN|EINSATZ", re.I)
ACCESSORY = re.compile(r"^(ZUBEH[ÖO]R|ACCESSOR)", re.I)
ARTNR = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9.\-/]{2,24}\*?$")  # „V11050*“: Stern = Fußnote
FOOTER = re.compile(r"\b(ltd|gmbh|inc|oy|s\.r\.l)\b\.?[ ,:]|www\.|https?://|\bp\.?\s?o\.? box\b|postfach|\bfon\b|\btel\.?\s*[+0-9(]|\bfax\b|@[\w-]+\.\w", re.I)
SKIP_LINE = re.compile(r"^(www\.|http|fon|fax|tel|e-?mail|seite|page)\b", re.I)

# Technische Daten -> Braun-&-Braun-Begriffe in der Reihenfolge der B&B-Datenblätter
# (Spannungsbereich, Lichtleistung, Wasserdicht, Montage, Zulassungen, Gehäuse, Abmessungen, Leuchtbild)
PROPERTY_SYNONYMS = {
    "Spannungsbereich": ("spannungsbereich", "betriebsspannung", "nennspannung", "spannung", "nominale spannung",
                         "eingangsspannung", "voltage", "supply voltage", "operating voltage", "nominal voltage",
                         "voltage (dc)", "input voltage"),
    "Lichtleistung": ("lichtleistung", "lichtstrom", "lichtausbeute", "theoretische lichtausbeute", "luminous flux",
                      "lumen", "light output", "effective lumens", "raw lumens", "actual lumen", "theoretical lumen"),
    "Wasserdicht": ("wasserdicht", "schutzart", "internationale schutzart", "schutzklasse", "ip-schutz", "ip rating",
                    "protection", "ingress", "ip class", "ip-class"),
    "Montage": ("montage", "befestigung", "mounting", "mount", "installation"),
    "Zulassungen": ("zulassung", "zulassungen", "approval", "ece approval", "e-approved", "homologation", "prüfzeichen",
                    "zertifizierung", "emv", "emc"),
    "Gehäuse": ("gehäuse", "material", "housing", "material housing"),
    "Abmessungen": ("abmessung", "abmessungen", "maße", "dimension", "größe", "size"),
    "Leuchtbild": ("leuchtbild", "abstrahlcharakteristik", "beam pattern", "lichtverteilung"),
}
BB_ORDER = list(PROPERTY_SYNONYMS)
# Produktarten im B&B-Sortiment: Einzahl (Artikelbeschreibung) -> Mehrzahl (Titel wie „LED RUNDUMLEUCHTEN“).
# Längere Begriffe zuerst, damit „Arbeitsscheinwerfer“ vor „Scheinwerfer“ gewinnt.
PRODUCT_TYPES = {
    "Arbeitsscheinwerfer": "Arbeitsscheinwerfer", "Rückfahrscheinwerfer": "Rückfahrscheinwerfer",
    "Rundumkennleuchte": "Rundumkennleuchten", "Rundumleuchte": "Rundumleuchten", "Lichtsignalgeber": "Lichtsignalgeber",
    "Leuchtbalken": "Leuchtbalken", "Blitzmodul": "Blitzmodule", "Blitzleuchte": "Blitzleuchten",
    "Frontblitzer": "Frontblitzer", "Kennleuchte": "Kennleuchten", "Warnleuchte": "Warnleuchten",
    "Positionsleuchte": "Positionsleuchten", "Begrenzungsleuchte": "Begrenzungsleuchten",
    "Kennzeichenleuchte": "Kennzeichenleuchten", "Schlussleuchte": "Schlussleuchten", "Rückleuchte": "Rückleuchten",
    "Innenraumleuchte": "Innenraumleuchten", "Umfeldleuchte": "Umfeldleuchten", "Nebelscheinwerfer": "Nebelscheinwerfer",
    "Fernscheinwerfer": "Fernscheinwerfer", "Zusatzscheinwerfer": "Zusatzscheinwerfer", "Scheinwerfer": "Scheinwerfer",
    "Rückfahrkamerasystem": "Rückfahrkamerasysteme", "Kamerasystem": "Kamerasysteme", "Rückfahrkamera": "Rückfahrkameras",
    "Signalsäule": "Signalsäulen", "Sirene": "Sirenen", "Signalhorn": "Signalhörner", "Ampel": "Ampeln",
}
PRODUCT_TYPES_EN = {"work light": "Arbeitsscheinwerfer", "worklight": "Arbeitsscheinwerfer", "work lamp": "Arbeitsscheinwerfer",
                    "reverse light": "Rückfahrscheinwerfer", "reversing lamp": "Rückfahrscheinwerfer",
                    "beacon": "Rundumleuchte", "light bar": "Leuchtbalken", "lightbar": "Leuchtbalken",
                    "reversing light": "Rückfahrscheinwerfer", "flasher": "Blitzleuchte", "strobe": "Blitzleuchte",
                    "camera system": "Kamerasystem", "headlight": "Scheinwerfer", "driving light": "Fernscheinwerfer"}
NO_LED = ("Kamerasystem", "Rückfahrkamerasystem", "Rückfahrkamera", "Sirene", "Signalhorn")
# Wichtige Technische Daten zuerst (Rest kommt in den Bericht, wenn das Blatt sonst zu voll wird)
SPEC_PRIORITY = ("leistung", "power", "lichtstärke", "lichtstrom", "luminous", "abmessung", "dimension", "maße",
                 "gehäuse", "housing", "material", "temperatur", "temperature", "anschluss", "kabel", "connection",
                 "gewicht", "weight", "blitz", "flash", "lichtaustritt", "abstrahl")
# Häufige englische Bezeichnungen der Technischen Daten auf Deutsch
SPEC_DE = {"power": "Leistung", "power consumption": "Leistungsaufnahme", "voltage": "Spannung", "weight": "Gewicht",
           "dimensions": "Abmessungen", "housing": "Gehäuse", "material": "Material", "operating temperature":
           "Betriebstemperatur", "temperature": "Temperatur", "cable length": "Kabellänge", "connection": "Anschluss",
           "luminous intensity": "Lichtstärke", "luminous flux": "Lichtstrom", "light colour": "Lichtfarbe",
           "light color": "Lichtfarbe", "lens colour": "Linsenfarbe", "flash pattern": "Blitzmuster",
           "protection class": "Schutzart", "approval": "Zulassung", "mounting": "Montage", "warranty": "Garantie",
           "consumption": "Leistungsaufnahme", "power consumption (w)": "Leistungsaufnahme",
           "color temperature": "Farbtemperatur", "colour temperature": "Farbtemperatur", "color lens": "Linsenfarbe",
           "colour lens": "Linsenfarbe", "material lens": "Linsenmaterial", "lens material": "Linsenmaterial",
           "functions": "Funktion", "function": "Funktion", "flash rate": "Blitzfrequenz", "fpm": "Blitze/min"}
# Englische Werte -> B&B-Wörter (Reihenfolge zählt: längere Ausdrücke zuerst). Siehe docs/DATENBLATT-REGELN.md.
VALUE_DE = [
    (r"\bflexi(ble)?\s+din\s+pole(\s+mount)?\b", "flexible Rohrmontage"),
    (r"\b(din\s+)?pole\s+mount\b|\bdin\s+pole\b", "Rohrmontage"),
    (r"\b\d?\s*bolt\s+flexi\b", "flexible Fixmontage"),
    (r"\b\d?\s*bolt(\s+conical)?(\s+mount)?\b|\bbolt-on\b|\bpermanent\s+mount\b", "Fixmontage"),
    (r"\bmag(netic)?(\s+\d+)?(\s+mount)?\b", "Magnetmontage"),
    (r"\bsingle\s+bolt\b|\bscrew\s+mount(ing)?\b", "Schraubmontage"),
    (r"\b(DT-?\d{1,2}\s*-?\s*PIN|DT0?\d-\dP|deutsch\s+(DT-?\d+\s*)?connector)\b", "Deutsch Stecker"),
    (r"\b(die-?cast\s+)?alumin(i)?um\b", "Aluminium"),
    (r"\bpolycarbonate\b", "Polycarbonat"),
    (r"\bdouble\s+flash\b", "Doppelblitz"), (r"\btriple\s+flash\b", "Dreifachblitz"),
    (r"\bsingle\s+flash\b", "Einzelblitz"), (r"\bsteady\s+burn\b", "Dauerlicht"), (r"\brotating\b", "Rotation"),
    (r"\bamber\b", "gelb"), (r"\byellow\b", "gelb"), (r"\bclear\b", "klar"), (r"\bred\b", "rot"),
    (r"\bblue\b", "blau"), (r"\bgreen\b", "grün"), (r"\bwhite\b", "weiß"),
    (r"\b(\d+)\s*years?\b", r"\1 Jahre"), (r"\bwork\s*light\b", "Arbeitsscheinwerfer"),
]
NO_VALUE = re.compile(r"^(no|nein|n/?a|-|–|none|keine?)$", re.I)
MEASURED = re.compile(r"actual|effective|gemessen|betrieb|measured|effektiv|tatsächlich", re.I)


@dataclass
class ImportResult:
    content: dict
    report: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class PdfError(ValueError):
    pass


# ---------- Text ----------

def check_pdf(data: bytes) -> None:
    if len(data) > MAX_PDF_BYTES:
        raise PdfError(f"Die Datei ist größer als {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not data.lstrip()[:5] == b"%PDF-":
        raise PdfError("Die Datei ist kein PDF")


def read_pdf(data: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    check_pdf(data)
    try:
        reader = PdfReader(io.BytesIO(data))
        # Viele Herstellerblätter sind nur gegen Bearbeiten geschützt (leeres Öffnen-Passwort): lesen geht
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfError("Das PDF ist mit einem Passwort geschützt und kann nicht gelesen werden")
        pages = reader.pages[:MAX_PAGES]
        texts = [_clean_text(p.extract_text(extraction_mode="layout") or "") for p in pages]
    except PdfError:
        raise
    except PdfReadError as exc:
        raise PdfError(f"Das PDF ist beschädigt: {exc}") from None
    except Exception as exc:  # noqa: BLE001 - fremde Dateien: nie mit Stacktrace abbrechen
        raise PdfError(f"Das PDF kann nicht gelesen werden ({exc.__class__.__name__})") from None
    return reader, pages, texts


GLYPHS = {"hyphen": "-", "endash": "–", "emdash": "—", "bullet": "•", "quoteright": "’", "registered": "®",
          "degree": "°", "multiply": "×"}
SYMBOL_FONT = {"\uf0fc": "✓", "\uf0b7": "•", "\uf0a7": "•", "\uf0d8": "•", "\uf0e0": "→"}


def _clean_text(text: str) -> str:
    """Reste aus Schriften ohne Zeichentabelle: „/hyphen.cap“ -> „-“, Wingdings-Häkchen -> „✓“."""
    text = re.sub(r"/([a-z]+)(?:\.[a-z0-9]+)?", lambda m: GLYPHS.get(m.group(1), m.group(0)), text)
    text = "".join(SYMBOL_FONT.get(ch, ch) for ch in text)
    text = re.sub(r"\bAluminum\b", "Aluminium", text)  # englische Schreibweise in übersetzten Blättern
    return re.sub(r"[\ue000-\uf8ff]", "", text)  # übrige Symbolzeichen (Privatbereich) weglassen


APPROVAL_ONLY = re.compile(r"^((ECE|UN)?[\s-]*R\s*-?\d{1,3}|KLASSE\s*\w+|CLASS\s*\w+|CISPR\s*\d+|E\d+)"
                           r"(\s+((ECE|UN)?[\s-]*R\s*-?\d{1,3}|KLASSE\s*\w+|CISPR\s*\d+))*$", re.I)


def _is_heading(line: str) -> bool:
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4 or len(s) > 60 or re.search(r"\s{3,}", s) or s.endswith((".", ",", ":")):
        return False
    if APPROVAL_ONLY.match(s):
        return False  # Zulassungslogo als Text („ECE-R65 KLASSE 2“), keine Überschrift
    return sum(c.isupper() for c in letters) / len(letters) > .85


def _clean_heading(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip())
    half = len(s) // 2  # manche PDFs schreiben fette Überschriften doppelt: „TITELTITEL“
    if len(s) % 2 == 0 and s[:half] == s[half:]:
        s = s[:half]
    return s


def sections(texts: list[str]) -> list[tuple[str, list[str]]]:
    """[(Überschrift, Zeilen)] in Lesereihenfolge; Text vor der ersten Überschrift unter „“."""
    out: list[tuple[str, list[str]]] = [("", [])]
    for text in texts:
        for line in text.splitlines():
            if not line.strip() or SKIP_LINE.match(line.strip()) or FOOTER.search(line):
                out[-1][1].append("")
                continue
            cells = _cells(line)
            if _is_heading(line) or (len(cells) == 1 and cells[0][0] < 20 and HEADING_EN.match(cells[0][2])):
                out.append((_clean_heading(line), []))
            elif len(cells) >= 2 and all(_is_heading(c[2]) for c in cells):
                out.append((" / ".join(_clean_heading(c[2]) for c in cells), []))  # „ANSCHLUSS   HAUPTMERKMALE“
            else:
                out[-1][1].append(line.rstrip())
    return [(h, lines) for h, lines in out if h or any(x.strip() for x in lines)]


BULLET = re.compile(r"^[•▪●◦■\-–*]\s+")


def _bullets(lines: list[str]) -> list[str]:
    """Aufzählungspunkte; eingerückte Folgezeile ohne Punkt gehört zum vorigen Punkt."""
    out, open_ = [], False
    for line in lines:
        s = line.strip()
        if BULLET.match(s):
            out.append(re.sub(r"\s+", " ", BULLET.sub("", s)))
            open_ = True
        elif open_ and s and line.startswith("  ") and len(_cells(line)) == 1 and len(out[-1]) < 120:
            out[-1] += " " + re.sub(r"\s+", " ", s)
        else:
            open_ = False
    return out


def _join_lines(lines: list[str]) -> list[str]:
    """Fließtext-Absätze: Zeilen verbinden, Silbentrennung am Zeilenende auflösen (Aufzählungen: _bullets)."""
    paras, cur = [], ""
    for line in lines + [""]:
        s = re.sub(r"\s+", " ", line.strip())
        if re.search(r"\S\s{3,}\S", line.strip()):
            first = _cells(line)[0]
            # Tabellenzeile (breite Lücken) – außer langer Text links mit einer rechten Spalte daneben
            s = re.sub(r"\s+", " ", first[2]) if first[0] < 4 and len(first[2]) > 50 else ""
        if not s or BULLET.match(s):
            if cur:
                paras.append(cur)
            cur = ""
            continue
        if cur.endswith("-") and s[:1].islower() and s.split(" ")[0] not in ("und", "oder", "bis", "sowie", "and", "or"):
            cur = cur[:-1] + s
        elif cur:
            cur += " " + s
        else:
            cur = s
    return [p for p in paras if len(p) > 40 and not re.search(r"\s{2,}", p)]


def _title(texts: list[str], meta_title: str | None = None) -> tuple[str, str]:
    """Produktbezeichnung und Serie: erste Überschrift auf Seite 1 (die kein Abschnitt wie „Technische Daten“
    ist), sonst der Titel aus den PDF-Eigenschaften, sonst die erste Zeile. Klammerzusatz bzw. „ - “ = Serie."""
    def plain(text):
        return [re.sub(r"\s+", " ", l.strip()) for l in text.splitlines() if l.strip() and not SKIP_LINE.match(l.strip())]

    first = plain(texts[0] if texts else "")
    title, sub = "", ""
    for i, line in enumerate(first[:12]):
        if _is_heading(line) and not (HEADING_SPEC.search(line) or HEADING_ARTICLES.search(line) or HEADING_TEXT.search(line)):
            title = line
            after = [x for x in first[i + 1:i + 4] if x.lower() != line.lower()]  # doppelte Überschrift überspringen
            nxt = after[0] if after else ""
            if nxt.startswith("(") or (nxt and _is_heading(nxt) and len(nxt) <= 30 and not HEADING_SPEC.search(nxt)
                                        and not HEADING_TEXT.search(nxt)):
                sub = nxt.strip("()")
            elif re.fullmatch(r"[A-Z0-9][A-Z0-9 .\-/+]{0,10}", nxt or "") and any(c.isdigit() for c in nxt):
                title = f"{title} {nxt}"  # Modellnummer in eigener Zeile, z. B. „SCORPIUS GO“ / „410“
            break
    for line in first[:10]:  # „400 Series“ / „Serie Atlas“ in eigener Zeile
        m = re.fullmatch(r"(?:(.{1,20}?)\s+series|(?:serie|series)\s+(.{1,20}))", line, re.I)
        if m and not sub and line.lower() != title.lower():
            sub = "Serie " + (m.group(1) or m.group(2))
            break
    if not title and meta_title:
        title = re.sub(r"\.(indd|docx?|pdf|ai|qxp)$", "", meta_title.strip(), flags=re.I)
    if not title and first:
        title = first[0]
    m = re.match(r"^(.*?)\s*\((.+)\)$", title)
    if m:
        title, sub = m.group(1), sub or m.group(2)
    elif " - " in title:
        title, sub = (x.strip() for x in title.split(" - ", 1))
    elif not sub and re.search(r"\s(Serie|Series)\s", title, re.I):
        title, sub = re.split(r"\s(?=(?:Serie|Series)\s)", title, maxsplit=1, flags=re.I)
    if title.isupper():
        def word(w):
            return "-".join(x if any(c.isdigit() for c in x) or len(x) <= 3 else x.capitalize() for x in w.split("-"))
        title = " ".join(word(w) for w in title.split(" "))
        sub = " ".join(word(w) for w in sub.split(" ")) if sub.isupper() else sub
    return title[:60], sub[:80]


# ---------- Tabellen mit Spalten (Technische Daten, Artikelnummern) ----------

def _cells(line: str) -> list[tuple[int, int, str]]:
    """Zellen einer Layout-Zeile: (Anfang, Ende, Text), getrennt durch mindestens zwei Leerzeichen."""
    return [(m.start(), m.end(), m.group().strip()) for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line)]


def _column_of(cell: tuple[int, int, str], centers: list[float]) -> int | None:
    if not centers:
        return None
    mid = (cell[0] + cell[1]) / 2
    return min(range(len(centers)), key=lambda i: abs(centers[i] - mid))


def _spans_all(cell: tuple[int, int, str], centers: list[float]) -> bool:
    """Ein Wert in der Mitte über alle Spalten (gilt für alle Ausführungen)."""
    if len(centers) < 2:
        return False
    mid = (cell[0] + cell[1]) / 2
    gap = (centers[-1] - centers[0]) / (len(centers) - 1)
    return all(abs(mid - c) > gap * .3 for c in centers) and centers[0] < mid < centers[-1]


def _is_label(text: str) -> bool:
    # „Spannung“, auch „IP-class“, „E-approved“
    return bool(re.match(r"^[A-ZÄÖÜ]([a-zäöüß]|[A-Z]?-[a-zäöüß])", text)) and sum(c.isalpha() for c in text) >= 4


def split_side_by_side(lines: list[str]) -> list[list[str]]:
    """Zwei Tabellen „Merkmal – Wert“ nebeneinander (z. B. Nordic Lights): an der gemeinsamen Anfangsspalte der
    rechten Merkmale teilen und nacheinander lesen. Sonst unverändert."""
    starts: dict[int, int] = {}
    for line in lines:
        cells = _cells(line)
        for k, c in enumerate(cells[1:-1], start=1):  # rechtes Merkmal: nicht erste Zelle, danach noch ein Wert
            if _is_label(c[2]) and c[0] > 30:
                key = round(c[0] / 3)
                starts[key] = starts.get(key, 0) + 1
    if not starts:
        return [lines]
    key, count = max(starts.items(), key=lambda kv: kv[1])
    if count < 3:
        return [lines]
    x = key * 3 - 3
    left = [line[:x].rstrip() for line in lines]
    right = [" " * 2 + line[x:] if len(line) > x else "" for line in lines]
    return [left, right]


def parse_spec(lines: list[str]) -> list[tuple[str, str]]:
    parts = split_side_by_side(lines)
    if len(parts) > 1:
        return [row for part in parts for row in _parse_spec(part)]
    return _parse_spec(lines)


def _parse_spec(lines: list[str]) -> list[tuple[str, str]]:
    """Technische Daten: Merkmal links, Wert(e) rechts. Mehrere Spaltenköpfe (z. B. 12 V / 24 V) werden als
    „12 V DC: …“ untereinander geschrieben. Mehrzeilige Werte gehören zur nächstgelegenen Merkmalszeile – auch
    wenn sie darüber stehen (senkrecht mittig gesetzt). Text weit rechts der Tabelle (Zeichnungen) zählt nicht."""
    label_end, centers, heads = None, [], []
    anchors: list[list] = []  # [Zeile, Merkmal, Zellen]
    loose: list[tuple[int, list]] = []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if not cells:
            continue
        first = cells[0]
        if label_end is None and first[0] > 20 and len(cells) >= 2 and not anchors:
            heads, centers = [c[2] for c in cells], [(c[0] + c[1]) / 2 for c in cells]
            continue
        indented = first[0] > (label_end if label_end is not None else 20)
        if not indented and len(cells) >= 2 and anchors and re.match(r"^[(a-zäöü]", first[2]):
            anchors[-1][1] += " " + first[2]  # zweite Zeile des Merkmals, z. B. „(GS)“
            anchors[-1][2].extend(cells[1:])
        elif not indented and len(cells) >= 2:
            label_end = max(label_end or 0, first[1] + 2)
            anchors.append([i, first[2], list(cells[1:])])
        else:
            loose.append((i, cells))
    anchors = [a for a in anchors if not APPROVAL_ONLY.match(a[1].strip(" :"))]  # Zeile mit Zulassungslogos
    if not anchors:
        return []
    ends = sorted(a[2][0][1] for a in anchors)
    # typischer rechter Tabellenrand (bei Spaltenköpfen die letzte Spalte); Zellen, die weiter rechts beginnen,
    # sind Beschriftungen einer Zeichnung daneben
    right = max([ends[len(ends) // 2]] + [int(c) + 15 for c in centers[-1:]]) + 10
    for a in anchors:
        a[2] = [c for c in a[2] if c[0] <= right] or a[2][:1]
    loose_rows = {i for i, _c in loose}
    for i, cells in loose:
        cells = [c for c in cells if c[0] <= right]
        if label_end is not None and cells and cells[0][1] < label_end and i > anchors[0][0]:
            # zweite Zeile des Merkmals („Eingangsspannungsbereich“ / „(GS)“)
            owner = max((a for a in anchors if a[0] < i), key=lambda a: a[0])
            owner[1] = f"{owner[1]} {cells[0][2]}"
            cells = cells[1:]
        if not cells:
            continue
        before = [a for a in anchors if a[0] < i]
        after = [a for a in anchors if a[0] > i]
        nearest = min(anchors, key=lambda a: (abs(a[0] - i), a[0] > i))
        if before and after and i - before[-1][0] == after[0][0] - i and after[0][0] + (after[0][0] - i) in loose_rows:
            nearest = after[0]  # mittig gesetzter Wert: Zeilen darüber und darunter gehören zur nächsten Zeile
        if i < anchors[0][0] and anchors[0][0] - i > 1:
            continue  # Text über der Tabelle (z. B. Logos), nicht direkt an der ersten Zeile
        if i < nearest[0]:
            nearest[2][:0] = cells
        else:
            nearest[2].extend(cells)
    rows = []
    for _i, label, cells in anchors:
        values: dict = {}
        for c in cells:
            col = None if _spans_all(c, centers) else _column_of(c, centers)
            if col not in values and None in values and len(values) == 1:
                col = None
            values.setdefault(col, []).append(c[2])
        rows.append([label, values])
    out = []
    def join(parts: list[str]) -> str:  # Folgezeile mit Großbuchstaben = eigene Angabe, sonst Zeilenumbruch im Wort
        out = ""
        for part in parts:
            new_line = (part[:1].isupper() and not out.endswith((",", "-"))) or (
                part[:1].isdigit() and re.search(r"\d\s*(V|W|A|K|lm|mm|cm|kg|g|Hz|°C)$", out))
            out = part if not out else out + ("\n" if new_line else " ") + part
        return out

    for label, values in rows:
        label = re.sub(r"\s+", " ", label).strip(" :")
        if None in values or not heads or len(values) == 1:
            text = join([v for vs in values.values() for v in vs])
        else:
            parts = [(heads[k] if k is not None and k < len(heads) else "", " ".join(v)) for k, v in sorted(
                values.items(), key=lambda kv: -1 if kv[0] is None else kv[0])]
            uniq = {p[1] for p in parts}
            text = parts[0][1] if len(uniq) == 1 else "\n".join(f"{h}: {v}" if h else v for h, v in parts)
        text = re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"[ \t]+", " ", text)).strip()
        text = re.sub(r"(?<=\dmm)(?=[A-ZØ])|(?<=\))(?=\d)", "\n", text)  # zusammengeklebt: „64mmL x“, „(Gecko 3)123 x“
        text = re.sub(r"(?<=[a-zäöü])-\n(?=[a-zäöü])", "", text)
        if label and text and text != "/":
            out.append((label, text))
    return out


def _is_list(lines: list[str]) -> bool:
    """Liste „Nummer – Beschreibung“ (statt Matrix): Zeilen beginnen mit einer Artikelnummer."""
    starts = [_cells(l)[0][2] for l in lines if _cells(l)]
    return sum(1 for t in starts if ARTNR.match(t)) >= max(2, len(starts) // 4)


HEAD_WORDS = re.compile(r"^(Artikel|Art\.?-?Nr\.?|Artikelnummer|Bestellnummer|Beschreibung|Bezeichnung|Description|Item|Part)",
                        re.I)


def _parse_list(lines: list[str], groups: list[dict]) -> None:
    """Nummer links, Beschreibung rechts – auch über mehrere Zeilen oberhalb/unterhalb der Nummer verteilt.
    Jede Beschreibungszeile gehört zur nächstgelegenen Nummer (bei Gleichstand zur vorherigen). Weitere Spalten
    der Kopfzeile rechts der Beschreibung (z. B. Länge, Zulassung) werden Zusatzspalten."""
    anchors, loose = [], []
    extra, extra_centers, desc_end = [], [], None
    attrs, attr_end = [], None  # Kopfzeile nur mit Merkmalen („PART NO. VOLTAGE FPM MOUNT“), ohne Beschreibung
    for i, line in enumerate(lines):
        cells = _cells(line)
        if not cells:
            continue
        if ARTNR.match(cells[0][2]):
            anchors.append([i, cells[0][2].rstrip("*"), [c for c in cells[1:] if c[2] not in "●•○"]])
        elif HEAD_WORDS.match(cells[0][2]) and len(cells) >= 2 and not anchors:
            heads = cells[2:] if HEAD_WORDS.match(cells[1][2]) else cells[1:]
            if cells[0][2].isupper() and not HEAD_WORDS.match(cells[1][2]):
                attrs = [c for c in heads if c[2].isupper()][:6]  # klein Geschriebenes rechts: Bildbeschriftung
                attr_end = attrs[-1][1] + 8 if attrs else None
            elif len(cells) >= 3 and HEAD_WORDS.match(cells[1][2]):
                desc_end = (cells[1][1] + cells[2][0]) / 2
                extra = [c[2] for c in heads][:ds.MAX_COLUMNS]
                extra_centers = [(c[0] + c[1]) / 2 for c in heads][:ds.MAX_COLUMNS]
        elif len(cells) == 1 and cells[0][0] < 12 and not anchors:
            _new_group(groups, cells[0][2])
        elif not HEAD_WORDS.match(cells[0][2]):
            loose.append((i, cells))
    for i, cells in loose:
        if not anchors:
            break
        nearest = min(anchors, key=lambda a: (abs(a[0] - i), a[0] > i))
        nearest[2][:0] = cells if i < nearest[0] else []
        if i > nearest[0]:
            nearest[2].extend(cells)
    groups[-1]["spalten"] = extra
    if attrs:
        centers = [(c[0] + c[1]) / 2 for c in attrs]
        table = {c[2]: [] for c in attrs}
        for _i, nr, cells in anchors:
            values = [""] * len(attrs)
            for c in cells:
                if c[0] <= attr_end:
                    k = _column_of(c, centers)
                    values[k] = f"{values[k]} {c[2]}".strip()
            for c, v in zip(attrs, values):
                table[c[2]].append(v)
            # Beschreibung aus den Merkmalen; reine Zahlen ohne Einheit (z. B. Blitze/min) weglassen
            desc = ", ".join(translate_value(v) for v in values if v and not re.fullmatch(r"[\d.,]+", v))
            groups[-1]["zeilen"].append((nr, desc, []))
        groups[-1]["attrs"] = table
        return
    for _i, nr, cells in anchors:
        desc, values = [], [""] * len(extra)
        for c in cells:
            if extra and desc_end is not None and c[0] > desc_end:
                k = _column_of(c, extra_centers)
                values[k] = f"{values[k]} {c[2]}".strip()
            else:
                desc.append(c[2])
        groups[-1]["zeilen"].append((nr, re.sub(r"\s+", " ", " ".join(desc)).strip(" ,"), values))


def parse_articles(lines: list[str], title: str = "") -> list[dict]:
    """Artikelnummern: entweder Liste (Nummer + Beschreibung) oder Matrix (Ausführung × Spalten wie 12 V / 24 V).
    Liefert Gruppen [{titel, zubehoer, zeilen: [(Artikelnummer, Beschreibung)]}]."""
    groups = [{"titel": title, "zubehoer": bool(ACCESSORY.match(title)), "zeilen": []}]
    if _is_list(lines):
        _parse_list(lines, groups)
        lines = []
    heads, centers = [], []
    for line in lines:
        cells = _cells(line)
        if not cells:
            continue
        texts = [c[2] for c in cells]
        numbers = [c for c in cells[1:] if ARTNR.match(c[2])]
        header_like = not numbers and not ARTNR.match(texts[0]) and (len(cells) >= 3 or cells[0][0] > 20)
        if header_like and len(cells) >= 2:
            # Kopfzeile mit Spaltenbezeichnungen (evtl. mit Gruppenname davor)
            if cells[0][0] < 20:
                _new_group(groups, texts[0])
                cells, texts = cells[1:], texts[1:]
            heads, centers = texts, [(c[0] + c[1]) / 2 for c in cells]
            continue
        if len(cells) == 1 and not ARTNR.match(texts[0]):
            _new_group(groups, texts[0])
            continue
        if not numbers and ARTNR.match(texts[0]) and len(texts) >= 2:
            groups[-1]["zeilen"].append((texts[0], " ".join(texts[1:])))  # einzelne Zeile „Nummer – Beschreibung“
            continue
        if not numbers:
            continue  # z. B. „LED blau – auf Anfrage“
        label = texts[0]
        by_number: dict[str, list[str]] = {}
        for c in numbers:
            col = _column_of(c, centers)
            by_number.setdefault(c[2], []).append(heads[col] if col is not None and col < len(heads) else "")
        for nr, cols in by_number.items():
            cols = [h for h in cols if h]
            if len(by_number) == 1 or not cols:
                groups[-1]["zeilen"].append((nr, label))
            else:
                groups[-1]["zeilen"].append((nr, f"{label}, {' / '.join(cols)}"))
    seen, out = set(), []
    for g in groups:
        rows = [r if len(r) == 3 else (*r, []) for r in g["zeilen"] if not (r[0] in seen or seen.add(r[0]))]
        if rows:
            out.append({**g, "zeilen": rows, "spalten": g.get("spalten") or []})
    return out


def _new_group(groups: list[dict], title: str) -> None:
    title = re.sub(r"\s+", " ", title).strip(" :")
    if groups[-1]["zeilen"] or groups[-1]["titel"]:
        groups.append({"titel": "", "zubehoer": False, "zeilen": []})
    groups[-1].update(titel=title, zubehoer=bool(ACCESSORY.match(title)))


# ---------- Bilder ----------

def _image_kind(img) -> str | None:
    """'produkt', 'zeichnung', 'foto' oder None (zu klein, Banner)."""
    from PIL import Image, ImageStat

    w, h = img.size
    if min(w, h) < 120 or max(w, h) / min(w, h) > 3.2 or w * h > 4_500_000:
        return None
    rgba = img.convert("RGBA")
    small = rgba.copy()
    small.thumbnail((120, 120))
    if ImageStat.Stat(small.convert("L")).stddev[0] < 6:
        # Farbe einheitlich: Fläche/Schattenmaske – oder schwarze Strichzeichnung, deren Form nur im Alphakanal steckt
        return "zeichnung" if _line_art(rgba) else None
    sw, sh = small.size
    px = small.load()
    border = [px[x, y] for x in range(sw) for y in (0, sh - 1)] + [px[x, y] for y in range(sh) for x in (0, sw - 1)]
    transparent = sum(1 for p in border if p[3] < 30) / len(border)
    white = sum(1 for p in border if p[3] >= 30 and min(p[:3]) > 228) / len(border)
    if transparent < .6 and white < .8:
        return "foto"
    hsv = small.convert("RGB").convert("HSV")
    mask = small.getchannel("A").point(lambda a: 255 if a > 30 else 0)
    if not mask.getbbox():
        return None
    saturation = ImageStat.Stat(hsv.getchannel("S"), mask).mean[0]
    opaque = [p for p in small.getdata() if p[3] > 30]
    paper = sum(1 for p in opaque if min(p[:3]) > 225) / len(opaque)
    # Maßzeichnung: farblos und überwiegend weißes Papier mit dünnen Linien
    return "zeichnung" if saturation < 18 and paper > .6 else "produkt"


def _line_art(rgba) -> bool:
    """Freigestellte Strichzeichnung: wenige deckende Pixel innerhalb der Umrissfläche (volle Auflösung,
    Verkleinern verschmiert die Linien). Gefüllte Silhouetten/Flächen decken ihren Umriss weitgehend."""
    alpha = rgba.getchannel("A")
    box = alpha.point(lambda a: 255 if a > 30 else 0).getbbox()
    if not box:
        return False
    hist = alpha.crop(box).histogram()
    return sum(hist[31:]) / ((box[2] - box[0]) * (box[3] - box[1])) < .2


def _drawn_names(page) -> set[str] | None:
    """Namen der Bilder, die der Seiteninhalt zeichnet („/I2 Do“); None, wenn nicht feststellbar
    (z. B. Bilder in Formularobjekten) – dann zählen alle Bilder der Seite."""
    try:
        contents = page.get_contents()
        data = contents.get_data() if contents is not None else b""
    except Exception:  # noqa: BLE001
        return None
    names = {m.decode("latin-1") for m in re.findall(rb"/([^\s/<>\[\]()]+)\s+Do\b", data)}
    try:
        xobjects = page["/Resources"]["/XObject"]
        forms = [n.lstrip("/") for n, o in xobjects.items() if o.get_object().get("/Subtype") == "/Form"]
    except Exception:  # noqa: BLE001
        forms = []
    if not names or any(f in names for f in forms):
        return None
    return names


def extract_images(pages) -> dict[str, list]:
    """Bilder je Art, frühe Seiten und größte zuerst. Logos (auf mehreren Seiten) und Kleinkram werden übersprungen."""
    seen: dict[str, int] = {}
    found = []
    for page_no, page in enumerate(pages):
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001 - kaputtes Bild-Objekt: Seite ohne Bilder behandeln
            continue
        drawn = _drawn_names(page)
        if drawn is not None:  # manche PDF-Ersteller hängen alle Bilder an jede Seite: nur gezeichnete zählen
            images = [im for im in images if im.name.rsplit(".", 1)[0].lstrip("/") in drawn]
        for im in images:
            try:
                img = im.image
            except Exception:  # noqa: BLE001
                continue
            if img is None:
                continue
            if img.mode == "CMYK":
                img = img.convert("RGB")
            key = hashlib.sha1(img.tobytes()[:65536] + bytes(str(img.size), "ascii")).hexdigest()
            if key in seen:
                if seen[key] != page_no:
                    seen[key] = -1  # auf mehreren Seiten: Logo/Deko
                continue
            seen[key] = page_no
            found.append((key, page_no, img))
    out: dict[str, list] = {"produkt": [], "zeichnung": [], "foto": []}
    for key, page_no, img in found:
        if seen.get(key) == -1:
            continue
        kind = _image_kind(img)
        if kind:
            out[kind].append((page_no, img))
    # Produktbilder nur von der ersten Seite mit Produktbild: spätere freigestellte Grafiken sind meist
    # Lichtverteilungen, Stecker oder Zubehör. Sonst: Seite zuerst, dann die größten.
    if out["produkt"]:
        first = min(pn for pn, _i in out["produkt"])
        out["produkt"] = [(pn, i) for pn, i in out["produkt"] if pn == first]
    return {k: [img for _p, img in sorted(v, key=lambda x: (x[0], -(x[1].size[0] * x[1].size[1])))]
            for k, v in out.items()}


def _store(settings: Settings, sheet_id: int, img, product: bool) -> str:
    folder = ds.image_dir(settings, sheet_id)
    folder.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    buf = io.BytesIO()
    if product:
        if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 30:
            img.save(buf, "PNG", optimize=True)  # schon freigestellt
            data = buf.getvalue()
        else:
            img.convert("RGB").save(buf, "PNG")
            data, _ = product_png(buf.getvalue())
        name = f"{token}.png"
    else:
        if img.mode in ("RGBA", "LA", "P"):  # Transparenz auf Weiß, sonst wird sie im JPG schwarz
            from PIL import Image

            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            img = flat
        img.convert("RGB").save(buf, "JPEG", quality=88)
        data, name = buf.getvalue(), f"{token}.jpg"
    (folder / name).write_bytes(data)
    return name


# ---------- Zusammenbauen ----------

def _property_for(label: str) -> str | None:
    """B&B-Begriff für ein Merkmal: ganzes Wort am Anfang oder als eigenes Wort („Nominale Spannung (GS)“,
    „Montage / Befestigung“ ja; „Gehäusefarben“ nein)."""
    low = re.sub(r"\s+", " ", label.lower().strip(" :"))
    if re.search(r"lens|linse|streuscheibe|lux\b|temperat", low):
        return None  # „Material lens“, „Color temperature“: eigene Zeilen, kein B&B-Standardbegriff
    for name, words in PROPERTY_SYNONYMS.items():
        if any(low == w or re.match(re.escape(w) + r"\b", low) or re.search(r"(^|[\s/(])" + re.escape(w) + r"\b", low)
               for w in words):
            return name
    return None


def translate_value(value: str) -> str:
    """Englische Werte in B&B-Wörter (VALUE_DE); unbekannte Wörter bleiben stehen."""
    for pattern, repl in VALUE_DE:
        value = re.sub(pattern, repl, value, flags=re.I)
    return value


def _thousands(m: re.Match) -> str:
    return f"{int(m.group()):,}".replace(",", ".")


def bb_value(name: str, value: str) -> str:
    """Wert in B&B-Schreibweise: Einheit ohne Leerzeichen („10-30V“, „1.520lm“), „IP67, IP69k“, „ECE-R10“."""
    value = translate_value(value.strip())
    if NO_VALUE.match(value):
        return ""
    value = re.sub(r"(\d)\s+(V|W|A|mm|cm|kg|lm|K|Hz)\b", r"\1\2", value)
    if name == "Spannungsbereich":
        value = re.sub(r"\s*\(?\bDC\b\)?", "", value)
        value = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", value)
    elif name == "Lichtleistung":
        value = re.sub(r"(?<![\d.,])\d{4,6}(?![\d.,])", _thousands, value)
    elif name == "Wasserdicht":
        value = re.sub(r"\bIP\s+(\d)", r"IP\1", value)
        parts = [x for x in re.split(r"\s*(?:/|,|&|\+|\bund\b|\band\b)\s*", value) if x]
        if parts and all(re.match(r"^(IP)?\d", x, re.I) for x in parts):
            value = ", ".join(x if x.upper().startswith("IP") else f"IP{x}" for x in parts)
            value = re.sub(r"\b(IP\d\d)K\b", r"\1k", value)  # „IP69k“ wie bei B&B, „IP6K9K“ bleibt
    elif name == "Zulassungen":
        value = re.sub(r"(?<![A-Za-z])(?:ECE|UN)?[\s-]*R\s?-?(\d{1,3})(?:\.\d+)?\b", r" ECE-R\1", value).strip()
        value = re.sub(r"\s+", " ", value).replace(" ,", ",")
    elif name == "Gehäuse":
        value = re.sub(r"\b(Polycarbonat|PC|plastic|nylon|ABS)\b", "Kunststoff", value, flags=re.I)
    elif name == "Leuchtbild":
        value = re.sub(r"\s+beam\b", "", value, flags=re.I)
    return value


def join_mounts(mounts: list[str]) -> str:
    """„Fixmontage, Magnetmontage, flexible Rohrmontage“ -> „Fix-, Magnet-, flexible Rohrmontage“ (wie bei B&B)."""
    mounts = sorted(dict.fromkeys(m for m in mounts if m), key=lambda m: m.startswith("flexible"))
    if len(mounts) < 2 or not all(m.endswith("montage") for m in mounts):
        return ", ".join(mounts)
    return ", ".join(m[:-len("montage")] + "-" for m in mounts[:-1]) + ", " + mounts[-1]


def with_product_type(product: str, desc: str) -> str:
    """Artikelart vor die Beschreibung, wie im B&B-Standard („LED Rundumleuchte, Rotation, gelb, …“):
    „LED rot, 12 V DC“ wird zu „LED-Lichtsignalgeber, rot, 12 V DC“. Wörter der Beschreibung, die schon in der
    Artikelart stehen (hier „LED“), entfallen; steht die Art schon vorne, bleibt alles wie es ist."""
    product = product.strip()
    if not product or not desc:
        return desc
    if desc.lower().startswith(product.lower()[:max(6, len(product) - 2)]):
        return desc  # Mehrzahl/Einzahl („Rundumleuchten“/„Rundumleuchte“) gilt als gleich
    known = {w.lower() for w in re.split(r"[\s\-/]+", product) if w}
    words = desc.split(" ")
    while words and words[0].strip(",").lower() in known:
        words.pop(0)
    rest = " ".join(words).lstrip(", ")
    return f"{product}, {rest}" if rest else product


def product_type(title: str, text: str) -> str | None:
    """Produktart (Einzahl, deutsch) aus Titel, sonst aus dem Text (häufigste Nennung)."""
    def find(hay: str) -> dict[str, int]:
        hay = hay.lower()
        counts: dict[str, int] = {}
        for word in PRODUCT_TYPES:  # längere zuerst: Treffer aus dem Text entfernen
            n = len(re.findall(word.lower(), hay))
            if n:
                counts[word] = n
                hay = hay.replace(word.lower(), " ")
        for en, de in PRODUCT_TYPES_EN.items():
            n = len(re.findall(r"\b" + en + r"s?\b", hay))
            if n:
                counts[de] = counts.get(de, 0) + n
        return counts

    for hay in (title, text):
        counts = find(hay)
        if counts:
            kind = max(counts, key=lambda k: (counts[k], len(k)))
            # B&B: nur blitzend, ohne rotierendes Leuchtbild = Blitzleuchte
            if kind == "Rundumleuchte" and re.search(r"\bbeacon", hay, re.I) \
                    and re.search(r"flash|blitz|\bfpm\b|strobe", text, re.I) and not re.search(r"rotat|rotier", text, re.I):
                kind = "Blitzleuchte"
            return kind
    return None


def series_name(text: str) -> str:
    """Serienname ohne Produktart, Leistung, Spannung und Doppelungen: „Unity Work Light 31W“ -> „Unity“,
    „Beacons 400 Series“ -> „400“."""
    s = re.sub(r"\s+", " ", text)
    for en in PRODUCT_TYPES_EN:
        s = re.sub(r"\b" + en + r"s?\b", " ", s, flags=re.I)
    for de, plural in PRODUCT_TYPES.items():
        s = re.sub(r"\b(" + re.escape(plural) + "|" + re.escape(de) + r")\b", " ", s, flags=re.I)
    s = re.sub(r"\b((wide\s+)?(flood|spot|combo|pencil)(\s+beam)?|LED|R\d{2,3}|\d+(\.\d+)?\s?W|\d+\s?-\s?\d+\s?V( DC)?|serie|series)\b|[|]", " ", s, flags=re.I)
    words = s.split()
    half = len(words) // 2  # „Unity Unity“ (Überschrift doppelt im PDF)
    if half and len(words) % 2 == 0 and [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
        words = words[:half]
    return " ".join(words).strip(" -,")


def numbers_in_text(text: str) -> list[tuple[str, str]]:
    """Artikelnummern im Fließtext einer Zelle: „Wide Flood (36-48 V): 988-208B, Flood (12-24 V): 988-202B“."""
    flat = re.sub(r"\s+", " ", text)
    out = []
    for m in re.finditer(r"([^:,]{2,60}?):\s*([A-Za-z0-9][\w.\-/]*\d[\w.\-/]*)", flat):
        out.append((m.group(2), m.group(1).strip(" ,")))
    return out


def _spec_rank(label: str) -> int:
    low = label.lower()
    return next((i for i, w in enumerate(SPEC_PRIORITY) if w in low), len(SPEC_PRIORITY))


def _sentences(text: str, limit: int) -> str:
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out) + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out[:limit + 200]


def build(data: bytes, settings: Settings, sheet_id: int, code: str | None = None,
          known_numbers: set[str] | None = None, ai=None, progress=None) -> ImportResult:
    """Baukasten-Inhalt aus einem Hersteller-PDF. code: Kürzel des Herstellers (vor die Artikelnummern),
    known_numbers: normalisierte Nummern der aktuellen Liste (für den Bericht), ai: KI-Anbieter oder None."""
    def step(msg):
        if progress:
            progress(msg)

    step("PDF lesen")
    reader, pages, texts = read_pdf(data)
    if not any(t.strip() for t in texts):
        raise PdfError("Im PDF steht kein lesbarer Text (eingescannt?). Bitte ein PDF mit echtem Text verwenden.")
    secs = sections(texts)
    report: list[str] = []
    content = ds.empty_content()
    meta = getattr(reader.metadata, "title", None) if reader.metadata else None
    titel, untertitel = _title(texts, meta if isinstance(meta, str) else None)
    # Produktart wie bei B&B in den Titel („LED Arbeitsscheinwerfer“), Produktname wird die Serie
    alltext = "\n".join(texts)
    kind = product_type(titel, alltext)
    led = kind not in NO_LED and bool(re.search(r"\bLED|\blm\b|lumen", alltext, re.I))
    named = kind and (kind.lower() in titel.lower()
                      or any(len(w) >= 5 and w.lower() in kind.lower() for w in re.findall(r"[\w-]+", titel)))
    if kind and not named:
        series = series_name(" ".join(x for x in (titel, untertitel) if x))
        untertitel = f"Serie {series}" if series else ""
        titel = ("LED " if led else "") + PRODUCT_TYPES.get(kind, kind)
    article_kind = titel if not kind or named else ("LED " if led else "") + kind
    content["kopf"] = {"titel": titel[:60], "untertitel": untertitel[:80]}

    # Technische Daten
    spec_rows: list[tuple[str, str]] = []
    for head, lines in secs:
        if HEADING_SPEC.search(head):
            spec_rows += parse_spec(lines)
    if not spec_rows:  # Datentabelle ohne Überschrift (z. B. Strands): Zeilen „Merkmal  Wert“ mit bekannten Merkmalen
        for head, lines in secs:
            known = [i for i, l in enumerate(lines) if len(_cells(l)) >= 2
                     and (_property_for(_cells(l)[0][2]) or _cells(l)[0][2].lower() in SPEC_DE)]
            if len(known) >= 3:
                spec_rows += parse_spec([l for l in lines[known[0]:known[-1] + 1] if len(_cells(l)) >= 2])
    props = {n: "" for n in BB_ORDER}
    rest, warranty, numbered, measured = [], "", [], ""
    for label, value in spec_rows:
        name = _property_for(label)
        if re.match(r"(artikel|art\.?-?nr|bestell|part\s*n|order)", label, re.I):
            numbered += numbers_in_text(value)  # „Wide Flood (36-48 V): 988-208B, …“
        elif re.match(r"garantie|gewährleistung|warranty", label, re.I):
            warranty = warranty or translate_value(value)
        elif NO_VALUE.match(value.strip()):
            continue  # „E-approved: No“
        elif name == "Lichtleistung" and MEASURED.search(label):
            measured = measured or value  # B&B: theoretischer Wert, gemessener in Klammern
        elif name and not props.get(name):
            props[name] = value
        else:
            rest.append((SPEC_DE.get(re.sub(r"\s+", " ", label.lower()), label), bb_value("", value)))
    props = {n: bb_value(n, v) if v else "" for n, v in props.items()}
    if measured:
        measured = bb_value("Lichtleistung", measured)
        props["Lichtleistung"] = (f"{props['Lichtleistung']} ({measured} gemessen)" if props["Lichtleistung"]
                                  else f"{measured} gemessen")
    if not props["Zulassungen"]:  # Zulassung nur im Text („ECE R65 Approved“, „R65 LED Beacons“)
        found_r = re.findall(r"\bECE[\s-]*R\s?-?(\d{1,3})\b|\bR(\d{2,3})\s+(?:LED|approved|approval)", alltext, re.I)
        props["Zulassungen"] = ", ".join(dict.fromkeys(f"ECE-R{a or b}" for a, b in found_r))
    rest.sort(key=lambda r: _spec_rank(r[0]))
    used, dropped = rest[:MAX_SPEC_ROWS_AUTO], rest[MAX_SPEC_ROWS_AUTO:]
    # B&B-Standardzeilen immer anlegen (leer = nicht gedruckt), Lichtleistung/Leuchtbild nur wenn vorhanden
    content["eigenschaften"] = [{"name": n, "wert": v[:150], "sichtbar": True} for n, v in props.items()
                                if v or n in ds.DEFAULT_PROPERTIES]
    content["spez"] = {"zeichen": [], "zeilen": [{"merkmal": l[:60], "wert": v[:300]} for l, v in used]}
    if dropped:
        report.append("Nicht übernommene Technische Daten (Blatt sonst zu voll): "
                      + "; ".join(f"{l}: {v.replace(chr(10), ' / ')}" for l, v in dropped))
    if not spec_rows and not any(props.values()):
        report.append("Keine Technischen Daten gefunden – Spezifikation bitte von Hand eintragen.")

    # Beschreibung
    text_secs = [(h, _join_lines(lines)) for h, lines in secs
                 if not HEADING_SPEC.search(h) and not HEADING_ARTICLES.search(h) and not _is_list(lines)]
    disclaimer = re.compile(r"nicht alle produkte|änderungen (und irrtümer )?vorbehalten|nominalwerte|irrtümer|"
                            r"subject to change|all rights reserved", re.I)
    text_secs = [(h, [p for p in ps if not disclaimer.search(p)]) for h, ps in text_secs]
    preferred = [p for h, ps in text_secs if HEADING_TEXT.search(h) for p in ps]
    paragraphs = preferred or [p for _h, ps in text_secs for p in ps]
    description = " ".join(paragraphs[:2])
    description = re.sub(r"\s*read more\s*$|\s*mehr lesen\s*$", "", description, flags=re.I)
    description = re.sub(r"(?<=[.!?])[^.!?]*…\s*$", "", description).strip()  # „… from 10…“ (gekürzt im PDF)
    bullets = [b for h, lines in secs if not HEADING_SPEC.search(h) and not HEADING_ARTICLES.search(h)
               for b in _bullets(lines)][:6]
    for h, lines in secs:  # „HAUPTMERKMALE“ u. ä.: kurze Zeilen sind Stichpunkte, auch ohne Aufzählungszeichen
        if re.search(r"MERKMAL|FEATURE|HIGHLIGHT|VORTEIL|BENEFIT", h, re.I) and not bullets:
            short = [re.sub(r"\s+", " ", l.strip()) for l in lines if l.strip() and len(_cells(l)) == 1]
            if short and all(len(x) <= 80 and not x.endswith(".") for x in short):
                bullets = short[:6]
    other_texts = [p for _h, ps in text_secs for p in ps if p not in paragraphs[:2]]
    if ai is not None and description:
        step("Beschreibung mit der KI formulieren")
        try:
            suggestion = ai.datasheet_text(titel, description, other_texts[:4])
            content["einleitung"] = suggestion.beschreibung.strip()
            bullets = bullets or [b.strip() for b in suggestion.punkte if b.strip()][:4]
        except Exception as exc:  # noqa: BLE001 - KI ist optional: ohne sie gekürzter Originaltext
            report.append(f"KI nicht verwendet ({exc.__class__.__name__}) – Beschreibung ist gekürzter Originaltext.")
            content["einleitung"] = _sentences(description, 450)
    else:
        content["einleitung"] = _sentences(description, 450)
    extras = dict(rest)
    cable = ""
    if extras.get("Kabellänge"):
        mm = re.match(r"(\d+)\s*mm$", extras["Kabellänge"])
        cable = f"{int(mm.group(1)) // 10}cm Anschlusskabel" if mm and int(mm.group(1)) % 10 == 0 else \
            f"{extras['Kabellänge']} Anschlusskabel"
        if "Deutsch Stecker" in extras.get("Anschluss", ""):
            cable += " mit Deutsch Stecker"
        if not any("kabel" in b.lower() for b in bullets):
            bullets.append(cable)  # B&B: „52cm Anschlusskabel mit Deutsch Stecker“
    if warranty and not any("garantie" in b.lower() for b in bullets):
        bullets.insert(0, f"{warranty} Garantie")  # B&B: „2 Jahre Garantie“ als erster Punkt
    content["eigenschaften"] += [{"name": "", "wert": b[:150], "sichtbar": True} for b in bullets]
    if not description:
        report.append("Kein Beschreibungstext gefunden – Einleitung bitte von Hand schreiben.")

    # Artikelnummern
    groups = []
    for head, lines in secs:
        if HEADING_SPEC.search(head):
            continue
        named = HEADING_ARTICLES.search(head)
        if named or _is_list(lines):
            if named:
                split = re.split(r"\s*[-–]\s+", head, maxsplit=1)
                zusatz = split[1] if len(split) == 2 else ""
            else:
                zusatz = head  # z. B. „GECKO 3 - HORIZONTALE MONTAGE“
            groups += parse_articles(lines, zusatz)
    # Merkmalsspalten der Modelltabelle füllen leere B&B-Zeilen („VOLTAGE“ -> Spannungsbereich, „MOUNT“ -> Montage)
    filled = {}
    for g in groups:
        for head, values in g.get("attrs", {}).items():
            name = _property_for(head)
            if name and not props.get(name):
                vals = list(dict.fromkeys(bb_value(name, v) for v in values if v))
                filled[name] = join_mounts(vals) if name == "Montage" else ", ".join(vals)
    if filled:
        props.update(filled)
        for e in content["eigenschaften"]:
            if e["name"] in filled:
                e["wert"] = filled[e["name"]][:150]
    if not groups and not numbered:  # Blatt für ein Modell: „Part No. 809237“
        m = re.search(r"\b(?:part\s*no\.?|art(?:ikel)?\.?\s*-?\s*nr\.?)\s*:?\s*([A-Z0-9][\w\-./]{2,24})", texts[0], re.I)
        if m:
            watt = re.search(r"\b(\d+(?:[.,]\d+)?)\s?W\b", " ".join(texts[0].splitlines()[:6]))
            parts = ["mit " + cable.replace(" mit ", " & ") if cable else "", props["Spannungsbereich"],
                     f"{watt.group(1)}W" if watt else ""]
            groups.append({"titel": "", "zubehoer": False, "spalten": [],
                           "zeilen": [(m.group(1), ", ".join(x for x in parts if x), [])]})
    if numbered:
        groups.insert(0, {"titel": "", "zubehoer": False, "spalten": [],
                          "zeilen": [(nr, f"{article_kind} {content['kopf']['untertitel'].removeprefix('Serie ')}, {label}", [])
                                     for nr, label in numbered]})
    found = total = 0
    blocks = [b for b in content["bloecke"]]
    for g in groups:
        table = ds.new_table(zubehoer=g["zubehoer"])
        table.update(spalten=[], zeilenbilder="klein")  # Herstellerblatt liefert keine Zusatzwerte/Zeilenbilder
        if not g["zubehoer"]:
            table["titel"], table["zusatz"] = "Bestellinformationen", g["titel"]
        rows = []
        table["spalten"] = g["spalten"]
        for nr, desc, werte in g["zeilen"][:ds.MAX_ROWS]:
            total += 1
            if known_numbers is not None and normalize_article_number(nr) in known_numbers:
                found += 1
            shown = f"{code}{nr}" if code and not nr.upper().startswith(code.upper()) else nr
            desc = translate_value(desc)
            if not g["zubehoer"]:
                desc = with_product_type(article_kind, desc)
            rows.append({"bild": None, "artnr": shown[:40], "farbe": ds.guess_color(desc), "beschreibung": desc[:300],
                         "werte": [w[:80] for w in werte]})
        table["zeilen"] = rows
        blocks.append(table)
    content["bloecke"] = blocks
    m = re.search(r"\s+((?:tri|dual|bi|multi)[- ]?colou?r)$", content["kopf"]["untertitel"], re.I)
    multi = [r["farbe"] for b in blocks if b.get("typ") == "tabelle" for r in b["zeilen"] if "/" in r["farbe"]]
    if m:
        content["kopf"]["untertitel"] = content["kopf"]["untertitel"][:m.start()]
        content["spez"]["zusatz"] = m.group(1)
        farben = (max(set(multi), key=multi.count) if multi else "").split("/")
        light = [f for f in farben if f in ("klar", "weiss")]
        if len(farben) == 3 and len(light) == 1:  # wie im B&B-Muster: hell in der Mitte („TRI CO LOUR“)
            rest = [f for f in farben if f not in light]
            farben = [rest[0], light[0], rest[1]]
        content["spez"]["zusatz_farben"] = "/".join(f for f in farben if f)
    if not groups:
        report.append("Keine Artikelnummern gefunden – Artikeltabelle bitte von Hand füllen oder aus Excel einfügen.")
    elif known_numbers is not None:
        report.append(f"{found} von {total} Artikelnummern stehen in eurer aktuellen Preisliste des Herstellers.")
    if any(r["artnr"].endswith(("-x", "-X")) for b in blocks if b.get("typ") == "tabelle" for r in b["zeilen"]):
        report.append("Einige Artikelnummern enden auf „-x“ (Platzhalter des Herstellers für eine Variante) – bitte prüfen.")

    # Bilder
    step("Bilder einordnen")
    imgs = extract_images(pages)
    content["bilder_oben"] = [_store(settings, sheet_id, i, True) for i in imgs["produkt"][:2]]
    content["zeichnungen"] = [_store(settings, sheet_id, i, False) for i in imgs["zeichnung"][:2]]
    content["bilder_unten"] = [_store(settings, sheet_id, i, False) for i in imgs["foto"][:2]]
    if not content["bilder_oben"]:
        report.append("Kein freigestelltes Produktbild gefunden – Produktbilder bitte hochladen.")
    extra = sum(max(0, len(v) - 2) for v in imgs.values())
    if extra:
        report.append(f"{extra} weitere Bilder im PDF wurden nicht übernommen (je Platz höchstens 2).")
    stats = {"seiten": len(pages), "technische_daten": len(spec_rows), "artikel": total, "bilder":
             sum(len(content[k]) for k in ("bilder_oben", "zeichnungen", "bilder_unten"))}
    return ImportResult(content=content, report=report, stats=stats)


def save_pdf(settings: Settings, sheet_id: int, data: bytes) -> Path:
    folder = ds.image_dir(settings, sheet_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "hersteller.pdf"
    path.write_bytes(data)
    return path
