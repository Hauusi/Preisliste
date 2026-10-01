"""Verwaltung auf dem Server: python -m backend.cli <befehl>

  init-db                       Datenbank anlegen/migrieren
  create-admin <benutzername>   Administrator anlegen (Passwort wird abgefragt)
  reset-password <benutzername> Passwort setzen, Sperre aufheben, Sessions beenden
"""

import getpass
import sys

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
        else:
            print(__doc__)
            return 2
    except AuthError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
