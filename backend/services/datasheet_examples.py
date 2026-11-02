"""Design-Vorlagen: unsere fertigen Datenblätter als Original-PDF.

Beim Hochladen wird nichts nachgebaut. Das Tool liest nur ab, wie das Blatt aufgebaut ist (Profil): wo welche Bilder
in welcher Größe sitzen, wie der Text geschrieben ist, welche Zeilen in der Spezifikation stehen, wie Artikel
beschrieben werden. Beim Import aus einem Herstellerblatt werden die Profile derselben Produktart (sonst alle)
zusammengefasst (design) und auf den neuen Inhalt angewendet; Text und Artikelbeschreibungen dienen der lokalen KI als
Stilvorbild. Werte, Artikel und Bilder der Vorlagen werden nie übernommen.
"""

from __future__ import annotations

import re
import statistics
import tempfile
from pathlib import Path

from backend.config import Settings
from backend.services import datasheets as ds

PT_MM = 25.4 / 72
HEADER_MM, FOOTER_MM = 35, 262  # Kopf (Balken, Titel) und Fußzeile (Logo, Firmendaten) zählen nicht als Bilder
# Unser Layout: Seitenrand 15 mm, Textspalte je Aufteilung, 9 mm Abstand -> Beginn der Bildspalte
RIGHT_COLUMN_MM = {key: 15 + mm + 9 for key, (_label, mm) in ds.LEAD_SPLITS.items()}
# Standardhöhen im Layout (datasheet.css): Produktbild, Zeichnung, Anwendungsbild
BASE_MM = {"produkt": 56, "zeichnung": 40, "anwendung": 62}
MAX_EXAMPLE_TEXTS = 2


def pdf_path(settings: Settings, example_id: int) -> Path:
    return settings.upload_dir / "vorlagen" / f"{example_id}.pdf"


def placements(pages) -> list[dict]:
    """Gezeichnete Bilder je Seite mit Position und Größe in mm (oben links = 0/0) und Art (wie im Import)."""
    from backend.services import datasheet_import as dsi

    out = []
    for page_no, page in enumerate(pages):
        try:
            images = {im.name.rsplit(".", 1)[0]: im for im in page.images}
            height = float(page.mediabox.height)
        except Exception:  # noqa: BLE001 - kaputte Seite: ohne Bilder weiter
            continue
        hits = []

        def visit(op, args, cm, _tm):
            if op == b"Do" and args:
                hits.append((str(args[0]).lstrip("/"), list(cm)))

        try:
            page.extract_text(visitor_operand_before=visit)
        except Exception:  # noqa: BLE001
            continue
        for name, cm in hits:
            im = images.get(name)
            if im is None:
                continue
            w, h = abs(cm[0]) * PT_MM, abs(cm[3]) * PT_MM
            x, y = cm[4] * PT_MM, (height - cm[5]) * PT_MM - h
            if y + h <= HEADER_MM or y >= FOOTER_MM or w < 8 or h < 8:
                continue  # Kopf, Fußzeile (Logo), Symbole
            try:
                img = im.image
            except Exception:  # noqa: BLE001
                continue
            if img is None or dsi._own_logo(img):
                continue
            kind = dsi._image_kind(img) if min(w, h) >= 20 else "zeile"  # klein: Bild in einer Tabellenzeile
            if kind:
                out.append({"seite": page_no, "art": kind, "x": round(x, 1), "y": round(y, 1),
                            "w": round(w, 1), "h": round(h, 1)})
    return out


def analyze(data: bytes, settings: Settings) -> dict:
    """Profil eines unserer Datenblätter (PDF). Nichts wird gespeichert außer diesem Profil."""
    from backend.services import datasheet_import as dsi

    reader, pages, _texts = dsi.read_pdf(data)
    with tempfile.TemporaryDirectory() as tmp:  # Bilder des Einlesens landen im Wegwerf-Ordner
        result = dsi.build(data, settings.model_copy(update={"data_dir": Path(tmp)}), 0, own_sheet=True)
    c = result.content
    tables = [b for b in c["bloecke"] if b.get("typ") == "tabelle"]
    return {
        "titel": c["kopf"]["titel"], "untertitel": c["kopf"]["untertitel"],
        "art": result.stats.get("produktart") or "",
        "text": c["einleitung"],
        "punkte": [p["wert"] for p in c["eigenschaften"] if not p["name"] and p["wert"]],
        "eigenschaften": [p["name"] for p in c["eigenschaften"] if p["name"] and p["wert"]],
        "spez": [z["merkmal"] for z in c["spez"]["zeilen"] if _label_like(z["merkmal"])],
        "artikel": [r["beschreibung"] for t in tables for r in t["zeilen"] if r["beschreibung"]][:12],
        "spalten": [s for t in tables for s in t["spalten"] if s],
        "bilder": placements(pages),
        "seiten": len(pages),
    }


