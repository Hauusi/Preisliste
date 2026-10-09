"""Datenblätter: Baukasten mit festem Layout (Kopf, Beschreibung, Spezifikationen, Artikel, Zubehör, Fußzeile).

Der Inhalt wird Schritt für Schritt abgefragt und als JSON gespeichert. Bilder liegen als Dateien unter
uploads/datenblatt/<id>/ (damit in der Sicherung enthalten), im JSON steht nur der Dateiname.
"""

from __future__ import annotations

import copy
import re
import secrets
import shutil
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

STEPS = [
    ("kopf", "Kopfzeile"),
    ("eigenschaften", "Eigenschaften"),
    ("bilder", "Produktbilder"),
    ("spez", "Spezifikationen"),
    ("zeichnungen", "Maßzeichnungen"),
    ("anwendung", "Anwendungsbilder"),
    ("artikel", "Artikel"),
    ("zubehoer", "Zubehör"),
    ("fuss", "Fußzeile"),
]
STEP_KEYS = [k for k, _ in STEPS]

# Bildplätze je Schritt (Schlüssel im Inhalt, Anzahl)
IMAGE_SLOTS = {"bilder": ("bilder_oben", 2), "zeichnungen": ("zeichnungen", 2), "anwendung": ("bilder_unten", 2)}

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
MAX_PROPERTIES = 25

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SPEC_ROWS, MAX_BADGES, MAX_COLUMNS = 20, 4, 3
MAX_GROUPS, MAX_GROUP_ROWS, MAX_ACCESSORIES = 20, 80, 80
SPARE_ROWS = 3
IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


class ImageError(ValueError):
    pass


def empty_content() -> dict:
    return {
        "kopf": {"titel": "", "untertitel": ""},
        "eigenschaften": [{"name": n, "wert": "", "sichtbar": True} for n in DEFAULT_PROPERTIES],
        "bilder_oben": [],
        "spez": {"zeichen": [], "zeilen": []},
        "zeichnungen": [],
        "bilder_unten": [],
        "gruppen": [],
        "zubehoer": [],
        "fuss": {"version": date.today().strftime("%d%m%Y")},
    }


def normalized(content: dict | None) -> dict:
    """Fehlende Schlüssel (ältere Datenblätter) mit Standardwerten auffüllen."""
    out = empty_content()
    for key, value in (content or {}).items():
        if key in out:
            out[key] = value
    # Ältere Datenblätter: Aufzählungspunkte der früheren Beschreibung als Eigenschaften ohne Namen übernehmen
    old = (content or {}).get("beschreibung")
    if "eigenschaften" not in (content or {}) and old and old.get("punkte"):
        out["eigenschaften"] = [{"name": "", "wert": p, "sichtbar": True} for p in old["punkte"]] + out["eigenschaften"]
    return out


def shown_properties(content: dict) -> list[dict]:
    """Eigenschaften, die gedruckt werden: eingeblendet und mit Wert."""
    return [e for e in normalized(content)["eigenschaften"] if e.get("sichtbar", True) and e.get("wert")]


def title_of(content: dict) -> str:
    k = content["kopf"]
    return " – ".join(p for p in (k["titel"], k["untertitel"]) if p) or "Neues Datenblatt"


# ---------- Bilder ----------

def image_dir(settings: Settings, sheet_id: int) -> Path:
    return settings.upload_dir / "datenblatt" / str(sheet_id)


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
    names += [g.get("bild") for g in c["gruppen"]] + [z.get("bild") for z in c["zubehoer"]]
    return {n for n in names if n}


def remove_unused_images(settings: Settings, sheet_id: int, content: dict) -> None:
    folder = image_dir(settings, sheet_id)
    if not folder.is_dir():
        return
    keep = referenced_images(content)
    for path in folder.iterdir():
        if path.is_file() and path.name not in keep:
            path.unlink()


def copy_images(settings: Settings, src_id: int, dst_id: int) -> None:
    src = image_dir(settings, src_id)
    if src.is_dir():
        shutil.copytree(src, image_dir(settings, dst_id), dirs_exist_ok=True)


def delete_images(settings: Settings, sheet_id: int) -> None:
    shutil.rmtree(image_dir(settings, sheet_id), ignore_errors=True)


# ---------- Formulare je Schritt ----------

def _text(form, key: str, limit: int) -> str:
    return str(form.get(key) or "").replace("\r\n", "\n").strip()[:limit]


