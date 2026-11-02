"""Design-Vorlagen: ein fertiges B&B-Datenblatt gibt beim Import aus einem Herstellerblatt Aufbau und Stil vor.

Übernommen werden nur Form und Reihenfolge (Eigenschaften, Spezifikationszeilen, Bausteine, Tabellen-Einstellungen)
und der Textstil für die lokale KI – nie Werte, Artikel oder Bilder der Vorlage.
"""

from __future__ import annotations

import re

from backend.services import datasheets as ds

# Einstellungen eines Bausteins, die aus der Vorlage kommen (Inhalt bleibt aus dem Herstellerblatt)
LAYOUT_KEYS = {"tabelle": ("neue_seite", "bild_pos", "zeilenbilder"), "bild": ("neue_seite", "hoehe"),
               "intro": ("neue_seite",), "spez": ("neue_seite",), "anwendung": ("neue_seite", "sichtbar")}
SLOTS = ("bilder_oben", "zeichnungen", "bilder_unten")


def choose(templates: list[dict], kind: str | None) -> dict | None:
    """Vorlage zur Produktart (Einzahl, z. B. „Arbeitsscheinwerfer“); bei mehreren die zuletzt geänderte.
    templates: [{titel, art, content, geaendert}]."""
    if not kind:
        return None
    hits = [t for t in templates if kind.lower() in kinds_of(t.get("art"))]
    return max(hits, key=lambda t: t.get("geaendert") or "") if hits else None


def kinds_of(value: str | None) -> list[str]:
    """Produktarten einer Vorlage: mehrere mit Komma, z. B. „Scheinwerfer, Arbeitsscheinwerfer“."""
    return [k.strip().lower() for k in (value or "").split(",") if k.strip()]


def spec_order(template: dict) -> list[str]:
    """Merkmale der Spezifikation in der Reihenfolge der Vorlage (klein geschrieben)."""
    return [z["merkmal"].strip().lower() for z in ds.normalized(template)["spez"]["zeilen"] if z.get("merkmal")]


def _is_accessories(block: dict) -> bool:
    return block.get("typ") == "tabelle" and (block.get("titel") or "").strip().lower() == "zubehör"


def apply(content: dict, template: dict) -> dict:
    """Aufbau der Vorlage auf den importierten Inhalt übertragen."""
    tpl = ds.normalized(template)

    # Eigenschaften: Namen und Reihenfolge der Vorlage; fehlende Werte bleiben leer (werden nicht gedruckt)
    imported = content["eigenschaften"]
    named = {p["name"]: p for p in imported if p["name"]}
    props = []
    for p in tpl["eigenschaften"]:
        if p["name"] and p["name"] not in {x["name"] for x in props}:
            props.append(named.pop(p["name"], {"name": p["name"], "wert": "", "sichtbar": True}))
    props += [p for p in imported if p["name"] and p["name"] in named]
    bullets = [p for p in imported if not p["name"]]
    if not any("garantie" in b["wert"].lower() for b in bullets):
        # Garantie-Punkt der Vorlage als ausgeblendeter Vorschlag: Auge an, wenn er auch hier gilt
        bullets[:0] = [{"name": "", "wert": p["wert"], "sichtbar": False} for p in tpl["eigenschaften"]
                       if not p["name"] and "garantie" in p["wert"].lower()][:1]
    content["eigenschaften"] = props + bullets

    # Spezifikationszeilen in der Reihenfolge der Vorlage
    order = spec_order(tpl)
    content["spez"]["zeilen"].sort(key=lambda z: order.index(z["merkmal"].strip().lower())
                                   if z["merkmal"].strip().lower() in order else len(order))

    # Bausteine: Reihenfolge und Einstellungen der Vorlage; Übriges hinten in bisheriger Reihenfolge
    pool, blocks = list(content["bloecke"]), []
    for tb in tpl["bloecke"]:
        if tb["typ"] == "tabelle":
            matches = [b for b in pool if b["typ"] == "tabelle" and _is_accessories(b) == _is_accessories(tb)]
        else:
            matches = [b for b in pool if b["typ"] == tb["typ"]][:1]
        for b in matches:
            pool.remove(b)
            for key in LAYOUT_KEYS.get(b["typ"], ()):
                if key in tb:
                    b[key] = tb[key]
            if b["typ"] == "tabelle" and not b.get("zusatz") and re.match(r"serie\b", tb.get("zusatz") or "", re.I):
                b["zusatz"] = content["kopf"]["untertitel"]  # „BESTELLINFORMATIONEN - SERIE UNITY“
            blocks.append(b)
    content["bloecke"] = blocks + pool

    # Bilder: so viele Produktbilder/Zeichnungen wie die Vorlage, Größe und Versatz je Platz (1. Bild, 2. Bild …)
    content["aufteilung"] = tpl.get("aufteilung") or "normal"
    sizes, offsets = {}, {}
    for slot in SLOTS:
        if slot != "bilder_unten" and tpl[slot]:
            content[slot] = content[slot][:len(tpl[slot])]
        pairs = list(zip(tpl[slot], content[slot]))
        _copy_image_layout(pairs, tpl, sizes, offsets if slot == "bilder_oben" else None)
    for typ in ("bild", "tabelle"):
        pairs = list(zip([b.get("bild") for b in tpl["bloecke"] if b["typ"] == typ],
                         [b.get("bild") for b in content["bloecke"] if b["typ"] == typ]))
        _copy_image_layout([(a, b) for a, b in pairs if a and b], tpl, sizes, None)
    content["bild_groesse"], content["bild_versatz"] = sizes, offsets
    return content


