"""Datenblätter: festes Firmenlayout (Kopf- und Fußzeile), Inhalt aus verschiebbaren Bausteinen.

Bausteine: Einleitung (Eigenschaften + Produktbilder), Spezifikationen (+ Zulassungslogos, Maßzeichnungen),
Anwendungsbilder, Artikel (Gruppen), Zubehör. Reihenfolge, „neue Seite“ und „ausblenden“ je Baustein.
Der Editor schickt den ganzen Inhalt als JSON; sanitize() prüft und begrenzt alles, bevor es gespeichert wird.
Bilder liegen als Dateien unter uploads/datenblatt/<id>/ (damit in der Sicherung enthalten), im JSON steht nur
der Dateiname.
"""

from __future__ import annotations

import re
import secrets
import shutil
import time
from datetime import date
from pathlib import Path

from backend.config import Settings

# Fußzeile ist fest (Design immer gleich), nur die Version kommt vom Benutzer
FOOTER = {
    "firma": "Braun & Braun GmbH",
    "web": "www.braun-braun.at",
    "mail": "office@braun-braun.at",
    "tel": "Tel. 0043 1 370 45 37",
    "hinweis": "Preise exkl. MwSt. Technische Irrtümer und Änderungen vorbehalten.",
}

# Bausteine zwischen Kopf- und Fußzeile (die beiden sind fest). Einleitung, Spezifikation und Anwendungsbilder gibt es
# genau einmal; Tabellen (Artikel, Zubehör) und freie Bilder beliebig oft, in beliebiger Reihenfolge.
BLOCKS = {"intro": "Einleitung: Text, Eigenschaften, Produktbilder", "spez": "Spezifikationen", "anwendung": "Anwendungsbilder",
          "tabelle": "Tabelle", "bild": "Bild"}
SINGLE_BLOCKS = ("intro", "spez", "anwendung")
MAX_BLOCKS = 40
IMAGE_HEIGHTS = {"S": ("klein", 25), "M": ("mittel", 45), "L": ("groß", 75)}
ROW_IMAGES = {"klein": "klein (Artikelliste)", "gross": "groß (Zubehör)"}
GROUP_IMAGE_POS = {"links": "links neben der Tabelle", "oben": "über der Tabelle"}


def new_table(titel: str = "", zubehoer: bool = False) -> dict:
    """Leere Tabelle; Zubehör: Überschrift „Zubehör“, große Zeilenbilder, eigene Seite wie im Muster Gecko."""
    return {"typ": "tabelle", "neue_seite": False, "sichtbar": True, "titel": titel or ("Zubehör" if zubehoer else ""),
            "zusatz": "", "bild": None, "bild_pos": "links", "zeilenbilder": "gross" if zubehoer else "klein",
            "spalten": [] if zubehoer else list(DEFAULT_COLUMNS), "zeilen": []}


def new_image_block() -> dict:
    return {"typ": "bild", "neue_seite": False, "sichtbar": True, "bild": None, "hoehe": "M"}


DEFAULT_BLOCKS = [{"typ": "intro", "neue_seite": False, "sichtbar": True},
                  {"typ": "spez", "neue_seite": False, "sichtbar": True},
                  {"typ": "anwendung", "neue_seite": False, "sichtbar": True}]

COLORS = {"": "keine", "gelb": "gelb", "blau": "blau", "rot": "rot", "gruen": "grün", "weiss": "weiß", "klar": "klar"}
COLOR_WORDS = {"gelb": "gelb", "amber": "gelb", "orange": "gelb", "blau": "blau", "blue": "blau", "rot": "rot",
               "red": "rot", "grün": "gruen", "gruen": "gruen", "green": "gruen", "weiß": "weiss", "weiss": "weiss",
               "white": "weiss", "klar": "klar", "clear": "klar"}
DEFAULT_COLUMNS = ["Zulassung", "Montage"]


