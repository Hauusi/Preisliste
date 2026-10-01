"""Job-Handler. Jeder Handler arbeitet mit eigenen, kurzen Transaktionen."""

from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import delete, select

from backend.ai.provider import AIInvalidResponse, AIUnavailable, get_provider
from backend.calculations.engine import RuleDefinition
from backend.comparison.service import run_comparison
from backend.database.engine import session_scope
from backend.excel import columns as col
from backend.excel.reader import read_sheet
from backend.jobs.runner import JobContext, handler
from backend.matching.cascade import Item, fuzzy_candidates
from backend.models.entities import AiMatchSuggestion, Article, Comparison, ComparisonItem, Manufacturer, PriceList
from backend.services.imports import confirm_import, stored_path

AI_CANDIDATES = 5
AI_NEW_THRESHOLD = 50


# ---------- Import ----------

@handler("IMPORT")
def import_job(ctx: JobContext, p: dict) -> dict:
    def progress(done, total):
        ctx.check_cancel()
        ctx.progress(done, total, f"Zeile {done} von {total}")

    manufacturer_id = p.get("manufacturer_id")
    if p.get("new_manufacturer"):
        # Eigene kurze Transaktion, damit die Schreibsperre nicht während des Einlesens gehalten wird
        with session_scope() as db:
            name = p["new_manufacturer"].strip()
            m = db.scalar(select(Manufacturer).where(Manufacturer.name == name))
            if m is None:
                m = Manufacturer(name=name, aliases=[])
                db.add(m)
                db.flush()
            manufacturer_id = m.id
    with session_scope() as db:
        pl = db.get(PriceList, p["price_list_id"])
        summary = confirm_import(
            db, pl, ctx.settings, sheet_name=p["sheet"], header_row=p["header_row"], header_rows=p["header_rows"],
            mapping=p["mapping"], manufacturer_id=manufacturer_id, new_manufacturer=None,
            currency=p.get("currency"), decimal_separators={int(k): v for k, v in p.get("separators", {}).items()},
            valid_from=p.get("valid_from"), progress=progress,
        )
    ctx.progress(1, 1, "Import abgeschlossen")
    return {"price_list_id": p["price_list_id"], "summary": summary}


@handler("IMPORT:finally")
def import_finally(ctx: JobContext, p: dict) -> None:
    """Bei Fehler oder Abbruch zurück auf ENTWURF, damit die Zuordnung korrigiert werden kann."""
    if p["_status"] == "FERTIG":
        return
    with session_scope() as db:
        pl = db.get(PriceList, p["price_list_id"])
        if pl is not None and pl.status == "WARTESCHLANGE":
            pl.status = "ENTWURF"


def recover_price_lists() -> None:
    from backend.models.entities import Job

    with session_scope() as db:
        waiting = {j.params.get("price_list_id") for j in db.scalars(
            select(Job).where(Job.type == "IMPORT", Job.status.in_(("WARTEND", "LAEUFT"))))}
        for pl in db.scalars(select(PriceList).where(PriceList.status == "WARTESCHLANGE")):
            if pl.id not in waiting:
                pl.status = "ENTWURF"


# ---------- KI: Spalten ----------

@handler("AI_COLUMNS")
def ai_columns(ctx: JobContext, p: dict) -> dict:
    with session_scope() as db:
        pl = db.get(PriceList, p["price_list_id"])
        path = stored_path(pl, ctx.settings)
    sheet = read_sheet(path, p["sheet"], max_rows=p["header_row"] + 5)
    labels = col.header_labels(sheet, p["header_row"], p.get("header_rows", 1))
    samples = sheet.rows[p["header_row"]: p["header_row"] + 5]
    ctx.progress(0, 1, "KI wird gefragt (kann auf CPU bis zu einer Minute dauern)")
    provider = get_provider(ctx.settings)
    try:
        s = provider.suggest_columns(labels, samples)
    except AIInvalidResponse as exc:
        return {"status": "UNKLAR", "message": str(exc)}
    except AIUnavailable as exc:
        return {"status": "FEHLER", "message": str(exc)}
    ctx.progress(1, 1)
    return {"status": "OK", "sheet": p["sheet"], "header_row": p["header_row"],
            "columns": {str(c.index): c.field for c in s.columns if c.field},
            "manufacturer": s.manufacturer, "confidence": s.confidence}


# ---------- KI: Regelvorschlag ----------

