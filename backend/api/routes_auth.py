from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.api.deps import COOKIE_NAME, check_csrf, client_ip, current_session, current_user
from backend.api.templating import templates
from backend.auth.core import (
    AuthError,
    authenticate,
    create_session,
    end_all_sessions,
    end_session,
    hash_password,
    ip_limiter,
    validate_password,
)
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import User
from backend.services.audit import audit
from backend.api.render import render

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, username: str = Form(..., max_length=64), password: str = Form(..., max_length=256),
          db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    ip = client_ip(request) or "unbekannt"
    if not ip_limiter.hit(ip, settings.login_ip_max_attempts, settings.login_ip_window_minutes * 60):
        audit(db, None, "login_ip_gesperrt", details={"username": username[:64]}, ip=ip)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Zu viele Anmeldeversuche. Bitte später erneut versuchen."},
            status_code=429,
        )
    try:
        user = authenticate(db, username, password, settings)
    except AuthError as exc:
        audit(db, None, "login_fehlgeschlagen", details={"username": username[:64]}, ip=ip)
        return templates.TemplateResponse(request, "login.html", {"error": str(exc)}, status_code=401)
    token = create_session(db, user, ip)
    audit(db, user, "login", ip=ip)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure, samesite="strict",
        max_age=settings.session_max_hours * 3600, path="/",
    )
    return response


@router.post("/logout", dependencies=[Depends(check_csrf)])
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    end_session(db, request.cookies.get(COOKIE_NAME))
    audit(db, user, "logout", ip=client_ip(request))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/konto")
def account(request: Request, _sess=Depends(current_session)):
    return render(request, "account.html", {"message": None, "error": None})


@router.post("/konto", dependencies=[Depends(check_csrf)])
def change_password(request: Request, old_password: str = Form(...), new_password: str = Form(...),
                    new_password2: str = Form(...), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings), user: User = Depends(current_user)):
    try:
        authenticate(db, user.username, old_password, settings)
        if new_password != new_password2:
            raise AuthError("Neue Passwörter stimmen nicht überein")
        validate_password(new_password, settings)
    except AuthError as exc:
        return render(request, "account.html", {"message": None, "error": str(exc)}, status_code=400)
    user.password_hash = hash_password(new_password)
    end_all_sessions(db, user.id)
    token = create_session(db, user, client_ip(request))
    audit(db, user, "passwort_geaendert", "user", user.id, ip=client_ip(request))
    response = RedirectResponse("/konto?ok=1", status_code=303)
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.session_max_hours * 3600, path="/")
    return response