def _indices(form, pattern: str) -> list[int]:
    """Alle Zeilennummern zu einem Feldmuster, z. B. r"merkmal_(\\d+)$"."""
    rx = re.compile(pattern)
    return sorted({int(m.group(1)) for key in form.keys() if (m := rx.match(key))})


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
        rows.append({"artnr": artnr, "farbe": guess_color(desc), "beschreibung": desc,
                     "werte": [c[:80] for c in cells[2:2 + n_columns]]})
    return rows


async def apply_step(content: dict, step: str, form, store) -> tuple[dict, list[str]]:
    """Formular eines Schritts übernehmen. store(upload) speichert ein Bild und liefert den Namen.

    Liefert den neuen Inhalt (Kopie) und Fehlermeldungen (z. B. ungültige Bilder); gültige Eingaben bleiben erhalten.
    """
    c = copy.deepcopy(normalized(content))
    errors: list[str] = []

    async def image(key: str, current: str | None) -> str | None:
        if form.get(f"{key}_weg") == "ja":
            current = None
        upload = form.get(key)
        if is_upload(upload):
            try:
                return await store(upload)
            except ImageError as e:
                errors.append(str(e))
        return current

    if step == "kopf":
        c["kopf"] = {"titel": _text(form, "titel", 60), "untertitel": _text(form, "untertitel", 80)}
    elif step == "eigenschaften":
        # Gleichnamige Felder in Reihenfolge der Seite (Drag & Drop ändert die Reihenfolge)
        names, values, shown = form.getlist("e_name"), form.getlist("e_wert"), form.getlist("e_sichtbar")
        props = []
        for i, name in enumerate(names):
            entry = {"name": str(name).strip()[:40], "wert": str(values[i] if i < len(values) else "").strip()[:150],
                     "sichtbar": str(shown[i] if i < len(shown) else "1") != "0"}
            if entry["name"] or entry["wert"]:
                props.append(entry)
        new = {"name": _text(form, "neu_name", 40), "wert": _text(form, "neu_wert", 150), "sichtbar": True}
        if new["name"] or new["wert"]:
            props.append(new)
        c["eigenschaften"] = props[:MAX_PROPERTIES]
    elif step in IMAGE_SLOTS:
        key, n = IMAGE_SLOTS[step]
        old = c[key] + [None] * n
        c[key] = [name for i in range(n) if (name := await image(f"bild_{i}", old[i]))]
    elif step == "spez":
        old = c["spez"]["zeichen"] + [None] * MAX_BADGES
        zeichen = [name for i in range(MAX_BADGES) if (name := await image(f"zeichen_{i}", old[i]))]
        zeilen = []
        for i in _indices(form, r"merkmal_(\d+)$"):
            merkmal, wert = _text(form, f"merkmal_{i}", 60), _text(form, f"wert_{i}", 300)
            if merkmal or wert:
                zeilen.append({"merkmal": merkmal, "wert": wert})
        c["spez"] = {"zeichen": zeichen, "zeilen": zeilen[:MAX_SPEC_ROWS]}
    elif step == "artikel":
        old = c["gruppen"]
        gruppen = []
        for gi in _indices(form, r"g(\d+)_titel$"):
            if form.get(f"g{gi}_weg") == "ja":
                continue
            prev = old[gi] if gi < len(old) else {}
            spalten = [_text(form, f"g{gi}_spalte{k}", 30) for k in range(MAX_COLUMNS)]
            n_cols = max((k + 1 for k, s in enumerate(spalten) if s), default=0)
            spalten = spalten[:n_cols]
            zeilen = []
            for ri in _indices(form, rf"g{gi}_r(\d+)_artnr$"):
                p = f"g{gi}_r{ri}_"
                row = {"artnr": _text(form, p + "artnr", 60), "beschreibung": _text(form, p + "beschreibung", 200),
                       "farbe": str(form.get(p + "farbe") or ""),
                       "werte": [_text(form, f"{p}w{k}", 80) for k in range(n_cols)]}
                if row["farbe"] not in COLORS:
                    row["farbe"] = ""
                if row["artnr"] or row["beschreibung"]:
                    zeilen.append(row)
            zeilen += parse_paste(str(form.get(f"g{gi}_einfuegen") or "")[:100_000], n_cols)
            group = {"titel": _text(form, f"g{gi}_titel", 80), "bild": await image(f"g{gi}_bild", prev.get("bild")),
                     "spalten": spalten, "zeilen": zeilen[:MAX_GROUP_ROWS]}
            if group["titel"] or group["bild"] or group["zeilen"]:
                gruppen.append(group)
        if form.get("aktion") == "gruppe" and len(gruppen) < MAX_GROUPS:
            gruppen.append({"titel": "", "bild": None, "spalten": list(DEFAULT_COLUMNS), "zeilen": []})
        c["gruppen"] = gruppen[:MAX_GROUPS]
    elif step == "zubehoer":
        old = c["zubehoer"]
        zeilen = []
        for i in _indices(form, r"z(\d+)_artnr$"):
            if form.get(f"z{i}_weg") == "ja":
                continue
            prev = old[i] if i < len(old) else {}
            row = {"artnr": _text(form, f"z{i}_artnr", 60), "beschreibung": _text(form, f"z{i}_beschreibung", 300),
                   "bild": await image(f"z{i}_bild", prev.get("bild"))}
            if row["artnr"] or row["beschreibung"] or row["bild"]:
                zeilen.append(row)
        c["zubehoer"] = zeilen[:MAX_ACCESSORIES]
    elif step == "fuss":
        c["fuss"] = {"version": _text(form, "version", 30)}
    else:
        raise ValueError(f"Unbekannter Schritt {step}")
    return c, errors