# Vorbelegte Eigenschaften (nur Wert eintragen); je Produkt ein-/ausblenden, verschieben, eigene ergänzen
DEFAULT_PROPERTIES = ["Spannung", "LED-Farbe", "Anzahl LEDs", "Schutzart", "Zulassung", "Montage", "Garantie"]
# Vorschläge beim Hinzufügen
PROPERTY_SUGGESTIONS = ["Länge", "Breite", "Höhe", "Leistung", "Lichtstrom", "Abstrahlwinkel", "Blitzfunktionen",
                        "Synchronisierbar", "Gehäuse", "Material", "Gewicht", "Kabellänge", "Betriebstemperatur",
                        "Stromaufnahme", "Linse", "Farbtemperatur"]

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PROPERTIES, MAX_SPEC_ROWS, MAX_COLUMNS = 25, 20, 3
MAX_ROWS = 80
IMAGE_SLOTS = {"bilder_oben": 2, "zeichnungen": 2, "bilder_unten": 2}
IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
# Nicht mehr verwendete Bilder erst löschen, wenn sie so alt sind: ein gerade hochgeladenes Bild ist evtl. noch
# nicht im gespeicherten Inhalt (Speichern und Hochladen laufen im Editor unabhängig voneinander)
UNUSED_IMAGE_GRACE_SECONDS = 600


class ImageError(ValueError):
    pass


def empty_content() -> dict:
    return {
        "kopf": {"titel": "", "untertitel": ""},
        "einleitung": "",
        "eigenschaften": [{"name": n, "wert": "", "sichtbar": True} for n in DEFAULT_PROPERTIES],
        "bilder_oben": [],
        "spez": {"zeichen": [], "zeilen": []},
        "zeichnungen": [],
        "bilder_unten": [],
        "fuss": {"version": date.today().strftime("%d%m%Y")},
        "bloecke": [dict(b) for b in DEFAULT_BLOCKS],
    }


def normalized(content: dict | None) -> dict:
    """Fehlende Schlüssel mit Standardwerten auffüllen und ältere Datenblätter ins Bausteinformat übernehmen."""
    content = content or {}
    out = empty_content()
    for key, value in content.items():
        if key in out:
            out[key] = value
    # Ältere Datenblätter: Aufzählungspunkte der früheren Beschreibung als Eigenschaften ohne Namen übernehmen
    old = content.get("beschreibung")
    if "einleitung" not in content and old and old.get("text"):
        out["einleitung"] = old["text"]
    if "eigenschaften" not in content and old and old.get("punkte"):
        out["eigenschaften"] = [{"name": "", "wert": p, "sichtbar": True} for p in old["punkte"]] + out["eigenschaften"]
    blocks = content.get("bloecke") if isinstance(content.get("bloecke"), list) else []
    if "gruppen" in content or "zubehoer" in content:
        # Format vor den Bausteinen: Artikelgruppen und Zubehör als Tabellen-Bausteine (Gecko-Aufbau)
        tables = [{**new_table(), "titel": g.get("titel", ""), "bild": g.get("bild"), "spalten": g.get("spalten", []),
                   "zeilen": [{**r, "bild": None} for r in g.get("zeilen", [])]}
                  for g in content.get("gruppen") or []]
        if tables:
            tables[0]["neue_seite"] = True
        if content.get("zubehoer"):
            tables.append({**new_table(zubehoer=True), "neue_seite": True,
                           "zeilen": [{"bild": z.get("bild"), "artnr": z.get("artnr", ""), "farbe": "",
                                       "beschreibung": z.get("beschreibung", ""), "werte": []}
                                      for z in content["zubehoer"]]})
        blocks = [b for b in blocks if isinstance(b, dict) and b.get("typ") in SINGLE_BLOCKS] + tables
    out["bloecke"] = _blocks(blocks)
    return out


def _blocks(raw) -> list[dict]:
    """Einleitung, Spezifikation und Anwendungsbilder genau einmal (fehlende vorne ergänzt), Rest wie gespeichert."""
    out, seen = [], set()
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, dict) or b.get("typ") not in BLOCKS:
            continue
        if b["typ"] in SINGLE_BLOCKS:
            if b["typ"] in seen:
                continue
            seen.add(b["typ"])
        out.append({**b, "neue_seite": b.get("neue_seite") is True, "sichtbar": b.get("sichtbar") is not False})
    missing = [dict(b) for b in DEFAULT_BLOCKS if b["typ"] not in seen]
    return (missing + out)[:MAX_BLOCKS]


