from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth.core import load_session
from backend.config import Settings, get_settings
from backend.database.engine import get_db
from backend.models.entities import User, UserSession

COOKIE_NAME = "sid"


class LoginRequired(Exception):
    pass


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_session(request: Request, db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)) -> UserSession:
    sess = load_session(db, request.cookies.get(COOKIE_NAME), settings)
    if sess is None:
        raise LoginRequired()
    request.state.session = sess
    request.state.user = sess.user
    return sess


def current_user(sess: UserSession = Depends(current_session)) -> User:
    return sess.user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    return user


async def check_csrf(request: Request, sess: UserSession = Depends(current_session)) -> None:
    token = request.headers.get("x-csrf-token")
    if token is None:
        form = await request.form()
        token = form.get("csrf_token")
    if not token or not hmac.compare_digest(str(token), sess.csrf_token):
        raise HTTPException(status_code=403, detail="Ungültiges Formular-Token. Seite neu laden.")