def step_done(content: dict, step: str) -> bool:
    c = normalized(content)
    return {
        "kopf": bool(c["kopf"]["titel"]),
        "eigenschaften": bool(shown_properties(c)),
        "bilder": bool(c["bilder_oben"]),
        "spez": bool(c["spez"]["zeilen"] or c["spez"]["zeichen"]),
        "zeichnungen": bool(c["zeichnungen"]),
        "anwendung": bool(c["bilder_unten"]),
        "artikel": any(g["zeilen"] for g in c["gruppen"]),
        "zubehoer": bool(c["zubehoer"]),
        "fuss": bool(c["fuss"]["version"]),
    }[step]


# ---------- Seitenaufteilung für Vorschau und Druck ----------
# Höhen in mm, abgeleitet vom Muster-Datenblatt (A4, Inhalt zwischen Kopf- und Fußzeile ca. 225 mm)
PAGE_BODY_MM = 222
GROUP_HEAD_MM, GROUP_GAP_MM, ROW_MM, ROW_EXTRA_MM, GROUP_MIN_MM = 17, 11, 6.5, 4, 16
ACC_HEAD_MM, ACC_ROW_MM = 17, 17


def _row_mm(row: dict) -> float:
    longest = max([len(row.get("beschreibung", ""))] + [len(v) * 2.5 for v in row.get("werte", [])])
    return ROW_MM + ROW_EXTRA_MM * (longest // 75)


def _group_mm(rows: list[dict]) -> float:
    return GROUP_HEAD_MM + max(GROUP_MIN_MM, sum(_row_mm(r) for r in rows)) + GROUP_GAP_MM


def paginate(content: dict) -> list[dict]:
    """Inhalt auf A4-Seiten verteilen: Startseite, Artikelseiten (Gruppen ganz, zu große geteilt), Zubehörseiten."""
    c = normalized(content)
    pages: list[dict] = []
    if any(step_done(c, s) for s in ("eigenschaften", "bilder", "spez", "zeichnungen", "anwendung")):
        pages.append({"art": "start"})

    current, used = [], 0.0
    for group in (g for g in c["gruppen"] if g["zeilen"]):
        rows, part = list(group["zeilen"]), 0
        while True:
            need = _group_mm(rows)
            if need <= PAGE_BODY_MM - used:
                current.append({**group, "zeilen": rows, "fortsetzung": part > 0})
                used += need
                break
            # passt nicht: so viele Zeilen wie möglich hier, wenn es sich lohnt, sonst neue Seite
            fit, height = 0, GROUP_HEAD_MM + GROUP_GAP_MM
            while fit < len(rows) and height + _row_mm(rows[fit]) <= PAGE_BODY_MM - used:
                height += _row_mm(rows[fit])
                fit += 1
            if fit >= 3 or (not current and fit >= 1):
                current.append({**group, "zeilen": rows[:fit], "fortsetzung": part > 0})
                rows, part = rows[fit:], part + 1
            elif not current:  # nicht einmal eine Zeile passt auf eine leere Seite (sehr lange Texte)
                current.append({**group, "zeilen": rows[:1], "fortsetzung": part > 0})
                rows, part = rows[1:], part + 1
            pages.append({"art": "artikel", "gruppen": current})
            current, used = [], 0.0
            if not rows:
                break
    if current:
        pages.append({"art": "artikel", "gruppen": current})

    per_page = int((PAGE_BODY_MM - ACC_HEAD_MM) // ACC_ROW_MM)
    acc = c["zubehoer"]
    for i in range(0, len(acc), per_page):
        pages.append({"art": "zubehoer", "zeilen": acc[i:i + per_page], "fortsetzung": i > 0})
    return pages or [{"art": "start"}]
