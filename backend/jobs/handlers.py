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
from backend.excel.importer import PRICE_TYPE
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
            owner_id = db.get(PriceList, p["price_list_id"]).uploaded_by
            name = p["new_manufacturer"].strip()
            m = db.scalar(select(Manufacturer).where(Manufacturer.name == name, Manufacturer.owner_id == owner_id))
            code = p.get("new_manufacturer_code")
            if m is None:
                m = Manufacturer(name=name, aliases=[], code=code, owner_id=owner_id)
                db.add(m)
                db.flush()
            elif code and not m.code:
                m.code = code
            manufacturer_id = m.id
    strip_prefix = None
    if p.get("strip_code") and manufacturer_id:
        with session_scope() as db:
            strip_prefix = db.get(Manufacturer, manufacturer_id).code
        if not strip_prefix:
            raise ValueError("Kürzel abschneiden gewählt, aber der Hersteller hat kein Kürzel")
    kwargs = dict(strip_prefix=strip_prefix, sheet_name=p["sheet"], header_row=p["header_row"], header_rows=p["header_rows"],
                  manufacturer_id=manufacturer_id, new_manufacturer=None, currency=p.get("currency"),
                  decimal_separators={int(k): v for k, v in p.get("separators", {}).items()},
                  valid_from=p.get("valid_from"), progress=progress)
    split = p.get("split")
    if not split:
        with session_scope() as db:
            pl = db.get(PriceList, p["price_list_id"])
            summary = confirm_import(db, pl, ctx.settings, mapping=p["mapping"], **kwargs)
        ctx.progress(1, 1, "Import abgeschlossen")
        return {"price_list_id": p["price_list_id"], "summary": summary}

    # Eine Datei mit zwei Preisspalten (z. B. EK 2025 und EK 2026): zwei Listen + Vergleich
    list_ids, summaries = [], []
    with session_scope() as db:
        base_name = db.get(PriceList, p["price_list_id"]).name
    for idx, (column, label) in enumerate(zip(split["columns"], split["labels"])):
        mapping = {**p["mapping"], split["field"]: column}
        with session_scope() as db:
            base = db.get(PriceList, p["price_list_id"])
            if idx == 0:
                pl = base
            else:
                pl = PriceList(source_file=base.source_file, stored_file=base.stored_file,
                               file_sha256=base.file_sha256, uploaded_by=base.uploaded_by,
                               status="WARTESCHLANGE", name="", kind=base.kind)
                db.add(pl)
                db.flush()
            pl.name = f"{base_name} – {label}"[:255]
            summaries.append(confirm_import(db, pl, ctx.settings, mapping=mapping, **kwargs))
            list_ids.append(pl.id)
    with session_scope() as db:
        cmp = Comparison(old_price_list_id=list_ids[0], new_price_list_id=list_ids[1], manufacturer_id=None,
                         price_type=PRICE_TYPE[split["field"]], quantity=Decimal(1),
                         created_by=p.get("user_id") or db.get(PriceList, list_ids[0]).uploaded_by)
        db.add(cmp)
        db.flush()
        run_comparison(db, cmp)
        cmp_id = cmp.id
    ctx.progress(1, 1, "Import und Vergleich abgeschlossen")
    return {"price_list_id": list_ids[0], "price_list_ids": list_ids, "summary": summaries[0],
            "summaries": summaries, "comparison_id": cmp_id, "labels": split["labels"]}


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


# ---------- KI: Jahresabgleich (fehlende / unklare Artikel) ----------

