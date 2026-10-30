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
MAX_SPEC_ROWS_AUTO = 8  # mehr Zeilen sprengen das Blatt; der Rest steht im Bericht

HEADING_SPEC = re.compile(r"TECHNISCHE\s+DATEN|TECHNICAL\s+DATA|SPEZIFIKATION|SPECIFICATION|KENNDATEN|DATENBLATT", re.I)
HEADING_ARTICLES = re.compile(r"ARTIKEL|BESTELL|ORDER|TYPEN|VARIANTEN|AUSF[ÜU]HRUNGEN|PART\s*NO", re.I)
HEADING_TEXT = re.compile(r"ANWENDUNG|BESCHREIBUNG|PRODUKT|VORTEIL|EIGENSCHAFT|DESCRIPTION|FEATURE|ALLGEMEIN|EINSATZ", re.I)
ACCESSORY = re.compile(r"^(ZUBEH[ÖO]R|ACCESSOR)", re.I)
ARTNR = re.compile(r"^(?=.*\d)[A-Za-z0-9][A-Za-z0-9.\-/]{2,24}$")
SKIP_LINE = re.compile(r"^(www\.|http|fon|fax|tel|e-?mail|seite|page)\b", re.I)

# Technische Daten -> benannte Eigenschaften des Baukastens (die stehen gedruckt oben in der Spezifikation)
PROPERTY_SYNONYMS = {
    "Spannung": ("spannungsbereich", "betriebsspannung", "nennspannung", "spannung", "voltage", "supply voltage"),
    "LED-Farbe": ("leuchtfarbe", "lichtfarbe", "led-farbe", "farbe der led", "light colour", "light color", "colour", "color"),
    "Anzahl LEDs": ("anzahl leds", "anzahl led", "led anzahl", "number of leds", "leds"),
    "Schutzart": ("schutzart", "schutzklasse", "ip-schutz", "protection", "ip rating", "wasserdicht"),
    "Zulassung": ("zulassung", "zulassungen", "approval", "homologation", "prüfzeichen"),
    "Montage": ("montage", "befestigung", "mounting", "installation"),
    "Garantie": ("garantie", "gewährleistung", "warranty"),
}
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
           "protection class": "Schutzart", "approval": "Zulassung", "mounting": "Montage", "warranty": "Garantie"}


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
        texts = [p.extract_text(extraction_mode="layout") or "" for p in pages]
    except PdfError:
        raise
    except PdfReadError as exc:
        raise PdfError(f"Das PDF ist beschädigt: {exc}") from None
    except Exception as exc:  # noqa: BLE001 - fremde Dateien: nie mit Stacktrace abbrechen
        raise PdfError(f"Das PDF kann nicht gelesen werden ({exc.__class__.__name__})") from None
    return reader, pages, texts


def _is_heading(line: str) -> bool:
    s = line.strip()
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 4 or len(s) > 60 or re.search(r"\s{3,}", s) or s.endswith((".", ",", ":")):
        return False
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
            if not line.strip() or SKIP_LINE.match(line.strip()):
                out[-1][1].append("")
                continue
            if _is_heading(line):
                out.append((_clean_heading(line), []))
            else:
                out[-1][1].append(line.rstrip())
    return [(h, lines) for h, lines in out if h or any(x.strip() for x in lines)]


BULLET = re.compile(r"^[•▪●◦■\-–*]\s+")


def _bullets(lines: list[str]) -> list[str]:
    return [re.sub(r"\s+", " ", BULLET.sub("", l.strip())) for l in lines if BULLET.match(l.strip())]


def _join_lines(lines: list[str]) -> list[str]:
    """Fließtext-Absätze: Zeilen verbinden, Silbentrennung am Zeilenende auflösen (Aufzählungen: _bullets)."""
    paras, cur = [], ""
    for line in lines + [""]:
        s = re.sub(r"\s+", " ", line.strip())
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
            nxt = first[i + 1] if i + 1 < len(first) else ""
            if nxt.startswith("(") or (nxt and _is_heading(nxt) and len(nxt) <= 30 and not HEADING_SPEC.search(nxt)
                                        and not HEADING_TEXT.search(nxt)):
                sub = nxt.strip("()")
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


