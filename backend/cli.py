"""Verwaltung auf dem Server: python -m backend.cli <befehl>

  init-db                       Datenbank anlegen/migrieren
  create-admin <benutzername>   Administrator anlegen (Passwort wird abgefragt)
  reset-password <benutzername> Passwort setzen, Sperre aufheben, Sessions beenden
  backup [anzahl]               Sicherung (Datenbank + Uploads) nach data/backups, behält die letzten N (Standard 14)
  clear-data --ja               Hersteller, Preislisten, Artikel, Kalkulationen, Vergleiche und Uploads löschen.
                                Benutzer, Regeln und Protokoll bleiben. Vorher automatische Sicherung.
  clear-data --ja --alles       Zusätzlich alle Regeln und alle Benutzer außer Administratoren löschen.
  reset-data --ja               ALLE Daten löschen (Listen, Hersteller, Regeln, Vergleiche, Benutzer, Uploads).
                                Vorher wird automatisch eine Sicherung erstellt. Danach create-admin ausführen.
"""

import getpass
import sys
from pathlib import Path

from sqlalchemy import select

from backend.auth.core import AuthError, create_user, end_all_sessions, hash_password, normalize_username, validate_password
from backend.config import get_settings
from backend.database import engine as db_engine
from backend.database.migrate import upgrade
from backend.models.entities import User
from backend.services.audit import audit


def _ask_password(settings) -> str:
    pw = getpass.getpass("Passwort: ")
    if pw != getpass.getpass("Passwort wiederholen: "):
        raise AuthError("Passwörter stimmen nicht überein")
    validate_password(pw, settings)
    return pw


def reset_data(settings) -> str:
    """Sicherung anlegen, dann Datenbank und Uploads löschen. Die nächste Migration legt alles leer neu an."""
    from backend.services.backup import create_backup

    backup, _ = create_backup(settings, keep=1000)
    db_engine.get_engine().dispose()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{settings.db_path}{suffix}").unlink(missing_ok=True)
    if settings.upload_dir.exists():
        for f in settings.upload_dir.iterdir():
            if f.is_file():
                f.unlink()
    return str(backup)


RULE_TRIGGERS = (
    """CREATE TRIGGER rule_versions_no_update BEFORE UPDATE ON rule_versions
        BEGIN SELECT RAISE(ABORT, 'Regelversionen sind unveraenderlich'); END""",
    """CREATE TRIGGER rule_versions_no_delete BEFORE DELETE ON rule_versions
        BEGIN SELECT RAISE(ABORT, 'Regelversionen sind unveraenderlich'); END""",
)


def clear_data(settings, everything: bool = False) -> tuple[str, dict]:
    """Geschäftsdaten löschen. Mit everything zusätzlich Regeln und Nicht-Admin-Benutzer."""
    from sqlalchemy import delete, func, select, text, update

    from backend.models import entities as e
    from backend.services.backup import create_backup

    backup, _ = create_backup(settings, keep=1000)
    counts = {}
    with db_engine.session_scope() as db:
        counts["Hersteller"] = db.scalar(select(func.count(e.Manufacturer.id)))
        counts["Preislisten"] = db.scalar(select(func.count(e.PriceList.id)))
        counts["Artikel"] = db.scalar(select(func.count(e.Article.id)))
        for model in (e.PriceUpdateItem, e.PriceUpdate, e.RuleException, e.AiMatchSuggestion, e.MatchDecision, e.ComparisonItem, e.Comparison, e.CalculationResult,
                      e.CalculationRun, e.Job, e.ImportMessage, e.ArticlePrice, e.Article, e.PriceList):
            db.execute(delete(model))
        if everything:
            counts["Regeln"] = db.scalar(select(func.count(e.Rule.id)))
            counts["Benutzer (ohne Admins)"] = db.scalar(select(func.count(e.User.id)).where(e.User.role != "admin"))
            db.execute(update(e.Manufacturer).values(default_rule_id=None))
            # Regelversionen sind per Trigger gegen Löschen geschützt: nur hier gezielt aufheben
            db.execute(text("DROP TRIGGER IF EXISTS rule_versions_no_delete"))
            db.execute(delete(e.RuleVersion))
            db.execute(text(RULE_TRIGGERS[1]))
            db.execute(delete(e.Rule))
            others = select(e.User.id).where(e.User.role != "admin")
            db.execute(delete(e.UserSession).where(e.UserSession.user_id.in_(others)))
            db.execute(update(e.AuditLog).where(e.AuditLog.user_id.in_(others)).values(user_id=None))
            db.execute(delete(e.User).where(e.User.role != "admin"))
            db.execute(delete(e.Setting))
        else:
            # Regeln bleiben, verlieren aber die Zuordnung zum gelöschten Hersteller
            db.execute(update(e.Rule).values(manufacturer_id=None))
        db.execute(delete(e.Manufacturer))
        audit(db, None, "daten_geloescht_cli", details={**counts, "sicherung": str(backup)})
    if settings.upload_dir.exists():
        for f in settings.upload_dir.iterdir():
            if f.is_file():
                f.unlink()
    return str(backup), counts


def main(argv: list[str]) -> int:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{settings.db_path}"
    upgrade(url)
    db_engine.configure(url)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "init-db":
            print("Datenbank ist aktuell.")
        elif cmd == "create-admin" and len(argv) == 2:
            pw = _ask_password(settings)
            with db_engine.session_scope() as db:
                user = create_user(db, argv[1], pw, "admin", settings)
                audit(db, None, "admin_angelegt_cli", "user", user.id, {"username": user.username})
            print(f"Administrator {normalize_username(argv[1])} angelegt.")
        elif cmd == "reset-password" and len(argv) == 2:
            pw = _ask_password(settings)
            with db_engine.session_scope() as db:
                user = db.scalar(select(User).where(User.username == normalize_username(argv[1])))
                if user is None:
                    raise AuthError("Benutzer nicht gefunden")
                user.password_hash = hash_password(pw)
                user.locked_until = None
                user.failed_logins = 0
                user.active = True
                end_all_sessions(db, user.id)
                audit(db, None, "passwort_gesetzt_cli", "user", user.id, {"username": user.username})
            print("Passwort gesetzt.")
        elif cmd == "clear-data":
            if argv[1:] not in (["--ja"], ["--ja", "--alles"]):
                print("Sicherheitsabfrage: 'clear-data --ja' oder 'clear-data --ja --alles' eingeben.", file=sys.stderr)
                return 2
            everything = "--alles" in argv
            backup, counts = clear_data(settings, everything)
            print("Gelöscht: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
            kept = "Administratoren und Protokoll" if everything else "Benutzer, Regeln und Protokoll"
            print(f"Erhalten: {kept}. Sicherung vorher: {backup}")
        elif cmd == "reset-data":
            if argv[1:] != ["--ja"]:
                print("Sicherheitsabfrage: zum Löschen aller Daten 'reset-data --ja' eingeben.", file=sys.stderr)
                return 2
            backup = reset_data(settings)
            upgrade(url)
            print(f"Alle Daten gelöscht. Sicherung vorher: {backup}")
            print("Jetzt Administrator anlegen: python -m backend.cli create-admin <name>")
        elif cmd == "backup":
            from backend.services.backup import create_backup

            keep = int(argv[1]) if len(argv) > 1 else 14
            path, removed = create_backup(settings, keep)
            print(f"Sicherung erstellt: {path} ({path.stat().st_size // 1024} KB), entfernt: {removed}")
        else:
            print(__doc__)
            return 2
    except AuthError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
