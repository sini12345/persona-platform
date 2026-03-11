"""Simple group-code authentication."""
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.config import ADMIN_PASSWORD


def get_group_id(request: Request) -> str | None:
    """Get the group_id from the session cookie."""
    return request.cookies.get("group_id")


def get_group_name(request: Request) -> str | None:
    """Get the group name from the session cookie."""
    return request.cookies.get("group_name")


def require_auth(request: Request) -> str | None:
    """Check if user is authenticated. Returns group_id or None."""
    return get_group_id(request)


def require_admin(request: Request) -> bool:
    """Check admin password from query param or cookie."""
    # Check query param first (for initial login)
    pwd = request.query_params.get("pwd", "")
    if pwd == ADMIN_PASSWORD:
        return True
    # Check cookie
    return request.cookies.get("is_admin") == "true"