def parse_spec(lines: list[str]) -> list[tuple[str, str]]:
    """Technische Daten: Merkmal links, Wert(e) rechts. Mehrere Spaltenköpfe (z. B. 12 V / 24 V) werden als
    „12 V DC: …“ untereinander geschrieben, Folgezeilen an den Wert der Spalte angehängt."""
    rows: list[list] = []  # [Merkmal, {Spalte: Text} oder Text]
    label_end, centers, heads = None, [], []
    for line in lines:
        cells = _cells(line)
        if not cells:
            continue
        first = cells[0]
        if label_end is None and first[0] > 20 and len(cells) >= 2 and not rows:
            heads, centers = [c[2] for c in cells], [(c[0] + c[1]) / 2 for c in cells]
            continue
        indented = first[0] > (label_end if label_end is not None else 20)
        if not indented and len(cells) >= 2:
            label_end = max(label_end or 0, first[1] + 2)
            values = {}
            for c in cells[1:]:
                col = None if _spans_all(c, centers) else _column_of(c, centers)
                values.setdefault(col, []).append(c[2])
            rows.append([first[2], values])
        elif rows:
            for c in cells:
                col = None if _spans_all(c, centers) else _column_of(c, centers)
                target = rows[-1][1]
                if col not in target and None in target and len(target) == 1:
                    col = None
                target.setdefault(col, []).append(c[2])
    out = []
    def join(parts: list[str]) -> str:  # Folgezeile mit Großbuchstaben = eigene Angabe, sonst Zeilenumbruch im Wort
        out = ""
        for part in parts:
            out = part if not out else out + ("\n" if part[:1].isupper() and not out.endswith((",", "-")) else " ") + part
        return out

    for label, values in rows:
        label = re.sub(r"\s+", " ", label).strip(" :")
        if None in values or not heads:
            text = join([v for vs in values.values() for v in vs])
        else:
            parts = [(heads[k] if k is not None and k < len(heads) else "", " ".join(v)) for k, v in sorted(
                values.items(), key=lambda kv: -1 if kv[0] is None else kv[0])]
            uniq = {p[1] for p in parts}
            text = parts[0][1] if len(uniq) == 1 else "\n".join(f"{h}: {v}" if h else v for h, v in parts)
        text = re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"[ \t]+", " ", text)).strip()
        text = re.sub(r"(?<=[a-zäöü])-\n(?=[a-zäöü])", "", text)
        if label and text and text != "/":
            out.append((label, text))
    return out


