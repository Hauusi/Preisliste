"""Datenbankmodell Gruppe A. Regeln, Vergleiche und Jobs folgen in Gruppe B/C per Migration."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.database.types import DecimalText


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # admin | benutzer
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class UserSession(Base):
    __tablename__ = "sessions"

    # SHA-256 des Cookie-Werts; der Klartext liegt nur im Browser.
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    # Jeder Benutzer hat eigene Hersteller: Name und Kürzel sind pro Besitzer eindeutig
    __table_args__ = (UniqueConstraint("owner_id", "code", name="uq_manufacturers_owner_code"),
                      UniqueConstraint("owner_id", "name", name="uq_manufacturers_owner_name"))

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_manufacturers_owner"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    # F2: führende Nullen bei rein numerischen Nummern ignorieren ("00123" == "123")
    ignore_leading_zeros: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # Festes Kürzel (z. B. RT), wird in Anzeige und Export vor die Artikelnummer gesetzt
    code: Mapped[str | None] = mapped_column(String(10))
    # Was liefert die Herstellerliste: EK direkt oder UVP (dann EK = UVP - Händlerrabatt)
    list_basis: Mapped[str] = mapped_column(String(5), default="EK", server_default="EK")
    dealer_discount: Mapped[object | None] = mapped_column(DecimalText)
    # Ab dieser EK-Änderung (in %, Betrag) muss ein Artikel geprüft werden
    review_threshold: Mapped[object] = mapped_column(DecimalText, default=Decimal(10), server_default="10")
    # Währung der Herstellerliste und Umrechnung: 1 Einheit list_currency = exchange_rate EUR (z. B. SEK 0,095)
    list_currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    exchange_rate: Mapped[object | None] = mapped_column(DecimalText)
    # Voreingestellte Kalkulationsregel (nur Vorauswahl)
    default_rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", use_alter=True,
                                                                   name="fk_manufacturers_default_rule"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def display_number(self, number: str | None) -> str | None:
        return f"{self.code}{number}" if number and self.code else number


class RuleException(Base):
    """Abweichende Kalkulationsregel für eine Serie (Kategorie) oder einen Nummernanfang eines Herstellers."""

    __tablename__ = "rule_exceptions"
    __table_args__ = (UniqueConstraint("manufacturer_id", "match_type", "value_normalized",
                                       name="uq_rule_exceptions_match"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturers.id", ondelete="CASCADE"), index=True)
    match_type: Mapped[str] = mapped_column(String(10))  # SERIE | PREFIX
    value: Mapped[str] = mapped_column(String(200))
    value_normalized: Mapped[str] = mapped_column(String(200))
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    rule: Mapped["Rule"] = relationship()


class PriceList(Base):
    """Ein Import (Importhistorie). Status: ENTWURF -> IMPORTIERT | FEHLGESCHLAGEN."""

    __tablename__ = "price_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_file: Mapped[str] = mapped_column(String(255))
    stored_file: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    sheet: Mapped[str | None] = mapped_column(String(255))
    header_row: Mapped[int | None] = mapped_column(Integer)
    column_mapping: Mapped[dict | None] = mapped_column(JSON)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    currency: Mapped[str | None] = mapped_column(String(3))
    decimal_separator: Mapped[str | None] = mapped_column(String(1))
    valid_from: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="ENTWURF")
    # UNSERE = unsere EK/VK-Liste, HERSTELLER = neue Liste des Herstellers (None bei Altbestand)
    kind: Mapped[str | None] = mapped_column(String(12))
    summary: Mapped[dict | None] = mapped_column(JSON)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)

    manufacturer: Mapped[Manufacturer | None] = relationship()


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_lookup", "price_list_id", "manufacturer_id", "article_number_normalized"),
        Index("ix_articles_status", "price_list_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    source_row: Mapped[int] = mapped_column(Integer)
    article_number: Mapped[str | None] = mapped_column(String(100))
    article_number_normalized: Mapped[str | None] = mapped_column(String(100))
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    manufacturer_raw: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))  # OK | WARNUNG | UNKLAR | FEHLER
    calc_factor: Mapped[object | None] = mapped_column(DecimalText)  # „Kalk“ aus unserer Liste: VK = EK × Faktor

    prices: Mapped[list["ArticlePrice"]] = relationship(back_populates="article")


class ArticlePrice(Base):
    __tablename__ = "article_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    price_type: Mapped[str] = mapped_column(String(10))  # EK | LISTE | UVP
    amount: Mapped[object] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3))
    min_quantity: Mapped[object | None] = mapped_column(DecimalText)
    discount_percent: Mapped[object | None] = mapped_column(DecimalText)
    transport_cost: Mapped[object | None] = mapped_column(DecimalText)
    valid_from: Mapped[str | None] = mapped_column(String(10))

    article: Mapped[Article] = relationship(back_populates="prices")


class ImportMessage(Base):
    __tablename__ = "import_messages"
    __table_args__ = (Index("ix_import_messages_list", "price_list_id", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    source_row: Mapped[int | None] = mapped_column(Integer)
    column: Mapped[str | None] = mapped_column(String(100))
    level: Mapped[str] = mapped_column(String(10))  # FEHLER | WARNUNG | UNKLAR
    code: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(50))
    entity: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(50))
    details: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_rules_owner"), index=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    manufacturer: Mapped[Manufacturer | None] = relationship(foreign_keys=[manufacturer_id])
    versions: Mapped[list["RuleVersion"]] = relationship(order_by="RuleVersion.version")


class RuleVersion(Base):
    """Unveränderlich: UPDATE und DELETE werden per DB-Trigger verhindert."""

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSON)
    comment: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CalculationRun(Base):
    __tablename__ = "calculation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rule_versions.id"))
    quantity: Mapped[object] = mapped_column(DecimalText)
    summary: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    rule_version: Mapped[RuleVersion] = relationship()


class CalculationResult(Base):
    __tablename__ = "calculation_results"
    __table_args__ = (Index("ix_calc_results_run", "run_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("calculation_runs.id", ondelete="CASCADE"))
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10))
    start_amount: Mapped[object | None] = mapped_column(DecimalText)
    result_amount: Mapped[object | None] = mapped_column(DecimalText)
    currency: Mapped[str | None] = mapped_column(String(3))
    trace: Mapped[list] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)

    article: Mapped[Article] = relationship()


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(primary_key=True)
    old_price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    new_price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    price_type: Mapped[str] = mapped_column(String(10))  # LISTE | EK | UVP | KALKULIERT
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("rule_versions.id"))
    quantity: Mapped[object] = mapped_column(DecimalText)
    summary: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    old_list: Mapped[PriceList] = relationship(foreign_keys=[old_price_list_id])
    new_list: Mapped[PriceList] = relationship(foreign_keys=[new_price_list_id])
    manufacturer: Mapped[Manufacturer | None] = relationship()
    rule_version: Mapped[RuleVersion | None] = relationship()


class ComparisonItem(Base):
    __tablename__ = "comparison_items"
    __table_args__ = (
        Index("ix_comparison_items_status", "comparison_id", "status"),
        Index("ix_comparison_items_new", "comparison_id", "new_article_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id", ondelete="CASCADE"))
    old_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    new_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    article_number: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    min_quantity: Mapped[object | None] = mapped_column(DecimalText)
    status: Mapped[str] = mapped_column(String(25))
    old_amount: Mapped[object | None] = mapped_column(DecimalText)
    new_amount: Mapped[object | None] = mapped_column(DecimalText)
    currency: Mapped[str | None] = mapped_column(String(3))
    difference: Mapped[object | None] = mapped_column(DecimalText)
    difference_percent: Mapped[object | None] = mapped_column(DecimalText)
    match_method: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[object | None] = mapped_column(DecimalText)
    changed_fields: Mapped[list | None] = mapped_column(JSON)
    candidates: Mapped[list | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)

    old_article: Mapped[Article | None] = relationship(foreign_keys=[old_article_id])
    new_article: Mapped[Article | None] = relationship(foreign_keys=[new_article_id])


class MatchDecision(Base):
    """Bestätigte oder abgelehnte Zuordnungen, werden bei späteren Vergleichen wiederverwendet."""

    __tablename__ = "match_decisions"
    __table_args__ = (UniqueConstraint("manufacturer_id", "old_number_normalized", "new_number_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    old_number_normalized: Mapped[str] = mapped_column(String(100))
    new_number_normalized: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(10))  # MATCH | NO_MATCH
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Job(Base):
    """Hintergrundjob. Status: WARTEND -> LAEUFT -> FERTIG | FEHLER | ABGEBROCHEN."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status", "status", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(15), default="WARTEND")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiMatchSuggestion(Base):
    """KI-Vorschlag zu einer Zuordnung. Wird nie automatisch übernommen (F3)."""

    __tablename__ = "ai_match_suggestions"
    __table_args__ = (UniqueConstraint("comparison_id", "new_article_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id", ondelete="CASCADE"))
    new_article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    old_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    match: Mapped[bool] = mapped_column(Boolean)
    confidence: Mapped[object | None] = mapped_column(DecimalText)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))  # OK | UNKLAR
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceUpdate(Base):
    """Neue Preisliste aus Herstellerliste, nur mit den Artikeln unserer Basisliste."""

    __tablename__ = "price_updates"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    source_price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    price_type: Mapped[str] = mapped_column(String(10))
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey("rule_versions.id"))
    quantity: Mapped[object] = mapped_column(DecimalText)
    # Einstellungen zum Zeitpunkt der Berechnung (Nachvollziehbarkeit)
    dealer_discount: Mapped[object | None] = mapped_column(DecimalText)
    review_threshold: Mapped[object | None] = mapped_column(DecimalText)
    # VOLL = Jahrespreisliste (fehlende Artikel prüfen), TEIL = Preiserhöhung einzelner Serien
    scope: Mapped[str] = mapped_column(String(5), default="VOLL", server_default="VOLL")
    list_currency: Mapped[str | None] = mapped_column(String(3))
    exchange_rate: Mapped[object | None] = mapped_column(DecimalText)
    # Ausnahmen zum Zeitpunkt der Berechnung: [{id, typ, wert, rule_version_id, regel}]
    exceptions: Mapped[list | None] = mapped_column(JSON)
    valid_from: Mapped[str | None] = mapped_column(String(10))  # neue Preise gültig ab (JJJJ-MM-TT)
    adopted_list_id: Mapped[int | None] = mapped_column(ForeignKey("price_lists.id", ondelete="SET NULL",
                                                                   name="fk_price_updates_adopted_list"))
    summary: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    base_list: Mapped[PriceList] = relationship(foreign_keys=[base_price_list_id])
    source_list: Mapped[PriceList] = relationship(foreign_keys=[source_price_list_id])
    rule_version: Mapped[RuleVersion | None] = relationship()