def _copy_image_layout(pairs: list[tuple[str, str]], tpl: dict, sizes: dict, offsets: dict | None) -> None:
    for old, new in pairs:
        key_old, key_new = ds.image_key(old), ds.image_key(new)
        if key_old in (tpl.get("bild_groesse") or {}):
            sizes[key_new] = tpl["bild_groesse"][key_old]
        if offsets is not None and key_old in (tpl.get("bild_versatz") or {}):
            offsets[key_new] = tpl["bild_versatz"][key_old]


def learned(template: dict) -> list[str]:
    """Was die Vorlage vorgibt, in Worten (für die Vorlagen-Seite)."""
    tpl = ds.normalized(template)
    names = [p["name"] for p in tpl["eigenschaften"] if p["name"]]
    out = []
    if names:
        out.append("Eigenschaften: " + ", ".join(names))
    if tpl["spez"]["zeilen"]:
        out.append("Spezifikation: " + ", ".join(z["merkmal"] for z in tpl["spez"]["zeilen"] if z["merkmal"]))
    labels = {"intro": "Einleitung", "spez": "Spezifikation", "anwendung": "Anwendungsbilder", "tabelle": "Tabelle",
              "bild": "Bild"}
    out.append("Bausteine: " + " → ".join(labels.get(b["typ"], b["typ"]) + (" (aus)" if not b["sichtbar"] else "")
                                         for b in tpl["bloecke"]))
    out.append(f"Bilder: {len(tpl['bilder_oben'])} Produktbild(er), {len(tpl['zeichnungen'])} bei der Spezifikation, "
               f"{len(tpl['bilder_unten'])} Anwendungsbild(er); Aufteilung "
               f"{ds.LEAD_SPLITS.get(tpl.get('aufteilung') or 'normal', ('Standard',))[0]}"
               + (f"; {len(tpl['bild_groesse'])} Bildgröße(n) angepasst" if tpl.get("bild_groesse") else ""))
    bullets = [p["wert"] for p in tpl["eigenschaften"] if not p["name"] and p["wert"]]
    if bullets:
        out.append("Aufzählung: " + " · ".join(bullets[:4]))
    if tpl["einleitung"]:
        out.append("Textstil der Einleitung (für die lokale KI)")
    return out


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def suggest_terms(template: dict, rows: list[dict]) -> list[dict]:
    """Wortvorschläge aus einem Vergleichspaar: Zeilen des Herstellerblatts (merkmal, wert, name = B&B-Zeile oder
    None) gegen die Vorlage desselben Produkts. Nur Wörter, keine Zahlen: Vorschlag nur, wenn die Zahlen gleich sind.
    Ergebnis [{art, begriff, ziel}] – der Admin entscheidet, was ins Wörterbuch kommt."""
    from backend.services import datasheet_import as dsi

    tpl = ds.normalized(template)
    named = {p["name"]: p["wert"] for p in tpl["eigenschaften"] if p["name"] and p["wert"]}
    spec = [(z["merkmal"].strip().rstrip(":"), z["wert"]) for z in tpl["spez"]["zeilen"] if z["merkmal"] and z["wert"]]
    for label, value in spec:
        named.setdefault(label, value)
    out, seen = [], set()

    def add(art, begriff, ziel):
        key = (art, dsi.term_key(begriff))
        if begriff and ziel and key not in seen and dsi.term_key(begriff) != dsi.term_key(ziel):
            seen.add(key)
            out.append({"art": art, "begriff": " ".join(begriff.split())[:120], "ziel": " ".join(ziel.split())[:200]})

    for row in rows:
        label, raw, name = row["merkmal"], (row["wert"] or "").strip(), row.get("name")
        if not raw:
            continue
        mine = dsi.bb_value(name or "", raw)
        if name and name in named:
            target = named[name]
            # gleiche Zahlen, anderer Wortlaut -> Wortwahl (z. B. „Single bolt (M8)“ -> „Schraubmontage (M8)“)
            if mine != target and _numbers(raw) == _numbers(target) and "\n" not in raw and len(raw) <= 80:
                add("WERT", raw, target)
            continue
        # Zeile ohne B&B-Begriff: gleicher Wert in der Vorlage -> deren Zeilenname ist unser Wort für das Merkmal
        for tpl_label, tpl_value in spec:
            if dsi.term_key(mine) == dsi.term_key(tpl_value) or dsi.term_key(raw) == dsi.term_key(tpl_value):
                add("MERKMAL", label, tpl_label)
                break
    return out
