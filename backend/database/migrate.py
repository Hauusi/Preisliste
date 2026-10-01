"""Migrationen programmatisch ausführen (Start, Tests, CLI)."""

from alembic import command
from alembic.config import Config

from backend.config import PROJECT_ROOT


def upgrade(db_url: str) -> None:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "backend/database/migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")