def update_targets(db, upd_id: int) -> list[tuple[int, list[int]]]:
    """(Position, Kandidaten aus der Herstellerliste) für fehlende und unklare, noch ungeprüfte Artikel."""
    from backend.models.entities import MatchDecision, PriceUpdate, PriceUpdateItem

    upd = db.get(PriceUpdate, upd_id)
    items = db.scalars(select(PriceUpdateItem).where(PriceUpdateItem.update_id == upd_id)).all()
    used = {i.source_article_id for i in items if i.source_article_id}
    no_match = {(d.manufacturer_id, d.old_number_normalized, d.new_number_normalized)
                for d in db.scalars(select(MatchDecision).where(MatchDecision.decision == "NO_MATCH"))}
    pool_by_mfr: dict = {}
    for a in db.scalars(select(Article).where(Article.price_list_id == upd.source_price_list_id)):
        if a.id not in used and a.article_number:
            pool_by_mfr.setdefault(a.manufacturer_id, []).append(
                Item(a.id, a.manufacturer_id, a.article_number, a.article_number_normalized, a.description))
    targets = []
    for i in items:
        if i.reviewed_at or i.status not in ("NICHT_IN_HERSTELLERLISTE", "NICHT_EINDEUTIG"):
            continue
        if i.status == "NICHT_EINDEUTIG" and i.candidates:
            targets.append((i.id, [c["new_id"] for c in i.candidates][:AI_CANDIDATES]))
            continue
        base = db.get(Article, i.base_article_id)
        if not base or not base.article_number:
            continue
        pool = [p for p in pool_by_mfr.get(base.manufacturer_id, [])
                if (base.manufacturer_id, base.article_number_normalized, p.normalized) not in no_match]
        me = Item(base.id, base.manufacturer_id, base.article_number, base.article_number_normalized, base.description)
        cands = fuzzy_candidates(me, pool, AI_NEW_THRESHOLD, combine="max")[:AI_CANDIDATES]
        # fuzzy_candidates liefert die ID aus dem Pool im Feld old_id; ohne Kandidaten wird die KI nicht gefragt
        targets.append((i.id, [c.old_id for c in cands]))
    return targets


@handler("AI_UPDATE_MATCH")
def ai_update_match(ctx: JobContext, p: dict) -> dict:
    from backend.models.entities import PriceUpdateItem

    upd_id = p["update_id"]
    provider = get_provider(ctx.settings)
    status = provider.status()
    if not status.active:
        raise AIUnavailable(status.message)
    with session_scope() as db:
        targets = update_targets(db, upd_id)
    total = len(targets)
    counts = {"OK": 0, "UNKLAR": 0, "treffer": 0}
    ctx.progress(0, total, f"{total} Artikel prüfen")
    for done, (item_id, cand_ids) in enumerate(targets, start=1):
        ctx.check_cancel()
        if not cand_ids:
            with session_scope() as db:
                db.get(PriceUpdateItem, item_id).ai_hint = {
                    "status": "KEIN_TREFFER", "reason": "Kein ähnlicher Artikel in der Herstellerliste gefunden.",
                    "model": None}
            ctx.progress(done, total, f"{done} von {total}")
            continue
        with session_scope() as db:
            item = db.get(PriceUpdateItem, item_id)
            base = db.get(Article, item.base_article_id)
            cands = {db.get(Article, c).article_number: db.get(Article, c) for c in cand_ids}
            payload = [_article_dict(a) for a in cands.values()]
            ours = _article_dict(base)
        try:
            j = provider.judge_renamed(ours, payload)
            hit = cands.get(j.old_article) if j.match else None
            hint = {"status": "TREFFER" if hit else "KEIN_TREFFER", "new_id": hit.id if hit else None,
                    "number": hit.article_number if hit else None, "description": hit.description if hit else None,
                    "confidence": str(round(j.confidence * 100)), "reason": j.reason[:300], "model": status.model}
            counts["OK"] += 1
            counts["treffer"] += int(bool(hit))
        except AIInvalidResponse as exc:
            hint = {"status": "UNKLAR", "reason": str(exc)[:300], "model": status.model}
            counts["UNKLAR"] += 1
        with session_scope() as db:
            db.get(PriceUpdateItem, item_id).ai_hint = hint
        ctx.progress(done, total, f"{done} von {total}")
    return {"update_id": upd_id, "anfragen": total, **counts}
