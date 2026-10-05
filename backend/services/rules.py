"""Regeln anlegen, versionieren, löschen; Kalkulation für eine Preisliste ausführen."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, selectinload

from backend.calculations.engine import PriceInput, RuleDefinition, calculate
from backend.models.entities import Article, CalculationResult, CalculationRun, Rule, RuleVersion, User


def _definition_json(defn: RuleDefinition) -> dict:
    return defn.model_dump(mode="json", exclude_none=True)


def create_rule(db: Session, name: str, manufacturer_id: int | None, defn: RuleDefinition, user: User,
                comment: str | None = None, owner_id: int | None = None) -> Rule:
    rule = Rule(name=name.strip()[:200], manufacturer_id=manufacturer_id, current_version=1,
                owner_id=owner_id if owner_id is not None else user.id)
    db.add(rule)
    db.flush()
    db.add(RuleVersion(rule_id=rule.id, version=1, definition=_definition_json(defn), comment=comment,
                       created_by=user.id))
    db.flush()
    return rule


def new_version(db: Session, rule: Rule, name: str, manufacturer_id: int | None, defn: RuleDefinition,
                user: User, comment: str | None = None) -> RuleVersion:
    if rule.deleted:
        raise ValueError("Regel ist gelöscht")
    version = (db.scalar(select(func.max(RuleVersion.version)).where(RuleVersion.rule_id == rule.id)) or 0) + 1
    rv = RuleVersion(rule_id=rule.id, version=version, definition=_definition_json(defn), comment=comment,
                     created_by=user.id)
    db.add(rv)
    rule.name = name.strip()[:200]
    rule.manufacturer_id = manufacturer_id
    rule.current_version = version
    db.flush()
    return rv


def current_version(db: Session, rule: Rule) -> RuleVersion:
    return db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id,
                                               RuleVersion.version == rule.current_version))


def run_calculation(db: Session, price_list_id: int, rv: RuleVersion, quantity: Decimal, user: User) -> CalculationRun:
    defn = RuleDefinition.model_validate(rv.definition)
    run = CalculationRun(price_list_id=price_list_id, rule_version_id=rv.id, quantity=quantity, created_by=user.id)
    db.add(run)
    db.flush()
    rule = db.get(Rule, rv.rule_id)
    stmt = (select(Article).where(Article.price_list_id == price_list_id).options(selectinload(Article.prices))
            .order_by(Article.source_row))
    if rule.manufacturer_id is not None:
        stmt = stmt.where(Article.manufacturer_id == rule.manufacturer_id)
    rows, counts = [], defaultdict(int)
    for a in db.scalars(stmt):
        inputs = [PriceInput(p.price_type, p.amount, p.currency, p.min_quantity, p.discount_percent, p.transport_cost)
                  for p in a.prices]
        res = calculate(defn, inputs, quantity)
        counts[res.status] += 1
        rows.append({"run_id": run.id, "article_id": a.id, "status": res.status, "start_amount": res.start,
                     "result_amount": res.result, "currency": res.currency, "trace": res.trace, "error": res.error})
    if rows:
        db.execute(insert(CalculationResult), rows)
    run.summary = {"artikel": len(rows), "OK": counts["OK"], "FEHLER": counts["FEHLER"]}
    return run
