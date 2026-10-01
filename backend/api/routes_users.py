from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.deps import check_csrf, client_ip, require_admin
from backend.api.render import render
from backend.auth.core import ROLES, AuthError, create_user, end_all_sessions, hash_password, validate_password
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import AuditLog, User
from backend.services.audit import audit

router = APIRouter()


def _page(request, db, error=None, status_code=200):
    users = db.scalars(select(User).order_by(User.username)).all()
    return render(request, "users.html", {"users": users, "roles": ROLES, "error": error}, status_code)


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    return target


@router.get("/benutzer")
def users(request: Request, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return _page(request, db)


@router.post("/benutzer", dependencies=[Depends(check_csrf)])
def add_user(request: Request, username: str = Form(..., max_length=64), password: str = Form(..., max_length=256),
             role: str = Form(...), db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
             admin: User = Depends(require_admin)):
    try:
        new = create_user(db, username, password, role, settings)
    except AuthError as exc:
        return _page(request, db, str(exc), 400)
    audit(db, admin, "benutzer_angelegt", "user", new.id, {"username": new.username, "rolle": role},
          client_ip(request))
    return RedirectResponse("/benutzer", status_code=303)


@router.post("/benutzer/{user_id}/aktiv", dependencies=[Depends(check_csrf)])
def toggle_active(request: Request, user_id: int, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    if target.id == admin.id:
        return _page(request, db, "Eigenes Konto kann nicht deaktiviert werden", 400)
    target.active = not target.active
    if not target.active:
        end_all_sessions(db, target.id)
    target.locked_until = None
    target.failed_logins = 0
    audit(db, admin, "benutzer_aktiviert" if target.active else "benutzer_deaktiviert", "user", target.id,
          {"username": target.username}, client_ip(request))
    return RedirectResponse("/benutzer", status_code=303)


@router.post("/benutzer/{user_id}/passwort", dependencies=[Depends(check_csrf)])
def reset_password(request: Request, user_id: int, password: str = Form(..., max_length=256),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                   admin: User = Depends(require_admin)):
    target = _target(db, user_id)
    try:
        validate_password(password, settings)
    except AuthError as exc:
        return _page(request, db, str(exc), 400)
    target.password_hash = hash_password(password)
    target.locked_until = None
    target.failed_logins = 0
    end_all_sessions(db, target.id)
    audit(db, admin, "passwort_zurueckgesetzt", "user", target.id, {"username": target.username},
          client_ip(request))
    return RedirectResponse("/benutzer", status_code=303)


@router.get("/audit")
def audit_log(request: Request, page: int = 1, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    size = 100
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset((max(page, 1) - 1) * size).limit(size)).all()
    return render(request, "audit.html", {"rows": rows, "page": max(page, 1), "size": size})
