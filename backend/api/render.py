from fastapi import Request

from backend.ai.provider import cached_status
from backend.api.templating import templates
from backend.config import get_settings


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    sess = getattr(request.state, "session", None)
    settings = request.app.dependency_overrides.get(get_settings, get_settings)()
    ctx = {
        "user": sess.user if sess else None,
        "csrf_token": sess.csrf_token if sess else "",
        "ai_status": cached_status(settings) if sess else None,
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
