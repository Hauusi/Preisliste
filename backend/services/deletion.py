"""Manuelles Löschen von Preislisten, Herstellern und Regeln (mit Folgen-Übersicht für die Bestätigung)."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models import entities as e


def price_list_impact(db: Session, pl: e.PriceList) -> list[str]:
    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery()))
    articles = count(select(e.Article.id).where(e.Article.price_list_id == pl.id))
    calcs = count(select(e.CalculationRun.id).where(e.CalculationRun.price_list_id == pl.id))
    cmps = count(select(e.Comparison.id).where(or_(e.Comparison.old_price_list_id == pl.id,
                                                   e.Comparison.new_price_list_id == pl.id)))
    upds = count(select(e.PriceUpdate.id).where(or_(e.PriceUpdate.base_price_list_id == pl.id,
                                                    e.PriceUpdate.source_price_list_id == pl.id)))
    return [f"{articles} Artikel mit Preisen und Importmeldungen", f"{calcs} Kalkulation(en)",
            f"{cmps} Vergleich(e), in denen die Liste vorkommt", f"{upds} neue Preisliste(n), die darauf aufbauen",
            "die hochgeladene Excel-Datei (falls keine andere Liste sie nutzt)"]


def delete_price_list(db: Session, pl: e.PriceList, settings: Settings) -> None:
    from backend.services.imports import stored_path

    shared = db.scalar(select(func.count(e.PriceList.id)).where(e.PriceList.stored_file == pl.stored_file,
                                                                e.PriceList.id != pl.id))
    path = stored_path(pl, settings)
    for model, cond in (
        (e.PriceUpdate, or_(e.PriceUpdate.base_price_list_id == pl.id, e.PriceUpdate.source_price_list_id == pl.id)),
        (e.Comparison, or_(e.Comparison.old_price_list_id == pl.id, e.Comparison.new_price_list_id == pl.id)),
        (e.CalculationRun, e.CalculationRun.price_list_id == pl.id),
    ):
        db.execute(delete(model).where(cond))  # Unterobjekte per ON DELETE CASCADE
    db.delete(pl)
    db.flush()
    if not shared:
        path.unlink(missing_ok=True)


def manufacturer_impact(db: Session, m: e.Manufacturer) -> tuple[list[str], str | None]:
    """(Folgen, Hinderungsgrund). Hersteller mit Artikeln wird nicht gelöscht."""
    used = db.scalar(select(func.count(func.distinct(e.Article.price_list_id))).where(e.Article.manufacturer_id == m.id))
    if used:
        return [], (f"{m.name} kommt noch in {used} Preisliste(n) vor. Bitte zuerst diese Preislisten löschen.")
    rules = db.scalar(select(func.count(e.Rule.id)).where(e.Rule.manufacturer_id == m.id, e.Rule.deleted.is_(False)))
    return [f"{rules} Regel(n) bleiben erhalten, gelten danach für alle Hersteller" if rules else "keine Regeln betroffen",
            "bestätigte Zuordnungen dieses Herstellers"], None


def delete_manufacturer(db: Session, m: e.Manufacturer) -> None:
    db.execute(update(e.Rule).where(e.Rule.manufacturer_id == m.id).values(manufacturer_id=None))
    db.execute(delete(e.MatchDecision).where(e.MatchDecision.manufacturer_id == m.id))
    db.execute(delete(e.RuleException).where(e.RuleException.manufacturer_id == m.id))
    db.delete(m)
    db.flush()


def rule_impact(db: Session, rule: e.Rule) -> list[str]:
    users = db.scalars(select(e.Manufacturer.name).where(e.Manufacturer.default_rule_id == rule.id)).all()
    exc = db.scalars(select(e.RuleException).where(e.RuleException.rule_id == rule.id)).all()
    extra = [f"{len(exc)} Serien-Ausnahme(n) mit dieser Regel werden entfernt"] if exc else []
    return extra + [f"alle {len(rule.versions)} Version(en) werden ausgeblendet; bisherige Kalkulationen bleiben nachvollziehbar",
            ("Standardregel von " + ", ".join(users) + " wird entfernt") if users else "ist bei keinem Hersteller Standardregel"]


def delete_rule(db: Session, rule: e.Rule) -> None:
    # Regelversionen sind unveränderlich und werden von alten Ergebnissen referenziert: nur ausblenden
    rule.deleted = True
    db.execute(update(e.Manufacturer).where(e.Manufacturer.default_rule_id == rule.id).values(default_rule_id=None))
    db.execute(delete(e.RuleException).where(e.RuleException.rule_id == rule.id))
    db.flush()
