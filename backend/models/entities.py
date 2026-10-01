"""Datenbankmodell Gruppe A. Regeln, Vergleiche und Jobs folgen in Gruppe B/C per Migration."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
