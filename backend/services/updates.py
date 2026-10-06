"""Jahresabgleich anlegen und berechnen (gemeinsam für Formular und automatischen Start nach dem Import)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.comparison.update import SCOPES, manufacturer_settings, run_update, snapshot_exceptions
from backend.models.entities import Article, ArticlePrice, Manufacturer, PriceList, PriceUpdate, Rule
from backend.services.rules import current_version

BASIS_TYPES = ("EK", "UVP")


def list_manufacturer(db: Session, pl: PriceList) -> int | None:
    """Hersteller der Liste: fest gewählt oder der einzige Hersteller der Artikel."""
    if pl.manufacturer_id:
        return pl.manufacturer_id
    mids = set(db.scalars(select(Article.manufacturer_id).distinct().where(Article.price_list_id == pl.id,
                                                                         Article.manufacturer_id.is_not(None))))
    return mids.pop() if len(mids) == 1 else None


def current_list(db: Session, m: Manufacturer) -> PriceList | None:
    """Aktuelle eigene EK/VK-Liste des Herstellers: neueste importierte 'Unsere Liste'."""
    for pl in db.scalars(select(PriceList).where(PriceList.status == "IMPORTIERT", PriceList.kind == "UNSERE",
                                                 PriceList.uploaded_by == m.owner_id)
                         .order_by(PriceList.id.desc())):
        if list_manufacturer(db, pl) == m.id:
            return pl
    return None


def list_currencies(db: Session, pl: PriceList) -> set[str]:
    return set(db.scalars(select(ArticlePrice.currency).distinct().join(Article)
                          .where(Article.price_list_id == pl.id)))


def currency_problems(db: Session, base: PriceList, source: PriceList, settings: dict) -> list[str]:
    """Falsch importierte Währung ist der teuerste Fehler (SEK als EUR = Faktor 10): vorher abfangen."""
    ours, theirs = list_currencies(db, base), list_currencies(db, source)
    errors = []
    if len(ours) > 1:
        errors.append(f"Unsere Liste enthält mehrere Währungen ({', '.join(sorted(ours))})")
    if len(theirs) > 1:
        errors.append(f"Herstellerliste enthält mehrere Währungen ({', '.join(sorted(theirs))})")
    if errors or not ours or not theirs:
        return errors
    our, their = ours.pop(), theirs.pop()
    expected = settings["currency"]
    if their != expected:
        errors.append(f"Herstellerliste ist in {their} importiert, laut Hersteller-Einstellung liefert der Hersteller "
                      f"in {expected}. Bitte Liste mit der richtigen Währung neu importieren oder Einstellung prüfen.")
    elif their != our and not (our == "EUR" and settings["rate"]):
        errors.append(f"Kein Umrechnungskurs {their} → {our} beim Hersteller hinterlegt")
    return errors


def start_update(db: Session, base: PriceList | None, source: PriceList | None, rule: Rule | None,
                 scope: str = "VOLL", price_type: str | None = None,
                 quantity: Decimal = Decimal(1)) -> tuple[PriceUpdate | None, list[str]]:
    """Prüft alles und legt den Abgleich an. (Abgleich, Fehler) – bei Fehlern wird nichts angelegt."""
    errors: list[str] = []
    mfr = None
    if not base or not source or base.status != "IMPORTIERT" or source.status != "IMPORTIERT":
        errors.append("Unsere Liste und Herstellerliste wählen")
    elif base.id == source.id:
        errors.append("Unsere Liste und Herstellerliste müssen verschieden sein")
    elif base.uploaded_by != source.uploaded_by:
        errors.append("Unsere Liste und Herstellerliste müssen demselben Benutzer gehören")
    else:
        if base.kind == "HERSTELLER":
            errors.append(f"„{base.name}“ ist als Herstellerliste importiert, nicht als unsere Liste")
        if source.kind == "UNSERE":
            errors.append(f"„{source.name}“ ist als unsere Liste importiert, nicht als Herstellerliste")
        mb, ms = list_manufacturer(db, base), list_manufacturer(db, source)
        if mb and ms and mb != ms:
            errors.append("Unsere Liste und Herstellerliste gehören zu verschiedenen Herstellern")
        mfr = db.get(Manufacturer, ms or mb) if (ms or mb) else None
    settings = manufacturer_settings(mfr)
    price_type = price_type or settings["basis"]
    if price_type not in BASIS_TYPES:
        errors.append("Herstellerliste enthält: EK oder UVP")
    elif price_type == "UVP" and settings["discount"] is None:
        errors.append("Händlerrabatt beim Hersteller hinterlegen (EK = UVP - Händlerrabatt)")
    if scope not in SCOPES:
        errors.append("Umfang wählen: Jahrespreisliste oder Teilliste")
    if quantity is None or quantity <= 0:
        errors.append("Menge muss größer 0 sein")
    if rule is not None and base is not None and rule.owner_id != base.uploaded_by:
        rule = None  # nur Regeln des Listen-Besitzers
    if rule is None or rule.deleted:
        errors.append("Kalkulationsregel für den VK wählen")
    if not errors:
        errors += currency_problems(db, base, source, settings)
    if errors:
        return None, errors
    upd = PriceUpdate(base_price_list_id=base.id, source_price_list_id=source.id, price_type=price_type,
                      rule_version_id=current_version(db, rule).id, quantity=quantity, created_by=base.uploaded_by,
                      dealer_discount=settings["discount"] if price_type == "UVP" else None,
                      review_threshold=settings["threshold"], scope=scope,
                      list_currency=settings["currency"],
                      exchange_rate=settings["rate"] if settings["currency"] != "EUR" else None,
                      exceptions=snapshot_exceptions(db, mfr.id if mfr else None))
    db.add(upd)
    db.flush()
    run_update(db, upd)
    return upd, []