class PriceUpdateItem(Base):
    __tablename__ = "price_update_items"
    __table_args__ = (Index("ix_price_update_items_status", "update_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(ForeignKey("price_updates.id", ondelete="CASCADE"))
    base_article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    source_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"))
    article_number: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    old_amount: Mapped[object | None] = mapped_column(DecimalText)
    new_amount: Mapped[object | None] = mapped_column(DecimalText)
    calculated_amount: Mapped[object | None] = mapped_column(DecimalText)
    currency: Mapped[str | None] = mapped_column(String(3))
    difference: Mapped[object | None] = mapped_column(DecimalText)
    difference_percent: Mapped[object | None] = mapped_column(DecimalText)
    match_method: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    trace: Mapped[list | None] = mapped_column(JSON)
    # Jahresabgleich: old_amount = EK alt, new_amount = EK neu, calculated_amount = VK neu
    source_amount: Mapped[object | None] = mapped_column(DecimalText)  # Preis laut Herstellerliste (EK oder UVP)
    vk_old: Mapped[object | None] = mapped_column(DecimalText)
    vk_difference: Mapped[object | None] = mapped_column(DecimalText)
    vk_difference_percent: Mapped[object | None] = mapped_column(DecimalText)
    final_ek: Mapped[object | None] = mapped_column(DecimalText)
    final_vk: Mapped[object | None] = mapped_column(DecimalText)
    decision: Mapped[str | None] = mapped_column(String(10))  # NEU | ALT | MANUELL
    reasons: Mapped[list | None] = mapped_column(JSON)
    candidates: Mapped[list | None] = mapped_column(JSON)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_currency: Mapped[str | None] = mapped_column(String(3))
    ek_text: Mapped[str | None] = mapped_column(Text)  # Rechenweg EK (Rabatt, Umrechnung)
    rule_label: Mapped[str | None] = mapped_column(String(250))
    factor: Mapped[object | None] = mapped_column(DecimalText)  # VK neu / EK neu
    check_ok: Mapped[bool | None] = mapped_column(Boolean)  # unabhängige Gegenrechnung
    # KI-Einschätzung bei fehlenden/unklaren Artikeln, nur Vorschlag:
    # {status: TREFFER|KEIN_TREFFER|UNKLAR|ABGELEHNT, new_id, number, description, confidence, reason, model}
    ai_hint: Mapped[dict | None] = mapped_column(JSON)


class Datasheet(Base):
    """Produktdatenblatt: festes Layout, Inhalte (Texte, Tabellen, Bildnamen) als JSON.

    Bilder liegen als Dateien unter uploads/datenblatt/<id>/, im JSON steht nur der Dateiname.
    """

    __tablename__ = "datasheets"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_datasheets_owner"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