@handler("AI_RULE")
def ai_rule(ctx: JobContext, p: dict) -> dict:
    ctx.progress(0, 1, "KI wird gefragt")
    try:
        s = get_provider(ctx.settings).suggest_rule(p["text"])
    except AIInvalidResponse as exc:
        return {"status": "UNKLAR", "message": str(exc)}
    except AIUnavailable as exc:
        return {"status": "FEHLER", "message": str(exc)}
    data = {"start_price": s.start_price, "steps": s.steps}
    try:
        RuleDefinition.model_validate(data)
    except ValidationError as exc:
        return {"status": "UNKLAR", "message": f"KI-Vorschlag ist keine gültige Regel: {exc.errors()[0]['msg']}",
                "definition": data, "explanation": s.explanation}
    ctx.progress(1, 1)
    return {"status": "OK", "definition": data, "explanation": s.explanation}


# ---------- KI: Zuordnung ----------

def _article_dict(a: Article) -> dict:
    return {"artikelnummer": a.article_number, "bezeichnung": (a.description or "")[:200],
            "kategorie": a.category}


def _targets(db, cmp_id: int) -> list[tuple[int, list[int]]]:
    """(neuer Artikel, Kandidaten alt) für unscharfe Fälle und neue Artikel mit möglichen Vorgängern."""
    items = db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id)).all()
    targets = []
    gone = [i for i in items if i.status == "ENTFALLENER_ARTIKEL"]
    gone_by_mfr: dict = {}
    for g in gone:
        a = db.get(Article, g.old_article_id)
        gone_by_mfr.setdefault(a.manufacturer_id, []).append(
            Item(a.id, a.manufacturer_id, a.article_number, a.article_number_normalized, a.description))
    for i in items:
        if i.status == "NICHT_EINDEUTIG" and i.match_method in ("UNSCHARF", "KI") and i.candidates:
            targets.append((i.new_article_id, [c["old_id"] for c in i.candidates]))
        elif i.status == "NEUER_ARTIKEL" and i.new_article_id:
            a = db.get(Article, i.new_article_id)
            pool = gone_by_mfr.get(a.manufacturer_id, [])
            if pool:
                n = Item(a.id, a.manufacturer_id, a.article_number, a.article_number_normalized, a.description)
                cands = fuzzy_candidates(n, pool, AI_NEW_THRESHOLD, combine="max")[:AI_CANDIDATES]
                if cands:
                    targets.append((a.id, [c.old_id for c in cands]))
    return targets


@handler("AI_MATCH")
def ai_match(ctx: JobContext, p: dict) -> dict:
    cmp_id = p["comparison_id"]
    provider = get_provider(ctx.settings)
    status = provider.status()
    if not status.active:
        raise AIUnavailable(status.message)
    with session_scope() as db:
        targets = _targets(db, cmp_id)
        db.execute(delete(AiMatchSuggestion).where(AiMatchSuggestion.comparison_id == cmp_id))
    total = len(targets)
    counts = {"OK": 0, "UNKLAR": 0, "treffer": 0}
    ctx.progress(0, total, f"{total} Artikel an die KI")
    try:
        for done, (new_id, cand_ids) in enumerate(targets, start=1):
            ctx.check_cancel()
            with session_scope() as db:
                new = db.get(Article, new_id)
                cands = {db.get(Article, c).article_number: c for c in cand_ids}
                payload = [_article_dict(db.get(Article, c)) for c in cand_ids]
                new_payload = _article_dict(new)
            try:
                j = provider.judge_match(new_payload, payload)
                row = {"match": j.match, "old_article_id": cands.get(j.old_article) if j.match else None,
                       "confidence": Decimal(str(round(j.confidence, 3))), "reason": j.reason, "status": "OK"}
                counts["OK"] += 1
                counts["treffer"] += int(j.match)
            except AIInvalidResponse as exc:
                row = {"match": False, "old_article_id": None, "confidence": None, "reason": str(exc)[:500],
                       "status": "UNKLAR"}
                counts["UNKLAR"] += 1
            with session_scope() as db:
                db.add(AiMatchSuggestion(comparison_id=cmp_id, new_article_id=new_id, model=status.model, **row))
            ctx.progress(done, total, f"{done} von {total}")
    finally:
        # Vorschläge immer einarbeiten, auch nach Abbruch oder Fehler
        with session_scope() as db:
            run_comparison(db, db.get(Comparison, cmp_id))
    return {"comparison_id": cmp_id, "anfragen": total, **counts}
