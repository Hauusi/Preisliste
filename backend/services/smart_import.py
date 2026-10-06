"""Smarter Import: erkennt aus einer hochgeladenen Datei alles Nötige und macht einen Vorschlag.

Erkannt werden Tabellenblatt, Kopfzeile, Spalten, Hersteller (Name/Kürzel/Dateiname), Art der Liste
(unsere EK/VK-Liste oder neue Herstellerliste), Währung, ob die Nummern unser Kürzel enthalten und – bei einer
Herstellerliste – wie viele unserer Artikel darin vorkommen (Teilliste?). Nichts wird geraten, was Geld kostet:
alles, was unklar ist, erscheint als Hinweis bzw. blockierender Punkt auf der Prüfseite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import FormData

from backend.comparison.update import manufacturer_settings
from backend.config import Settings
from backend.excel.importer import cell_text, normalize_article_number
from backend.excel.numbers import SUPPORTED_CURRENCIES
from backend.excel.reader import read_sheet
from backend.matching.cascade import strip_zeros
from backend.models.entities import Article, Manufacturer, PriceList, Rule
from backend.services.calc_setup import describe, factor_of, rounding_of
from backend.services.imports import build_preview, stored_path
from backend.services.updates import current_list

PRICE_KEYS = ("supplier_price", "list_price", "rrp")
PARTIAL_SHARE = 0.5  # weniger als die Hälfte unserer Artikel in der Liste -> Teilliste vorschlagen
_CURRENCY_RE = re.compile(r"\b(" + "|".join(SUPPORTED_CURRENCIES) + r")\b")


@dataclass
class Proposal:
    pv: object
    cols: dict
    manufacturer: Manufacturer | None
    manufacturers: list[Manufacturer]
    kind: str
    currency: str
    currency_source: str
    strip_code: bool
    base: PriceList | None = None
    rule: Rule | None = None
    factor: object = None
    scope: str = "VOLL"
    scope_suggested: str = "VOLL"
    stats: dict = field(default_factory=dict)
    sample: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    total_rows: int = 0
    prefix_share: float = 0.0
    calc_text: str = ""  # Anteil der Nummern, die mit dem Kürzel des Herstellers beginnen

    @property
    def ready(self) -> bool:
        return not self.issues and not self.cols["errors"]


def columns_from_detection(pv) -> dict:
    """Spaltenzuordnung im selben Format wie das Formular (für _parse_columns)."""
    from backend.api.routes_imports import _parse_columns

    items = [("sheet", pv.sheet.name), ("header_row", str(pv.detection.header_row)),
             ("header_rows", str(pv.detection.header_rows))]
    for c in pv.detection.columns:
        if c.field:
            items.append((f"col_{c.index}", c.field))
    for idx, sep in pv.detection.decimal_separators.items():
        if sep:
            items.append((f"sep_{idx}", sep))
    return _parse_columns(FormData(items))


def _currency_in_file(pv, mapping: dict | None = None) -> str | None:
    """Währung der verwendeten Preisspalten; sonst aus allen Überschriften und Titelzeilen, wenn eindeutig."""
    if mapping:
        by_index = {c.index: c for c in pv.detection.columns}
        used = {by_index[i].currency for f, i in mapping.items() if f in PRICE_KEYS and i in by_index}
        used.discard(None)
        if len(used) == 1:
            return used.pop()
        if len(used) > 1:
            return None
    texts = [c.label or "" for c in pv.detection.columns if not c.alt_field]
    texts += [str(v) for row in pv.sheet.rows[:max(pv.detection.header_row - 1, 0)] for v in row if v]
    found = {m.group(1) for t in texts for m in _CURRENCY_RE.finditer(str(t).upper())}
    return found.pop() if len(found) == 1 else None


def _norm(number: str, m: Manufacturer | None) -> str:
    n = normalize_article_number(number)
    return strip_zeros(n) if m and m.ignore_leading_zeros else n


def build_proposal(db: Session, pl: PriceList, settings: Settings, overrides: dict | None = None,
                   stored_cols: dict | None = None) -> Proposal:
    o = overrides or {}
    pv = build_preview(db, pl, settings, (stored_cols or {}).get("sheet") or None,
                       (stored_cols or {}).get("header_row"), (stored_cols or {}).get("header_rows"))
    cols = stored_cols or columns_from_detection(pv)
    mapping = cols["mapping"]
    mfrs = db.scalars(select(Manufacturer).where(Manufacturer.owner_id == pl.uploaded_by)
                      .order_by(Manufacturer.name)).all()

    # Hersteller: Auswahl des Benutzers > Erkennung
    m = None
    if o.get("manufacturer_id") == "neu":
        m = None
    elif o.get("manufacturer_id"):
        m = next((x for x in mfrs if str(x.id) == str(o["manufacturer_id"])), None)
    elif pv.manufacturer_suggestion:
        m = next((x for x in mfrs if x.id == pv.manufacturer_suggestion), None)

    has_ek, has_vk = "supplier_price" in mapping, "list_price" in mapping
    kind = o.get("kind") if o.get("kind") in ("UNSERE", "HERSTELLER") else ("UNSERE" if has_ek and has_vk else "HERSTELLER")
    st = manufacturer_settings(m)

    # Herstellerliste mit nur einer allgemeinen „Preis“-Spalte: Bedeutung kommt aus der Hersteller-Einstellung
    remapped = None
    pending_hints: list[str] = []
    prices_mapped = [f for f in ("supplier_price", "list_price", "rrp") if f in mapping]
    if kind == "HERSTELLER" and m and stored_cols is None and prices_mapped == ["list_price"]:
        target = "rrp" if st["basis"] == "UVP" else "supplier_price"
        idx = mapping.pop("list_price")
        mapping[target] = idx
        cols["assigned"][target] = cols["assigned"].pop("list_price")
        remapped = next((c.label for c in pv.detection.columns if c.index == idx), None) or f"Spalte {idx + 1}"
        remapped = (remapped, "UVP" if target == "rrp" else "EK")

    # Gleiche Preisart in mehreren Währungen (z. B. „Nettoeinkauf SEK“ und „Nettoeinkauf Euro“):
    # gewählte Währung > Hersteller-Einstellung (Herstellerliste) > Euro bestimmt, welche Spalte gilt.
    by_index = {c.index: c for c in pv.detection.columns}
    alternates = [c for c in pv.detection.columns if c.alt_field and c.currency]
    if alternates and stored_cols is None:
        wanted = o.get("currency") if o.get("currency") in SUPPORTED_CURRENCIES else (
            st["currency"] if kind == "HERSTELLER" and m else "EUR")
        candidates = {alt.alt_field: {mapping[alt.alt_field]} for alt in alternates if alt.alt_field in mapping}
        for alt in alternates:
            candidates.setdefault(alt.alt_field, set()).add(alt.index)
            cur_idx = mapping.get(alt.alt_field)
            if alt.currency == wanted and cur_idx is not None and by_index[cur_idx].currency != wanted:
                mapping[alt.alt_field] = alt.index
                cols["assigned"][alt.alt_field] = [alt.index]
        for fld, idxs in candidates.items():
            used = by_index[mapping[fld]]
            for i in sorted(idxs - {mapping[fld]}):
                pending_hints.append(f"Spalte „{by_index[i].label}“ ({by_index[i].currency}) wird nicht verwendet – "
                                     f"es gilt „{used.label}“ ({used.currency}). Andere Spalte: Währung oben umstellen.")
    used_cur = {by_index[i].currency for f, i in mapping.items() if f in PRICE_KEYS and by_index.get(i)}

    file_cur = _currency_in_file(pv, mapping)
    if o.get("currency") in SUPPORTED_CURRENCIES:
        currency, source = o["currency"], "gewählt"
    elif file_cur:
        currency, source = file_cur, "aus der Datei"
    elif kind == "HERSTELLER" and m:
        currency, source = st["currency"], "laut Hersteller-Einstellung"
    else:
        currency, source = "EUR", "Standard"

    if "strip_code" in o:
        strip = o["strip_code"] in ("1", True)
    else:
        strip = bool(m and m.code and pv.prefix_suggestion)

    p = Proposal(pv=pv, cols=cols, manufacturer=m, manufacturers=list(mfrs), kind=kind, currency=currency,
                 currency_source=source, strip_code=strip, settings=st)

    # Alle Nummern der Datei (für Abdeckung und Statistik)
    nr_col = mapping.get("article_number")
    numbers: list[str] = []
    if nr_col is not None:
        full = read_sheet(stored_path(pl, settings), pv.sheet.name)
        for row in full.rows[cols["header_row"]:]:
            text = cell_text(row[nr_col]) if nr_col < len(row) else None
            if text:
                if strip and m and m.code and text.upper().startswith(m.code) and len(text) > len(m.code):
                    text = text[len(m.code):]
                numbers.append(text)
    p.total_rows = len(numbers)
    if m and m.code and numbers:
        raw_numbers = numbers if not strip else None
        if raw_numbers is None:  # Kürzel wurde schon abgeschnitten -> Anteil aus der Erkennung
            p.prefix_share = 1.0
        else:
            p.prefix_share = sum(1 for n in numbers if n.upper().startswith(m.code)) / len(numbers)

    # Beispielzeilen so, wie sie gespeichert und angezeigt werden
    for row in pv.sample_rows[:6]:
        def val(f):
            i = mapping.get(f)
            return row[i] if i is not None and i < len(row) else None
        raw = cell_text(val("article_number")) or ""
        nr = raw[len(m.code):] if strip and m and m.code and raw.upper().startswith(m.code) else raw
        if not raw:
            continue
        p.sample.append({"raw": raw, "display": f"{m.code}{nr}" if m and m.code else nr,
                         "description": val("description"), "ek": val("supplier_price"),
                         "vk": val("list_price"), "uvp": val("rrp")})

    # Blockierende Punkte und Hinweise
    if cols["errors"]:
        p.issues.append("Spalten nicht vollständig erkannt: " + "; ".join(cols["errors"]))
    if m is None and o.get("manufacturer_id") != "neu" and "manufacturer" not in mapping:
        p.issues.append("Hersteller wählen oder neu anlegen")
    if o.get("manufacturer_id") == "neu" and kind == "HERSTELLER":
        p.issues.append("Ein neuer Hersteller hat noch keine eigene EK/VK-Liste – diese Datei als „Unsere Liste“ "
                        "importieren oder zuerst unsere Liste einspielen")
    used_cur.discard(None)
    if len(used_cur) > 1:
        p.issues.append("Die verwendeten Preisspalten haben verschiedene Währungen ("
                        + ", ".join(sorted(used_cur)) + ") – bitte unter „Spalten anpassen“ korrigieren")
    elif used_cur and currency not in used_cur:
        p.issues.append(f"Die Preisspalten sind in {used_cur.pop()}, gewählt ist {currency}")
    has_ek, has_vk = "supplier_price" in mapping, "list_price" in mapping
    if kind == "UNSERE":
        if not has_ek:
            p.issues.append("Unsere Liste braucht eine EK-Spalte")
        if not has_vk:
            p.issues.append("Unsere Liste braucht eine VK-Spalte")
        if m and current_list(db, m):
            p.hints.append(f"Für {m.name} gibt es schon eine aktuelle Liste („{current_list(db, m).name}“). "
                           "Diese Datei wird die neue aktuelle Liste.")
    elif m is not None:
        p.base = current_list(db, m)
        rule = db.get(Rule, m.default_rule_id) if m.default_rule_id else None
        p.rule = rule if rule is not None and not rule.deleted else None
        p.factor = factor_of(db, m)
        p.calc_text = describe(p.factor, rounding_of(db, m))
        if p.base is None:
            p.issues.append(f"Für {m.name} gibt es noch keine eigene EK/VK-Liste. Erst unsere Liste vom Vorjahr "
                            "einspielen – oder diese Datei als „Unsere Liste“ importieren.")
        if p.rule is None:
            p.issues.append(f"Für {m.name} ist noch keine Kalkulation hinterlegt (Faktor fehlt)")
        if st["basis"] == "UVP" and "rrp" not in mapping:
            p.issues.append(f"{m.name} ist auf UVP-Listen eingestellt, in der Datei wurde aber keine UVP-Spalte erkannt")
        if st["basis"] == "EK" and "supplier_price" not in mapping:
            p.issues.append(f"{m.name} ist auf EK-Listen eingestellt, in der Datei wurde aber keine EK-Spalte erkannt "
                            "(UVP-Liste? Dann beim Hersteller „UVP“ und Händlerrabatt einstellen)")
        if st["basis"] == "UVP" and st["discount"] is None:
            p.issues.append(f"Händlerrabatt für {m.name} fehlt (EK = UVP − Rabatt)")
        if currency != st["currency"]:
            p.issues.append(f"Die Liste ist in {currency}, {m.name} ist auf {st['currency']} eingestellt")
        elif currency != "EUR" and st["rate"] is None:
            p.issues.append(f"Umrechnungskurs {currency} → EUR fehlt bei {m.name}")
        if p.base is not None:
            ours = db.scalars(select(Article.article_number).where(Article.price_list_id == p.base.id,
                                                                  Article.article_number.is_not(None))).all()
            ours_n = {_norm(n, m) for n in ours}
            file_n = {_norm(n, m) for n in numbers}
            found = len(ours_n & file_n)
            p.stats = {"ours": len(ours_n), "found": found, "missing": len(ours_n - file_n),
                       "new": len(file_n - ours_n)}
            if ours_n and found == 0:
                p.issues.append("Keiner unserer Artikel wurde in der Datei gefunden – falscher Hersteller oder "
                                "Kürzel-Einstellung prüfen")
            share = found / len(ours_n) if ours_n else 1
            p.scope_suggested = "TEIL" if share < PARTIAL_SHARE else "VOLL"
    p.scope = o.get("scope") if o.get("scope") in ("VOLL", "TEIL") else p.scope_suggested
    if remapped:
        p.hints.append(f"Die Spalte „{remapped[0]}“ wird als {remapped[1]} gelesen "
                       f"(laut Einstellung schickt {m.name} {remapped[1]}-Preise).")
    p.hints.extend(pending_hints)
    if cols.get("split"):
        p.hints.append("Zwei Preisspalten derselben Art: Die Datei wird in zwei Listen aufgeteilt und automatisch "
                       "verglichen (älteres Jahr bzw. linke Spalte = alt).")
    if pv.duplicate_of:
        p.hints.append(f"Diese Datei wurde bereits importiert ({pv.duplicate_of.name}).")
    return p