def tables(content: dict) -> list[dict]:
    return [b for b in normalized(content)["bloecke"] if b["typ"] == "tabelle"]


ECE_RX = re.compile(r"\b(?:ECE|UN)?[\s-]*R\s*-?\s*(\d{1,3})\b", re.IGNORECASE)
CLASS_RX = re.compile(r"\b(?:Klasse|Kl\.?|Class)\s*(II|I|2|1)\b", re.IGNORECASE)
CISPR_RX = re.compile(r"\bCISPR\s*-?\s*(\d{1,3})\b", re.IGNORECASE)


def approval_badges(content: dict) -> list[dict]:
    """Zulassungslogos aus dem Feld „Zulassung“ (Eigenschaften und Spezifikationstabelle), z. B.
    „ECE-R65 Klasse II, ECE-R10, CISPR 25“ -> ECE-R65 Klasse 2 (blau), ECE-R10 (schwarz), CISPR 25 (gold).
    Bei ECE-R65 wird die Klasse aus dem Text bis zur nächsten Regelung gelesen."""
    c = normalized(content)
    texts = [e.get("wert", "") for e in c["eigenschaften"] if e.get("name", "").lower().startswith("zulass")]
    texts += [z.get("wert", "") for z in c["spez"]["zeilen"] if z.get("merkmal", "").lower().startswith("zulass")]
    found: dict[tuple, set] = {}
    for text in texts:
        # „CISPR 25“ nicht zusätzlich als „R 25“ lesen
        ece_text = CISPR_RX.sub(lambda m: " " * len(m.group(0)), text)
        matches = list(ECE_RX.finditer(ece_text))
        hits = [(m.start(), ("CISPR", str(int(m.group(1)))), None) for m in CISPR_RX.finditer(text)]
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(ece_text)
            hits.append((m.start(), ("ECE", str(int(m.group(1)))), ece_text[m.end():end]))
        for _, key, rest in sorted(hits, key=lambda h: h[0]):  # Reihenfolge wie eingegeben
            classes = found.setdefault(key, set())
            if key == ("ECE", "65"):
                for k in CLASS_RX.findall(rest):
                    classes.add({"I": "1", "II": "2"}.get(k.upper(), k))
    # Mehrere Klassen (z. B. Gecko 3 Klasse I, Gecko 6 Klasse II): ein Logo mit der höchsten, wie im Muster
    return [{"art": art, "nr": nr, "klasse": max(classes) if classes else None} for (art, nr), classes in found.items()]


def shown_properties(content: dict) -> list[dict]:
    """Eigenschaften, die gedruckt werden: eingeblendet und mit Wert."""
    return [e for e in normalized(content)["eigenschaften"] if e.get("sichtbar", True) and e.get("wert")]


def title_of(content: dict) -> str:
    k = content["kopf"]
    return " – ".join(p for p in (k["titel"], k["untertitel"]) if p) or "Neues Datenblatt"


# ---------- Eingaben aus dem Editor prüfen ----------