def _is_list(lines: list[str]) -> bool:
    """Liste „Nummer – Beschreibung“ (statt Matrix): Zeilen beginnen mit einer Artikelnummer."""
    starts = [_cells(l)[0][2] for l in lines if _cells(l)]
    return sum(1 for t in starts if ARTNR.match(t)) >= max(2, len(starts) // 4)


def _parse_list(lines: list[str], groups: list[dict]) -> None:
    """Nummer links, Beschreibung rechts – auch über mehrere Zeilen oberhalb/unterhalb der Nummer verteilt.
    Jede Beschreibungszeile gehört zur nächstgelegenen Nummer (bei Gleichstand zur vorherigen)."""
    anchors, loose = [], []
    for i, line in enumerate(lines):
        cells = _cells(line)
        if not cells:
            continue
        if ARTNR.match(cells[0][2]):
            anchors.append([i, cells[0][2], [c[2] for c in cells[1:] if c[2] not in "●•○"]])
        elif len(cells) == 1 and cells[0][0] < 12 and not anchors:
            _new_group(groups, cells[0][2])
        elif not re.fullmatch(r"(Artikel|Art\.?-?Nr\.?|Beschreibung|Description|Item)(\s.*)?", cells[0][2], re.I):
            loose.append((i, " ".join(c[2] for c in cells)))
    for i, text in loose:
        if not anchors:
            break
        nearest = min(anchors, key=lambda a: (abs(a[0] - i), a[0] > i))
        (nearest[2].insert(0, text) if i < nearest[0] else nearest[2].append(text))
    for _i, nr, parts in anchors:
        groups[-1]["zeilen"].append((nr, re.sub(r"\s+", " ", " ".join(parts)).strip(" ,")))


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
        rows = [r for r in g["zeilen"] if not (r[0] in seen or seen.add(r[0]))]
        if rows:
            out.append({**g, "zeilen": rows})
    return out


def _new_group(groups: list[dict], title: str) -> None:
    title = re.sub(r"\s+", " ", title).strip(" :")
    if groups[-1]["zeilen"] or groups[-1]["titel"]:
        groups.append({"titel": "", "zubehoer": False, "zeilen": []})
    groups[-1].update(titel=title, zubehoer=bool(ACCESSORY.match(title)))


# ---------- Bilder ----------

def _image_kind(img) -> str | None:
    """'produkt', 'zeichnung', 'foto' oder None (zu klein, Banner)."""
    from PIL import ImageStat

    w, h = img.size
    if min(w, h) < 120 or max(w, h) / min(w, h) > 3.2 or w * h > 4_500_000:
        return None
    rgba = img.convert("RGBA")
    small = rgba.copy()
    small.thumbnail((120, 120))
    if max(ImageStat.Stat(small.convert("L")).stddev[0], 0) < 6:
        return None  # einfarbige Fläche (Hintergrund, Platzhalter)
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


def extract_images(pages) -> dict[str, list]:
    """Bilder je Art, frühe Seiten und größte zuerst. Logos (auf mehreren Seiten) und Kleinkram werden übersprungen."""
    seen: dict[str, int] = {}
    found = []
    for page_no, page in enumerate(pages):
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001 - kaputtes Bild-Objekt: Seite ohne Bilder behandeln
            continue
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
    # Bilder der ersten Seiten zeigen meist das Hauptprodukt: Seite zuerst, dann die größten
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
    low = label.lower()
    for name, words in PROPERTY_SYNONYMS.items():
        if any(low == w or low.startswith(w) for w in words):
            return name
    return None


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
    content["kopf"] = {"titel": titel, "untertitel": untertitel}

    # Technische Daten
    spec_rows: list[tuple[str, str]] = []
    for head, lines in secs:
        if HEADING_SPEC.search(head):
            spec_rows += parse_spec(lines)
    props = {n: "" for n in ds.DEFAULT_PROPERTIES}
    rest = []
    for label, value in spec_rows:
        name = _property_for(label)
        if name and not props.get(name):
            props[name] = value
        else:
            rest.append((SPEC_DE.get(label.lower(), label), value))
    rest.sort(key=lambda r: _spec_rank(r[0]))
    used, dropped = rest[:MAX_SPEC_ROWS_AUTO], rest[MAX_SPEC_ROWS_AUTO:]
    content["eigenschaften"] = [{"name": n, "wert": v[:150], "sichtbar": True} for n, v in props.items()]
    content["spez"] = {"zeichen": [], "zeilen": [{"merkmal": l[:60], "wert": v[:300]} for l, v in used]}
    if dropped:
        report.append("Nicht übernommene Technische Daten (Blatt sonst zu voll): "
                      + "; ".join(f"{l}: {v.replace(chr(10), ' / ')}" for l, v in dropped))
    if not spec_rows:
        report.append("Keine Technischen Daten gefunden – Spezifikation bitte von Hand eintragen.")

    # Beschreibung
    text_secs = [(h, _join_lines(lines)) for h, lines in secs if not HEADING_SPEC.search(h) and not HEADING_ARTICLES.search(h)]
    preferred = [p for h, ps in text_secs if HEADING_TEXT.search(h) for p in ps]
    paragraphs = preferred or [p for _h, ps in text_secs for p in ps]
    description = " ".join(paragraphs[:2])
    bullets = [b for h, lines in secs if not HEADING_SPEC.search(h) and not HEADING_ARTICLES.search(h)
               for b in _bullets(lines)][:6]
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
    content["eigenschaften"] += [{"name": "", "wert": b[:150], "sichtbar": True} for b in bullets]
    if not description:
        report.append("Kein Beschreibungstext gefunden – Einleitung bitte von Hand schreiben.")

    # Artikelnummern
    groups = []
    for head, lines in secs:
        if HEADING_ARTICLES.search(head) and not HEADING_SPEC.search(head):
            zusatz = head.split(" - ", 1)[1] if " - " in head else ""
            groups += parse_articles(lines, zusatz)
    found = total = 0
    blocks = [b for b in content["bloecke"]]
    for g in groups:
        table = ds.new_table(zubehoer=g["zubehoer"])
        table.update(spalten=[], zeilenbilder="klein")  # Herstellerblatt liefert keine Zusatzwerte/Zeilenbilder
        if not g["zubehoer"]:
            table["titel"], table["zusatz"] = "Bestellinformationen", g["titel"]
        rows = []
        for nr, desc in g["zeilen"][:ds.MAX_ROWS]:
            total += 1
            if known_numbers is not None and normalize_article_number(nr) in known_numbers:
                found += 1
            shown = f"{code}{nr}" if code and not nr.upper().startswith(code.upper()) else nr
            rows.append({"bild": None, "artnr": shown[:40], "farbe": ds.guess_color(desc), "beschreibung": desc[:300],
                         "werte": []})
        table["zeilen"] = rows
        blocks.append(table)
    content["bloecke"] = blocks
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
