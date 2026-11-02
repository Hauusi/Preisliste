"""Design-Vorlagen: ein fertiges B&B-Datenblatt gibt beim Import aus einem Herstellerblatt Aufbau und Stil vor.

Übernommen werden nur Form und Reihenfolge (Eigenschaften, Spezifikationszeilen, Bausteine, Tabellen-Einstellungen)
und der Textstil für die lokale KI – nie Werte, Artikel oder Bilder der Vorlage.
"""

from __future__ import annotations

import re

from backend.services import datasheets as ds

# Einstellungen eines Bausteins, die aus der Vorlage kommen (Inhalt bleibt aus dem Herstellerblatt)
LAYOUT_KEYS = {"tabelle": ("neue_seite", "bild_pos", "zeilenbilder"), "bild": ("neue_seite", "hoehe"),
               "intro": ("neue_seite",), "spez": ("neue_seite",), "anwendung": ("neue_seite",)}


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
    return content
