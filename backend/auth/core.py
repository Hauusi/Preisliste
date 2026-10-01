"""Anmeldung: Argon2id-Passwörter, serverseitige Sessions, Konto-Sperre, IP-Begrenzung."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.entities import User, UserSession, utcnow

ROLES = ("admin", "benutzer")
_hasher = PasswordHasher()
# Für unbekannte Benutzernamen trotzdem einen Hash prüfen (gleiche Laufzeit, keine Benutzer-Erkennung)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def validate_password(password: str, settings: Settings) -> None:
    if len(password) < settings.min_password_length:
        raise AuthError(f"Passwort muss mindestens {settings.min_password_length} Zeichen haben")
    if len(password) > 256:
        raise AuthError("Passwort ist zu lang")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class IpRateLimiter:
    """Gleitendes Fenster pro IP, im Speicher (ein Prozess)."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def hit(self, ip: str, max_attempts: int, window_seconds: int) -> bool:
        """Zählt einen Versuch. False, wenn das Limit überschritten ist."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(ip, deque())
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= max_attempts:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


ip_limiter = IpRateLimiter()


def authenticate(db: Session, username: str, password: str, settings: Settings) -> User:
    """Prüft Zugangsdaten. Wirft AuthError mit allgemeiner Meldung."""
    generic = AuthError("Benutzername oder Passwort falsch, oder Konto gesperrt")
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        raise generic
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise generic
    try:
        _hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_logins = 0
        db.flush()
        raise generic
    if not user.active:
        raise generic
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = now
    return user


def create_session(db: Session, user: User, ip: str | None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(id_hash=_hash_token(token), user_id=user.id,
                       csrf_token=secrets.token_urlsafe(32), ip=ip))
    db.flush()
    return token


def load_session(db: Session, token: str | None, settings: Settings) -> UserSession | None:
    if not token or len(token) > 128:
        return None
    sess = db.get(UserSession, _hash_token(token))
    if sess is None:
        return None
    now = utcnow()
    expired = (
        now - sess.last_seen > timedelta(minutes=settings.session_idle_minutes)
        or now - sess.created_at > timedelta(hours=settings.session_max_hours)
        or not sess.user.active
    )
    if expired:
        db.delete(sess)
        return None
    if now - sess.last_seen > timedelta(minutes=1):
        sess.last_seen = now
    return sess


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.id_hash == _hash_token(token)))


def end_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))


def create_user(db: Session, username: str, password: str, role: str, settings: Settings) -> User:
    username = normalize_username(username)
    if not username or len(username) > 64 or not username.replace(".", "").replace("-", "").replace("_", "").isalnum():
        raise AuthError("Benutzername: nur Buchstaben, Ziffern, Punkt, Bindestrich, Unterstrich")
    if role not in ROLES:
        raise AuthError("Unbekannte Rolle")
    validate_password(password, settings)
    if db.scalar(select(User).where(User.username == username)):
        raise AuthError("Benutzername existiert bereits")
    user = User(username=username, password_hash=hash_password(password), role=role, active=True)
    db.add(user)
    db.flush()
    return user
