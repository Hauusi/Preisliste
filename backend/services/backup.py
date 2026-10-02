"""Sicherung: konsistente Kopie der SQLite-Datenbank (Backup-API, WAL-sicher) plus Upload-Dateien."""

from __future__ import annotations

import datetime as dt
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from backend.config import Settings


def create_backup(settings: Settings, keep: int = 14) -> tuple[Path, int]:
    if keep < 1:
        raise ValueError("Mindestens eine Sicherung behalten")
    target_dir = settings.data_dir / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = target_dir / f"preisliste-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(dir=target_dir) as tmp:
        db_copy = Path(tmp) / "preisliste.sqlite3"
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(db_copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        check = sqlite3.connect(db_copy)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Integritätsprüfung der Sicherung fehlgeschlagen")
        finally:
            check.close()
        partial = archive.with_suffix(".partial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(db_copy, arcname="preisliste.sqlite3")
            if settings.upload_dir.exists():
                tar.add(settings.upload_dir, arcname="uploads")
        partial.rename(archive)
    archive.chmod(0o600)
    backups = sorted(target_dir.glob("preisliste-*.tar.gz"))
    old = backups[:-keep]
    for b in old:
        b.unlink()
    return archive, len(old)
