"""Kennzahlen und Aufgaben für das Dashboard (nur lesend)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.services.calc_setup import describe, factor_of, rounding_of
from backend.models.entities import (
    Article,
    AuditLog,
    Manufacturer,
    PriceList,
    PriceUpdate,
    PriceUpdateItem,
    Rule,
    RuleException,
    utcnow,
)

ACTION_LABELS = {
    "import_gestartet": "Liste importiert", "jahresabgleich": "Jahresabgleich gestartet",
    "abgleich_sammelbestaetigung": "Positionen bestätigt", "abgleich_position_bestaetigen": "Position bestätigt",
    "abgleich_position_zuordnen": "Zuordnung entschieden", "abgleich_uebernommen": "Als aktuelle Liste übernommen",
    "neue_artikel_aufgenommen": "Neue Artikel aufgenommen", "artikel_ausnahme_setzen": "Eigene Kalkulation gesetzt",
    "artikel_ausnahme_entfernen": "Eigene Kalkulation entfernt", "export": "Export", "export_entwurf": "Entwurf exportiert",
    "hersteller_angelegt": "Hersteller angelegt", "hersteller_geaendert": "Hersteller geändert",
    "regel_angelegt": "Regel angelegt", "regel_geaendert": "Regel geändert", "login": "Anmeldung",
}


def _list_manufacturers(db: Session) -> dict[int, int | None]:
    """Hersteller je Liste: fest gewählt oder einziger Hersteller der Artikel."""
    out = {}
    rows = db.execute(select(Article.price_list_id, func.min(Article.manufacturer_id), func.max(Article.manufacturer_id))
                      .group_by(Article.price_list_id)).all()
    by_articles = {lid: (lo if lo == hi else None) for lid, lo, hi in rows}
    for pl in db.scalars(select(PriceList)):
        out[pl.id] = pl.manufacturer_id or by_articles.get(pl.id)
    return out


def _avg(values: list[Decimal]) -> Decimal | None:
    return (sum(values) / len(values)).quantize(Decimal("0.1")) if values else None


def build(db: Session, user) -> dict:
    """Alles nur aus Sicht des Benutzers (Admin: alles)."""
    from backend.services.access import is_admin, visible

    lists = db.scalars(visible(select(PriceList).order_by(PriceList.id.desc()), PriceList, user)).all()
    list_mfr = _list_manufacturers(db)
    updates = db.scalars(visible(select(PriceUpdate).order_by(PriceUpdate.id.desc()), PriceUpdate, user)).all()
    manufacturers = db.scalars(visible(select(Manufacturer).order_by(Manufacturer.name), Manufacturer, user)).all()
    rules = {r.id: r for r in db.scalars(visible(select(Rule).where(Rule.deleted.is_(False)), Rule, user))}
    counts = dict(db.execute(select(Article.price_list_id, func.count()).group_by(Article.price_list_id)).all())
    exc_counts = dict(db.execute(select(RuleException.manufacturer_id, func.count())
                                 .group_by(RuleException.manufacturer_id)).all())
    used_sources = {u.source_price_list_id for u in updates}

    cards, todo = [], []
    for m in manufacturers:
        mine = [pl for pl in lists if pl.status == "IMPORTIERT" and list_mfr.get(pl.id) == m.id]
        current = next((pl for pl in mine if pl.kind == "UNSERE"), None)
        latest_mfr = next((pl for pl in mine if pl.kind == "HERSTELLER"), None)
        upd = next((u for u in updates if list_mfr.get(u.base_price_list_id) == m.id), None)
        ek_avg = vk_avg = None
        if upd:
            rows = db.execute(select(PriceUpdateItem.difference_percent, PriceUpdateItem.vk_difference_percent)
                              .where(PriceUpdateItem.update_id == upd.id, PriceUpdateItem.decision == "NEU")).all()
            ek_avg = _avg([r[0] for r in rows if r[0] is not None])
            vk_avg = _avg([r[1] for r in rows if r[1] is not None])
        rule = rules.get(m.default_rule_id)
        cards.append({"m": m, "current": current, "articles": counts.get(current.id, 0) if current else 0,
                      "latest_mfr": latest_mfr, "upd": upd, "ek_avg": ek_avg, "vk_avg": vk_avg, "rule": rule,
                      "factor": factor_of(db, m), "calc_text": describe(factor_of(db, m), rounding_of(db, m)),
                      "exceptions": exc_counts.get(m.id, 0),
                      "pending_source": latest_mfr if latest_mfr and latest_mfr.id not in used_sources else None})
        if rule is None:
            todo.append(("warn", f"{m.name}: keine Standardregel", "Ohne Regel kann kein VK berechnet werden.",
                         f"/hersteller/{m.id}", "Regel festlegen"))
        if current is None:
            todo.append(("info", f"{m.name}: noch keine aktuelle EK/VK-Liste",
                         "Unsere Liste importieren und in Schritt 3 „Unsere Liste“ wählen.", "/import", "Importieren"))
        if latest_mfr and latest_mfr.id not in used_sources and current:
            todo.append(("info", f"{m.name}: neue Herstellerliste noch nicht abgeglichen", latest_mfr.name,
                         f"post:/hersteller/{m.id}/abgleich", "Abgleich starten"))

    for u in updates:
        s = u.summary or {}
        if s.get("offen"):
            who = u.base_list.manufacturer.name if u.base_list.manufacturer else u.base_list.name
            todo.insert(0, ("err", f"{who}: {s['offen']} Positionen prüfen", f"Jahresabgleich vom {u.created_at:%d.%m.%Y}",
                            f"/aktualisierungen/{u.id}?status=offen", "Jetzt prüfen"))
        elif not u.adopted_list_id and u is next((x for x in updates if x.base_price_list_id == u.base_price_list_id), None):
            who = u.base_list.manufacturer.name if u.base_list.manufacturer else u.base_list.name
            todo.append(("ok", f"{who}: geprüft – jetzt abschließen", "übernehmen und Excel herunterladen",
                         f"/aktualisierungen/{u.id}", "Abschließen"))
    for pl in lists:
        if pl.status == "ENTWURF":
            todo.append(("warn", "Import nicht abgeschlossen", pl.source_file, f"/import/{pl.id}", "Fortsetzen"))

    def own(stmt):
        return stmt if is_admin(user) else stmt.where(AuditLog.user_id == user.id)

    year_start = utcnow().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    current_ids = [c["current"].id for c in cards if c["current"]]
    kpis = {
        "manufacturers": len(manufacturers),
        "articles": sum(counts.get(i, 0) for i in current_ids),
        "open": sum((u.summary or {}).get("offen", 0) for u in updates),
        "updates_year": sum(1 for u in updates if u.created_at >= year_start),
        "adopted_year": sum(1 for u in updates if u.created_at >= year_start and u.adopted_list_id),
        "new_articles_30d": sum(len((a.details or {}).get("artikel", [])) for a in db.scalars(
            own(select(AuditLog).where(AuditLog.action == "neue_artikel_aufgenommen",
                                       AuditLog.timestamp >= utcnow() - timedelta(days=30))))),
    }
    activity = db.scalars(own(select(AuditLog).where(AuditLog.action.in_(list(ACTION_LABELS)), AuditLog.action != "login"))
                          .order_by(AuditLog.id.desc()).limit(8)).all()
    setup = {"manufacturer": bool(manufacturers), "rule": any(c["rule"] for c in cards),
             "ours": any(c["current"] for c in cards), "update": bool(updates)}
    from backend.models.entities import User

    owners = {u.id: u.username for u in db.scalars(select(User))} if is_admin(user) else {}
    return {"owners": owners, "cards": cards, "todo": todo, "kpis": kpis, "activity": activity, "labels": ACTION_LABELS,
            "setup": setup, "drafts": [pl for pl in lists if pl.status == "ENTWURF"]}