def _s(value, limit: int) -> str:
    """Text auf Länge begrenzen; alles, was kein Text/keine Zahl ist, wird leer."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value).replace("\r\n", "\n").strip()[:limit]


def _list(value, limit: int) -> list:
    return [v for v in value if isinstance(v, dict)][:limit] if isinstance(value, list) else []


def _images(value, valid: set[str], limit: int) -> list[str]:
    names = value if isinstance(value, list) else []
    return [n for n in names if isinstance(n, str) and n in valid][:limit]


def _image(value, valid: set[str]) -> str | None:
    return value if isinstance(value, str) and value in valid else None


def _table(b: dict, valid: set[str]) -> dict:
    spalten = [_s(x, 30) for x in (b.get("spalten") if isinstance(b.get("spalten"), list) else [])][:MAX_COLUMNS]
    while spalten and not spalten[-1]:
        spalten.pop()
    zeilen = []
    for r in _list(b.get("zeilen"), MAX_ROWS):
        werte = r.get("werte") if isinstance(r.get("werte"), list) else []
        row = {"bild": _image(r.get("bild"), valid), "artnr": _s(r.get("artnr"), 60),
               "farbe": r.get("farbe") if r.get("farbe") in COLORS else "",
               "beschreibung": _s(r.get("beschreibung"), 300),
               "werte": [_s(werte[k] if k < len(werte) else "", 80) for k in range(len(spalten))]}
        if row["bild"] or row["artnr"] or row["beschreibung"] or any(row["werte"]):
            zeilen.append(row)
    return {"titel": _s(b.get("titel"), 80), "zusatz": _s(b.get("zusatz"), 80), "bild": _image(b.get("bild"), valid),
            "bild_pos": b.get("bild_pos") if b.get("bild_pos") in GROUP_IMAGE_POS else "links",
            "zeilenbilder": b.get("zeilenbilder") if b.get("zeilenbilder") in ROW_IMAGES else "klein",
            "spalten": spalten, "zeilen": zeilen}


def sanitize(raw, valid_images: set[str]) -> dict:
    """Inhalt aus dem Editor: nur bekannte Felder, Längen begrenzt, nur vorhandene Bilder dieses Datenblatts."""
    raw = raw if isinstance(raw, dict) else {}
    c = empty_content()
    kopf = raw.get("kopf") if isinstance(raw.get("kopf"), dict) else {}
    c["kopf"] = {"titel": _s(kopf.get("titel"), 60), "untertitel": _s(kopf.get("untertitel"), 80)}
    c["einleitung"] = _s(raw.get("einleitung"), 2000)
    c["eigenschaften"] = [
        {"name": _s(e.get("name"), 40), "wert": _s(e.get("wert"), 150), "sichtbar": e.get("sichtbar") is not False}
        for e in _list(raw.get("eigenschaften"), MAX_PROPERTIES)
        if _s(e.get("name"), 40) or _s(e.get("wert"), 150)]
    for key, n in IMAGE_SLOTS.items():
        c[key] = _images(raw.get(key), valid_images, n)
    spez = raw.get("spez") if isinstance(raw.get("spez"), dict) else {}
    c["spez"] = {"zeichen": [], "zeilen": [
        {"merkmal": _s(z.get("merkmal"), 60), "wert": _s(z.get("wert"), 300)}
        for z in _list(spez.get("zeilen"), MAX_SPEC_ROWS) if _s(z.get("merkmal"), 60) or _s(z.get("wert"), 300)]}
    fuss = raw.get("fuss") if isinstance(raw.get("fuss"), dict) else {}
    c["fuss"] = {"version": _s(fuss.get("version"), 30)}
    blocks = []
    for b in _list(raw.get("bloecke"), MAX_BLOCKS):
        base = {"typ": b.get("typ"), "neue_seite": b.get("neue_seite") is True, "sichtbar": b.get("sichtbar") is not False}
        if base["typ"] in SINGLE_BLOCKS:
            blocks.append(base)
        elif base["typ"] == "tabelle":
            # Leere Tabellen bleiben erhalten (gerade angelegt), gedruckt werden nur Tabellen mit Zeilen
            blocks.append({**base, **_table(b, valid_images)})
        elif base["typ"] == "bild":
            blocks.append({**base, "bild": _image(b.get("bild"), valid_images),
                           "hoehe": b.get("hoehe") if b.get("hoehe") in IMAGE_HEIGHTS else "M"})
    c["bloecke"] = _blocks(blocks)
    return c


# ---------- Bilder ----------

def image_dir(settings: Settings, sheet_id: int) -> Path:
    return settings.upload_dir / "datenblatt" / str(sheet_id)


def image_names(settings: Settings, sheet_id: int) -> set[str]:
    folder = image_dir(settings, sheet_id)
    return {p.name for p in folder.iterdir() if p.is_file() and IMAGE_NAME.match(p.name)} if folder.is_dir() else set()


def _image_type(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def is_upload(value) -> bool:
    return bool(getattr(value, "filename", None)) and hasattr(value, "read")


async def save_image(settings: Settings, sheet_id: int, upload) -> str:
    """Bild prüfen (Inhalt, nicht Dateiendung) und speichern; liefert den neuen Dateinamen."""
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"„{upload.filename}“ ist größer als {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    kind = _image_type(data[:16])
    if kind is None:
        raise ImageError(f"„{upload.filename}“ ist kein Bild (erlaubt: JPG, PNG, GIF, WebP)")
    folder = image_dir(settings, sheet_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(8)}.{kind}"
    (folder / name).write_bytes(data)
    return name


def image_path(settings: Settings, sheet_id: int, name: str) -> Path | None:
    if not IMAGE_NAME.match(name):
        return None
    path = image_dir(settings, sheet_id) / name
    return path if path.is_file() else None


def referenced_images(content: dict) -> set[str]:
    c = normalized(content)
    names = [*c["bilder_oben"], *c["spez"]["zeichen"], *c["zeichnungen"], *c["bilder_unten"]]
    for b in c["bloecke"]:
        names.append(b.get("bild"))
        names += [r.get("bild") for r in b.get("zeilen", [])]
    return {n for n in names if n}


def remove_unused_images(settings: Settings, sheet_id: int, content: dict, grace: float = 0) -> None:
    """Nicht (mehr) verwendete Bilder löschen; grace: nur Dateien, die älter sind (Sekunden)."""
    folder = image_dir(settings, sheet_id)
    if not folder.is_dir():
        return
    keep = referenced_images(content)
    limit = time.time() - grace
    for path in folder.iterdir():
        if path.is_file() and path.name not in keep and path.stat().st_mtime <= limit:
            path.unlink()


def copy_images(settings: Settings, src_id: int, dst_id: int) -> None:
    src = image_dir(settings, src_id)
    if src.is_dir():
        shutil.copytree(src, image_dir(settings, dst_id), dirs_exist_ok=True)


def delete_images(settings: Settings, sheet_id: int) -> None:
    shutil.rmtree(image_dir(settings, sheet_id), ignore_errors=True)


# ---------- Zeilen aus Excel einfügen ----------

def guess_color(description: str) -> str:
    words = re.findall(r"[a-zäöüß]+", description.lower())
    for word in reversed(words):
        if word in COLOR_WORDS:
            return COLOR_WORDS[word]
    return ""


def parse_paste(text: str, n_columns: int) -> list[dict]:
    """Aus Excel kopierte Zeilen: Artikelnummer, Beschreibung, danach die Zusatzspalten (Tab oder Semikolon)."""
    rows = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip():
            continue
        cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.split(";"))]
        cells += [""] * (2 + n_columns - len(cells))
        artnr, desc = cells[0][:60], cells[1][:200]
        if not artnr and not desc:
            continue
        rows.append({"bild": None, "artnr": artnr, "farbe": guess_color(desc), "beschreibung": desc,
                     "werte": [c[:80] for c in cells[2:2 + n_columns]]})
    return rows[:MAX_ROWS]


# ---------- Seitenaufteilung für Vorschau und Druck ----------
# Höhen in mm, im Browser an der Druckvorlage gemessen (Seitenkörper zwischen Kopf- und Fußzeile 226 mm).
# Schätzwerte: Was trotzdem nicht passt, markiert die Vorschau rot (Messung im Browser).
PAGE_BODY_MM = 224  # 2 mm Reserve
GAP_MM = 8  # Abstand nach jedem Baustein (entfällt nach dem letzten einer Seite)
TABLE_TITLE_MM, TABLE_HEAD_MM, TABLE_GAP_MM, BANNER_MM, TABLE_MIN_MM = 8, 6.6, 11, 30, 16
SPLIT_MIN_TABLE = 6  # Tabellen bis zu so vielen Zeilen werden nie auf zwei Seiten geteilt
ROW_MM, ROW_EXTRA_MM = {"": 7.7, "klein": 9.3, "gross": 17.2}, 3.8


def _lines(text: str, chars: int) -> int:
    return sum(max(1, -(-len(part) // chars)) for part in (text or "").split("\n"))


def _row_height(table: dict):
    with_images = any(r.get("bild") for r in table["zeilen"])
    base = ROW_MM[table["zeilenbilder"]] if with_images else ROW_MM[""]

    def height(row: dict) -> float:
        extra = max(_lines(row.get("beschreibung", ""), 70), *[_lines(v, 18) for v in row.get("werte", [])] or [1]) - 1
        return max(base, ROW_MM[""] + ROW_EXTRA_MM * extra)
    return height


def _lead_mm(text: str, props: list[dict], spez: dict | None, images: list[str], drawings: list[str]) -> float:
    """Kopfbereich wie im Standard: links Text, Aufzählung, Spezifikation; rechts die Bilder untereinander."""
    # Absatzabstand 4 mm (nicht nach dem letzten Absatz), vor der Aufzählung 6 mm (Abstände fallen zusammen)
    paragraphs = [par for par in text.split("\n\n") if par.strip()]
    left = sum(4.67 * _lines(par, 47) for par in paragraphs) + 4 * max(0, len(paragraphs) - 1)
    left += sum(0.6 + 4.7 * _lines(f"{e['name']}: {e['wert']}", 45) for e in props) + (6 if props and paragraphs else 0)
    if spez is not None:
        left += (9 if left else 0) + 11.7 + (13 if spez["logos"] else 0)
        left += sum(6.6 + 4.2 * (_lines(r["wert"], 40) - 1) for r in spez["zeilen"])
    right = 56 * len(images) + 40 * len(drawings)
    right += 5 * max(0, len(images) + len(drawings) - 1)
    return max(left, right)


def paginate(content: dict, editor: bool = False) -> list[dict]:
    """Bausteine in ihrer Reihenfolge auf A4-Seiten verteilen.

    Einleitung, Spezifikation, Anwendungsbilder und Bilder sind ganze Teile; passen sie nicht mehr, beginnen sie auf
    der nächsten Seite. Tabellen werden bei Bedarf zeilenweise geteilt („Fortsetzung“).
    Ergebnis: [{"teile": [{"typ": ..., "index": Baustein-Nr., ...}, ...]}, ...]
    editor: Live-Vorschau – die Einleitung erscheint auch leer (Platzhalter zeigt, wo der Text hinkommt).
    """
    c = normalized(content)
    pages: list[list[dict]] = [[]]
    used = 0.0

    def new_page():
        nonlocal used
        if pages[-1]:
            pages.append([])
        used = 0.0

    def place(part: dict, height: float):
        nonlocal used
        if used + height > PAGE_BODY_MM and pages[-1]:
            new_page()
        pages[-1].append(part)
        used += height + GAP_MM

    def place_table(part: dict, rows: list, row_mm):
        """Zeilen so weit wie möglich auf die aktuelle Seite, Rest mit „Fortsetzung“ auf die nächsten."""
        nonlocal used
        rows, piece = list(rows), 0
        while True:
            # Bild über der Tabelle nur beim ersten Teil
            head = ((TABLE_TITLE_MM if part["titel"] or part["zusatz"] else 0) + TABLE_HEAD_MM
                    + (BANNER_MM if part["bild_oben"] and piece == 0 else 0))
            min_body = TABLE_MIN_MM if part["bild_links"] else 0
            need = head + max(min_body, sum(row_mm(r) for r in rows))
            if need <= PAGE_BODY_MM - used:
                pages[-1].append({**part, "zeilen": rows, "fortsetzung": piece > 0})
                used += need + TABLE_GAP_MM
                return
            fit, height = 0, head
            while fit < len(rows) and height + row_mm(rows[fit]) <= PAGE_BODY_MM - used:
                height += row_mm(rows[fit])
                fit += 1
            # Nicht zerreißen: kleine Tabellen (bis 6 Zeilen) ganz auf die nächste Seite, sonst mindestens
            # 3 Zeilen auf jeder Seite – außer die Tabelle passt nicht einmal auf eine leere Seite
            if pages[-1] and (len(rows) <= SPLIT_MIN_TABLE or fit < 3):
                fit = 0
            elif pages[-1] and len(rows) - fit < 3:
                fit = len(rows) - 3 if len(rows) - 3 >= 3 else 0
            if fit >= 3 or (not pages[-1] and fit >= 1):
                pages[-1].append({**part, "zeilen": rows[:fit], "fortsetzung": piece > 0})
                rows, piece = rows[fit:], piece + 1
            elif not pages[-1]:  # nicht einmal eine Zeile passt auf eine leere Seite (sehr lange Texte)
                pages[-1].append({**part, "zeilen": rows[:1], "fortsetzung": piece > 0})
                rows, piece = rows[1:], piece + 1
            new_page()
            if not rows:
                return

    props, badges = shown_properties(c), approval_badges(c)
    blocks = c["bloecke"]
    has_intro = editor or bool(c["einleitung"] or props or c["bilder_oben"])
    # Überschrift „Produkttyp - Serie / Spezifikationen“ steht, sobald Produkttyp oder Serie eingetragen sind
    has_spez = bool(c["spez"]["zeilen"] or badges or c["zeichnungen"] or c["kopf"]["titel"] or c["kopf"]["untertitel"]
                    or editor)
    joined = set()  # Spezifikation, die schon im Kopfbereich mit der Einleitung steht
    for index, block in enumerate(blocks):
        typ = block["typ"]
        if not block["sichtbar"] or index in joined:
            continue
        part, height = None, 0.0
        if (typ == "intro" and has_intro) or (typ == "spez" and has_spez):
            # Kopfbereich wie im Standard-Datenblatt: folgt die Spezifikation direkt auf die Einleitung (ohne neue
            # Seite), stehen beide links untereinander und die Bilder rechts über die ganze Höhe
            nxt = index + 1
            with_spez = typ == "spez" or (nxt < len(blocks) and blocks[nxt]["typ"] == "spez" and blocks[nxt]["sichtbar"]
                                          and not blocks[nxt]["neue_seite"] and has_spez)
            if typ == "intro" and with_spez:
                joined.add(nxt)
            spez = ({"zeilen": c["spez"]["zeilen"], "logos": badges, "index": index if typ == "spez" else nxt}
                    if with_spez else None)
            intro = typ == "intro"
            part = {"typ": "kopfbereich", "intro_index": index if intro else None,
                    "einleitung": c["einleitung"] if intro else "", "eigenschaften": props if intro else [],
                    "bilder": c["bilder_oben"] if intro else [], "spez": spez,
                    "zeichnungen": c["zeichnungen"] if with_spez else []}
            height = _lead_mm(part["einleitung"], part["eigenschaften"], spez, part["bilder"], part["zeichnungen"])
        elif typ == "anwendung" and c["bilder_unten"]:
            part, height = {"typ": "anwendung", "bilder": c["bilder_unten"]}, 62
        elif typ == "bild" and block.get("bild"):
            part = {"typ": "bild", "bild": block["bild"], "hoehe": block.get("hoehe", "M")}
            height = IMAGE_HEIGHTS[part["hoehe"]][1] + 1.2
        elif typ == "tabelle" and block.get("zeilen"):
            part = {k: block[k] for k in ("titel", "zusatz", "bild", "spalten", "zeilenbilder")}
            part.update(typ="tabelle", bild_links=bool(block["bild"]) and block["bild_pos"] == "links",
                        bild_oben=bool(block["bild"]) and block["bild_pos"] == "oben",
                        zeilen_bilder=any(r.get("bild") for r in block["zeilen"]),
                        farben=any(r.get("farbe") for r in block["zeilen"]))
        if part is None:
            continue
        part["index"] = index
        if block["neue_seite"]:
            new_page()
        if typ == "tabelle":
            place_table(part, block["zeilen"], _row_height(block))
        else:
            place(part, height)
    return [{"teile": p} for p in pages if p] or [{"teile": []}]