def _label_like(text: str) -> bool:
    """Echter Zeilenname („Blitzmuster“), keine Bildunterschrift („Magnetmontage ø 200 x 156mm, Doppelblitz“)."""
    return bool(text) and len(text) <= 30 and not re.search(r"\d|ø|,", text)


# ---------- Regeln aus mehreren Vorlagen ----------

def kinds_of(value: str | None) -> list[str]:
    return [k.strip().lower() for k in (value or "").split(",") if k.strip()]


def choose(examples: list[dict], kind: str | None) -> tuple[list[dict], bool]:
    """Profile derselben Produktart; gibt es keine, alle (gemeinsame Regeln). examples: [{art, profil}].
    Ergebnis (Profile, nach Produktart?)."""
    usable = [e for e in examples if e.get("profil")]
    kind = (kind or "").lower()
    same = [e for e in usable if kind and kind in kinds_of(e.get("art"))]
    if not same and kind:  # verwandte Art: „Arbeitsscheinwerfer“ nimmt die Vorlagen für „Scheinwerfer“
        same = [e for e in usable if any(kind.endswith(k) or k.endswith(kind) for k in kinds_of(e.get("art")))]
    return ([e["profil"] for e in same], True) if same else ([e["profil"] for e in usable], False)


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _order(lists: list[list[str]]) -> list[str]:
    """Gemeinsame Reihenfolge: Begriffe nach mittlerer Position, nur was in mindestens einer Vorlage steht."""
    pos: dict[str, list[float]] = {}
    for items in lists:
        for i, name in enumerate(items):
            pos.setdefault(name, []).append(i / max(1, len(items) - 1))
    return sorted(pos, key=lambda n: (statistics.mean(pos[n]), -len(pos[n])))


def design(profiles: list[dict]) -> dict | None:
    """Zusammengefasste Regeln aus den Profilen (Bilder: Median; Anzeige: Mehrheit)."""
    if not profiles:
        return None
    first = [[b for b in p.get("bilder", []) if b["seite"] == 0] for p in profiles]

    def right(b, column=100):
        return b["x"] + b["w"] / 2 > column

    products = [[b for b in bs if b["art"] in ("produkt", "produktfoto") and right(b) and b["y"] < 190] for bs in first]
    drawings = [[b for b in bs if b["art"] == "zeichnung" and right(b)] for bs in first]
    photos = [[b for b in bs if b["y"] >= 185 and b["w"] >= 60 and b["art"] in ("foto", "produktfoto")] for bs in first]
    xs = [min(b["x"] for b in bs) for bs in products if bs]
    x = _median(xs)
    split = min(RIGHT_COLUMN_MM, key=lambda k: abs(RIGHT_COLUMN_MM[k] - x)) if x is not None else "normal"
    with_photos = [bs for bs in photos if bs]
    return {
        "anzahl": len(profiles),
        "aufteilung": split,
        "produktbilder": min(2, max(1, round(_median([len(bs) for bs in products]) or 1))),
        "produkt_h": _median([b["h"] for bs in products for b in bs]),
        "zeichnungen": min(2, round(_median([len(bs) for bs in drawings]) or 0)),
        "zeichnung_h": _median([b["h"] for bs in drawings for b in bs]),
        "anwendung": len(with_photos) * 2 >= len(profiles),
        "anwendung_h": _median([b["h"] for bs in with_photos for b in bs]),
        "eigenschaften": _order([p.get("eigenschaften", []) for p in profiles]),
        "spez": _order([[x for x in p.get("spez", []) if _label_like(x)] for p in profiles]),
        "punkte": [x for p in profiles for x in p.get("punkte", [])],
        "texte": [p["text"] for p in profiles if p.get("text")][:MAX_EXAMPLE_TEXTS],
        "artikel": [a for p in profiles for a in p.get("artikel", [])][:8],
    }


