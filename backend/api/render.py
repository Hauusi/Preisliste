from fastapi import Request

from backend.api.templating import templates


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    sess = getattr(request.state, "session", None)
    ctx = {
        "user": sess.user if sess else None,
        "csrf_token": sess.csrf_token if sess else "",
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
