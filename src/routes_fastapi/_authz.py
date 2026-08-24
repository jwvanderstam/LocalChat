"""Shared workspace-authorisation helper for route modules.

Wraps ``check_workspace_access`` in the ``{"success": False, "message": ...}`` envelope
the route layer already uses, so the security module stays free of response shaping.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..security_fastapi import check_workspace_access, get_current_user_id


def deny(request: Request, workspace_id: str | None, min_role: str) -> JSONResponse | None:
    """Return an error response when the caller lacks *min_role*, else ``None``.

    Pass ``workspace_id=None`` for header-scoped routes; scope then resolves from
    ``X-Workspace-ID`` (or the ``workspace_id`` query param) and falls back to the
    default workspace. Pass the path value explicitly when the route has one.
    """
    denial = check_workspace_access(request, workspace_id, min_role)
    if denial is None:
        return None
    code, message = denial
    return JSONResponse({"success": False, "message": message}, status_code=code)


def require_caller(request: Request) -> str:
    """Return the authenticated caller's id, or raise 401.

    Six OAuth routes and the connector create path used to fall back to the
    literal string ``"admin"`` here, putting a non-identity where a user id was
    expected (BUG-4). There is no safe default for "who is this", so refuse.
    """
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(401, detail={"message": "Authentication required"})
    return user_id
