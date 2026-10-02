import re

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import AuditLog, User
from tests.conftest import ADMIN_PW, USER_PW, login


def test_pages_require_login(client):
    for path in ("/", "/listen", "/import", "/benutzer", "/konto"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/api/status").status_code == 401
    assert client.get("/health").json() == {"status": "ok"}


def test_login_sets_secure_cookie_and_logout(client):
    r = client.post("/login", data={"username": "Admin", "password": ADMIN_PW}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert client.get("/").status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/").text).group(1)
    client.post("/logout", data={"csrf_token": csrf})
    assert client.get("/", follow_redirects=False).status_code == 303


def test_wrong_password_generic_message(client):
    r = client.post("/login", data={"username": "admin", "password": "falsch"})
    assert r.status_code == 401 and "Benutzername oder Passwort falsch" in r.text
    r = client.post("/login", data={"username": "gibtsnicht", "password": "falsch"})
    assert r.status_code == 401 and "Benutzername oder Passwort falsch" in r.text


def test_account_lockout_after_failures(client):
    for _ in range(5):
        client.post("/login", data={"username": "anna", "password": "falsch"})
    r = client.post("/login", data={"username": "anna", "password": USER_PW})
    assert r.status_code == 401  # gesperrt trotz richtigem Passwort
    with session_scope() as db:
        assert db.scalar(select(User).where(User.username == "anna")).locked_until is not None


def test_ip_rate_limit(client):
    codes = [client.post("/login", data={"username": f"x{i}", "password": "y"}).status_code for i in range(21)]
    assert codes[-1] == 429


def test_csrf_required(admin_client):
    r = admin_client.post("/benutzer", data={"username": "neu", "password": "x" * 12, "role": "benutzer"})
    assert r.status_code == 403
    r = admin_client.post("/benutzer", data={"username": "neu", "password": "x" * 12, "role": "benutzer",
                                             "csrf_token": "falsch"})
    assert r.status_code == 403


def test_foreign_origin_rejected(admin_client):
    r = admin_client.post("/logout", data={"csrf_token": admin_client.csrf},
                          headers={"origin": "https://boese.example"})
    assert r.status_code == 403


def test_security_headers(client):
    r = client.get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_admin_only_pages(user_client):
    assert user_client.get("/benutzer").status_code == 403
    assert user_client.get("/audit").status_code == 403
    r = user_client.post("/benutzer", data={"username": "x", "password": "y" * 12, "role": "admin",
                                            "csrf_token": user_client.csrf})
    assert r.status_code == 403


def test_admin_creates_user_and_deactivates(admin_client, app):
    r = admin_client.post("/benutzer", data={"username": "bernd", "password": "kurz", "role": "benutzer",
                                             "csrf_token": admin_client.csrf})
    assert r.status_code == 400 and "mindestens 12" in r.text
    r = admin_client.post("/benutzer", data={"username": "bernd", "password": "lang-genug-123",
                                             "role": "benutzer", "csrf_token": admin_client.csrf},
                          follow_redirects=False)
    assert r.status_code == 303
    from fastapi.testclient import TestClient
    other = TestClient(app, base_url="https://testserver")
    login(other, "bernd", "lang-genug-123")
    assert other.get("/").status_code == 200
    with session_scope() as db:
        uid = db.scalar(select(User).where(User.username == "bernd")).id
    admin_client.post(f"/benutzer/{uid}/aktiv", data={"csrf_token": admin_client.csrf})
    assert other.get("/", follow_redirects=False).status_code == 303  # Session beendet
    with session_scope() as db:
        actions = set(db.scalars(select(AuditLog.action)))
    assert {"login", "benutzer_angelegt", "benutzer_deaktiviert"} <= actions


def test_change_own_password(user_client):
    r = user_client.post("/konto", data={"old_password": USER_PW, "new_password": "neues-passwort-1",
                                         "new_password2": "neues-passwort-1", "csrf_token": user_client.csrf})
    assert r.status_code == 200 and "Passwort geändert" in r.text


def test_telemetry_disabled(app):
    t = app._telemetry
    assert not t["tracing"] and not t["metrics"] and not t["logs"] and not t["auto_configure"]
    assert not app._native_telemetry.enabled()
