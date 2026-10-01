"""Zentrale Konfiguration. Werte kommen aus Umgebungsvariablen mit Präfix PREIS_."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PREIS_", env_file=".env", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data"
    config_dir: Path = PROJECT_ROOT / "config"

    # Upload-Grenzen
    max_upload_mb: int = 25
    max_uncompressed_mb: int = 300
    max_zip_entries: int = 5000

    # Anmeldung
    session_idle_minutes: int = 480
    session_max_hours: int = 72
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    login_ip_max_attempts: int = 20
    login_ip_window_minutes: int = 15
    min_password_length: int = 12
    cookie_secure: bool = True

    # Anzeige
    page_size: int = 50

    @property
    def db_path(self) -> Path:
        return self.data_dir / "preisliste.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