def _scale(height: float | None, base: float) -> int | None:
    if not height:
        return None
    pct = round(height / base * 100 / 5) * 5
    return max(ds.MIN_SCALE, min(ds.MAX_SCALE, pct)) if abs(pct - 100) >= 10 else None


def apply(content: dict, rules: dict) -> dict:
    """Regeln auf den importierten Inhalt anwenden (Form und Bilder; Inhalte bleiben aus dem Herstellerblatt)."""
    # Eigenschaften: Namen und Reihenfolge wie bei uns; fehlende Werte bleiben leer (werden nicht gedruckt)
    imported = content["eigenschaften"]
    named = {p["name"]: p for p in imported if p["name"]}
    props = [named.pop(n, {"name": n, "wert": "", "sichtbar": True}) for n in rules["eigenschaften"]]
    props += [p for p in imported if p["name"] and p["name"] in named]
    bullets = [p for p in imported if not p["name"]]
    if not any("garantie" in b["wert"].lower() for b in bullets):
        # Garantie-Punkt wie in unseren Blättern als ausgeblendeter Vorschlag (Auge an, wenn er auch hier gilt)
        bullets[:0] = [{"name": "", "wert": w, "sichtbar": False} for w in rules["punkte"] if "garantie" in w.lower()][:1]
    content["eigenschaften"] = props + bullets

    order = [s.strip().rstrip(":").lower() for s in rules["spez"]]
    content["spez"]["zeilen"].sort(key=lambda z: order.index(z["merkmal"].strip().rstrip(":").lower())
                                   if z["merkmal"].strip().rstrip(":").lower() in order else len(order))

    # Bilder: Anzahl, Größe, Aufteilung wie in unseren Blättern
    content["aufteilung"] = rules["aufteilung"]
    content["bilder_oben"] = content["bilder_oben"][:rules["produktbilder"]]
    if rules["zeichnungen"]:
        content["zeichnungen"] = content["zeichnungen"][:rules["zeichnungen"]]
    sizes = {}
    for slot, base, key in (("bilder_oben", BASE_MM["produkt"], "produkt_h"),
                            ("zeichnungen", BASE_MM["zeichnung"], "zeichnung_h"),
                            ("bilder_unten", BASE_MM["anwendung"], "anwendung_h")):
        pct = _scale(rules.get(key), base)
        if pct:
            sizes.update({ds.image_key(n): pct for n in content[slot]})
    content["bild_groesse"] = sizes
    content["bild_versatz"] = {}
    for b in content["bloecke"]:
        if b["typ"] == "anwendung":
            b["sichtbar"] = rules["anwendung"]
    return content


def summary(rules: dict | None) -> list[str]:
    """Regeln in Worten (Vorlagen-Seite)."""
    if not rules:
        return []
    split = ds.LEAD_SPLITS[rules["aufteilung"]][0]
    out = [f"Produktbilder oben rechts: {rules['produktbilder']}"
           + (f", etwa {rules['produkt_h']:.0f} mm hoch" if rules.get("produkt_h") else "") + f"; Aufteilung: {split}",
           f"Zeichnungen neben der Spezifikation: {rules['zeichnungen'] or 'keine'}",
           "Anwendungsbilder unten: " + ("ja" + (f", etwa {rules['anwendung_h']:.0f} mm hoch"
                                                 if rules.get("anwendung_h") else "") if rules["anwendung"] else "nein")]
    if rules["eigenschaften"] or rules["spez"]:
        out.append("Zeilen in dieser Reihenfolge: " + ", ".join(rules["eigenschaften"] + rules["spez"]))
    garantie = [p for p in rules["punkte"] if "garantie" in p.lower()]
    if garantie:
        out.append(f"Aufzählung beginnt mit: {garantie[0]}")
    if rules["texte"]:
        out.append(f"Textstil: {len(rules['texte'])} Beispieltext(e) für die lokale KI")
    if rules["artikel"]:
        out.append(f"Artikelbeschreibungen: z. B. „{rules['artikel'][0]}“")
    return out


def clean_filename(name: str) -> str:
    return re.sub(r"[^\w .,()&+-]", "_", name)[:200] or "vorlage.pdf"
